from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from .domain import LABEL_PATTERN, InvalidThreadError, ThreadInput
from .pipeline import DecisionPipeline, DecisionRecord
from .playbook import Playbook

COLUMNS = ["thread_id", "date", "supplier", "category", "quantity", "round", "our_last_counter", "supplier_message"]


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (root / path, root / "dataset" / path):
        if candidate.exists():
            return candidate
    return root / path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        rows = list(reader)
    ids = [r["thread_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path} contains duplicate thread_id values")
    return rows


def run_rows(pipeline: DecisionPipeline, rows: list[dict[str, str]]) -> list[DecisionRecord]:
    records = []
    for row in rows:
        try:
            records.append(pipeline.decide(ThreadInput.from_mapping(row)))
        except InvalidThreadError as error:
            if pipeline.strict:
                raise
            records.append(pipeline.invalid_input(row.get("thread_id", "?"), str(error)))
    return records


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def cmd_generate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    playbook = Playbook.load(root)
    errors = [i for i in playbook.validate() if i.severity == "error"]
    if errors:
        raise ValueError("Playbook has errors: " + "; ".join(i.message for i in errors))
    rows = read_rows(_resolve(root, args.input))
    started = time.perf_counter()
    records = run_rows(DecisionPipeline(playbook, strict=args.strict), rows)
    elapsed = time.perf_counter() - started
    for r in records:
        if not LABEL_PATTERN.fullmatch(r.label):
            raise ValueError(f"Invalid label for {r.thread.thread_id}: {r.label!r}")
    out = Path(args.output)                      # outputs are relative to where the command is run
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["thread_id", "label"])
        writer.writerows([r.thread.thread_id, r.label] for r in records)
    if args.audit_output:
        _write_jsonl(Path(args.audit_output), [r.to_dict() for r in records])
    if args.escalations_output:
        _write_jsonl(Path(args.escalations_output), [t for r in records if (t := r.escalation_ticket())])
    print(f"Wrote {len(records)} labels to {out.resolve()}  ({elapsed:.2f}s, playbook {playbook.fingerprint})")
    for label, n in Counter(r.label.rsplit(":", 1)[0] for r in records).most_common():
        print(f"  {label}: {n}")
    flagged = Counter(f for r in records for f in r.flags)
    if flagged:
        print("Advisory flags (review recommended): " + ", ".join(f"{k}={v}" for k, v in flagged.items()))
    return 1 if any(r.error for r in records) else 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    pipeline = DecisionPipeline(Playbook.load(root), strict=args.strict)
    truth: dict[str, str] = {}
    with _resolve(root, args.answers).open(newline="", encoding="utf-8") as handle:
        truth = {r["thread_id"]: r["label"] for r in csv.DictReader(handle)}
    records = [r for r in run_rows(pipeline, read_rows(_resolve(root, args.threads))) if r.thread.thread_id in truth]
    exact = sum(r.label == truth[r.thread.thread_id] for r in records)
    action = sum(r.label.split(":")[0] == truth[r.thread.thread_id].split(":")[0] for r in records)
    print(f"Exact match: {exact}/{len(records)} = {exact / max(len(records), 1):.2%}")
    print(f"Action accuracy: {action}/{len(records)} = {action / max(len(records), 1):.2%}")
    for r in records:
        if r.label != truth[r.thread.thread_id]:
            print(f"\n{r.thread.thread_id}: predicted={r.label!r} expected={truth[r.thread.thread_id]!r}\n{r.explain()}")
    return 0 if exact == len(records) else 1


def cmd_explain(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    pipeline = DecisionPipeline(Playbook.load(root))
    for row in read_rows(_resolve(root, args.input)):
        if row["thread_id"] == args.thread_id:
            if args.show_message:
                print(row["supplier_message"] + "\n" + "-" * 60)
            print(pipeline.decide(ThreadInput.from_mapping(row)).explain())
            return 0
    print(f"thread {args.thread_id} not found", file=sys.stderr)
    return 2


def cmd_validate(args: argparse.Namespace) -> int:
    playbook = Playbook.load(Path(args.root).resolve())
    print(f"Loaded {len(playbook.categories)} categories, {len(playbook.suppliers)} suppliers, "
          f"{len(playbook.amendments)} amendments, {sum(map(len, playbook.precedents.values()))} precedents "
          f"(fingerprint {playbook.fingerprint}).")
    issues = playbook.validate()
    for issue in issues:
        print(f"  [{issue.severity}] {issue.message}")
    return 1 if any(i.severity == "error" for i in issues) else 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .service import make_server
    server = make_server(DecisionPipeline(Playbook.load(Path(args.root).resolve())), args.host, args.port)
    print(f"Serving on http://{args.host}:{args.port}  (GET /healthz, POST /v1/decisions)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="procurement-desk", description="Acme procurement decision engine")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Decide every thread and write the submission CSV")
    gen.add_argument("--root", default=".")
    gen.add_argument("--input", default="threads.csv")
    gen.add_argument("--output", default="outputs/submission.csv")
    gen.add_argument("--audit-output", default="outputs/audit.jsonl", help="Per-thread audit trail ('' disables)")
    gen.add_argument("--escalations-output", default="outputs/escalations.jsonl", help="Review tickets ('' disables)")
    gen.add_argument("--strict", action="store_true", help="Fail on any bad row or internal error instead of escalating it")
    gen.set_defaults(run=cmd_generate)

    ev = sub.add_parser("evaluate", help="Compare with labelled examples")
    ev.add_argument("--root", default=".")
    ev.add_argument("--threads", default="sample_threads.csv")
    ev.add_argument("--answers", default="sample_answers.csv")
    ev.add_argument("--strict", action="store_true")
    ev.set_defaults(run=cmd_evaluate)

    ex = sub.add_parser("explain", help="Show how one thread was decided")
    ex.add_argument("thread_id")
    ex.add_argument("--root", default=".")
    ex.add_argument("--input", default="threads.csv")
    ex.add_argument("--show-message", action="store_true")
    ex.set_defaults(run=cmd_explain)

    val = sub.add_parser("validate-playbook", help="Parse and sanity-check the playbook")
    val.add_argument("--root", default=".")
    val.set_defaults(run=cmd_validate)

    srv = sub.add_parser("serve", help="Run the HTTP service")
    srv.add_argument("--root", default=".")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8080)
    srv.set_defaults(run=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        code = args.run(args)
    except Exception as error:  # noqa: BLE001
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    raise SystemExit(code)


if __name__ == "__main__":
    main()
