"""Extraction + normalization: every rule in policies/units-and-currency.md and the precedents."""
import unittest
from fractions import Fraction as F

from tests.support import PB, decide, needs_data, price


@needs_data
class UnitsAndCurrency(unittest.TestCase):
    def test_per_ream_is_times_ten(self):
        self.assertEqual(price("printer-paper", "For the 12 boxs you requested, we can do ₹257 per ream."), 2570)
        self.assertEqual(price("printer-paper", "we can do ₹257 per reams."), 2570)

    def test_per_n_units_and_packs_and_dozens(self):
        self.assertEqual(price("led-lighting", "For the 200 fixtures you requested, our revised offer is ₹1,92,980 per 100 fixtures.", qty=200), F(192980, 100))
        self.assertEqual(price("led-lighting", "we are pleased to quote ₹9,913 per pack of 4 fixtures."), F(9913, 4))
        self.assertEqual(price("led-lighting", "we are pleased to quote ₹9,913 per pack."), F(9913, 4))
        self.assertEqual(price("headsets", "we can do INR 48,000 per dozen headsets.", qty=5), 4000)

    def test_gst_totals_and_list_price_discounts(self):
        self.assertEqual(price("headsets", "the best we can offer is INR 4,130 per headset including GST.", qty=5), F(4130) / (1 + PB.categories["headsets"].gst_rate))
        self.assertEqual(price("monitors", "We are pleased to quote ₹7,00,000 in total for all 50 monitors.", qty=50), 14000)
        self.assertEqual(price("monitors", "we can do a 10% discount on our list price of ₹20,000 per monitor."), 18000)
        self.assertEqual(price("monitors", "we can do 10% off our list price of ₹20,000 per monitor."), 18000)   # wording in units-and-currency.md

    def test_notation_lakh_k_and_words(self):
        self.assertEqual(price("crm-licenses", "our final price is ₹1.2 lakh per seat per year."), 120000)
        self.assertEqual(price("laptops", "our final price is ₹58.3k per laptop."), 58300)
        self.assertEqual(price("crm-licenses", "our final price is one lakh seven thousand three hundred rupees per seat per year."), 107300)
        self.assertEqual(price("laptops", "we can do seventeen thousand four hundred rupees per laptop."), 17400)

    def test_currencies(self):
        self.assertEqual(price("laptops", "we can do $760 per laptop."), F(760) * F(845, 10))
        self.assertEqual(price("laptops", "we can do €700 per laptop."), 700 * 91)
        self.assertEqual(price("laptops", "we can do £700 per laptop.", supplier="Falcon Security Services"), 700 * F(1055, 10))   # contract rate (P-03)
        for unsupported in ("JPY 658", "SGD 900", "AED 3,000", "CHF 800"):
            self.assertEqual(decide("laptops", f"we can do {unsupported} per laptop."), "ESCALATE:MISSING_INFO:")

    def test_billing_period(self):
        self.assertEqual(price("crm-licenses", "we can do ₹1,600 per seat per month."), 19200)             # P-06
        self.assertEqual(price("crm-licenses", "we can do ₹1,600 per seat / month."), 19200)
        self.assertEqual(price("crm-licenses", "we can do ₹24,000 per seat per annum."), 24000)
        self.assertEqual(price("cleaning", "we can do ₹60,000 per site per year."), 5000)
        self.assertEqual(decide("crm-licenses", "We can offer ₹19,000 per seat for this order."), "ESCALATE:MISSING_INFO:")

    def test_ranges_tiers_free_units_volume(self):
        self.assertEqual(price("monitors", "our revised offer is between ₹13,400 and ₹14,600 per monitor depending on final specs."), 14600)   # P-01
        line = "we can do INR 28,862 per seat per year for orders of up to 100 seats, and ₹27,130 per seat per year for larger orders."
        self.assertEqual(price("design-software", line, qty=80), 28862)
        self.assertEqual(price("design-software", line, qty=100), 28862)
        self.assertEqual(price("design-software", line, qty=150), 27130)
        self.assertEqual(price("catering", "we can do ₹300 per meal, plus 1 free meal for every 10 you pay for."), F(3000, 11))             # P-02
        self.assertEqual(price("courier", "we can do ₹170 per shipment, plus 1 free shipment for every 5 you pay for."), F(850, 6))        # P-05
        vol = "we can do INR 10,000 per chair, with a further 10% off for orders of 50 chairs or more."
        self.assertEqual((price("office-chairs", vol, qty=49), price("office-chairs", vol, qty=50)), (10000, 9000))

    def test_previous_quote_and_correction(self):
        msg = ("[Earlier message — Cobalt Compute, 2026-10-08]\nOur quote is ₹3,910 per headset.\n\n"
               "[Latest message — Cobalt Compute, 2026-10-13]\nHello,\n\nour revised offer is a further 5% off our previous quote.\n")
        self.assertEqual(price("headsets", msg), F(3910) * F(95, 100))
        no_prior = "our revised offer is a further 5% off our previous quote."
        self.assertEqual(decide("headsets", no_prior), "ESCALATE:MISSING_INFO:")
        corr = ("[Earlier message — X, 2026-09-17]\nWe can do ₹3,181 per box.\n\n"
                "[Latest message — X, 2026-09-22]\nCORRECTION — the price in my previous email should read Rs. 2,766 per box, not ₹3,181.\n")
        self.assertEqual(price("printer-paper", corr), 2766)

    def test_only_the_latest_offer_counts_and_stale_quotes_are_ignored(self):
        msg = ("[Earlier message — X, 2026-09-17]\nWe can do ₹2,100 per box.\n\n"
               "[Latest message — X, 2026-09-22]\nOur earlier quote was ₹9,999 per box.\nWe can do ₹2,300 per box.\n")
        self.assertEqual(price("printer-paper", msg), 2300)
        silent = ("[Earlier message — X, 2026-09-17]\nWe can do ₹2,100 per box.\n\n"
                  "[Latest message — X, 2026-09-22]\nWe can definitely give you a competitive price. Let's get on a call.\n")
        self.assertEqual(decide("printer-paper", silent), "ESCALATE:MISSING_INFO:")

    def test_fullwidth_digits_and_hidden_characters(self):
        self.assertEqual(price("laptops", "we can do ₹６２,０００ per laptop."), 62000)
        self.assertEqual(price("laptops", "we can do ₹62\u200b,000 per laptop."), 62000)


if __name__ == "__main__":
    unittest.main()
