"""Behaviour pinned for scripts/confirmations.py.

Audit finding #22. Every script in the toolkit answers "is *this* record
clean?" and nothing answered "does this run need a person?", so the model
answered it — by reading whichever flag list it happened to look at last. On
6 August a family artifact certified `No human confirmation required` over a
record carrying `REQUIRES_HUMAN_CONFIRMATION`, because the *other* script in
the same run had returned `flags: []` legitimately.

That is the split of labour failing on a status instead of on a number. This
script makes the answer deterministic: it reads every result a run produced,
merges what each one flagged, and renders one sentence the artifacts quote.

The invariant the whole file exists to protect is
`TestNoFlagIsEverSwallowed` — **no input carrying any flag may produce
`human_confirmation_required: false`**, including a flag this script has never
heard of. Fail-safe is the only safe direction here: an unknown flag that reads
as "nothing to see" is precisely the defect being fixed.
"""

import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"
SCRIPT = SCRIPTS / "confirmations.py"

sys.path.insert(0, str(SCRIPTS))

import confirmations  # noqa: E402
import insurance_claim_review  # noqa: E402
import letter_record  # noqa: E402


# --------------------------------------------------------------------------
# source builders — real results, stamped with the real hash functions
# --------------------------------------------------------------------------

def record_source(missing=(), problems=(), flags=(), as_of="2026-08-06",
                  record_id="letter-aaaa1111"):
    """A letter_record.py result, hashed the way letter_record hashes it."""
    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": "2026-08-06T09:00:00+08:00",
        "as_of": as_of,
        "mode": "record",
        "content_hash": "sha256:" + "a" * 64,
        "id": record_id,
        "pages": [{"path": "/care/inbox/letter.txt", "sha256": "b" * 64,
                   "bytes": 100}],
        "conventions": {"evidence": "..."},
        "already_extracted": False,
        "missing_evidence": list(missing),
        "evidence_problems": [dict(p) for p in problems],
        "summary": "A letter.",
        "record": {
            "id": record_id,
            "doc_type": "insurance",
            "issuer": "GREAT EASTERN LIFE ASSURANCE LIMITED",
            "issue_date": "2026-07-28",
            "deadline": None,
            "amounts": ["1220.00"],
            "required_action": "Appeal within 30 days.",
            "evidence": {},
            "extracted_at": "2026-08-06T09:00:00+08:00",
            "flags": list(flags),
        },
    }
    result["audit_hash"] = letter_record.audit_hash_of(result)
    return result


def claims_source(missing=(), flags=(), as_of="2026-08-06",
                  claim_id="CLM-2026-0088"):
    """An insurance_claim_review.py result, hashed the way it hashes itself."""
    claim = {
        "id": claim_id,
        "insurer": "GREAT EASTERN LIFE ASSURANCE LIMITED",
        "policy_reference": "GE-4471902",
        "insurer_decision": "partially_paid",
        "incident_date": None,
        "decision_date": "2026-07-28",
        "amounts": {"billed": "1220.00", "insurer_paid": "860.00",
                    "household_paid": None},
        "outstanding": "360.00",
        "refund_due": None,
        "deadlines": [],
        "documents_outstanding": [],
        "evidence": {},
        "missing_evidence": sorted(missing),
        "flags": list(flags),
        "summary": "A claim.",
    }
    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": "2026-08-06T09:00:00+08:00",
        "as_of": as_of,
        "currency": "SGD",
        "claims": [claim],
        "claims_counted": 1,
        "claims_requiring_human_confirmation": 1 if flags else 0,
        "conventions": {"evidence": "..."},
    }
    result["audit_hash"] = insurance_claim_review.audit_hash_of(result)
    return result


FLAG = "REQUIRES_HUMAN_CONFIRMATION"

REFUSED_DEADLINE = {
    "field": "deadline",
    "reason": "value_not_in_snippet",
    "detail": "deadline does not appear in the text quoted for it",
}


def payload(records=(), claims=(), **extra):
    document = {"records": list(records), "claims": list(claims)}
    document.update(extra)
    return document


def run(document):
    """Call the module directly. Returns the result dict."""
    return confirmations.build_confirmations(document)


def run_cli(document, *args):
    """Call it as a subprocess, the way a skill invokes it."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(document), capture_output=True, text=True)


# --------------------------------------------------------------------------


class TestTheKeysAreRequired(unittest.TestCase):
    """A required key is not a defaulted one. Both lists are legal empty and
    illegal absent: a run that passed no outputs and a run whose key was
    misspelled must not look identical, because the first is a real answer
    about nothing and the second is silence dressed as one."""

    def test_records_is_required_even_when_empty_is_legal(self):
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run({"claims": []})
        self.assertIn("records", str(ctx.exception))

    def test_claims_is_required_even_when_empty_is_legal(self):
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run({"records": []})
        self.assertIn("claims", str(ctx.exception))

    def test_both_empty_is_a_legal_run(self):
        result = run(payload())
        self.assertFalse(result["human_confirmation_required"])
        self.assertEqual(result["items"], [])

    def test_an_unrecognised_top_level_key_is_refused(self):
        # Findings #17 and #19 in advance: a misspelled key takes no effect
        # and says nothing, which reads downstream as a run that had nothing
        # to check.
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run(payload(recrods=[]))
        self.assertIn("recrods", str(ctx.exception))

    def test_the_lists_must_be_lists(self):
        with self.assertRaises(confirmations.InvalidInput):
            run({"records": record_source(), "claims": []})


class TestNoFlagIsEverSwallowed(unittest.TestCase):
    """The invariant. Finding #22 was a false `false`; nothing else in this
    file matters as much as never producing one."""

    def test_a_flagged_record_requires_confirmation(self):
        result = run(payload(records=[record_source(
            missing=["deadline"], problems=[REFUSED_DEADLINE], flags=[FLAG])]))
        self.assertTrue(result["human_confirmation_required"])

    def test_a_flagged_claim_requires_confirmation(self):
        result = run(payload(claims=[claims_source(
            missing=["incident_date"], flags=[FLAG])]))
        self.assertTrue(result["human_confirmation_required"])

    def test_one_clean_source_does_not_clear_a_flagged_one(self):
        # This is the measured failure, exactly. The claim review returned
        # flags: [] — correctly, household_paid was absent, not unquotable —
        # and the agent generalised that over the whole run while the record
        # sat there flagged.
        result = run(payload(
            records=[record_source(missing=["deadline"],
                                   problems=[REFUSED_DEADLINE], flags=[FLAG])],
            claims=[claims_source()]))
        self.assertTrue(result["human_confirmation_required"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["field"], "deadline")

    def test_a_flag_this_script_has_never_heard_of_still_requires_a_person(self):
        # Fail-safe. An unknown flag that reads as "nothing to see" is the
        # defect, not a tidy edge case.
        result = run(payload(records=[record_source(flags=["UNREADABLE"])]))
        self.assertTrue(result["human_confirmation_required"])
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("UNREADABLE", json.dumps(result["items"][0]))

    def test_missing_evidence_without_a_flag_still_requires_a_person(self):
        # Belt and braces against a producer that lists a field and forgets to
        # flag. The two are meant to move together; if they ever disagree, the
        # answer is the cautious one.
        result = run(payload(records=[record_source(
            missing=["issuer"], problems=[], flags=[])]))
        self.assertTrue(result["human_confirmation_required"])

    def test_a_genuinely_clean_run_is_allowed_to_say_so(self):
        # The ban is on the *model* certifying this without checking. A script
        # that read every output it was given may say what it found.
        result = run(payload(records=[record_source()],
                             claims=[claims_source()]))
        self.assertFalse(result["human_confirmation_required"])
        self.assertEqual(result["items"], [])


class TestEachItemSaysWhoRaisedItAndWhy(unittest.TestCase):

    def setUp(self):
        self.result = run(payload(
            records=[record_source(missing=["deadline"],
                                   problems=[REFUSED_DEADLINE], flags=[FLAG])],
            claims=[claims_source(missing=["incident_date"], flags=[FLAG])]))

    def test_every_item_names_the_script_that_raised_it(self):
        tools = {item["tool"] for item in self.result["items"]}
        self.assertEqual(tools, {"letter_record.py",
                                 "insurance_claim_review.py"})

    def test_every_item_names_its_subject(self):
        subjects = {item["subject"] for item in self.result["items"]}
        self.assertEqual(subjects, {"letter-aaaa1111", "CLM-2026-0088"})

    def test_every_item_carries_the_audit_hash_of_its_source(self):
        for item in self.result["items"]:
            with self.subTest(item=item["field"]):
                self.assertTrue(item["source_audit_hash"].startswith("sha256:"))

    def test_the_reason_is_copied_from_the_producer_not_invented(self):
        by_field = {item["field"]: item for item in self.result["items"]}
        self.assertEqual(by_field["deadline"]["reason"], "value_not_in_snippet")

    def test_a_claim_field_says_only_what_the_claim_review_knows(self):
        # The claim review records *that* a snippet failed, never which of the
        # four ways it failed. Reporting a reason it did not produce would be
        # inventing provenance.
        by_field = {item["field"]: item for item in self.result["items"]}
        self.assertEqual(by_field["incident_date"]["reason"],
                         "missing_evidence")

    def test_every_item_carries_a_plain_words_ask(self):
        for item in self.result["items"]:
            with self.subTest(field=item["field"]):
                self.assertIn(item["field"], item["ask"])
                self.assertGreater(len(item["ask"].split()), 5)

    def test_items_are_ordered_deterministically(self):
        first = run(payload(
            records=[record_source(missing=["issuer", "deadline"],
                                   flags=[FLAG])],
            claims=[claims_source(missing=["incident_date"], flags=[FLAG])]))
        second = run(payload(
            records=[record_source(missing=["deadline", "issuer"],
                                   flags=[FLAG])],
            claims=[claims_source(missing=["incident_date"], flags=[FLAG])]))
        self.assertEqual([i["field"] for i in first["items"]],
                         [i["field"] for i in second["items"]])


class TestItRefusesASourceItCannotTrust(unittest.TestCase):
    """The same refusal deadline_calendar.py and pharmacy_cart.py apply."""

    def test_an_edited_record_is_refused(self):
        source = record_source(missing=["deadline"], flags=[FLAG])
        source["record"]["deadline"] = "2026-08-27"  # hash no longer matches
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run(payload(records=[source]))
        self.assertIn("audit_hash", str(ctx.exception))

    def test_an_edited_claims_review_is_refused(self):
        source = claims_source()
        source["claims"][0]["outstanding"] = "0.00"
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run(payload(claims=[source]))
        self.assertIn("audit_hash", str(ctx.exception))

    def test_something_that_is_not_a_result_is_refused(self):
        with self.assertRaises(confirmations.InvalidInput) as ctx:
            run(payload(records=[{"flags": [], "audit_hash": "sha256:x"}]))
        self.assertIn("letter_record", str(ctx.exception))

    def test_a_source_dated_after_as_of_is_refused(self):
        with self.assertRaises(confirmations.InvalidInput):
            run(payload(records=[record_source(as_of="2026-09-01")],
                        as_of="2026-08-06"))

    def test_a_claims_result_passed_as_a_record_is_refused(self):
        with self.assertRaises(confirmations.InvalidInput):
            run(payload(records=[claims_source()]))


class TestTheSentenceTheArtifactsQuote(unittest.TestCase):
    """The model copies this rather than composing one. If it composes, #22
    comes back — the whole point is that the status stops being a judgement."""

    def test_the_sentence_names_every_field_needing_a_person(self):
        result = run(payload(
            records=[record_source(missing=["deadline"],
                                   problems=[REFUSED_DEADLINE], flags=[FLAG])],
            claims=[claims_source(missing=["incident_date"], flags=[FLAG])]))
        self.assertIn("deadline", result["sentence"])
        self.assertIn("incident_date", result["sentence"])

    def test_a_clean_sentence_states_its_scope_rather_than_certifying(self):
        # "Nothing needs a person" is only true of what was checked. The
        # sentence has to carry that, because an output nobody passed is an
        # output nobody checked, and the reader cannot see the difference.
        result = run(payload(records=[record_source()],
                             claims=[claims_source()]))
        self.assertIn("2", result["sentence"])
        self.assertIn("checked", result["sentence"].lower())

    def test_the_empty_run_does_not_read_as_a_clean_run(self):
        result = run(payload())
        self.assertIn("0", result["sentence"])

    def test_sources_checked_lists_every_source(self):
        result = run(payload(records=[record_source()],
                             claims=[claims_source()]))
        self.assertEqual(len(result["sources_checked"]), 2)
        self.assertEqual({s["tool"] for s in result["sources_checked"]},
                         {"letter_record.py", "insurance_claim_review.py"})

    def test_the_summary_says_nothing_was_submitted(self):
        result = run(payload(records=[record_source()]))
        self.assertIn("submitted", result["summary"].lower())


class TestTheEnvelope(unittest.TestCase):

    def test_it_carries_the_three_envelope_fields(self):
        result = run(payload())
        uuid.UUID(result["tool_run_id"])
        self.assertTrue(result["issued_at"].endswith("+08:00"))
        self.assertTrue(result["audit_hash"].startswith("sha256:"))

    def test_the_hash_excludes_the_run_id_and_the_clock(self):
        first = run(payload(records=[record_source()]))
        second = run(payload(records=[record_source()]))
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])
        self.assertEqual(first["audit_hash"], second["audit_hash"])

    def test_the_hash_changes_when_the_answer_changes(self):
        clean = run(payload(records=[record_source()]))
        flagged = run(payload(records=[record_source(
            missing=["deadline"], problems=[REFUSED_DEADLINE], flags=[FLAG])]))
        self.assertNotEqual(clean["audit_hash"], flagged["audit_hash"])

    def test_the_conventions_say_it_answers_only_for_what_it_was_given(self):
        result = run(payload())
        text = json.dumps(result["conventions"]).lower()
        self.assertIn("checked", text)


class TestTheCommandLine(unittest.TestCase):

    def test_json_to_stdout_and_logging_to_stderr(self):
        done = run_cli(payload(records=[record_source()]))
        self.assertEqual(done.returncode, 0)
        parsed = json.loads(done.stdout)
        self.assertIn("human_confirmation_required", parsed)
        self.assertNotIn("{", done.stderr)

    def test_invalid_input_exits_nonzero_with_the_reason_on_stderr(self):
        done = run_cli({"records": []})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("claims", done.stderr)

    def test_it_writes_to_an_output_path_when_given_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "confirmations.json"
            done = run_cli(payload(records=[record_source()]),
                           "--output", str(out))
            self.assertEqual(done.returncode, 0)
            self.assertIn("human_confirmation_required",
                          json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
