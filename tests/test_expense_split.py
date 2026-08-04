"""Behaviour pinned for scripts/expense_split.py.

Every case in docs/AUDIT-FINDINGS.md section 1 has a test here, plus the
failure paths that section says were never exercised.
"""

import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "care-coordinator-toolkit" / "scripts" / "expense_split.py"

sys.path.insert(0, str(SCRIPT.parent))

import expense_split  # noqa: E402


def payload(expenses=None, split_rule=None, members=None, as_of="2026-08-04"):
    doc = {
        "as_of": as_of,
        "members": members if members is not None else [
            {"id": "older-brother"},
            {"id": "younger-sister"},
        ],
        "expenses": expenses if expenses is not None else [],
        "split_rule": split_rule if split_rule is not None else {"mode": "even"},
    }
    return doc


def run(doc):
    """Round-trip through JSON so tests see exactly what the CLI would parse."""
    return expense_split.split_expenses(json.loads(json.dumps(doc), parse_float=Decimal))


def shares(result):
    return {s["member_id"]: Decimal(s["share"]) for s in result["splits"]}


THREE = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
ONE_EXPENSE = [
    {"id": "e1", "amount": 123.70, "paid_by": "a", "description": "GP visit"}
]
ONE_EXPENSE_FOR_TWO = [
    {"id": "e1", "amount": 123.70, "paid_by": "older-brother"}
]


class TestEvenSplit(unittest.TestCase):
    def test_residual_cent_goes_to_first_member_by_id_and_total_is_exact(self):
        result = run(payload(expenses=ONE_EXPENSE, members=THREE))
        self.assertEqual(shares(result), {
            "a": Decimal("41.24"),
            "b": Decimal("41.23"),
            "c": Decimal("41.23"),
        })
        self.assertEqual(sum(shares(result).values()), Decimal("123.70"))
        self.assertEqual(result["residual_cents"], 1)

    def test_residual_absorbed_is_reported_per_member(self):
        result = run(payload(expenses=ONE_EXPENSE, members=THREE))
        absorbed = {s["member_id"]: s["residual_cents_absorbed"]
                    for s in result["splits"]}
        self.assertEqual(absorbed, {"a": 1, "b": 0, "c": 0})

    def test_no_expenses_yields_zero_shares_not_an_error(self):
        result = run(payload(expenses=[], members=THREE))
        self.assertEqual(result["total"], "0.00")
        self.assertEqual(set(shares(result).values()), {Decimal("0.00")})
        self.assertEqual(result["residual_cents"], 0)

    def test_two_residual_cents_spread_across_two_members(self):
        # 10.00 across 3 -> 3.3333 each; 333+333+333 = 999, one cent short.
        # 10.01 across 3 -> 1001 cents, floors 333/333/333 = 999, two short.
        exp = [{"id": "e1", "amount": 10.01, "paid_by": "a"}]
        result = run(payload(expenses=exp, members=THREE))
        self.assertEqual(result["residual_cents"], 2)
        self.assertEqual(shares(result), {
            "a": Decimal("3.34"),
            "b": Decimal("3.34"),
            "c": Decimal("3.33"),
        })
        self.assertEqual(sum(shares(result).values()), Decimal("10.01"))


class TestWeightedSplit(unittest.TestCase):
    """The CRITICAL finding: weights were accepted and never applied."""

    def test_eighty_twenty_is_actually_applied(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 0.8, "younger-sister": 0.2}}
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))
        self.assertEqual(shares(result), {
            "older-brother": Decimal("98.96"),
            "younger-sister": Decimal("24.74"),
        })
        self.assertEqual(sum(shares(result).values()), Decimal("123.70"))

    def test_seventy_thirty_sums_exactly_to_total(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 0.7, "younger-sister": 0.3}}
        exp = [{"id": "e1", "amount": 100.01, "paid_by": "older-brother"}]
        result = run(payload(expenses=exp, split_rule=rule))
        self.assertEqual(sum(shares(result).values()), Decimal("100.01"))

    def test_weights_not_summing_to_one_is_rejected_loudly(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 0.7, "younger-sister": 0.35}}
        with self.assertRaises(expense_split.InvalidInput) as ctx:
            run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))
        self.assertIn("sum", str(ctx.exception).lower())

    def test_zero_weight_member_gets_nothing_and_absorbs_no_residual(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 1, "younger-sister": 0}}
        exp = [{"id": "e1", "amount": 10.01, "paid_by": "older-brother"}]
        result = run(payload(expenses=exp, split_rule=rule))
        self.assertEqual(shares(result)["younger-sister"], Decimal("0.00"))
        self.assertEqual(shares(result)["older-brother"], Decimal("10.01"))

    def test_negative_weight_is_rejected(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 1.2, "younger-sister": -0.2}}
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))

    def test_missing_member_in_weights_is_rejected(self):
        rule = {"mode": "weighted", "weights": {"older-brother": 1.0}}
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))

    def test_unknown_member_in_weights_is_rejected(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 0.5, "younger-sister": 0.4,
                            "ghost-cousin": 0.1}}
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))

    def test_weights_as_given_and_applied_are_both_reported(self):
        rule = {"mode": "weighted",
                "weights": {"older-brother": 0.8, "younger-sister": 0.2}}
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))
        self.assertEqual(result["split_rule"]["weights_as_given"],
                         {"older-brother": "0.8", "younger-sister": "0.2"})
        self.assertEqual(result["split_rule"]["weights_applied"],
                         {"older-brother": "0.8", "younger-sister": "0.2"})
        self.assertFalse(result["split_rule"]["normalised"])


class TestRatioSplit(unittest.TestCase):
    def test_two_to_one_normalises_and_reports_both_forms(self):
        rule = {"mode": "ratio",
                "weights": {"older-brother": 2, "younger-sister": 1}}
        exp = [{"id": "e1", "amount": 90.00, "paid_by": "older-brother"}]
        result = run(payload(expenses=exp, split_rule=rule))
        self.assertEqual(shares(result), {
            "older-brother": Decimal("60.00"),
            "younger-sister": Decimal("30.00"),
        })
        self.assertTrue(result["split_rule"]["normalised"])
        self.assertEqual(result["split_rule"]["weights_as_given"],
                         {"older-brother": "2", "younger-sister": "1"})

    def test_thirds_still_sum_exactly_to_total(self):
        rule = {"mode": "ratio", "weights": {"a": 1, "b": 1, "c": 1}}
        exp = [{"id": "e1", "amount": 123.70, "paid_by": "a"}]
        result = run(payload(expenses=exp, members=THREE, split_rule=rule))
        self.assertEqual(sum(shares(result).values()), Decimal("123.70"))

    def test_all_zero_ratio_is_rejected(self):
        rule = {"mode": "ratio",
                "weights": {"older-brother": 0, "younger-sister": 0}}
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=ONE_EXPENSE_FOR_TWO, split_rule=rule))


class TestUnmatchedPayer(unittest.TestCase):
    """The vanishing-money finding: paid_by matching no member."""

    def test_unmatched_payer_raises_rather_than_silently_dropping(self):
        exp = [{"id": "e1", "amount": 50.00, "paid_by": "cousin-who-helped"}]
        with self.assertRaises(expense_split.InvalidInput) as ctx:
            run(payload(expenses=exp))
        self.assertIn("cousin-who-helped", str(ctx.exception))

    def test_matched_payer_paid_totals_are_attributed(self):
        exp = [
            {"id": "e1", "amount": 100.00, "paid_by": "older-brother"},
            {"id": "e2", "amount": 50.00, "paid_by": "younger-sister"},
        ]
        result = run(payload(expenses=exp))
        paid = {s["member_id"]: Decimal(s["paid"]) for s in result["splits"]}
        self.assertEqual(paid, {"older-brother": Decimal("100.00"),
                                "younger-sister": Decimal("50.00")})

    def test_balance_is_paid_minus_share(self):
        exp = [{"id": "e1", "amount": 100.00, "paid_by": "older-brother"}]
        result = run(payload(expenses=exp))
        balances = {s["member_id"]: Decimal(s["balance"])
                    for s in result["splits"]}
        self.assertEqual(balances, {"older-brother": Decimal("50.00"),
                                    "younger-sister": Decimal("-50.00")})
        self.assertEqual(sum(balances.values()), Decimal("0.00"))


class TestMoneyPrecision(unittest.TestCase):
    def test_binary_float_amount_is_rejected(self):
        doc = payload(expenses=[{"id": "e1", "amount": 123.70,
                                 "paid_by": "older-brother"}])
        # Bypass the parse_float=Decimal boundary: a genuine float object.
        doc["expenses"][0]["amount"] = 123.70
        with self.assertRaises(expense_split.InvalidInput) as ctx:
            expense_split.split_expenses(doc)
        self.assertIn("float", str(ctx.exception).lower())

    def test_string_amount_is_accepted(self):
        exp = [{"id": "e1", "amount": "123.70", "paid_by": "older-brother"}]
        result = run(payload(expenses=exp))
        self.assertEqual(result["total"], "123.70")

    def test_three_decimal_places_is_rejected(self):
        exp = [{"id": "e1", "amount": "10.005", "paid_by": "older-brother"}]
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=exp))

    def test_negative_amount_is_rejected(self):
        exp = [{"id": "e1", "amount": "-10.00", "paid_by": "older-brother"}]
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=exp))

    def test_non_numeric_amount_is_rejected(self):
        exp = [{"id": "e1", "amount": "twenty dollars",
                "paid_by": "older-brother"}]
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=exp))

    def test_total_is_a_string_not_a_float(self):
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO))
        self.assertIsInstance(result["total"], str)
        for s in result["splits"]:
            self.assertIsInstance(s["share"], str)


class TestStructuralValidation(unittest.TestCase):
    def test_empty_members_is_rejected(self):
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(members=[]))

    def test_duplicate_member_ids_are_rejected(self):
        dup = [{"id": "a"}, {"id": "a"}]
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(members=dup))

    def test_member_without_id_is_rejected(self):
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(members=[{"name": "Ah Seng"}, {"id": "b"}]))

    def test_duplicate_expense_ids_are_rejected(self):
        exp = [
            {"id": "e1", "amount": "10.00", "paid_by": "older-brother"},
            {"id": "e1", "amount": "10.00", "paid_by": "older-brother"},
        ]
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=exp))

    def test_unknown_split_mode_is_rejected(self):
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(split_rule={"mode": "proportional-to-income"}))

    def test_missing_split_rule_is_rejected(self):
        doc = payload()
        del doc["split_rule"]
        with self.assertRaises(expense_split.InvalidInput):
            run(doc)

    def test_expense_missing_paid_by_is_rejected(self):
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(expenses=[{"id": "e1", "amount": "10.00"}]))

    def test_expense_dated_after_as_of_is_rejected(self):
        exp = [{"id": "e1", "amount": "10.00", "paid_by": "older-brother",
                "date": "2026-08-05"}]
        with self.assertRaises(expense_split.InvalidInput) as ctx:
            run(payload(expenses=exp, as_of="2026-08-04"))
        self.assertIn("2026-08-05", str(ctx.exception))

    def test_expense_dated_on_as_of_is_accepted(self):
        exp = [{"id": "e1", "amount": "10.00", "paid_by": "older-brother",
                "date": "2026-08-04"}]
        result = run(payload(expenses=exp, as_of="2026-08-04"))
        self.assertEqual(result["total"], "10.00")

    def test_malformed_as_of_is_rejected(self):
        with self.assertRaises(expense_split.InvalidInput):
            run(payload(as_of="4 Aug 2026"))

    def test_absent_as_of_defaults_and_is_echoed(self):
        doc = payload()
        del doc["as_of"]
        result = run(doc)
        self.assertRegex(result["as_of"], r"^\d{4}-\d{2}-\d{2}$")


class TestEnvelope(unittest.TestCase):
    def test_carries_tool_run_id_and_sg_issued_at(self):
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO))
        self.assertRegex(result["tool_run_id"],
                         r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-")
        self.assertTrue(result["issued_at"].endswith("+08:00"))

    def test_residual_rule_is_stated_in_the_output(self):
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO))
        self.assertIn("largest", result["residual_rule"])

    def test_expenses_counted_is_reported(self):
        exp = [
            {"id": "e1", "amount": "10.00", "paid_by": "older-brother"},
            {"id": "e2", "amount": "10.00", "paid_by": "younger-sister"},
        ]
        result = run(payload(expenses=exp))
        self.assertEqual(result["expenses_counted"], 2)


class TestAuditHash(unittest.TestCase):
    def test_identical_input_produces_identical_hash_across_runs(self):
        doc = payload(expenses=ONE_EXPENSE_FOR_TWO)
        a = run(doc)
        b = run(doc)
        self.assertNotEqual(a["tool_run_id"], b["tool_run_id"])
        self.assertEqual(a["audit_hash"], b["audit_hash"])

    def test_hash_changes_when_weights_change_the_shares(self):
        even = run(payload(expenses=ONE_EXPENSE_FOR_TWO))
        weighted = run(payload(
            expenses=ONE_EXPENSE_FOR_TWO,
            split_rule={"mode": "weighted",
                        "weights": {"older-brother": 0.8,
                                    "younger-sister": 0.2}}))
        self.assertNotEqual(even["audit_hash"], weighted["audit_hash"])

    def test_hash_covers_computed_shares_not_only_inputs(self):
        result = run(payload(expenses=ONE_EXPENSE_FOR_TWO))
        tampered = json.loads(json.dumps(result))
        tampered["splits"][0]["share"] = "999.99"
        self.assertNotEqual(expense_split.audit_hash_of(tampered),
                            tampered["audit_hash"])


class TestCommandLine(unittest.TestCase):
    def test_stdin_to_stdout_emits_only_json_on_stdout(self):
        doc = payload(expenses=ONE_EXPENSE_FOR_TWO)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(doc), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed["total"], "123.70")

    def test_invalid_input_exits_non_zero_with_nothing_on_stdout(self):
        doc = payload(expenses=[{"id": "e1", "amount": "10.00",
                                 "paid_by": "nobody"}])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(doc), capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("nobody", proc.stderr)

    def test_output_file_is_written_utf8_and_stdout_stays_clean(self):
        import tempfile
        doc = payload(
            expenses=[{"id": "e1", "amount": "123.70",
                       "paid_by": "older-brother",
                       "description": "陈奶奶 GP visit"}])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(out)],
                input=json.dumps(doc), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["total"], "123.70")

    def test_input_file_flag(self):
        import tempfile
        doc = payload(expenses=ONE_EXPENSE_FOR_TWO)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.json"
            src.write_text(json.dumps(doc), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(src)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["total"], "123.70")

    def test_missing_input_file_exits_non_zero(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", "/no/such/file.json"],
            capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
