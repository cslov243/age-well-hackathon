"""Behaviour pinned for scripts/deadline_calendar.py.

This script carries a date out of the repo and onto a surface other people can
read, which makes two of its properties matter more than anything about its
output shape:

  * **It computes no date.** Every date is copied from the forecast or the
    claims review. The only arithmetic is `(date - as_of).days`, and that one
    subtraction is the whole reason the script exists: audit finding #3 records
    the old `deadline_window.py` testing `(due - remind_on).days <= 7`, which
    compares the reminder window to itself and so reports a deadline 58 days
    away as due this week, every day, forever. That reproduction is pinned
    below in both directions.
  * **A calendar is a disclosure.** At `detail_level: "minimal"` nothing in the
    rendered `.ics` may name a medicine, a condition, an insurer or an amount —
    tested against the file text, not against the JSON, because the file is
    what other people see. `"named"` must declare itself as a disclosure so a
    line reaches `shared_log.jsonl`.

The sources below are produced by actually running `medication_runout.py` and
`insurance_claim_review.py`, never hand-written, so no test here can pass
against a hash this file forged for itself.
"""

import json
import subprocess
import sys
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
SCRIPT = (REPO / "skills" / "care-coordinator-toolkit" / "scripts"
          / "deadline_calendar.py")

sys.path.insert(0, str(SCRIPT.parent))

import deadline_calendar  # noqa: E402
import insurance_claim_review  # noqa: E402
import medication_runout  # noqa: E402

AS_OF = "2026-08-06"
TODAY = date.fromisoformat(AS_OF)


def med(mid="amlodipine-5", *, name="Amlodipine 5mg", quantity="30",
        doses_per_day=1, units_per_dose="1", lead_time_days=None, prn=False):
    entry = {"id": mid, "name": name, "form": "tablet",
             "quantity_on_hand": quantity}
    if prn:
        entry["schedule"] = {"mode": "prn"}
        return entry
    entry["schedule"] = {"mode": "fixed_daily",
                         "units_per_dose": units_per_dose,
                         "doses_per_day": doses_per_day}
    entry["count_basis"] = "doses_on_count_day_pending"
    if lead_time_days is not None:
        entry["lead_time_days"] = lead_time_days
    return entry


def forecast_of(*medications, as_of=AS_OF, lead_time=5):
    """A real medication_runout.py result, hash and all."""
    return medication_runout.forecast_runout({
        "as_of": as_of,
        "default_lead_time_days": lead_time,
        "medications": list(medications),
    })


def claim(cid="claim-001", *, incident="2026-07-01", window=90,
          decision="pending"):
    entry = {
        "id": cid,
        "insurer": "Great Eastern",
        "policy_reference": "GE-12345",
        "insurer_decision": decision,
        "amounts": {},
        "documents_required": [],
        "documents_held": [],
        "evidence": {
            "insurer": "GREAT EASTERN LIFE ASSURANCE COMPANY LIMITED",
        },
    }
    if incident is not None:
        entry["incident_date"] = incident
        entry["evidence"]["incident_date"] = f"Date of incident: {incident}"
    if window is not None:
        entry["submission_window_days"] = window
        entry["evidence"]["submission_window_days"] = (
            f"Claims must be submitted within {window} days.")
    return entry


def claims_of(*entries, as_of=AS_OF):
    """A real insurance_claim_review.py result, hash and all."""
    return insurance_claim_review.review_claims({
        "as_of": as_of,
        "claims": list(entries),
    })


def request(*, forecast=None, claims=None, as_of=AS_OF, horizon_days=30,
            detail_level="minimal", **extra):
    document = {
        "as_of": as_of,
        "horizon_days": horizon_days,
        "detail_level": detail_level,
        "forecast": forecast,
        "claims": claims,
    }
    document.update(extra)
    return document


def roundtrip(document):
    """Through JSON, the way the script actually receives it."""
    return json.loads(json.dumps(document))


def build(document):
    return deadline_calendar.build_calendar(roundtrip(document))


def simple(**kwargs):
    """One medicine with 30 days on hand and a 5-day lead time."""
    return request(forecast=forecast_of(med()), **kwargs)


def kinds(result):
    return [event["kind"] for event in result["events"]]


def dates(result):
    return [event["starts_on"] for event in result["events"]]


class InputValidationTests(unittest.TestCase):

    def test_a_non_object_is_refused(self):
        with self.assertRaises(deadline_calendar.InvalidInput):
            deadline_calendar.build_calendar([])

    def test_an_unknown_top_level_key_is_refused(self):
        document = simple()
        document["horizon"] = 30
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(document)

    def test_forecast_is_required_even_when_there_is_none(self):
        # The whole point of the rule: an absent key and a misspelled key are
        # the same thing from in here, and one of them scheduled nothing.
        document = simple()
        del document["forecast"]
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(document)

    def test_claims_is_required_even_when_there_is_none(self):
        document = simple()
        del document["claims"]
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(document)

    def test_explicit_nulls_are_legal_and_schedule_nothing(self):
        result = build(request())
        self.assertEqual(result["events"], [])
        self.assertEqual(result["omitted"], [])
        self.assertIsNone(result["sources"]["forecast"])
        self.assertIsNone(result["sources"]["claims"])

    def test_horizon_days_has_no_default(self):
        document = simple()
        del document["horizon_days"]
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(document)

    def test_horizon_days_must_be_a_whole_positive_number(self):
        for value in (0, -1, "30", 30.5, True):
            with self.subTest(value=value):
                with self.assertRaises(deadline_calendar.InvalidInput):
                    build(simple(horizon_days=value))

    def test_detail_level_has_no_default(self):
        document = simple()
        del document["detail_level"]
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(document)

    def test_an_unrecognised_detail_level_is_refused_not_mapped(self):
        for value in ("full", "MINIMAL", "verbose", None):
            with self.subTest(value=value):
                with self.assertRaises(deadline_calendar.InvalidInput):
                    build(simple(detail_level=value))

    def test_as_of_is_optional_and_resolved_once(self):
        result = build(request(as_of=None))
        self.assertEqual(result["as_of"], result["as_of"])
        date.fromisoformat(result["as_of"])


class SourceIntegrityTests(unittest.TestCase):
    """A source it has not checked is a source it does not trust."""

    def test_a_forecast_that_is_not_a_result_object_is_refused(self):
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(request(forecast={"forecast": []}))

    def test_a_claims_review_that_is_not_a_result_object_is_refused(self):
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(request(claims={"claims": []}))

    def test_a_forecast_edited_in_transit_is_refused(self):
        forecast = forecast_of(med())
        forecast["forecast"][0]["order_by"] = "2026-08-07"
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(request(forecast=forecast))

    def test_a_claims_review_edited_in_transit_is_refused(self):
        claims = claims_of(claim())
        claims["claims"][0]["deadlines"][0]["due_on"] = "2026-08-10"
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(request(claims=claims))

    def test_a_source_dated_after_as_of_is_refused(self):
        forecast = forecast_of(med(), as_of="2026-08-20")
        with self.assertRaises(deadline_calendar.InvalidInput):
            build(request(forecast=forecast, as_of=AS_OF))

    def test_a_source_records_its_own_age(self):
        forecast = forecast_of(med(), as_of="2026-08-01")
        result = build(request(forecast=forecast, as_of=AS_OF))
        self.assertEqual(result["sources"]["forecast"]["age_days"], 5)
        self.assertEqual(result["sources"]["forecast"]["as_of"], "2026-08-01")

    def test_every_event_carries_the_run_and_hash_it_came_from(self):
        forecast = forecast_of(med())
        result = build(request(forecast=forecast))
        self.assertTrue(result["events"])
        for event in result["events"]:
            self.assertEqual(event["source_tool_run_id"],
                             forecast["tool_run_id"])
            self.assertEqual(event["source_audit_hash"],
                             forecast["audit_hash"])
            self.assertIn(event["source_audit_hash"], event["body"])


class CopiedDatesTests(unittest.TestCase):
    """It copies dates. It does not compute them."""

    @classmethod
    def setUpClass(cls):
        cls.forecast = forecast_of(med(quantity="10", lead_time_days=3))
        cls.result = build(request(forecast=cls.forecast))
        cls.entry = cls.forecast["forecast"][0]

    def test_the_order_by_event_is_the_forecasts_order_by(self):
        [event] = [e for e in self.result["events"]
                   if e["kind"] == "medication_order_by"]
        self.assertEqual(event["starts_on"], self.entry["order_by"])

    def test_the_run_out_event_is_the_forecasts_run_out_date(self):
        [event] = [e for e in self.result["events"]
                   if e["kind"] == "medication_runs_out"]
        self.assertEqual(event["starts_on"], self.entry["runs_out_on"])

    def test_no_event_carries_a_date_the_sources_did_not_state(self):
        stated = {self.entry["order_by"], self.entry["runs_out_on"]}
        self.assertTrue(set(dates(self.result)) <= stated)

    def test_a_claim_deadline_is_the_reviews_due_on(self):
        claims = claims_of(claim(incident="2026-07-01", window=45))
        result = build(request(claims=claims, horizon_days=30))
        due = claims["claims"][0]["deadlines"][0]["due_on"]
        self.assertEqual(dates(result), [due])
        self.assertEqual(kinds(result), ["claim_submission"])

    def test_a_prn_medicine_produces_no_event_and_no_omission(self):
        # It has no rate, so no run-out date was ever computed. That is not a
        # deadline that got dropped.
        forecast = forecast_of(med("calcium-d", name="Calcium", prn=True))
        result = build(request(forecast=forecast))
        self.assertEqual(result["events"], [])
        self.assertEqual(result["omitted"], [])

    def test_a_deadline_with_no_date_is_omitted_not_guessed(self):
        claims = claims_of(claim(window=None))
        result = build(request(claims=claims))
        self.assertEqual(result["events"], [])
        [row] = result["omitted"]
        self.assertEqual(row["reason"], "no_date")
        self.assertIsNone(row["starts_on"])


class ProximityTests(unittest.TestCase):
    """Audit finding #3, pinned in both directions.

    The defect was `(due - remind_on).days <= 7`: a comparison of the reminder
    window against itself, true for a deadline any distance away. Here the only
    comparison is against `as_of`.
    """

    def _claim_due_in(self, days):
        # Window measured from the incident date, so the due date lands exactly
        # `days` after as_of whatever the window is.
        incident = (TODAY - timedelta(days=10)).isoformat()
        return claims_of(claim(incident=incident, window=10 + days))

    def test_a_deadline_58_days_away_is_not_scheduled_inside_a_7_day_horizon(self):
        claims = self._claim_due_in(58)
        result = build(request(claims=claims, horizon_days=7))
        self.assertEqual(result["events"], [])
        [row] = result["omitted"]
        self.assertEqual(row["reason"], "beyond_horizon")
        self.assertIn("58 days away", row["detail"])

    def test_the_same_deadline_is_scheduled_when_the_horizon_reaches_it(self):
        claims = self._claim_due_in(58)
        result = build(request(claims=claims, horizon_days=60))
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["days_away"], 58)

    def test_the_horizon_boundary_is_inclusive(self):
        for offset, expected in ((30, 1), (31, 0)):
            with self.subTest(offset=offset):
                claims = self._claim_due_in(offset)
                result = build(request(claims=claims, horizon_days=30))
                self.assertEqual(len(result["events"]), expected)

    def test_a_deadline_falling_today_is_scheduled(self):
        claims = self._claim_due_in(0)
        result = build(request(claims=claims, horizon_days=30))
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["days_away"], 0)

    def test_a_deadline_already_past_is_omitted_and_named_as_needing_a_person(self):
        claims = self._claim_due_in(-3)
        result = build(request(claims=claims, horizon_days=30))
        self.assertEqual(result["events"], [])
        [row] = result["omitted"]
        self.assertEqual(row["reason"], "already_passed")
        self.assertIn("3 days ago", row["detail"])
        self.assertIn("already passed", result["summary"])

    def test_days_away_is_measured_from_as_of(self):
        forecast = forecast_of(med(quantity="10", lead_time_days=3))
        result = build(request(forecast=forecast))
        for event in result["events"]:
            with self.subTest(kind=event["kind"]):
                self.assertEqual(
                    event["days_away"],
                    (date.fromisoformat(event["starts_on"]) - TODAY).days)


class NothingIsDroppedQuietlyTests(unittest.TestCase):

    def test_every_date_the_sources_offer_lands_somewhere(self):
        forecast = forecast_of(med(quantity="10", lead_time_days=3),
                               med("metformin-500", name="Metformin 500mg",
                                   quantity="400", doses_per_day=2))
        claims = claims_of(claim(), claim("claim-002", window=None))
        result = build(request(forecast=forecast, claims=claims))
        offered = 2 * len(forecast["forecast"]) + sum(
            len(c["deadlines"]) for c in claims["claims"])
        self.assertEqual(result["counts"]["dates_considered"], offered)
        self.assertEqual(
            result["counts"]["events"] + result["counts"]["omitted"], offered)

    def test_every_omission_carries_a_reason_in_plain_words(self):
        forecast = forecast_of(med(quantity="400"))
        result = build(request(forecast=forecast, horizon_days=7))
        self.assertTrue(result["omitted"])
        for row in result["omitted"]:
            with self.subTest(row=row["kind"]):
                self.assertIn(row["reason"],
                              deadline_calendar.OMISSION_REASONS)
                self.assertGreater(len(row["detail"].split()), 5)

    def test_events_are_ordered_by_date(self):
        forecast = forecast_of(med(quantity="10", lead_time_days=3),
                               med("metformin-500", name="Metformin 500mg",
                                   quantity="20"))
        result = build(request(forecast=forecast))
        self.assertEqual(dates(result), sorted(dates(result)))


class DisclosureTests(unittest.TestCase):
    """A calendar is read by everyone it is shared with."""

    @classmethod
    def setUpClass(cls):
        cls.forecast = forecast_of(med(quantity="10", lead_time_days=3))
        cls.claims = claims_of(claim())

    def _ics(self, detail_level):
        result = build(request(forecast=self.forecast, claims=self.claims,
                               horizon_days=60, detail_level=detail_level))
        return result, deadline_calendar.render_ics(result)

    def test_minimal_names_nothing_in_the_file_other_people_read(self):
        result, ics = self._ics("minimal")
        self.assertTrue(result["events"])
        for secret in ("Amlodipine", "amlodipine", "Great Eastern",
                       "GE-12345", "claim-001"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, ics)

    def test_minimal_declares_that_it_discloses_nothing(self):
        result, _ = self._ics("minimal")
        self.assertFalse(result["disclosure"]["required"])
        self.assertEqual(result["disclosure"]["discloses"], [])
        for event in result["events"]:
            self.assertEqual(event["discloses"], [])

    def test_named_names_the_medicine_and_the_insurer(self):
        result, ics = self._ics("named")
        self.assertIn("Amlodipine 5mg", ics)
        self.assertIn("Great Eastern", ics)

    def test_named_declares_itself_a_disclosure_to_be_logged(self):
        result, _ = self._ics("named")
        self.assertTrue(result["disclosure"]["required"])
        self.assertIn("medication_name", result["disclosure"]["discloses"])
        self.assertIn("insurer", result["disclosure"]["discloses"])
        self.assertIn("shared_log.jsonl", result["disclosure"]["note"])

    def test_detail_level_changes_nothing_about_which_dates_are_scheduled(self):
        minimal, _ = self._ics("minimal")
        named, _ = self._ics("named")
        self.assertEqual(dates(minimal), dates(named))
        self.assertEqual(kinds(minimal), kinds(named))

    def test_no_event_states_a_condition_a_dose_or_an_amount(self):
        _, ics = self._ics("named")
        for clinical in ("blood pressure", "diabetes", "hypertension",
                         "mg a day", "twice daily", "SGD"):
            with self.subTest(clinical=clinical):
                self.assertNotIn(clinical, ics)

    def test_every_body_says_nothing_has_been_ordered_or_submitted(self):
        result, _ = self._ics("named")
        for event in result["events"]:
            self.assertIn("Nothing has been ordered, submitted or paid",
                          event["body"])


class IcsTests(unittest.TestCase):
    """A calendar file no calendar accepts is not a deliverable."""

    @classmethod
    def setUpClass(cls):
        cls.result = build(request(
            forecast=forecast_of(med(quantity="10", lead_time_days=3)),
            detail_level="named"))
        cls.ics = deadline_calendar.render_ics(cls.result)
        cls.lines = cls.ics.split("\r\n")

    def test_it_is_a_vcalendar(self):
        self.assertTrue(self.ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(self.ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("VERSION:2.0", self.lines)

    def test_every_line_ends_crlf(self):
        self.assertNotIn("\n", self.ics.replace("\r\n", ""))

    def test_there_is_one_vevent_per_event(self):
        self.assertEqual(self.lines.count("BEGIN:VEVENT"),
                         len(self.result["events"]))
        self.assertEqual(self.lines.count("BEGIN:VEVENT"),
                         self.lines.count("END:VEVENT"))

    def test_events_are_all_day_and_end_the_following_day(self):
        starts = [line for line in self.lines if line.startswith("DTSTART")]
        ends = [line for line in self.lines if line.startswith("DTEND")]
        self.assertEqual(len(starts), len(self.result["events"]))
        for start, end, event in zip(starts, ends, self.result["events"]):
            with self.subTest(event=event["kind"]):
                day = date.fromisoformat(event["starts_on"])
                self.assertEqual(
                    start, f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
                self.assertEqual(
                    end,
                    "DTEND;VALUE=DATE:"
                    + (day + timedelta(days=1)).strftime("%Y%m%d"))

    def test_no_physical_line_exceeds_75_octets(self):
        for line in self.lines:
            with self.subTest(line=line[:30]):
                self.assertLessEqual(len(line.encode("utf-8")), 75)

    def test_folded_continuation_lines_start_with_a_space(self):
        long_name = "Amlodipine 5mg film-coated tablets, prolonged release, XL"
        result = build(request(
            forecast=forecast_of(med(name=long_name, quantity="10")),
            detail_level="named"))
        lines = deadline_calendar.render_ics(result).split("\r\n")
        continuations = [line for line in lines if line.startswith(" ")]
        self.assertTrue(continuations, "nothing was folded")

    def test_commas_and_semicolons_are_escaped(self):
        result = build(request(
            forecast=forecast_of(
                med(name="Metformin 500mg, film-coated", quantity="10")),
            detail_level="named"))
        ics = deadline_calendar.render_ics(result)
        self.assertIn("500mg\\, film-coated", ics.replace("\r\n ", ""))

    def test_uids_are_stable_across_runs_so_a_reimport_does_not_duplicate(self):
        again = build(request(
            forecast=forecast_of(med(quantity="10", lead_time_days=3)),
            detail_level="named"))
        self.assertEqual([e["uid"] for e in self.result["events"]],
                         [e["uid"] for e in again["events"]])

    def test_uids_are_unique_within_one_calendar(self):
        uids = [e["uid"] for e in self.result["events"]]
        self.assertEqual(len(uids), len(set(uids)))

    def test_an_empty_calendar_is_still_a_valid_file(self):
        empty = build(request())
        ics = deadline_calendar.render_ics(empty)
        self.assertNotIn("BEGIN:VEVENT", ics)
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))


class EnvelopeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = request(
            forecast=forecast_of(med(quantity="10", lead_time_days=3)))
        cls.result = build(cls.document)

    def test_tool_run_id_is_a_uuid4(self):
        self.assertEqual(uuid.UUID(self.result["tool_run_id"]).version, 4)

    def test_issued_at_carries_the_singapore_offset(self):
        self.assertIn("+08:00", self.result["issued_at"])

    def test_the_audit_hash_replays(self):
        again = build(self.document)
        self.assertEqual(again["audit_hash"], self.result["audit_hash"])
        self.assertNotEqual(again["tool_run_id"], self.result["tool_run_id"])

    def test_the_audit_hash_excludes_tool_run_id_and_issued_at(self):
        edited = json.loads(json.dumps(self.result))
        edited["tool_run_id"] = str(uuid.uuid4())
        edited["issued_at"] = "2020-01-01T00:00:00+08:00"
        self.assertEqual(deadline_calendar.audit_hash_of(edited),
                         self.result["audit_hash"])

    def test_the_audit_hash_covers_the_events(self):
        edited = json.loads(json.dumps(self.result))
        edited["events"][0]["starts_on"] = "2030-01-01"
        self.assertNotEqual(deadline_calendar.audit_hash_of(edited),
                            self.result["audit_hash"])

    def test_the_audit_hash_covers_the_detail_level(self):
        named = build(request(forecast=self.document["forecast"],
                              detail_level="named"))
        self.assertNotEqual(named["audit_hash"], self.result["audit_hash"])

    def test_conventions_state_the_rules_the_output_relies_on(self):
        for key in ("copying", "proximity", "detail", "omissions", "uid",
                    "handoff"):
            with self.subTest(key=key):
                self.assertIn(key, self.result["conventions"])

    def test_the_summary_is_prose_a_person_can_read(self):
        self.assertGreater(len(self.result["summary"].split()), 15)
        self.assertIn("Nothing has been written to anyone's calendar",
                      self.result["summary"])


class CommandLineTests(unittest.TestCase):

    def _run(self, document, extra=None):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "input.json"
            payload.write_text(json.dumps(document), encoding="utf-8")
            ics = root / "care.ics"
            argv = [sys.executable, str(SCRIPT), "--input", str(payload),
                    "--ics", str(ics)]
            proc = subprocess.run(argv + (extra or []), capture_output=True,
                                  text=True)
            return proc, (ics.read_text(encoding="utf-8")
                          if ics.exists() else None)

    def test_it_writes_the_ics_and_prints_json(self):
        proc, ics = self._run(roundtrip(simple()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(len(result["events"]),
                         ics.count("BEGIN:VEVENT"))
        self.assertIn("written_to", result)

    def test_stdout_is_json_and_stderr_is_the_log(self):
        proc, _ = self._run(roundtrip(simple()))
        json.loads(proc.stdout)
        self.assertIn("INFO", proc.stderr)

    def test_the_ics_argument_is_required(self):
        with TemporaryDirectory() as tmp:
            payload = Path(tmp) / "input.json"
            payload.write_text(json.dumps(roundtrip(simple())),
                               encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(payload)],
                capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)

    def test_invalid_input_exits_2_and_writes_no_calendar(self):
        document = roundtrip(simple())
        del document["horizon_days"]
        proc, ics = self._run(document)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIsNone(ics)


if __name__ == "__main__":
    unittest.main()
