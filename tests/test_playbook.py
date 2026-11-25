import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from tests.support import PB, ROOT, needs_data
from procurement_desk import Playbook


@needs_data
class PlaybookTests(unittest.TestCase):
    def test_everything_is_loaded(self):
        self.assertEqual((len(PB.categories), len(PB.suppliers), len(PB.amendments)), (15, 40, 9))
        self.assertEqual([i for i in PB.validate() if i.severity == "error"], [])

    def test_conversion_keys(self):
        self.assertEqual(PB.categories["printer-paper"].sub_units, {"ream": 10})      # singular key (was a bug)
        self.assertEqual(PB.categories["led-lighting"].pack_size, {"pack": 4})
        self.assertEqual(PB.categories["crm-licenses"].period, "year")
        self.assertEqual(PB.categories["cleaning"].period, "month")
        self.assertIsNone(PB.categories["laptops"].period)

    def test_amendments_by_date_and_contract_cap(self):
        walk = lambda sup, day: PB.values_for("led-lighting", sup, day).walkaway
        self.assertEqual(walk("Everbright Lighting", "2026-12-04"), 2330)    # AMD-08 effective 12-04
        self.assertEqual(walk("Everbright Lighting", "2026-12-05"), 2360)    # AMD-07 effective 12-05 replaces it
        self.assertEqual(walk("Xenon Displays", "2026-12-10"), 2300)         # contract cap overrides amendments

    def test_provenance_is_recorded(self):
        v = PB.values_for("led-lighting", "Xenon Displays", "2026-12-10")
        self.assertTrue(any("AMD-07" in p for p in v.provenance))
        self.assertTrue(any("contract price cap" in p for p in v.provenance))

    def test_contract_exchange_rate_replaces_table(self):
        self.assertEqual(PB.fx_rate("Falcon Security Services", "GBP")[0], Fraction(1055, 10))
        self.assertEqual(PB.fx_rate("Garnet Print & Paper", "GBP")[0], 106)
        self.assertIsNone(PB.fx_rate("Garnet Print & Paper", "JPY"))

    def test_unknown_supplier_is_treated_as_approved_but_marked_unknown(self):
        s = PB.supplier_for("Nobody Ltd")
        self.assertFalse(s.known or s.blacklisted or s.probation)

    def test_fingerprint_changes_when_the_playbook_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "pb"
            shutil.copytree(PB.root, copy)
            before = Playbook.load(copy)
            self.assertEqual(before.fingerprint, PB.fingerprint)
            target = next((copy / "categories").glob("*.md"))
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            self.assertNotEqual(Playbook.load(copy).fingerprint, PB.fingerprint)

    def test_validation_catches_a_bad_playbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "pb"
            shutil.copytree(PB.root, copy)
            path = copy / "categories" / "laptops.md"
            text = path.read_text(encoding="utf-8")
            import re
            path.write_text(re.sub(r"(\*\*Walk-away price:\*\*\s*)₹[\d,]+", r"\g<1>₹1", text), encoding="utf-8")
            messages = [i.message for i in Playbook.load(copy).validate() if i.severity == "error"]
            self.assertTrue(any("laptops" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
