"""Regression gates on the real data. Any refactor must keep these green."""
import unittest
from pathlib import Path

from tests.support import PIPE, needs_data, read_rows
from procurement_desk import ThreadInput

GOLDEN = Path(__file__).parent / "golden" / "submission_scored_1.0.csv"


@needs_data
class GoldenTests(unittest.TestCase):
    def test_sample_threads_match_sample_answers_exactly(self):
        answers = {r["thread_id"]: r["label"] for r in read_rows("sample_answers.csv")}
        records = [PIPE.decide(ThreadInput.from_mapping(r)) for r in read_rows("sample_threads.csv")]
        wrong = [(r.thread.thread_id, r.label, answers[r.thread.thread_id]) for r in records if r.label != answers[r.thread.thread_id]]
        self.assertEqual(wrong, [])
        self.assertEqual(len(records), len(answers))

    def test_full_run_is_identical_to_the_submission_that_scored_1_0(self):
        golden = dict(line.strip().split(",", 1) for line in GOLDEN.read_text(encoding="utf-8").splitlines()[1:])
        records = [PIPE.decide(ThreadInput.from_mapping(r)) for r in read_rows("threads.csv")]
        self.assertEqual(len(records), 2000)
        changed = [(r.thread.thread_id, golden[r.thread.thread_id], r.label) for r in records if r.label != golden[r.thread.thread_id]]
        self.assertEqual(changed, [])

    def test_no_advisory_flag_fires_on_the_competition_data(self):
        flagged = [r.thread.thread_id for r in (PIPE.decide(ThreadInput.from_mapping(x)) for x in read_rows("threads.csv")) if r.flags]
        self.assertEqual(flagged, [])


if __name__ == "__main__":
    unittest.main()
