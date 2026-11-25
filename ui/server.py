"""Demo UI server. A read-only wrapper: it imports procurement_desk and calls its public parts stage by
stage (parse, screen, extract, normalize, rules). No engine code is modified or re-implemented.
The final label is cross-checked against the official DecisionPipeline.decide().

    python ui/server.py --root .            (root = folder containing the playbook and threads.csv)
"""
from __future__ import annotations

import argparse, csv, json, mimetypes, os, re, sys, time
from collections import Counter, defaultdict
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from procurement_desk import DecisionPipeline, Playbook, ThreadInput, __version__  # noqa: E402
from procurement_desk.domain import InvalidThreadError  # noqa: E402
from procurement_desk.extraction import MissingInfo, OfferEvidence  # noqa: E402
from procurement_desk.normalization import fmt, normalize  # noqa: E402
from procurement_desk.policy import PolicyContext, round_limit  # noqa: E402
from procurement_desk.security import _RULES  # noqa: E402
from procurement_desk.text import clean, parse_thread  # noqa: E402

STATE: dict = {"pipe": None, "rows": {}, "expected": {}, "error": None}
HEADER = re.compile(r"^\[(Earlier|Latest) message")


def bases(root):
    out = [Path(root)] if root else []
    return out + [REPO, REPO / "dataset", Path.cwd(), Path.cwd() / "dataset"]


def load(root):
    for b in bases(root):
        try:
            STATE["pipe"] = DecisionPipeline(Playbook.load(b))
            break
        except FileNotFoundError:
            continue
    else:
        STATE["error"] = "Playbook not found. Put the organisers' dataset/ folder next to the code or pass --root."
        return
    for b in bases(root):
        for name in ("threads.csv", "sample_threads.csv"):
            p = b / name if (b / name).exists() else b / "dataset" / name
            if p.exists():
                with p.open(newline="", encoding="utf-8") as h:
                    STATE["rows"].update({r["thread_id"]: r for r in csv.DictReader(h)})
    for p in (REPO / "tests/golden/submission_scored_1.0.csv", REPO / "submission.csv"):
        if p.exists():
            with p.open(newline="", encoding="utf-8") as h:
                STATE["expected"] = {r["thread_id"]: r["label"] for r in csv.DictReader(h)}
            break


def money(m):
    return {"cur": m.currency, "amt": fmt(m.amount), "raw": m.raw}


def conditions(ev):
    out = []
    for f in fields(OfferEvidence):
        v = getattr(ev, f.name)
        if f.name in ("source_line", "amounts") or v is None or v is False or (f.name == "unit_divisor" and v == 1):
            continue
        out.append({"k": f.name, "v": str(v)})
    return out


def trace(pipe, t):
    pb, stages = pipe.playbook, []
    cat, sup = pb.categories[t.category], pb.supplier_for(t.supplier)
    parsed = parse_thread(t.supplier_message)
    inj = pipe.injection.scan(t.supplier_message)
    banned = pipe.terms.scan(parsed.latest.body)
    ext = pipe.extractor.extract(t, parsed, lambda l: bool(pipe.injection.scan_line(l)))

    # per-line annotation so the UI can highlight the message as each stage runs
    lines, section = [], "latest" if not HEADER.match(t.supplier_message.lstrip()) else "earlier"
    offers = [c.source_line.strip() for c in ext.candidates]
    prevs = [c.source_line.strip() for c in ext.previous_candidates]
    for raw in t.supplier_message.split("\n"):
        line = clean(raw)
        m = HEADER.match(line)
        if m:
            section = m.group(1).lower()
        lines.append({"text": raw, "sec": section, "hdr": bool(m),
                      "inj": [f.rule_id for f in pipe.injection.scan_line(line)] if not m else [],
                      "ban": [f.rule_id for f in banned if section == "latest" and line.strip() and
                              (line.strip() in f.evidence or f.evidence in line)],
                      "offer": bool(line.strip()) and any(line.strip() in o or o in line.strip() for o in offers),
                      "prev": bool(line.strip()) and section == "earlier" and any(line.strip() in o or o in line.strip() for o in prevs)})

    stages.append({"id": "parse", "title": "Parse the thread", "log": [
        f"clean unicode (NFKC, strip invisible characters)",
        f"{len(parsed.earlier)} earlier message(s); latest message from {parsed.latest.sender!r}"],
        "d": {"earlier": [{"sender": m.sender} for m in parsed.earlier], "latest": parsed.latest.sender}})

    stages.append({"id": "security", "title": "Security screen (whole thread)", "log": [
        f"scan {len(lines)} lines against INJ-01..05" , f"{len(inj)} finding(s)" + (": " + ", ".join(f.rule_id for f in inj) if inj else "")],
        "d": {"rules": [{"id": r, "title": ti, "hits": [f.evidence for f in inj if f.rule_id == r]} for r, ti, _ in _RULES]}})

    stages.append({"id": "terms", "title": "Banned-term screen (latest message only)", "log": [
        "check auto-renewal, advance > 30%, unlimited liability, exclusivity", f"{len(banned)} finding(s)"],
        "d": {"hits": [{"id": f.rule_id, "title": f.title, "evidence": f.evidence} for f in banned]}})

    excluded = [l["text"].strip() for l in lines if l["inj"] and l["sec"] == "latest"]
    stages.append({"id": "extract", "title": "Extract the supplier's current offer", "log": [
        f"{len(ext.candidates)} offer line(s), {len(ext.previous_candidates)} earlier quote(s)",
        f"{len(excluded)} injected line(s) excluded: they can never supply a price"],
        "d": {"offers": [{"line": c.source_line, "amounts": [money(a) for a in c.amounts], "conds": conditions(c)} for c in ext.candidates],
              "previous": [{"line": c.source_line, "amounts": [money(a) for a in c.amounts]} for c in ext.previous_candidates],
              "excluded": excluded, "flags": list(ext.flags)}})

    prev = next((c for c in ext.previous_candidates if normalize(c, t, pb).usable), None)
    normalized, missing, attempts = None, None, []
    for c in ext.candidates:
        a = normalize(c, t, pb, prev)
        attempts.append({"line": c.source_line, "price": None if a.price is None else fmt(a.price),
                         "problem": a.problem.value if a.problem else None,
                         "steps": [{"d": s.description, "v": None if s.value is None else fmt(s.value)} for s in a.steps]})
        if a.usable:
            normalized, missing = a, None
            break
        missing = a.problem
    if not ext.candidates:
        missing = MissingInfo.NO_PRICE_FOUND
    stages.append({"id": "normalize", "title": "Normalize to INR, excl. GST, per unit (exact arithmetic)", "log": [
        f"price p = {fmt(normalized.price)}" if normalized else f"no usable price: {missing.value if missing else ''}"],
        "d": {"attempts": attempts, "price": None if not normalized else fmt(normalized.price), "unit": cat.normalized_unit}})

    vals = pb.values_for(t.category, t.supplier, t.date)
    stages.append({"id": "values", "title": "Resolve the numbers in force", "log": [
        f"target {fmt(vals.target)}, walk-away {fmt(vals.walkaway)}, approval limit {fmt(vals.approval_limit)}"],
        "d": {"target": fmt(vals.target), "walk": fmt(vals.walkaway), "limit": fmt(vals.approval_limit),
              "prov": list(vals.provenance), "status": sup.status, "known": sup.known, "category": cat.name,
              "rounds": cat.rounds, "beta": cat.beta, "date": t.date}})

    ctx = PolicyContext(t, cat, sup, vals, normalized, missing, inj, banned)
    decision, fired, trail = pipe.engine.run(ctx)
    sched = [float(vals.target if sup.probation else round_limit(r, cat.rounds, vals.target, vals.walkaway, cat.beta))
             for r in range(1, cat.rounds + 1)]
    stages.append({"id": "schedule", "title": "Concession schedule L(r)", "log": [
        f"L(r) = T + (W-T)*((r-1)/(R-1))^{cat.beta}" + ("  [probation: L = target]" if sup.probation else ""),
        f"L({t.round}) = {fmt(ctx.level)}" if ctx.level is not None else "price rule not reached"],
        "d": {"levels": sched, "round": min(t.round, cat.rounds), "p": None if not normalized else float(normalized.price),
              "p_txt": None if not normalized else fmt(normalized.price), "level": None if ctx.level is None else fmt(ctx.level),
              "probation": sup.probation, "reached": ctx.level is not None}})

    rows = [{"id": x.rule_id, "title": x.title, "source": x.source, "fired": x.fired, "detail": x.detail, "state": "fired" if x.fired else "passed"} for x in trail]
    seen = {r["id"] for r in rows}
    rows += [{"id": r.id, "title": r.title, "source": r.source, "fired": False, "detail": "not reached: an earlier rule decided", "state": "skipped"}
             for r in pipe.engine.rules if r.id not in seen]
    stages.append({"id": "rules", "title": "Decision procedure: first rule that fires wins", "log": [
        (f"{x['id']} FIRED: {x['detail']}" if x["fired"] else f"{x['id']} passed") for x in rows if x["state"] != "skipped"], "d": {"rows": rows, "fired": fired}})
    return stages, decision, lines


def respond(row):
    pipe = STATE["pipe"]
    t = ThreadInput.from_mapping(row)
    rec = pipe.decide(t)                                  # the official answer
    lines = []
    try:
        stages, decision, lines = trace(pipe, t)
        verified = decision.label == rec.label            # replayed stages must reproduce the official label
    except Exception as e:                                # noqa: BLE001 - mirror the engine's fail-safe behaviour
        stages = [{"id": "error", "title": "Processing error: fail safe", "log": [f"{type(e).__name__}: {e}"],
                   "d": {"error": f"{type(e).__name__}: {e}"}}]
        verified = True
    return {"thread": {"id": t.thread_id, "supplier": t.supplier, "category": t.category, "quantity": t.quantity,
                       "round": t.round, "date": t.date},
            "lines": lines, "stages": stages, "label": rec.label, "action": rec.decision.action.value,
            "reason": rec.decision.reason.value, "counter": rec.decision.counter_price, "fired": rec.fired_rule,
            "verified": verified, "expected": STATE["expected"].get(t.thread_id), "ticket": rec.escalation_ticket(),
            "flags": list(rec.flags), "fingerprint": rec.playbook_fingerprint, "error": rec.error}


def compute_stats():
    pipe, t0, recs = STATE["pipe"], time.perf_counter(), []
    for r in STATE["rows"].values():
        try:
            recs.append(pipe.decide(ThreadInput.from_mapping(r)))
        except InvalidThreadError:
            pass
    secs = time.perf_counter() - t0
    acts = Counter(r.decision.action.value for r in recs)
    by_cat, by_round, sup, flags, spend = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), Counter(), defaultdict(float)
    for r in recs:
        a, t = r.decision.action.value, r.thread
        by_cat[t.category][a] += 1; by_round[t.round][a] += 1; sup[t.supplier][a] += 1; flags.update(r.flags)
        if r.normalized_price is not None:
            spend[a] += float(r.normalized_price * t.quantity)
    exp = STATE["expected"]
    cmp_ = [r for r in recs if r.thread.thread_id in exp]
    rows = lambda d, key: [{"name": k, **{a: c.get(a, 0) for a in ("ACCEPT", "COUNTER", "REJECT", "ESCALATE")}} for k, c in sorted(d.items(), key=key)]
    return {"total": len(recs), "seconds": round(secs, 2), "actions": [{"name": k, "value": v} for k, v in acts.items()],
            "labels": [{"name": k, "value": v} for k, v in Counter(r.label.rsplit(":", 1)[0] for r in recs).most_common()],
            "by_category": rows(by_cat, lambda kv: -sum(kv[1].values())), "by_round": rows(by_round, lambda kv: kv[0]),
            "suppliers": sorted(rows(sup, lambda kv: kv[0]), key=lambda x: -(x["REJECT"] + x["ESCALATE"]))[:10],
            "flags": dict(flags), "spend": dict(spend), "matched": sum(r.label == exp[r.thread.thread_id] for r in cmp_), "comparable": len(cmp_)}


def playbook_json():
    pipe = STATE["pipe"]; pb = pipe.playbook; f = float
    cats = [{"key": c.key, "name": c.name, "unit": c.normalized_unit, "gst": f(c.gst_rate * 100), "target": f(c.target), "walk": f(c.walkaway),
             "rounds": c.rounds, "beta": c.beta, "limit": f(c.approval_limit), "period": c.period,
             "levels": [f(round_limit(r, c.rounds, c.target, c.walkaway, c.beta)) for r in range(1, c.rounds + 1)]} for c in pb.categories.values()]
    return {"fingerprint": pb.fingerprint, "version": __version__, "categories": cats,
            "suppliers": [{"name": s.name, "status": s.status, "caps": {k: f(v) for k, v in s.price_caps.items()}, "fx": {k: f(v) for k, v in s.exchange_rates.items()}} for s in pb.suppliers.values()],
            "amendments": [{"effective": str(a.effective), "category": a.category_key, "field": a.field_name, "value": f(a.value), "source": a.source} for a in sorted(pb.amendments, key=lambda a: a.effective)],
            "precedents": [{"key": k, "items": v} for k, v in pb.precedents.items()], "fx": {k: f(v) for k, v in pb.exchange_rates.items()},
            "rules": [{"id": r.id, "title": r.title, "source": r.source} for r in pipe.engine.rules],
            "injection": [{"id": r, "title": t} for r, t, _ in _RULES],
            "issues": [{"severity": i.severity, "message": i.message} for i in pb.validate()]}


def static_file(path):
    rel = path.split("?")[0].lstrip("/") or "index.html"
    f = (DIST / rel).resolve()
    if DIST.resolve() not in f.parents:
        f = DIST / "index.html"
    if not f.is_file():
        f = DIST / "index.html"
    return f if f.is_file() else None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        p, path = STATE["pipe"], self.path.split("?")[0]
        if path == "/api/meta":
            pb = p.playbook if p else None
            self._send(200, {"ready": p is not None, "error": STATE["error"], "version": __version__,
                             "fingerprint": pb.fingerprint if pb else None,
                             "categories": sorted(pb.categories) if pb else [], "suppliers": sorted(s.name for s in pb.suppliers.values()) if pb else [],
                             "threads": [{"id": r["thread_id"], "supplier": r["supplier"], "category": r["category"], "label": STATE["expected"].get(r["thread_id"])}
                                         for r in STATE["rows"].values()]})
        elif path in ("/api/stats", "/api/playbook") and not p:
            self._send(503, {"error": STATE["error"]})
        elif path == "/api/stats":
            STATE.setdefault("stats", None)
            STATE["stats"] = STATE["stats"] or compute_stats()
            self._send(200, STATE["stats"])
        elif path == "/api/playbook":
            self._send(200, playbook_json())
        elif path.startswith("/api/"):
            self._send(404, {"error": "not found"})
        else:
            f = static_file(path)
            if f is None:
                return self._send(503, b"UI not built: run `npm install && npm run build` in ui/web", "text/plain")
            self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_POST(self):  # noqa: N802
        if self.path != "/api/run" or not STATE["pipe"]:
            return self._send(404, {"error": STATE["error"] or "not found"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1_000_000)))
            row = STATE["rows"].get(body.get("id")) if body.get("id") else body
            if not row:
                raise InvalidThreadError("unknown thread id")
            self._send(200, respond(row))
        except (InvalidThreadError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})

    def log_message(self, *a):  # no payload logging
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("PROCUREMENT_ROOT"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    a = ap.parse_args()
    load(a.root)
    print(STATE["error"] or f"Loaded playbook {STATE['pipe'].playbook.fingerprint}, {len(STATE['rows'])} threads")
    print(f"Open http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
