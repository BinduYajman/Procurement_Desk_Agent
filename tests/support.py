"""Shared test helpers. Tests that need the competition data skip themselves when it is not available.

Set PROCUREMENT_ROOT to the folder containing playbook/ and the CSV files (or keep them in ./dataset).
"""
from __future__ import annotations

import csv
import os
import sys
import unittest
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from procurement_desk import DecisionPipeline, Playbook, ThreadInput  # noqa: E402


def _find_root() -> Optional[Path]:
    candidates = [Path(os.environ["PROCUREMENT_ROOT"])] if os.environ.get("PROCUREMENT_ROOT") else []
    candidates += [REPO, REPO / "dataset", Path.cwd(), Path.cwd() / "dataset"]
    for candidate in candidates:
        try:
            Playbook.load(candidate)
            return candidate
        except FileNotFoundError:
            continue
    return None


ROOT = _find_root()
needs_data = unittest.skipIf(ROOT is None, "playbook data not found; set PROCUREMENT_ROOT")
PB = Playbook.load(ROOT) if ROOT else None
PIPE = DecisionPipeline(PB, strict=True) if PB else None


def locate(name: str) -> Optional[Path]:
    for base in ([ROOT, ROOT / "dataset"] if ROOT else []):
        if (base / name).exists():
            return base / name
    return None


def read_rows(name: str) -> list[dict[str, str]]:
    path = locate(name)
    if path is None:
        raise unittest.SkipTest(f"{name} not found")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def make_thread(category: str, message: str, qty: int = 10, rnd: int = 1, supplier: str = "Garnet Print & Paper",
                date: str = "2026-10-01", thread_id: str = "T") -> ThreadInput:
    return ThreadInput(thread_id, date, supplier, category, qty, rnd, None, message)


def decide(category: str, message: str, **kw) -> str:
    return PIPE.decide(make_thread(category, message, **kw)).label


def price(category: str, message: str, **kw):
    return PIPE.decide(make_thread(category, message, **kw)).normalized_price
