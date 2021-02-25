import os
from glob import iglob
from unittest import TestCase

from bankruptcy import (
    extract_all,
    extract_official_form_106_a_b,
    extract_official_form_106_d,
    extract_official_form_106_e_f,
    extract_official_form_106_sum,
)


class BankruptcyTest(TestCase):
    def setUp(self) -> None:
        self.root = os.path.dirname(os.path.realpath(__file__))
        self.files = iglob(f"{self.root}/test_assets/*.pdf")
        self.assets = f"{self.root}/test_assets"

    def test_scanned_pdfs(self):
        """Can we gracefully fail on scans?"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.507503.11.0.pdf"
        results = extract_all(filepath=filepath)
        self.assertFalse(results)

    def test_can_we_handle_missing_checkboxes(self):
        """Can we handle partially bad PDF can still return content?"""

        filepath = f"{self.assets}/gov.uscourts.ganb.1125040.35.0.pdf"
        results = extract_all(filepath=filepath)
        self.assertEqual(
            results["form_106_d"]["error"], "Failed to find document."
        )
        self.assertEqual(len(results["form_106_ef"]["creditors"]), 22)

    def test_offical_form_106_sum(self):
        """Can we extract content from Official Form 106 Sum"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.473342.1.0.pdf"
        results = extract_official_form_106_sum(filepath=filepath)
        self.assertTrue(results["7/11/13"])
        self.assertTrue(results["non_consumer_debts"])
        self.assertEqual(results["3_total"], "863,842.00")
        self.assertEqual(results["9g"], "142,500.00")

    def test_official_form_106_e_f(self):
        """Can we extract content for unsecured creditors"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.473342.1.0.pdf"
        results = extract_official_form_106_e_f(filepath=filepath)
        self.assertEqual(
            len(results["creditors"]), 19, msg="Failed to extract creditors"
        )
        self.assertEqual(results["creditors"][-1]["debtor"], ['At least one of the debtors and another'])

    def test_official_form_106_d(self):
        """Can we extract secured creditors from form 106D"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.473342.1.0.pdf"
        results = extract_official_form_106_d(filepath=filepath)
        self.assertEqual(
            len(results["creditors"]), 9, msg="Failed to extract creditors"
        )

    def test_official_form_106_a_b(self):
        """Can we extract content from Form 106 A/B"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.473342.1.0.pdf"
        results = extract_official_form_106_a_b(filepath=filepath)
        auto = results["cars_land_and_crafts"][3]
        self.assertEqual(
            len(results["cars_land_and_crafts"]),
            4,
            msg="Failed to extract cars_land_and_crafts",
        )
        self.assertEqual(
            auto["make"], "Skido", msg="Failed to extract cars_land_and_crafts"
        )
        self.assertEqual(
            auto["model"], "SM", msg="Failed to extract cars_land_and_crafts"
        )

    def test_all_methods(self):
        """Can we extract content from all four documents?"""

        filepath = f"{self.root}/test_assets/gov.uscourts.orb.473342.1.0.pdf"
        results = extract_all(filepath=filepath)

        self.assertIn("Jr.", results["info"]["debtor_1"])
        self.assertEqual(results["form_106_sum"]["1a"], "325,882.00")
        self.assertEqual(results["form_106_sum"]["9g"], "142,500.00")
        self.assertEqual(
            results["form_106_ef"]["creditors"][0]["name"],
            "Internal Revenue Service",
        )
        self.assertEqual(
            results["form_106_d"]["creditors"][0]["name"], "Ally Financial"
        )
        self.assertEqual(
            results["form_106_ab"]["cars_land_and_crafts"][1]["make"],
            "Chevrolet",
        )
