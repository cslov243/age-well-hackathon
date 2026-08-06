"""Behaviour pinned for scripts/letter_record.py.

This is the script that stands between a vision model and `extracted/`. Three
properties carry the whole weight of the entry point, and each one is a defect
the repo has already paid for once:

  * **Absent is not unevidenced.** A field the letter never mentioned is null
    and unremarkable. A field the model believes it saw but cannot quote is
    *unknown*, and the record must say so out loud. Substituting one for the
    other once produced a draft claiming SGD 4,320.00 owed against a letter
    that said SGD 1,220.00.
  * **A snippet has to contain the value it is evidence for.** Vision
    confidence is highest exactly when it is confabulating a familiar-looking
    form, so "I quoted something" is not the check — "the number I extracted
    appears in the text I quoted" is. It is a weak check and it is the only
    mechanical one available against an image.
  * **The same letter is never extracted twice.** Content hash first, vision
    second. A re-extraction costs money and produces a second record that
    silently competes with the first.

Sources are built as real files on disk, because the identity half of this
script is about bytes and a fixture dict would test nothing.
"""

import json
import sys
import unittest
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from letter_record import (  # noqa: E402
    FLAG, InvalidInput, audit_hash_of, build_record)

TODAY = date(2026, 8, 6)

LETTER = b"a scan of an insurer's letter, as bytes\n"
OTHER = b"a completely different letter\n"


def parse(text):
    """Read a payload the way the script's own front door reads it."""
    return json.loads(text, parse_float=Decimal)


class Workspace:
    """A temp directory holding inbox pages and an extracted/ records dir."""

    def __init__(self, stack):
        self.root = Path(stack.enter_context(TemporaryDirectory()))
        self.records = self.root / "extracted"
        self.records.mkdir()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()

    def page(self, name, payload=LETTER):
        path = self.inbox / name
        path.write_bytes(payload)
        return str(path)


def request(files, mode="record", doc_type="insurance", fields=None,
            evidence=None, as_of=TODAY.isoformat(), **extra):
    document = {"as_of": as_of, "mode": mode, "source_files": list(files)}
    if mode == "record":
        document["doc_type"] = doc_type
        document["fields"] = FIELDS if fields is None else fields
        document["evidence"] = EVIDENCE if evidence is None else evidence
    document.update(extra)
    return document


FIELDS = {
    "issuer": "Great Eastern Life Assurance",
    "issue_date": "2026-07-28",
    "deadline": "2026-09-15",
    "amounts": ["1220.00"],
    "required_action": "Send the receipts to your insurer before 15 September.",
}

EVIDENCE = {
    "issuer": "GREAT EASTERN LIFE ASSURANCE LIMITED",
    "issue_date": "Date of this letter: 28 July 2026",
    "deadline": "Documents must reach us by 15 September 2026.",
    "amounts[0]": "Total billed: SGD 1,220.00",
}


def fields_with(**changes):
    merged = dict(FIELDS)
    merged.update(changes)
    return merged


def evidence_with(**changes):
    merged = dict(EVIDENCE)
    for key, value in changes.items():
        key = key.replace("amount0", "amounts[0]")
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


class ScriptShapeTests(unittest.TestCase):

    def test_it_lives_in_the_toolkit(self):
        self.assertTrue((SCRIPTS / "letter_record.py").is_file())

    def test_invalid_input_is_the_refusal_type(self):
        self.assertTrue(issubclass(InvalidInput, ValueError))

    def test_the_flag_is_the_one_every_other_file_spells_the_same_way(self):
        self.assertEqual(FLAG, "REQUIRES_HUMAN_CONFIRMATION")


class ValidationTests(unittest.TestCase):

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)
        self.page = self.ws.page("letter.jpg")

    def build(self, document):
        return build_record(document, self.ws.records)

    def refuses(self, document, fragment):
        with self.assertRaises(InvalidInput) as caught:
            self.build(document)
        self.assertIn(fragment, str(caught.exception).lower())

    def test_input_must_be_an_object(self):
        self.refuses(["not", "an", "object"], "json object")

    def test_an_unknown_top_level_key_is_refused(self):
        self.refuses(request([self.page], confidence=0.97), "unknown key")

    def test_mode_is_required_and_has_no_default(self):
        document = request([self.page])
        del document["mode"]
        self.refuses(document, "mode is required")

    def test_an_unrecognised_mode_is_refused_not_guessed(self):
        self.refuses(request([self.page], mode="maybe"), "mode")

    def test_check_mode_refuses_an_extraction_it_did_not_ask_for(self):
        # Asking "should I extract this?" while already holding the extraction
        # means the vision call has been made and the question is moot. It is
        # more likely a mode typo than a real check.
        document = request([self.page], mode="check")
        document["fields"] = FIELDS
        self.refuses(document, "check")

    def test_source_files_is_required(self):
        document = request([self.page])
        del document["source_files"]
        self.refuses(document, "source_files is required")

    def test_an_empty_source_files_is_refused(self):
        self.refuses(request([]), "at least one")

    def test_a_source_file_that_does_not_exist_is_refused(self):
        missing = str(self.ws.inbox / "nothing-here.jpg")
        self.refuses(request([missing]), "not found")

    def test_the_same_page_listed_twice_is_refused(self):
        self.refuses(request([self.page, self.page]), "twice")

    def test_record_mode_requires_doc_type_fields_and_evidence(self):
        for key in ("doc_type", "fields", "evidence"):
            with self.subTest(key=key):
                document = request([self.page])
                del document[key]
                self.refuses(document, f"{key} is required")

    def test_an_unrecognised_doc_type_is_refused_not_mapped(self):
        self.refuses(request([self.page], doc_type="letter"), "doc_type")

    def test_every_field_key_is_required_even_when_null(self):
        # A field the model never considered and a field it considered and
        # found nothing for are the same JSON. Requiring the key forces the
        # second answer to be given deliberately.
        for key in FIELDS:
            with self.subTest(field=key):
                missing = {k: v for k, v in FIELDS.items() if k != key}
                self.refuses(request([self.page], fields=missing), key)

    def test_an_unknown_field_is_refused(self):
        self.refuses(
            request([self.page], fields=fields_with(policy_number="X")),
            "unknown")

    def test_an_evidence_key_naming_no_field_is_refused(self):
        # A snippet filed under a name nothing reads is a snippet nobody
        # checks, and it reads like diligence.
        self.refuses(
            request([self.page], evidence=evidence_with(issuer_name="x")),
            "evidence")

    def test_an_evidence_key_for_an_amount_that_was_not_supplied_is_refused(self):
        self.refuses(
            request([self.page],
                    evidence={**EVIDENCE, "amounts[3]": "SGD 9.00"}),
            "amounts[3]")

    def test_a_binary_float_amount_is_refused_rather_than_coerced(self):
        self.refuses(request([self.page], fields=fields_with(amounts=[1220.0])),
                     "float")

    def test_a_negative_amount_is_refused(self):
        self.refuses(
            request([self.page], fields=fields_with(amounts=["-5.00"]),
                    evidence=evidence_with(amount0="less SGD -5.00")),
            "negative")

    def test_a_non_iso_date_is_refused(self):
        self.refuses(
            request([self.page], fields=fields_with(deadline="15/09/2026")),
            "iso date")

    def test_a_future_issue_date_is_refused_against_as_of(self):
        self.refuses(
            request([self.page], fields=fields_with(issue_date="2026-12-01"),
                    evidence=evidence_with(issue_date="dated 1 December 2026")),
            "future")


class IdentityTests(unittest.TestCase):
    """Content hash first, vision second."""

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)

    def build(self, document):
        return build_record(document, self.ws.records)

    def test_the_hash_follows_the_bytes_not_the_filename(self):
        first = self.build(request([self.ws.page("a.jpg")], mode="check"))
        second = self.build(request([self.ws.page("renamed.jpg")],
                                    mode="check"))
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(first["id"], second["id"])

    def test_different_bytes_are_a_different_letter(self):
        first = self.build(request([self.ws.page("a.jpg")], mode="check"))
        second = self.build(request([self.ws.page("b.jpg", OTHER)],
                                    mode="check"))
        self.assertNotEqual(first["content_hash"], second["content_hash"])

    def test_page_order_is_part_of_the_identity(self):
        # Two pages the other way round is a different document, and the
        # contract biases toward splitting: a duplicate record costs a second
        # notification, a false merge eats a deadline.
        one, two = self.ws.page("p1.jpg"), self.ws.page("p2.jpg", OTHER)
        forwards = self.build(request([one, two], mode="check"))
        backwards = self.build(request([two, one], mode="check"))
        self.assertNotEqual(forwards["content_hash"],
                            backwards["content_hash"])

    def test_every_page_is_hashed_individually_as_well(self):
        one, two = self.ws.page("p1.jpg"), self.ws.page("p2.jpg", OTHER)
        result = self.build(request([one, two], mode="check"))
        self.assertEqual([page["path"] for page in result["pages"]], [one, two])
        self.assertEqual(len({page["sha256"] for page in result["pages"]}), 2)
        self.assertEqual(result["pages"][0]["bytes"], len(LETTER))

    def test_the_id_is_derived_from_the_content_hash(self):
        result = self.build(request([self.ws.page("a.jpg")], mode="check"))
        digest = result["content_hash"].split(":", 1)[1]
        self.assertTrue(result["id"].endswith(digest[:16]))


class IdempotencyTests(unittest.TestCase):
    """Never re-extract, never re-charge for vision."""

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)
        self.page = self.ws.page("letter.jpg")

    def build(self, document):
        return build_record(document, self.ws.records)

    def written(self):
        return sorted(path.name for path in self.ws.records.glob("*.json"))

    def test_a_check_on_an_empty_workspace_says_to_extract(self):
        result = self.build(request([self.page], mode="check"))
        self.assertTrue(result["should_extract"])
        self.assertFalse(result["already_extracted"])
        self.assertIsNone(result["record"])
        self.assertEqual(self.written(), [])

    def test_recording_writes_one_file_named_for_the_record(self):
        result = self.build(request([self.page]))
        self.assertEqual(self.written(), [f"{result['id']}.json"])
        self.assertEqual(result["record_path"],
                         str(self.ws.records / f"{result['id']}.json"))

    def test_the_written_file_is_the_whole_result(self):
        result = self.build(request([self.page]))
        stored = parse(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored["record"]["id"], result["id"])
        self.assertEqual(stored["audit_hash"], result["audit_hash"])

    def test_a_second_record_run_on_the_same_bytes_writes_nothing(self):
        first = self.build(request([self.page]))
        before = Path(first["record_path"]).read_text(encoding="utf-8")

        again = self.build(request([self.ws.page("rescanned.jpg")]))
        self.assertTrue(again["already_extracted"])
        self.assertIsNone(again["record"])
        self.assertEqual(again["existing_record_path"], first["record_path"])
        self.assertEqual(self.written(), [f"{first['id']}.json"])
        self.assertEqual(
            Path(first["record_path"]).read_text(encoding="utf-8"), before,
            "the existing record was rewritten")

    def test_a_check_after_a_record_says_not_to_extract(self):
        first = self.build(request([self.page]))
        result = self.build(request([self.page], mode="check"))
        self.assertFalse(result["should_extract"])
        self.assertTrue(result["already_extracted"])
        self.assertEqual(result["existing_record_path"], first["record_path"])

    def test_a_different_letter_is_extracted_alongside_the_first(self):
        self.build(request([self.page]))
        second = self.build(request([self.ws.page("b.jpg", OTHER)]))
        self.assertFalse(second["already_extracted"])
        self.assertEqual(len(self.written()), 2)

    def test_an_unreadable_record_is_counted_and_does_not_stop_the_run(self):
        # One corrupt file in extracted/ must not block every future letter,
        # and must not disappear either: a hash that cannot be read is a
        # duplicate this run cannot rule out.
        (self.ws.records / "broken.json").write_text("{ not json",
                                                     encoding="utf-8")
        result = self.build(request([self.page]))
        self.assertEqual(result["records_unreadable"], ["broken.json"])
        self.assertFalse(result["already_extracted"])
        self.assertIn("broken.json", result["summary"])


class EvidenceGateTests(unittest.TestCase):
    """Absent is not unevidenced."""

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)
        self.page = self.ws.page("letter.jpg")

    def build(self, **kwargs):
        return build_record(request([self.page], **kwargs), self.ws.records)

    def problems(self, result):
        return {row["field"]: row["reason"] for row in
                result["evidence_problems"]}

    def test_a_fully_quoted_letter_keeps_every_field_and_carries_no_flag(self):
        result = self.build()
        record = result["record"]
        self.assertEqual(record["issuer"], "Great Eastern Life Assurance")
        self.assertEqual(record["deadline"], "2026-09-15")
        self.assertEqual(record["amounts"], ["1220.00"])
        self.assertEqual(result["missing_evidence"], [])
        self.assertEqual(record["flags"], [])

    def test_a_value_with_no_snippet_is_nulled_and_flagged(self):
        result = self.build(evidence=evidence_with(deadline=None))
        self.assertIsNone(result["record"]["deadline"])
        self.assertIn("deadline", result["missing_evidence"])
        self.assertEqual(self.problems(result)["deadline"], "no_snippet")
        self.assertIn(FLAG, result["record"]["flags"])

    def test_a_blank_snippet_is_not_a_snippet(self):
        result = self.build(evidence=evidence_with(deadline="   \n  "))
        self.assertIsNone(result["record"]["deadline"])
        self.assertEqual(self.problems(result)["deadline"], "blank_snippet")

    def test_an_absent_value_is_null_without_a_flag(self):
        # The letter never mentioned a deadline. That is an answer, not a
        # failure, and flagging it would train the caregiver to ignore flags.
        result = self.build(fields=fields_with(deadline=None),
                            evidence=evidence_with(deadline=None))
        self.assertIsNone(result["record"]["deadline"])
        self.assertEqual(result["missing_evidence"], [])
        self.assertEqual(result["record"]["flags"], [])

    def test_a_snippet_that_does_not_contain_the_date_is_refused_as_evidence(self):
        result = self.build(
            evidence=evidence_with(deadline="Please respond promptly."))
        self.assertIsNone(result["record"]["deadline"])
        self.assertEqual(self.problems(result)["deadline"],
                         "value_not_in_snippet")
        self.assertIn(FLAG, result["record"]["flags"])

    def test_a_snippet_that_does_not_contain_the_amount_is_refused(self):
        # The audit story, reproduced: a plausible number quoted against text
        # that says something else. 4,320.00 must not survive a snippet
        # reading 1,220.00.
        result = self.build(fields=fields_with(amounts=["4320.00"]))
        self.assertIsNone(result["record"]["amounts"])
        self.assertEqual(self.problems(result)["amounts[0]"],
                         "value_not_in_snippet")
        self.assertIn(FLAG, result["record"]["flags"])

    def test_one_unevidenced_amount_nulls_the_whole_list(self):
        # A list with the unquotable one quietly dropped reads as complete.
        result = self.build(
            fields=fields_with(amounts=["1220.00", "80.00"]),
            evidence={**EVIDENCE, "amounts[1]": "no figure here"})
        self.assertIsNone(result["record"]["amounts"])
        self.assertIn("amounts[1]", result["missing_evidence"])
        self.assertNotIn("amounts[0]", result["missing_evidence"])

    def test_an_amount_survives_grouping_separators_and_a_currency_prefix(self):
        result = self.build(
            fields=fields_with(amounts=["1220"]),
            evidence=evidence_with(amount0="you owe S$1,220.00 in total"))
        self.assertEqual(result["record"]["amounts"], ["1220"])
        self.assertEqual(result["missing_evidence"], [])

    def test_a_date_is_recognised_written_out_or_in_numbers(self):
        for snippet in ("reply by 15 September 2026",
                        "reply by 15 Sept 2026",
                        "reply by 15/09/2026",
                        "reply by 2026-09-15"):
            with self.subTest(snippet=snippet):
                # A fresh workspace each time: the same bytes filed twice is a
                # no-op, which is the behaviour tested three classes up.
                other = Workspace(self.stack)
                result = build_record(
                    request([other.page("letter.jpg")],
                            evidence=evidence_with(deadline=snippet)),
                    other.records)
                self.assertEqual(result["record"]["deadline"], "2026-09-15",
                                 f"{snippet!r} was not accepted as evidence")

    def test_a_date_off_by_one_day_is_not_evidence_for_the_one_extracted(self):
        result = self.build(
            evidence=evidence_with(deadline="reply by 16 September 2026"))
        self.assertIsNone(result["record"]["deadline"])

    def test_an_issuer_must_appear_in_its_own_snippet(self):
        result = self.build(
            evidence=evidence_with(issuer="Yours faithfully, the Claims Team"))
        self.assertIsNone(result["record"]["issuer"])
        self.assertEqual(self.problems(result)["issuer"],
                         "value_not_in_snippet")

    def test_an_issuer_survives_a_different_case_and_a_company_suffix(self):
        result = self.build(
            fields=fields_with(issuer="Great Eastern Life Assurance Pte Ltd"))
        self.assertEqual(result["record"]["issuer"],
                         "Great Eastern Life Assurance Pte Ltd")

    def test_a_record_with_nothing_quotable_is_flagged_anyway(self):
        # A blurred photo extracts to all-nulls with no missing evidence, and
        # would otherwise exit 0 looking like a clean letter with no deadlines.
        result = self.build(
            fields={"issuer": None, "issue_date": None, "deadline": None,
                    "amounts": None, "required_action": None},
            evidence={})
        self.assertEqual(result["missing_evidence"], [])
        self.assertIn(FLAG, result["record"]["flags"])
        self.assertIn("nothing_evidenced",
                      [row["reason"] for row in result["evidence_problems"]])

    def test_required_action_is_kept_without_a_snippet(self):
        # It is the model's plain-language reading, not a claim about a number.
        result = self.build()
        self.assertIn("receipts", result["record"]["required_action"])
        self.assertNotIn("required_action", result["missing_evidence"])

    def test_the_snippets_are_kept_on_the_record_for_a_human_to_check(self):
        result = self.build()
        self.assertEqual(result["record"]["evidence"]["deadline"],
                         EVIDENCE["deadline"])

    def test_a_refused_snippet_is_still_kept_on_the_record(self):
        # The field is nulled; the text the model thought it saw is exactly
        # what the human confirming it needs to look at.
        result = self.build(
            evidence=evidence_with(deadline="Please respond promptly."))
        self.assertEqual(result["record"]["evidence"]["deadline"],
                         "Please respond promptly.")


class EnvelopeTests(unittest.TestCase):

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)
        self.page = self.ws.page("letter.jpg")

    def build(self, **kwargs):
        return build_record(request([self.page], **kwargs), self.ws.records)

    def test_tool_run_id_is_a_uuid4(self):
        result = self.build()
        self.assertEqual(uuid.UUID(result["tool_run_id"]).version, 4)

    def test_issued_at_carries_the_singapore_offset(self):
        self.assertIn("+08:00", self.build()["issued_at"])

    def test_extracted_at_is_the_moment_of_this_run(self):
        result = self.build()
        self.assertEqual(result["record"]["extracted_at"], result["issued_at"])

    def test_the_audit_hash_replays(self):
        first = self.build()
        second = build_record(request([self.page]), self.ws.records)
        # The second run is a no-op on an existing record, so hash the first
        # result again by hand: same inputs, same hash, different run id.
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])
        self.assertEqual(first["audit_hash"], audit_hash_of(first))

    def test_the_audit_hash_moves_when_a_field_does(self):
        first = self.build()
        other = Workspace(self.stack)
        page = other.page("letter.jpg")
        changed = build_record(
            request([page], fields=fields_with(required_action="Do nothing.")),
            other.records)
        self.assertNotEqual(first["audit_hash"], changed["audit_hash"])

    def test_conventions_state_the_rules_in_words(self):
        conventions = self.build()["conventions"]
        for key in ("evidence", "identity", "idempotency", "splitting",
                    "verbatim_limit", "handoff"):
            with self.subTest(key=key):
                self.assertIn(key, conventions)

    def test_the_verbatim_limit_is_stated_rather_than_claimed_away(self):
        note = self.build()["conventions"]["verbatim_limit"].lower()
        self.assertIn("cannot", note)

    def test_the_summary_reads_as_a_sentence(self):
        summary = self.build()["summary"]
        self.assertTrue(summary.endswith("."))
        self.assertGreater(len(summary.split()), 15)

    def test_the_summary_gets_the_article_right_before_a_doc_type(self):
        # Found by reading the output, not by a test: "a insurance letter".
        # The family artifact quotes this sentence.
        for doc_type, article in (("insurance", "an insurance"),
                                  ("appointment", "an appointment"),
                                  ("chas", "a chas"), ("bill", "a bill")):
            with self.subTest(doc_type=doc_type):
                other = Workspace(self.stack)
                result = build_record(
                    request([other.page(f"{doc_type}.jpg",
                                        doc_type.encode("utf-8"))],
                            doc_type=doc_type,
                            fields=fields_with(amounts=None),
                            evidence=evidence_with(amount0=None)),
                    other.records)
                self.assertIn(f"{article} letter", result["summary"])

    def test_the_summary_says_when_a_human_has_to_look(self):
        result = self.build(evidence=evidence_with(deadline=None))
        self.assertIn("deadline", result["summary"])
        self.assertIn("confirm", result["summary"].lower())

    def test_the_summary_ends_by_saying_nothing_was_acted_on(self):
        # It is read aloud into a family artifact. The last thing it says is
        # the thing the reader carries away.
        self.assertIn("Nothing has been answered, submitted or filed",
                      self.build()["summary"])


class DecimalTests(unittest.TestCase):
    """Money is exact and stays as written."""

    def setUp(self):
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.ws = Workspace(self.stack)
        self.page = self.ws.page("letter.jpg")

    def test_an_amount_keeps_the_string_the_letter_used(self):
        result = build_record(
            request([self.page], fields=fields_with(amounts=["1220.00"])),
            self.ws.records)
        self.assertEqual(result["record"]["amounts"], ["1220.00"])

    def test_a_decimal_amount_is_accepted_from_the_json_front_door(self):
        # json.loads(..., parse_float=Decimal) hands Decimals through, and the
        # script must take one without turning it into a float on the way out.
        document = parse(json.dumps(
            request([self.page], fields=fields_with(amounts=["1220.00"]))))
        result = build_record(document, self.ws.records)
        self.assertEqual(Decimal(result["record"]["amounts"][0]),
                         Decimal("1220.00"))


if __name__ == "__main__":
    unittest.main()
