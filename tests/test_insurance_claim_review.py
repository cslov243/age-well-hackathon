"""Behaviour pinned for scripts/insurance_claim_review.py.

The script reports what an insurer's letter says and does the arithmetic around
it. It never decides coverage, never submits anything, and never interprets the
medical content. The tests below exist mostly to keep it that way:

  * every deadline, amount and issuer is evidence-gated — no verbatim snippet
    means the field is null and the claim carries REQUIRES_HUMAN_CONFIRMATION;
  * `insurer_decision` is a closed set read off the document, never inferred,
    so no code path can produce "you are covered";
  * every date and status derives from one resolved `as_of`.
"""

import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = (REPO / "skills" / "care-coordinator-toolkit" / "scripts"
          / "insurance_claim_review.py")

sys.path.insert(0, str(SCRIPT.parent))

import insurance_claim_review as icr  # noqa: E402

FLAG = "REQUIRES_HUMAN_CONFIRMATION"

FULL_EVIDENCE = {
    "insurer": "GREAT EASTERN LIFE ASSURANCE COMPANY LIMITED",
    "incident_date": "Date of admission: 01 Jun 2026",
    "submission_window_days": "Claims must be submitted within 90 days of "
                              "the date of discharge.",
    "decision_date": "Assessment date: 20 Jul 2026",
    "appeal_window_days": "Any appeal must be lodged within 30 days.",
    "amounts.billed": "Total hospital bill: SGD 4,820.00",
    "amounts.insurer_paid": "Amount payable by us: SGD 3,100.00",
    "amounts.household_paid": "Deductible borne by policyholder: SGD 500.00",
}


def claim(**over):
    entry = {
        "id": "claim-001",
        "insurer": "Great Eastern",
        "policy_reference": "GE-12345",
        "incident_date": "2026-06-01",
        "submission_window_days": 90,
        "insurer_decision": "partially_paid",
        "decision_date": "2026-07-20",
        "appeal_window_days": 30,
        "amounts": {
            "billed": "4820.00",
            "insurer_paid": "3100.00",
            "household_paid": "500.00",
        },
        "documents_required": ["original receipt", "discharge summary"],
        "documents_held": ["original receipt"],
        "evidence": dict(FULL_EVIDENCE),
    }
    entry.update(over)
    return entry


AMOUNT_LINES = {
    "billed": "Total hospital bill: SGD {}",
    "insurer_paid": "Amount payable by us: SGD {}",
    "household_paid": "Deductible borne by policyholder: SGD {}",
}


def money(**amounts):
    """A claim whose evidence quotes exactly the figures passed to it.

    An arithmetic test is about the arithmetic. Without this it trips the
    evidence gate on the fixture's own stale snippets instead, and passes or
    fails for a reason it was not written to check.
    """
    evidence = {k: v for k, v in FULL_EVIDENCE.items()
                if not k.startswith("amounts.")}
    for key, value in amounts.items():
        evidence[f"amounts.{key}"] = AMOUNT_LINES[key].format(value)
    return claim(amounts=dict(amounts), evidence=evidence)


def undecided():
    """A claim the insurer has not yet ruled on, so it is valid at any as_of
    on or after the incident date."""
    entry = claim(insurer_decision="pending")
    del entry["decision_date"]
    del entry["appeal_window_days"]
    del entry["evidence"]["decision_date"]
    del entry["evidence"]["appeal_window_days"]
    return entry


def payload(claims=None, *, as_of="2026-08-04"):
    return {"as_of": as_of,
            "claims": [claim()] if claims is None else claims}


def run(doc):
    return icr.review_claims(json.loads(json.dumps(doc), parse_float=Decimal))


def only(result):
    entries = result["claims"]
    assert len(entries) == 1, entries
    return entries[0]


def deadline(entry, kind):
    for item in entry["deadlines"]:
        if item["kind"] == kind:
            return item
    raise AssertionError(f"no {kind} deadline in {entry['deadlines']}")


# ---------------------------------------------------------------------------
# The evidence rule
# ---------------------------------------------------------------------------

class TestEvidenceRule(unittest.TestCase):
    def test_amount_without_a_snippet_is_nulled_and_flagged(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["amounts.billed"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["amounts"]["billed"])
        self.assertIn(FLAG, entry["flags"])
        self.assertIn("amounts.billed", entry["missing_evidence"])

    def test_a_nulled_amount_stops_the_arithmetic_rather_than_guessing(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["amounts.billed"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["outstanding"])

    def test_an_unevidenced_deduction_is_not_silently_treated_as_zero(self):
        """Found in self-review: nulling insurer_paid left the script
        subtracting zero for it and reporting SGD 4320.00 outstanding instead
        of SGD 1220.00 — a confident wrong number overstating what is owed."""
        evidence = dict(FULL_EVIDENCE)
        del evidence["amounts.insurer_paid"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["outstanding"])
        self.assertIsNone(entry["refund_due"])
        self.assertNotIn("4320", entry["summary"])

    def test_the_suppressed_total_is_explained_rather_than_just_absent(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["amounts.insurer_paid"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIn("no outstanding total is calculated", entry["summary"])
        self.assertIn("4820.00", entry["summary"])

    def test_an_absent_amount_still_counts_as_zero(self):
        """Absent means 'the letter never mentioned it', which is not the same
        as 'stated but unquotable'. Only the latter suppresses the total."""
        entry = only(run(payload([money(billed="100.00",
                                        insurer_paid="40.00")])))
        self.assertEqual(Decimal(entry["outstanding"]), Decimal("60.00"))

    def test_deadline_without_a_snippet_is_nulled_and_flagged(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["submission_window_days"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(deadline(entry, "submission")["due_on"])
        self.assertEqual(deadline(entry, "submission")["status"], "unknown")
        self.assertIn(FLAG, entry["flags"])

    def test_issuer_without_a_snippet_is_nulled_and_flagged(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["insurer"]
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["insurer"])
        self.assertIn(FLAG, entry["flags"])

    def test_an_empty_snippet_does_not_count_as_evidence(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["amounts.billed"] = "   "
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["amounts"]["billed"])
        self.assertIn(FLAG, entry["flags"])

    def test_a_field_absent_from_the_document_is_null_but_not_flagged(self):
        """Omission means 'not found', which is honest. Only an unevidenced
        *assertion* is a problem."""
        entry = claim()
        del entry["appeal_window_days"]
        del entry["evidence"]["appeal_window_days"]
        reviewed = only(run(payload([entry])))
        self.assertNotIn(FLAG, reviewed["flags"])
        self.assertEqual(reviewed["missing_evidence"], [])

    def test_a_fully_evidenced_claim_carries_no_flag(self):
        entry = only(run(payload()))
        self.assertEqual(entry["flags"], [])
        self.assertEqual(entry["missing_evidence"], [])

    def test_policy_reference_is_not_evidence_gated(self):
        """An identifier is not a claim about the world."""
        entry = only(run(payload()))
        self.assertEqual(entry["policy_reference"], "GE-12345")

    def test_every_missing_snippet_is_listed_not_just_the_first(self):
        evidence = {"incident_date": FULL_EVIDENCE["incident_date"]}
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertEqual(
            sorted(entry["missing_evidence"]),
            ["amounts.billed", "amounts.household_paid", "amounts.insurer_paid",
             "appeal_window_days", "decision_date", "insurer",
             "submission_window_days"],
        )

    def test_evidence_snippets_are_echoed_so_a_human_can_check_them(self):
        entry = only(run(payload()))
        self.assertEqual(entry["evidence"]["amounts.billed"],
                         "Total hospital bill: SGD 4,820.00")


# ---------------------------------------------------------------------------
# No coverage assertion, ever
# ---------------------------------------------------------------------------

class TestNeverAssertsCoverage(unittest.TestCase):
    def test_insurer_decision_vocabulary_is_closed(self):
        self.assertEqual(
            set(icr.DECISIONS),
            {"paid", "partially_paid", "rejected", "pending", "not_stated"},
        )

    def test_an_unknown_decision_is_refused_not_mapped(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(insurer_decision="probably fine")]))

    def test_absent_decision_becomes_not_stated_not_a_guess(self):
        entry = claim()
        del entry["insurer_decision"]
        del entry["decision_date"]
        del entry["appeal_window_days"]
        del entry["evidence"]["decision_date"]
        del entry["evidence"]["appeal_window_days"]
        reviewed = only(run(payload([entry])))
        self.assertEqual(reviewed["insurer_decision"], "not_stated")

    def test_no_summary_ever_asserts_coverage(self):
        for decision in icr.DECISIONS:
            entry = claim(insurer_decision=decision)
            reviewed = only(run(payload([entry])))
            lowered = reviewed["summary"].lower()
            for phrase in ("you qualify", "you are covered", "is covered",
                           "you're covered", "approved", "guaranteed",
                           "will be paid", "should be paid"):
                self.assertNotIn(phrase, lowered, f"{decision}: {lowered}")

    def test_no_summary_gives_clinical_or_financial_advice(self):
        for decision in icr.DECISIONS:
            reviewed = only(run(payload([claim(insurer_decision=decision)])))
            lowered = reviewed["summary"].lower()
            for phrase in ("you should", "we recommend", "diagnos",
                           "treatment was", "medically"):
                self.assertNotIn(phrase, lowered)

    def test_the_decision_is_reported_as_the_insurer_s_not_the_script_s(self):
        reviewed = only(run(payload([claim(insurer_decision="rejected")])))
        self.assertIn("the insurer", reviewed["summary"].lower())

    def test_hand_off_line_is_present_on_every_claim(self):
        for decision in icr.DECISIONS:
            reviewed = only(run(payload([claim(insurer_decision=decision)])))
            self.assertIn(icr.HANDOFF, reviewed["summary"])


# ---------------------------------------------------------------------------
# Deadline arithmetic, all from one as_of
# ---------------------------------------------------------------------------

class TestSubmissionDeadline(unittest.TestCase):
    def test_submit_by_is_incident_date_plus_window(self):
        entry = only(run(payload()))
        self.assertEqual(deadline(entry, "submission")["due_on"], "2026-08-30")

    def test_days_remaining_counts_from_as_of(self):
        entry = only(run(payload()))
        self.assertEqual(deadline(entry, "submission")["days_remaining"], 26)

    def test_due_today_when_the_window_closes_on_as_of(self):
        entry = only(run(payload(as_of="2026-08-30")))
        item = deadline(entry, "submission")
        self.assertEqual(item["status"], "due_today")
        self.assertEqual(item["days_remaining"], 0)

    def test_overdue_when_the_window_has_closed(self):
        entry = only(run(payload(as_of="2026-08-31")))
        item = deadline(entry, "submission")
        self.assertEqual(item["status"], "overdue")
        self.assertEqual(item["days_remaining"], -1)

    def test_zero_day_window_is_the_incident_date_itself(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["submission_window_days"] = ("Claims close 0 days after the "
                                              "date of discharge.")
        entry = only(run(payload([claim(submission_window_days=0,
                                        evidence=evidence)])))
        self.assertEqual(deadline(entry, "submission")["due_on"], "2026-06-01")

    def test_status_vocabulary_is_closed(self):
        allowed = {"ok", "due_today", "overdue", "unknown"}
        for as_of in ("2026-06-01", "2026-08-30", "2026-08-31"):
            entry = only(run(payload([undecided()], as_of=as_of)))
            for item in entry["deadlines"]:
                self.assertIn(item["status"], allowed)

    def test_the_basis_of_each_deadline_is_stated_in_words(self):
        entry = only(run(payload()))
        self.assertIn("90", deadline(entry, "submission")["basis"])
        self.assertIn("1 Jun 2026", deadline(entry, "submission")["basis"])

    def test_incident_date_after_as_of_is_refused(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["incident_date"] = "Date of admission: 01 Sep 2026"
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(incident_date="2026-09-01",
                               evidence=evidence)]))

    def test_negative_window_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(submission_window_days=-1)]))

    def test_fractional_window_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(submission_window_days="30.5")]))


class TestAppealDeadline(unittest.TestCase):
    def test_appeal_deadline_exists_for_a_partially_paid_claim(self):
        entry = only(run(payload()))
        self.assertEqual(deadline(entry, "appeal")["due_on"], "2026-08-19")

    def test_appeal_deadline_exists_for_a_rejected_claim(self):
        entry = only(run(payload([claim(insurer_decision="rejected")])))
        self.assertEqual(deadline(entry, "appeal")["due_on"], "2026-08-19")

    def test_no_appeal_deadline_when_the_claim_was_paid_in_full(self):
        entry = only(run(payload([claim(insurer_decision="paid")])))
        self.assertEqual([d["kind"] for d in entry["deadlines"]],
                         ["submission"])

    def test_no_appeal_deadline_while_the_decision_is_pending(self):
        entry = claim(insurer_decision="pending")
        del entry["decision_date"]
        del entry["evidence"]["decision_date"]
        reviewed = only(run(payload([entry])))
        self.assertEqual([d["kind"] for d in reviewed["deadlines"]],
                         ["submission"])

    def test_appeal_window_without_a_decision_date_is_flagged_not_computed(self):
        entry = claim()
        del entry["decision_date"]
        reviewed = only(run(payload([entry])))
        self.assertIsNone(deadline(reviewed, "appeal")["due_on"])
        self.assertEqual(deadline(reviewed, "appeal")["status"], "unknown")

    def test_decision_date_after_as_of_is_refused(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["decision_date"] = "Assessment date: 01 Sep 2026"
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(decision_date="2026-09-01",
                               evidence=evidence)]))


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

class TestAmounts(unittest.TestCase):
    def test_outstanding_is_billed_less_everything_already_paid(self):
        entry = only(run(payload()))
        self.assertEqual(Decimal(entry["outstanding"]), Decimal("1220.00"))

    def test_outstanding_is_exact_to_the_cent(self):
        entry = only(run(payload([money(billed="100.05",
                                        insurer_paid="33.35",
                                        household_paid="0.01")])))
        self.assertEqual(Decimal(entry["outstanding"]), Decimal("66.69"))

    def test_overpayment_is_reported_as_a_refund_not_a_negative(self):
        entry = only(run(payload([money(billed="100.00",
                                        insurer_paid="120.00")])))
        self.assertEqual(Decimal(entry["refund_due"]), Decimal("20.00"))
        self.assertEqual(Decimal(entry["outstanding"]), Decimal("0.00"))

    def test_absent_optional_amounts_are_treated_as_zero_paid(self):
        entry = only(run(payload([money(billed="100.00")])))
        self.assertEqual(Decimal(entry["outstanding"]), Decimal("100.00"))

    def test_binary_float_amount_is_refused_not_coerced(self):
        doc = payload()
        doc["claims"][0]["amounts"]["billed"] = 4820.55
        with self.assertRaises(icr.InvalidInput) as ctx:
            icr.review_claims(doc)
        self.assertIn("float", str(ctx.exception))

    def test_negative_amount_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(amounts={"billed": "-1.00"})]))

    def test_three_decimal_places_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload([claim(amounts={"billed": "10.005"})]))

    def test_unknown_amount_key_is_refused(self):
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([claim(amounts={"billed": "10.00", "gst": "0.70"})]))
        self.assertIn("gst", str(ctx.exception))

    def test_currency_is_stated(self):
        self.assertEqual(run(payload())["currency"], "SGD")


# ---------------------------------------------------------------------------
# Documents outstanding
# ---------------------------------------------------------------------------

class TestDocuments(unittest.TestCase):
    def test_documents_still_needed_is_the_difference(self):
        entry = only(run(payload()))
        self.assertEqual(entry["documents_outstanding"], ["discharge summary"])

    def test_holding_everything_leaves_nothing_outstanding(self):
        entry = only(run(payload([claim(
            documents_held=["original receipt", "discharge summary"])])))
        self.assertEqual(entry["documents_outstanding"], [])

    def test_document_matching_ignores_case_and_surrounding_space(self):
        entry = only(run(payload([claim(
            documents_held=["  Original Receipt ", "Discharge Summary"])])))
        self.assertEqual(entry["documents_outstanding"], [])

    def test_holding_a_document_that_was_not_asked_for_is_not_an_error(self):
        entry = only(run(payload([claim(documents_held=["passport"])])))
        self.assertEqual(entry["documents_outstanding"],
                         ["original receipt", "discharge summary"])


# ---------------------------------------------------------------------------
# Envelope, replay, validation
# ---------------------------------------------------------------------------

class TestEnvelopeAndValidation(unittest.TestCase):
    def test_envelope_carries_run_id_and_sg_offset(self):
        result = run(payload())
        self.assertTrue(result["issued_at"].endswith("+08:00"))
        self.assertEqual(result["as_of"], "2026-08-04")
        self.assertTrue(result["tool_run_id"])

    def test_same_input_replays_to_the_same_audit_hash(self):
        first, second = run(payload()), run(payload())
        self.assertEqual(first["audit_hash"], second["audit_hash"])
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])

    def test_audit_hash_covers_the_computed_output(self):
        result = run(payload())
        tampered = json.loads(json.dumps(result))
        tampered["claims"][0]["outstanding"] = "0.00"
        self.assertNotEqual(icr.audit_hash_of(tampered), result["audit_hash"])

    def test_historical_as_of_gives_historical_status(self):
        entry = only(run(payload([undecided()], as_of="2026-06-02")))
        self.assertEqual(deadline(entry, "submission")["status"], "ok")
        self.assertEqual(deadline(entry, "submission")["days_remaining"], 89)

    def test_absent_claims_key_is_refused_not_treated_as_empty(self):
        with self.assertRaises(icr.InvalidInput):
            run({"as_of": "2026-08-04", "claim": [claim()]})

    def test_empty_claim_list_is_not_an_error(self):
        result = run(payload([]))
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["claims_counted"], 0)

    def test_duplicate_claim_id_is_refused(self):
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([claim(), claim()]))
        self.assertIn("duplicate", str(ctx.exception))

    def test_non_object_input_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            icr.review_claims([])

    def test_missing_evidence_block_is_refused(self):
        entry = claim()
        del entry["evidence"]
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([entry]))
        self.assertIn("evidence", str(ctx.exception))

    def test_flags_needing_human_confirmation_are_counted_at_the_top(self):
        evidence = dict(FULL_EVIDENCE)
        del evidence["insurer"]
        result = run(payload([claim(evidence=evidence),
                              claim(id="claim-002")]))
        self.assertEqual(result["claims_requiring_human_confirmation"], 1)

    def test_malformed_as_of_is_refused(self):
        with self.assertRaises(icr.InvalidInput):
            run(payload(as_of="4 August 2026"))


class TestUnrecognisedClaimKeys(unittest.TestCase):
    """Audit finding #17. A key the script does not know is refused, never
    dropped.

    `amounts` has rejected unknown keys since it was written; the claim object
    around it did not, so a misspelled field arrived, took no effect, and was
    read downstream as *absent* — the one reading that carries no flag and no
    null. Absent means the letter never said it. A typo means nobody knows.
    """

    def test_the_key_that_was_actually_dropped_is_refused(self):
        # Verbatim from the case G run of 6 August 2026: the agent sent
        # claim_reference next to policy_reference and the script exited 0.
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([claim(claim_reference="CLM-2026-0088")]))
        self.assertIn("claim_reference", str(ctx.exception))

    def test_a_misspelled_date_field_is_refused_not_read_as_absent(self):
        # The dangerous shape: incidence_date looks answered and is not. Left
        # to drop, the submission deadline reads 'unknown' as though the letter
        # had been silent about an admission it plainly states.
        entry = claim()
        entry["incidence_date"] = entry.pop("incident_date")
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([entry]))
        self.assertIn("incidence_date", str(ctx.exception))

    def test_the_refusal_names_the_keys_it_would_have_accepted(self):
        with self.assertRaises(icr.InvalidInput) as ctx:
            run(payload([claim(appeal_window="30 days")]))
        message = str(ctx.exception)
        self.assertIn("appeal_window_days", message)
        self.assertIn("claims[0]", message)

    def test_the_allowed_set_is_exactly_the_contract(self):
        # A guard on the guard. An allowed set that drifts from
        # InsuranceClaimRecord starts refusing fields the contract promises.
        self.assertEqual(set(claim()), set(icr.CLAIM_KEYS))


class TestTheSnippetMustContainTheValue(unittest.TestCase):
    """Audit finding #14, measured 6 August 2026 in eval case G.

    A snippet that exists and is not blank was accepted as evidence for any
    value at all. The cold agent worked the household's share out by
    subtraction, quoted it against a line of prose with no number in it, and
    was told SGD 0.00 was outstanding against a letter saying SGD 360.00.

    `letter_record.py` refused the identical value-and-snippet pair in the same
    run. These tests hold the two scripts to one strength.
    """

    def reproduction(self):
        """The payload from the finding, verbatim."""
        return payload([claim(
            insurer_decision="partially_paid",
            decision_date="2026-07-28",
            appeal_window_days=30,
            amounts={"billed": "1220.00", "insurer_paid": "860.00",
                     "household_paid": "360.00"},
            evidence={
                "insurer": FULL_EVIDENCE["insurer"],
                "incident_date": FULL_EVIDENCE["incident_date"],
                "submission_window_days":
                    FULL_EVIDENCE["submission_window_days"],
                "decision_date": "Assessment date: 28 Jul 2026",
                "appeal_window_days": "Any appeal must be lodged within 30 days.",
                "amounts.billed": "Total hospital bill: SGD 1,220.00",
                "amounts.insurer_paid": "Amount payable by us: SGD 860.00",
                "amounts.household_paid":
                    "The balance is payable by the policyholder",
            },
        )], as_of="2026-08-06")

    def test_the_invented_figure_is_nulled(self):
        entry = only(run(self.reproduction()))
        self.assertIsNone(entry["amounts"]["household_paid"])

    def test_the_invented_figure_is_listed_as_missing_evidence(self):
        entry = only(run(self.reproduction()))
        self.assertIn("amounts.household_paid", entry["missing_evidence"])

    def test_the_claim_is_flagged(self):
        entry = only(run(self.reproduction()))
        self.assertIn(FLAG, entry["flags"])

    def test_no_outstanding_total_is_produced(self):
        """The observed failure was 'SGD 0.00 outstanding'. The right answer is
        not SGD 360.00 either — with the household's share unquotable, what is
        still owed is unknown, and an unevidenced amount suppresses the total.
        """
        entry = only(run(self.reproduction()))
        self.assertIsNone(entry["outstanding"])
        self.assertIsNone(entry["refund_due"])

    def test_the_summary_never_says_zero_is_outstanding(self):
        entry = only(run(self.reproduction()))
        self.assertNotIn("SGD 0.00 outstanding", entry["summary"])
        self.assertIn("no outstanding total is calculated", entry["summary"])

    def test_the_refused_snippet_is_not_echoed_as_evidence(self):
        """Echoing it would present the thing that failed the check as the
        thing that passed it."""
        entry = only(run(self.reproduction()))
        self.assertNotIn("amounts.household_paid", entry["evidence"])

    def test_a_deadline_computed_from_a_relative_window_is_refused(self):
        """The other half of the same run: '30 days' quoted against a phrase
        that says 'within 30 days' is fine; a date quoted against it is not."""
        evidence = dict(FULL_EVIDENCE)
        evidence["decision_date"] = "within 30 days of the date of this letter"
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["decision_date"])
        self.assertIsNone(deadline(entry, "appeal")["due_on"])
        self.assertIn(FLAG, entry["flags"])

    def test_an_issuer_quoted_against_another_insurer_is_refused(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["insurer"] = "NTUC INCOME INSURANCE LIMITED"
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertIsNone(entry["insurer"])
        self.assertIn(FLAG, entry["flags"])

    def test_a_window_quoted_against_a_different_number_is_refused(self):
        evidence = dict(FULL_EVIDENCE)
        evidence["submission_window_days"] = ("Claims must be submitted within "
                                              "60 days of the date of discharge.")
        entry = only(run(payload([claim(evidence=evidence)])))
        self.assertEqual(deadline(entry, "submission")["status"], "unknown")
        self.assertIn("submission_window_days", entry["missing_evidence"])

    def test_a_refusal_reads_the_same_way_in_both_scripts(self):
        """Same value, same snippet, same verdict, whichever script sees it."""
        import letter_record
        self.assertFalse(letter_record.snippet_has_amount(
            "The balance is payable by the policyholder", Decimal("360.00")))
        entry = only(run(self.reproduction()))
        self.assertIn("amounts.household_paid", entry["missing_evidence"])


class TestCommandLine(unittest.TestCase):
    def _run(self, doc, extra=()):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra],
            input=json.dumps(doc), capture_output=True, text=True,
        )

    def test_stdout_is_json_only_and_logs_go_to_stderr(self):
        proc = self._run(payload())
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(
            json.loads(proc.stdout)["claims"][0]["outstanding"], "1220.00"
        )
        self.assertIn("insurance_claim_review", proc.stderr)

    def test_invalid_input_exits_two_with_no_stdout(self):
        proc = self._run({"as_of": "2026-08-04"})
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")

    def test_output_file_is_written_as_utf8(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            evidence = dict(FULL_EVIDENCE)
            evidence["insurer"] = "鹰星保险有限公司"
            proc = self._run(payload([claim(insurer="鹰星保险",
                                            evidence=evidence)]),
                             extra=["--output", str(out)])
            self.assertEqual(proc.returncode, 0)
            self.assertIn("鹰星保险",
                          out.read_text(encoding="utf-8"))

    def test_missing_input_file_is_refused(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", "/no/such/file.json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
