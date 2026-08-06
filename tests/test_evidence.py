"""Behaviour pinned for scripts/_evidence.py — the containment checks.

A snippet that is present and non-blank is not evidence. Evidence is a snippet
that *contains the value it is offered for*. Audit finding #14 is what happens
when one script enforces that and another does not: a cold agent worked a
balance out by subtraction, quoted it against a line of text with no number in
it, and was told the household owed SGD 0.00 against a letter saying SGD
360.00.

So the first thing pinned here is not a behaviour at all. It is that both
scripts call the *same function object*. Two implementations of one rule is two
answers that eventually disagree, and the finding is that they already did.

What these checks cannot do is verify that a snippet is verbatim. There is no
document text to diff against — only an image the model already looked at. They
catch a value quoted against text stating a different value, which is what
confabulation on a familiar-looking form looks like. They do not catch a
snippet invented whole, and nothing available offline would.
"""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"
MODULE = SCRIPTS / "_evidence.py"

sys.path.insert(0, str(SCRIPTS))

import _evidence  # noqa: E402
import insurance_claim_review as icr  # noqa: E402
import letter_record  # noqa: E402


class TestOneImplementation(unittest.TestCase):
    """The finding, stated as an assertion: one rule, one implementation."""

    def test_the_module_is_not_a_command(self):
        """A leading underscore keeps it out of the SKILL.md invocation rule.

        It is imported by scripts, never run by a person, and the manifest
        test's script glob skips underscore-prefixed files for that reason.
        """
        self.assertTrue(MODULE.is_file())
        self.assertNotIn("argparse", MODULE.read_text(encoding="utf-8"))

    def test_both_scripts_share_the_amount_check(self):
        self.assertIs(icr.snippet_has_amount, _evidence.snippet_has_amount)
        self.assertIs(letter_record.snippet_has_amount,
                      _evidence.snippet_has_amount)

    def test_both_scripts_share_the_date_check(self):
        self.assertIs(icr.snippet_has_date, _evidence.snippet_has_date)
        self.assertIs(letter_record.snippet_has_date, _evidence.snippet_has_date)

    def test_both_scripts_share_the_issuer_check(self):
        self.assertIs(icr.snippet_has_issuer, _evidence.snippet_has_issuer)
        self.assertIs(letter_record.snippet_has_issuer,
                      _evidence.snippet_has_issuer)

    def test_neither_script_reimplements_a_check(self):
        """Guards against the fix being undone by a helpful local copy."""
        for script in ("letter_record.py", "insurance_claim_review.py"):
            with self.subTest(script=script):
                body = (SCRIPTS / script).read_text(encoding="utf-8")
                self.assertNotIn("def snippet_has_", body)
                self.assertNotIn("def _snippet_has_", body)


class TestAmountContainment(unittest.TestCase):
    def test_a_grouped_figure_matches_the_plain_decimal(self):
        self.assertTrue(_evidence.snippet_has_amount(
            "Total hospital bill: SGD 4,820.00", Decimal("4820.00")))

    def test_trailing_zeroes_do_not_decide_it(self):
        """Decimal equality, not string equality: 1220 is 1220.00."""
        self.assertTrue(_evidence.snippet_has_amount(
            "Total: SGD 1,220", Decimal("1220.00")))

    def test_a_near_miss_is_not_a_match(self):
        self.assertFalse(_evidence.snippet_has_amount(
            "Total hospital bill: SGD 4,820.00", Decimal("4821.00")))

    def test_a_digit_substring_is_not_a_match(self):
        """482 appears inside 4,820 as characters; it is not the figure."""
        self.assertFalse(_evidence.snippet_has_amount(
            "Total hospital bill: SGD 4,820.00", Decimal("482.00")))

    def test_the_reproduction_from_finding_14(self):
        """The exact snippet that produced SGD 0.00 outstanding."""
        self.assertFalse(_evidence.snippet_has_amount(
            "The balance is payable by the policyholder", Decimal("360.00")))

    def test_prose_with_no_number_at_all_carries_no_amount(self):
        self.assertFalse(_evidence.snippet_has_amount(
            "the remainder falls to the family", Decimal("0.00")))

    def test_zero_still_has_to_be_printed_to_count(self):
        self.assertTrue(_evidence.snippet_has_amount(
            "Amount payable by us: SGD 0.00", Decimal("0.00")))

    def test_a_day_count_is_read_the_same_way(self):
        self.assertTrue(_evidence.snippet_has_days(
            "Claims must be submitted within 90 days of discharge.", 90))
        self.assertFalse(_evidence.snippet_has_days(
            "Claims must be submitted within 90 days of discharge.", 30))

    def test_a_window_with_no_number_is_refused(self):
        """'within a month' is a reading, not a quotation of 30."""
        self.assertFalse(_evidence.snippet_has_days(
            "Any appeal must be lodged within a month.", 30))


class TestDateContainment(unittest.TestCase):
    def test_a_month_written_short_is_evidence(self):
        self.assertTrue(_evidence.snippet_has_date(
            "Date of admission: 01 Jun 2026", date(2026, 6, 1)))

    def test_a_month_written_out_is_evidence(self):
        self.assertTrue(_evidence.snippet_has_date(
            "Issued on 28 July 2026", date(2026, 7, 28)))

    def test_an_all_numeric_date_is_evidence(self):
        self.assertTrue(_evidence.snippet_has_date(
            "Assessment date: 2026-07-20", date(2026, 7, 20)))

    def test_a_day_off_by_one_is_not_evidence(self):
        self.assertFalse(_evidence.snippet_has_date(
            "Date of admission: 01 Jun 2026", date(2026, 6, 2)))

    def test_a_transposed_day_and_month_is_not_evidence(self):
        """20 Jul against 02 Jul: the day is simply not on the page."""
        self.assertFalse(_evidence.snippet_has_date(
            "Assessment date: 02 Jul 2026", date(2026, 7, 20)))

    def test_the_wrong_year_is_not_evidence(self):
        self.assertFalse(_evidence.snippet_has_date(
            "Date of admission: 01 Jun 2026", date(2025, 6, 1)))

    def test_a_relative_window_is_not_a_date(self):
        """The reproduction from finding #14's sibling: a deadline computed in
        the model's head, quoted against the phrase it was computed from."""
        self.assertFalse(_evidence.snippet_has_date(
            "within 30 days of the date of this letter", date(2026, 8, 27)))


class TestIssuerContainment(unittest.TestCase):
    def test_case_and_company_suffix_do_not_decide_it(self):
        self.assertTrue(_evidence.snippet_has_issuer(
            "GREAT EASTERN LIFE ASSURANCE COMPANY LIMITED", "Great Eastern"))

    def test_a_suffix_in_the_name_but_not_on_the_page_is_forgiven(self):
        self.assertTrue(_evidence.snippet_has_issuer(
            "GREAT EASTERN LIFE ASSURANCE", "Great Eastern Pte Ltd"))

    def test_a_missing_word_is_not_forgiven(self):
        self.assertFalse(_evidence.snippet_has_issuer(
            "EASTERN LIFE ASSURANCE", "Great Eastern"))

    def test_a_different_insurer_is_not_evidence(self):
        self.assertFalse(_evidence.snippet_has_issuer(
            "GREAT EASTERN LIFE ASSURANCE", "NTUC Income"))


if __name__ == "__main__":
    unittest.main()
