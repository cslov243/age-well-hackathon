"""Behaviour pinned for scripts/medication_runout.py.

docs/AUDIT-FINDINGS.md section 2 lists three defects. Each has a test here:

  * banker's rounding made 15 and 17 tablets produce the same run-out date,
    and rounded 7.5 days *up* to 8;
  * dates came from `as_of` while status came from the wall clock, so nothing
    replayed;
  * a bare day count never said whether today's doses were already taken.

Plus the failure paths, which is what section 2 says was never exercised.
"""

import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = (REPO / "skills" / "care-coordinator-toolkit" / "scripts"
          / "medication_runout.py")

sys.path.insert(0, str(SCRIPT.parent))

import medication_runout  # noqa: E402

PENDING = "doses_on_count_day_pending"
TAKEN = "doses_on_count_day_taken"


def med(quantity, *, mid="metformin-500", name="Metformin 500mg",
        form="tablet", doses_per_day=2, units_per_dose="1",
        count_basis=PENDING, counted_on=None, lead_time_days=None,
        form_plural=None):
    entry = {
        "id": mid,
        "name": name,
        "form": form,
        "quantity_on_hand": quantity,
        "count_basis": count_basis,
        "schedule": {
            "mode": "fixed_daily",
            "units_per_dose": units_per_dose,
            "doses_per_day": doses_per_day,
        },
    }
    if counted_on is not None:
        entry["counted_on"] = counted_on
    if lead_time_days is not None:
        entry["lead_time_days"] = lead_time_days
    if form_plural is not None:
        entry["form_plural"] = form_plural
    return entry


def prn(quantity="12", *, mid="paracetamol-500", name="Paracetamol 500mg",
        form="tablet", **extra):
    entry = {
        "id": mid,
        "name": name,
        "form": form,
        "quantity_on_hand": quantity,
        "schedule": {"mode": "prn"},
    }
    entry.update(extra)
    return entry


def payload(medications=None, *, as_of="2026-08-03", lead_time=7):
    doc = {"as_of": as_of, "medications": medications or []}
    if lead_time is not None:
        doc["default_lead_time_days"] = lead_time
    return doc


def run(doc):
    """Round-trip through JSON so tests see exactly what the CLI would parse."""
    return medication_runout.forecast_runout(
        json.loads(json.dumps(doc), parse_float=Decimal)
    )


def only(result):
    self_check = result["forecast"]
    assert len(self_check) == 1, self_check
    return self_check[0]


# ---------------------------------------------------------------------------
# docs/AUDIT-FINDINGS.md section 2 — the rounding defect
# ---------------------------------------------------------------------------

class TestFloorNeverRoundsSupplyUp(unittest.TestCase):
    def test_13_15_17_tablets_give_three_distinct_last_days(self):
        """The reported defect: 15 and 17 produced the same date."""
        days = {}
        for quantity in ("13", "15", "17"):
            entry = only(run(payload([med(quantity)])))
            days[quantity] = entry["last_full_dose_day"]
        self.assertEqual(days, {
            "13": "2026-08-08",
            "15": "2026-08-09",
            "17": "2026-08-10",
        })
        self.assertEqual(len(set(days.values())), 3)

    def test_seven_and_a_half_days_floors_to_seven_never_eight(self):
        entry = only(run(payload([med("15")])))
        self.assertEqual(entry["days_of_supply"], 7)
        self.assertEqual(entry["leftover_units"], "1")

    def test_exact_boundary_is_not_nudged_upward(self):
        """14 tablets at 2/day is exactly 7.0 days, with nothing left over."""
        entry = only(run(payload([med("14")])))
        self.assertEqual(entry["days_of_supply"], 7)
        self.assertEqual(entry["leftover_units"], "0")
        self.assertEqual(entry["last_full_dose_day"], "2026-08-09")

    def test_one_unit_short_of_a_day_loses_the_whole_day(self):
        entry = only(run(payload([med("13")])))
        self.assertEqual(entry["days_of_supply"], 6)
        self.assertEqual(entry["last_full_dose_day"], "2026-08-08")

    def test_half_tablet_doses_stay_exact(self):
        """0.5 as a binary float is the error class that caused the finding."""
        entry = only(run(payload([
            med("7", units_per_dose="0.5", doses_per_day=1)
        ])))
        self.assertEqual(entry["units_per_day"], "0.5")
        self.assertEqual(entry["days_of_supply"], 14)
        self.assertEqual(entry["leftover_units"], "0")

    def test_thirds_of_a_unit_do_not_accumulate_error(self):
        entry = only(run(payload([
            med("100", units_per_dose="1", doses_per_day=3)
        ])))
        self.assertEqual(entry["units_per_day"], "3")
        self.assertEqual(entry["days_of_supply"], 33)
        self.assertEqual(entry["leftover_units"], "1")

    def test_runs_out_on_is_the_day_after_the_last_full_day(self):
        entry = only(run(payload([med("15")])))
        self.assertEqual(entry["last_full_dose_day"], "2026-08-09")
        self.assertEqual(entry["runs_out_on"], "2026-08-10")


# ---------------------------------------------------------------------------
# The dose-boundary convention
# ---------------------------------------------------------------------------

class TestCountBasis(unittest.TestCase):
    def test_missing_count_basis_is_refused_not_defaulted(self):
        entry = med("15")
        del entry["count_basis"]
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([entry]))
        self.assertIn("count_basis", str(ctx.exception))

    def test_taken_and_pending_differ_by_exactly_one_day(self):
        pending = only(run(payload([med("15", count_basis=PENDING)])))
        taken = only(run(payload([med("15", count_basis=TAKEN)])))
        self.assertEqual(pending["last_full_dose_day"], "2026-08-09")
        self.assertEqual(taken["last_full_dose_day"], "2026-08-10")
        self.assertEqual(pending["days_of_supply"], taken["days_of_supply"])

    def test_unknown_count_basis_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15", count_basis="probably_taken")]))

    def test_summary_states_the_convention_in_words(self):
        taken = only(run(payload([med("15", count_basis=TAKEN)])))
        self.assertIn("already been taken", taken["summary"])
        pending = only(run(payload([med("15", count_basis=PENDING)])))
        self.assertIn("not yet been taken", pending["summary"])

    def test_summary_carries_dates_not_a_bare_day_count(self):
        entry = only(run(payload([med("15")])))
        self.assertIn("9 Aug 2026", entry["summary"])
        self.assertIn("10 Aug 2026", entry["summary"])

    def test_coverage_start_reflects_the_basis(self):
        pending = only(run(payload([med("15", count_basis=PENDING)])))
        taken = only(run(payload([med("15", count_basis=TAKEN)])))
        self.assertEqual(pending["coverage_starts_on"], "2026-08-03")
        self.assertEqual(taken["coverage_starts_on"], "2026-08-04")


# ---------------------------------------------------------------------------
# A stale count is supply already consumed
# ---------------------------------------------------------------------------

class TestCountedOn(unittest.TestCase):
    def test_counted_on_defaults_to_as_of(self):
        entry = only(run(payload([med("15")])))
        self.assertEqual(entry["counted_on"], "2026-08-03")

    def test_a_stale_count_does_not_extend_the_run_out_date(self):
        """Counting on 1 Aug and running on 3 Aug must not buy two extra days."""
        fresh = only(run(payload([med("15", counted_on="2026-08-03")])))
        stale = only(run(payload([med("15", counted_on="2026-08-01")])))
        self.assertEqual(fresh["last_full_dose_day"], "2026-08-09")
        self.assertEqual(stale["last_full_dose_day"], "2026-08-07")

    def test_a_stale_count_reduces_days_remaining_not_days_of_supply(self):
        stale = only(run(payload([med("15", counted_on="2026-08-01")])))
        self.assertEqual(stale["days_of_supply"], 7)
        self.assertEqual(stale["full_dose_days_remaining"], 5)

    def test_counted_on_after_as_of_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([med("15", counted_on="2026-08-04")]))
        self.assertIn("counted_on", str(ctx.exception))

    def test_a_count_stale_enough_to_be_exhausted_reports_no_supply(self):
        entry = only(run(payload([med("4", counted_on="2026-07-01")])))
        self.assertEqual(entry["status"], "no_supply")
        self.assertEqual(entry["full_dose_days_remaining"], 0)


# ---------------------------------------------------------------------------
# One resolved as_of drives every date and every status
# ---------------------------------------------------------------------------

class TestAsOfDrivesEverything(unittest.TestCase):
    def test_historical_as_of_gives_historical_status_not_present_urgency(self):
        """The finding: past dates carried present-tense urgency."""
        entry = only(run(payload([med("15")], as_of="2020-01-01")))
        self.assertEqual(entry["last_full_dose_day"], "2020-01-07")
        self.assertEqual(entry["order_by"], "2020-01-01")
        self.assertEqual(entry["status"], "order_now")

    def test_same_input_replays_to_the_same_audit_hash(self):
        first = run(payload([med("15")]))
        second = run(payload([med("15")]))
        self.assertEqual(first["audit_hash"], second["audit_hash"])
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])

    def test_audit_hash_excludes_run_id_and_issued_at(self):
        result = run(payload([med("15")]))
        recomputed = dict(result)
        recomputed["tool_run_id"] = "different"
        recomputed["issued_at"] = "1999-01-01T00:00:00+08:00"
        self.assertEqual(
            medication_runout.audit_hash_of(recomputed), result["audit_hash"]
        )

    def test_audit_hash_covers_the_computed_output_not_only_the_input(self):
        result = run(payload([med("15")]))
        tampered = json.loads(json.dumps(result))
        tampered["forecast"][0]["last_full_dose_day"] = "2026-09-09"
        self.assertNotEqual(
            medication_runout.audit_hash_of(tampered), result["audit_hash"]
        )

    def test_as_of_absent_resolves_once_and_is_reported(self):
        doc = {"default_lead_time_days": 7, "medications": [med("15")]}
        result = run(doc)
        self.assertEqual(result["as_of"], result["forecast"][0]["counted_on"])

    def test_envelope_carries_sg_offset(self):
        result = run(payload([med("15")]))
        self.assertTrue(result["issued_at"].endswith("+08:00"))
        self.assertEqual(result["as_of"], "2026-08-03")


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    def test_ok_when_order_by_is_in_the_future(self):
        entry = only(run(payload([med("40")])))
        self.assertEqual(entry["status"], "ok")

    def test_order_now_when_order_by_equals_as_of(self):
        # 15 tablets, pending basis: runs out 10 Aug, lead 7 -> order by 3 Aug.
        entry = only(run(payload([med("15")])))
        self.assertEqual(entry["order_by"], "2026-08-03")
        self.assertEqual(entry["status"], "order_now")

    def test_order_overdue_when_order_by_has_passed(self):
        # 11 tablets, pending basis: runs out 8 Aug, lead 7 -> order by 1 Aug.
        entry = only(run(payload([med("11")])))
        self.assertEqual(entry["order_by"], "2026-08-01")
        self.assertEqual(entry["status"], "order_overdue")

    def test_no_supply_when_nothing_is_left_at_as_of(self):
        entry = only(run(payload([med("0")])))
        self.assertEqual(entry["status"], "no_supply")
        self.assertEqual(entry["days_of_supply"], 0)
        self.assertEqual(entry["runs_out_on"], "2026-08-03")

    def test_no_supply_wins_over_order_overdue(self):
        entry = only(run(payload([med("1")])))
        self.assertEqual(entry["status"], "no_supply")

    def test_status_vocabulary_is_closed(self):
        allowed = {"ok", "order_now", "order_overdue", "no_supply"}
        result = run(payload([med("0"), med("1", mid="b"),
                              med("15", mid="c"), med("40", mid="d")]))
        self.assertTrue(
            {e["status"] for e in result["forecast"]}.issubset(allowed)
        )

    def test_no_clinical_language_in_any_summary(self):
        result = run(payload([med("0"), med("15", mid="b"),
                              med("40", mid="c")], ))
        banned = ("you should", "urgent", "danger", "risk", "dose adjust",
                  "consult", "skip", "recommend")
        for entry in result["forecast"]:
            lowered = entry["summary"].lower()
            for phrase in banned:
                self.assertNotIn(phrase, lowered)


# ---------------------------------------------------------------------------
# Lead time
# ---------------------------------------------------------------------------

class TestLeadTime(unittest.TestCase):
    def test_missing_default_lead_time_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([med("15")], lead_time=None))
        self.assertIn("default_lead_time_days", str(ctx.exception))

    def test_per_medication_lead_time_overrides_the_default(self):
        entry = only(run(payload([med("15", lead_time_days=2)])))
        self.assertEqual(entry["lead_time_days"], 2)
        self.assertEqual(entry["lead_time_source"], "medication")
        self.assertEqual(entry["order_by"], "2026-08-08")

    def test_default_lead_time_is_reported_as_such(self):
        entry = only(run(payload([med("15")])))
        self.assertEqual(entry["lead_time_source"], "default")

    def test_zero_lead_time_makes_order_by_equal_run_out(self):
        entry = only(run(payload([med("15", lead_time_days=0)])))
        self.assertEqual(entry["order_by"], entry["runs_out_on"])

    def test_negative_lead_time_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15", lead_time_days=-1)]))

    def test_fractional_lead_time_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15", lead_time_days="2.5")]))

    def test_order_by_rule_is_stated_in_the_output(self):
        result = run(payload([med("15")]))
        self.assertIn("lead_time_days", result["conventions"]["order_by"])


# ---------------------------------------------------------------------------
# PRN
# ---------------------------------------------------------------------------

class TestPrn(unittest.TestCase):
    def test_prn_is_excluded_from_the_forecast(self):
        result = run(payload([med("15"), prn()]))
        self.assertEqual([e["id"] for e in result["forecast"]],
                         ["metformin-500"])

    def test_prn_is_reported_separately_with_a_reason(self):
        result = run(payload([prn()]))
        self.assertEqual(len(result["not_forecast"]), 1)
        entry = result["not_forecast"][0]
        self.assertEqual(entry["reason"], "prn_no_fixed_rate")
        self.assertEqual(entry["quantity_on_hand"], "12")

    def test_prn_carries_no_dates_at_all(self):
        entry = run(payload([prn()]))["not_forecast"][0]
        for field in ("runs_out_on", "order_by", "last_full_dose_day",
                      "status", "days_of_supply"):
            self.assertNotIn(field, entry)

    def test_prn_summary_says_no_date_is_forecast(self):
        entry = run(payload([prn()]))["not_forecast"][0]
        self.assertIn("no run-out date", entry["summary"].lower())

    def test_prn_with_a_lead_time_is_refused_rather_than_ignored(self):
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([prn(lead_time_days=5)]))
        self.assertIn("lead_time_days", str(ctx.exception))

    def test_prn_with_a_count_basis_is_refused_rather_than_ignored(self):
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([prn(count_basis=PENDING)]))
        self.assertIn("count_basis", str(ctx.exception))

    def test_prn_with_a_dose_rate_is_refused(self):
        entry = prn()
        entry["schedule"] = {"mode": "prn", "doses_per_day": 2}
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([entry]))

    def test_prn_only_input_still_requires_a_default_lead_time(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([prn()], lead_time=None))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_binary_float_quantity_is_refused_not_coerced(self):
        doc = payload([med("15")])
        doc["medications"][0]["quantity_on_hand"] = 15.5  # a real Python float
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            medication_runout.forecast_runout(doc)
        self.assertIn("float", str(ctx.exception))

    def test_json_float_parsed_as_decimal_is_accepted(self):
        entry = only(run(payload([med(7.5, units_per_dose="0.5",
                                      doses_per_day=1)])))
        self.assertEqual(entry["days_of_supply"], 15)

    def test_negative_quantity_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("-1")]))

    def test_zero_doses_per_day_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15", doses_per_day=0)]))

    def test_negative_units_per_dose_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15", units_per_dose="-1")]))

    def test_unknown_schedule_mode_is_refused(self):
        entry = med("15")
        entry["schedule"] = {"mode": "weekly"}
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([entry]))

    def test_missing_schedule_is_refused(self):
        entry = med("15")
        del entry["schedule"]
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([entry]))

    def test_duplicate_medication_id_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run(payload([med("15"), med("20")]))
        self.assertIn("duplicate", str(ctx.exception))

    def test_missing_name_is_refused(self):
        entry = med("15")
        del entry["name"]
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([entry]))

    def test_missing_form_is_refused(self):
        entry = med("15")
        del entry["form"]
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([entry]))

    def test_non_object_input_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            medication_runout.forecast_runout([])

    def test_medications_must_be_a_list(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run({"as_of": "2026-08-03", "default_lead_time_days": 7,
                 "medications": {}})

    def test_absent_medications_key_is_refused_not_treated_as_empty(self):
        """Found in self-review: a typo'd key would exit 0 forecasting nothing."""
        with self.assertRaises(medication_runout.InvalidInput) as ctx:
            run({"as_of": "2026-08-03", "default_lead_time_days": 7,
                 "medication": [med("15")]})
        self.assertIn("medications", str(ctx.exception))

    def test_empty_medication_list_is_not_an_error(self):
        result = run(payload([]))
        self.assertEqual(result["forecast"], [])
        self.assertEqual(result["not_forecast"], [])
        self.assertEqual(result["medications_counted"], 0)

    def test_malformed_as_of_is_refused(self):
        with self.assertRaises(medication_runout.InvalidInput):
            run(payload([med("15")], as_of="3 August 2026"))

    def test_boolean_quantity_is_refused(self):
        doc = payload([med("15")])
        doc["medications"][0]["quantity_on_hand"] = True
        with self.assertRaises(medication_runout.InvalidInput):
            medication_runout.forecast_runout(doc)


# ---------------------------------------------------------------------------
# Prose rendering
# ---------------------------------------------------------------------------

class TestSummaryText(unittest.TestCase):
    def test_form_plural_defaults_to_form_plus_s(self):
        entry = only(run(payload([med("15")])))
        self.assertIn("tablets", entry["summary"])

    def test_form_plural_can_be_supplied(self):
        entry = only(run(payload([med("15", form="ml", form_plural="ml")])))
        self.assertNotIn("mls", entry["summary"])

    def test_leftover_is_mentioned_only_when_non_zero(self):
        self.assertIn("left over", only(run(payload([med("15")])))["summary"])
        self.assertNotIn("left over",
                         only(run(payload([med("14")])))["summary"])

    def test_no_supply_summary_says_so(self):
        entry = only(run(payload([med("0")])))
        self.assertIn("no ", entry["summary"].lower())

    def test_a_single_unit_is_not_pluralised(self):
        """Found in self-review: '1 tablets left over' shipped in draft 1."""
        entry = only(run(payload([med("15")])))
        self.assertIn("1 tablet left over", entry["summary"])
        self.assertNotIn("1 tablets", entry["summary"])

    def test_a_once_daily_rate_is_not_pluralised(self):
        entry = only(run(payload([med("15", doses_per_day=1)])))
        self.assertIn("At 1 tablet a day", entry["summary"])

    def test_a_one_day_lead_time_is_not_pluralised(self):
        entry = only(run(payload([med("15", lead_time_days=1)])))
        self.assertIn("1 day lead time", entry["summary"])

    def test_summary_reads_as_a_sentence_not_a_double_verb(self):
        """Found in self-review: 'to have had already been taken'."""
        entry = only(run(payload([med("15", count_basis=TAKEN)])))
        self.assertNotIn("have had", entry["summary"])
        self.assertIn("that day's doses had already been taken",
                      entry["summary"])

    def test_order_by_appears_in_the_summary(self):
        entry = only(run(payload([med("40")])))
        self.assertIn("Order by", entry["summary"])


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

class TestCommandLine(unittest.TestCase):
    def _run(self, doc, extra=()):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra],
            input=json.dumps(doc), capture_output=True, text=True,
        )

    def test_stdout_is_json_only_and_logs_go_to_stderr(self):
        proc = self._run(payload([med("15")]))
        self.assertEqual(proc.returncode, 0)
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed["forecast"][0]["last_full_dose_day"],
                         "2026-08-09")
        self.assertIn("medication_runout", proc.stderr)

    def test_invalid_input_exits_two_with_no_stdout(self):
        proc = self._run(payload([med("15")], lead_time=None))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("default_lead_time_days", proc.stderr)

    def test_empty_stdin_is_refused(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], input="",
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)

    def test_output_file_is_written_as_utf8(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            doc = payload([med("15", name="二甲双胍")])
            proc = self._run(doc, extra=["--output", str(out)])
            self.assertEqual(proc.returncode, 0)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("二甲双胍",
                          written["forecast"][0]["summary"])

    def test_missing_input_file_is_refused(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", "/no/such/file.json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
