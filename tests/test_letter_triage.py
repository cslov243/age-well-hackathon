"""Behaviour pinned for skills/letter-triage/SKILL.md.

The entry point of the core loop, and the only skill where the model itself is
the instrument rather than the narrator. Three properties carry the weight, and
each one is the model being asked to do the opposite of what it is good at:

  * **Check before you look.** The hash comes first and the vision call second.
    A skill file that reads as though extraction were step one produces a
    second record for every letter that gets rescanned.
  * **Quote or say nothing.** A field is kept only when it can be quoted. The
    temptation is a plausible number with a nearby snippet, and the file has to
    forbid it in the imperative rather than describe the script's behaviour.
  * **Split rather than merge.** Grouping pages is the model's call and the
    script cannot check it. A duplicate record costs a second notification; a
    merge silently eats a deadline.

Following the direction set 6 August: pin structure and the handful of semantic
musts, not wording.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills" / "letter-triage"
SKILL = SKILL_DIR / "SKILL.md"
TOOLKIT_SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    SECRET_SHAPES, parse_frontmatter, read_text, split_frontmatter)

SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
SCRIPT_MENTION = re.compile(r"\b(\w+\.py)\b")
FENCED = re.compile(r"```.*?```", re.DOTALL)

# Invocation order: identity first, the extraction it guards second, and the
# claim review only once there is a record with a doc_type to route on.
CHAIN = ("letter_record.py", "insurance_claim_review.py", "confirmations.py")

# Ratchet, not a target. Lower it when the file shrinks; do not raise it.
# Set at the measured value on 6 Aug 2026. It sits above deadline-watch because
# this is the only skill that runs a script, then the model, then the same
# script again, and the ordering is the thing being taught.
#
# Re-pointed 1000 -> 991 the same day, cycle L. The file gained the language
# rules and the refused-value rule and still came out smaller, because the
# budget forced the question of what the older prose was earning. The SGD
# 4,320.00 anecdote went: cycle K made that rule a check in code, so the file
# no longer has to argue for it.
WORD_BUDGET = 991


def body():
    return split_frontmatter(read_text(SKILL))[1]


def prose_only(text):
    """Body with fenced blocks removed — an example is not documentation."""
    return FENCED.sub("", text)


class SkillFileTests(unittest.TestCase):

    def test_skill_md_exists_not_skill_yml(self):
        # The published English docs say `skill.yml`. They are wrong.
        self.assertTrue(SKILL.exists(), f"missing {SKILL}")
        self.assertFalse((SKILL_DIR / "skill.yml").exists())
        self.assertFalse((SKILL_DIR / "skill.yaml").exists())

    def test_it_ships_no_scripts_of_its_own(self):
        self.assertFalse((SKILL_DIR / "scripts").exists())

    def test_it_is_within_its_word_budget(self):
        words = len(read_text(SKILL).split())
        self.assertLessEqual(
            words, WORD_BUDGET,
            f"SKILL.md is {words} words against a budget of {WORD_BUDGET}. "
            f"This file is injected on every document that arrives. Cut a "
            f"sentence rather than raising the number.")


class FrontmatterTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fm_text, cls.body = split_frontmatter(read_text(SKILL))
        cls.fm = parse_frontmatter(cls.fm_text)

    def test_frontmatter_is_minimal(self):
        self.assertEqual(set(self.fm), {"name", "description"})

    def test_name_matches_the_directory(self):
        self.assertEqual(self.fm["name"], SKILL_DIR.name)

    def test_description_labels_its_trigger(self):
        self.assertIn("trigger:", self.fm["description"].lower())

    def test_description_covers_both_trigger_modes(self):
        # Whether a watched folder fires unattended is [UNKNOWN]. A description
        # naming only file arrival would stop the skill being selected when a
        # caregiver drops a photo into the chat and asks what it says.
        lower = self.fm["description"].lower()
        self.assertIn("arriv", lower)
        self.assertIn("asks", lower)

    def test_description_is_third_person(self):
        match = SECOND_PERSON.search(self.fm["description"])
        self.assertIsNone(
            match, f"description is second person at {match.group(0)!r}"
            if match else "")

    def test_description_is_within_the_length_limit(self):
        self.assertLessEqual(len(self.fm["description"]), 1024)

    def test_frontmatter_names_no_scripts(self):
        self.assertEqual(SCRIPT_MENTION.findall(self.fm_text), [])


class ChainTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.body = body()
        cls.prose = prose_only(cls.body)
        cls.named = set(SCRIPT_MENTION.findall(cls.body))

    def test_every_script_it_names_exists(self):
        for name in sorted(self.named):
            with self.subTest(script=name):
                self.assertTrue(
                    (TOOLKIT_SCRIPTS / name).is_file(),
                    f"SKILL.md names {name}, which is not in the toolkit")

    def test_it_names_every_script_in_the_chain(self):
        self.assertEqual(self.named, set(CHAIN))

    def test_the_chain_appears_in_invocation_order(self):
        positions = [self.body.index(name) for name in CHAIN]
        self.assertEqual(positions, sorted(positions),
                         f"scripts are not first mentioned in {CHAIN} order")

    def test_it_says_paths_must_be_absolute(self):
        self.assertIn("absolute", self.body.lower())

    def test_the_check_comes_before_the_extraction(self):
        # A vision call is the expensive step and the only irreversible cost in
        # the loop. Both modes must be named, and check must come first.
        prose = self.prose
        self.assertIn("check", prose)
        self.assertIn("record", prose)
        self.assertLess(prose.index('"check"'), prose.index('"record"'),
                        "the record mode is described before the check")

    def test_it_says_an_already_extracted_letter_is_not_read_again(self):
        lower = self.prose.lower()
        self.assertIn("already", lower)
        self.assertIn("again", lower)

    def test_it_says_the_required_keys_are_required_even_when_null(self):
        prose = self.prose
        self.assertIn("null", prose)
        for key in ("issuer", "issue_date", "deadline", "amounts",
                    "required_action"):
            with self.subTest(key=key):
                self.assertIn(key, prose)

    def test_insurance_routes_to_the_claim_review_rather_than_a_new_skill(self):
        self.assertIn("insurance", self.prose.lower())


class EvidenceTests(unittest.TestCase):
    """The one thing the model does here is the one thing it can fake."""

    @classmethod
    def setUpClass(cls):
        cls.prose = prose_only(body())
        cls.lower = cls.prose.lower()

    def test_it_demands_a_verbatim_snippet(self):
        self.assertIn("verbatim", self.lower)

    def test_it_distinguishes_absent_from_unquotable(self):
        # Absent means the letter never said it and zero is often right.
        # Unquotable means unknown. Substituting the second for the first is
        # the SGD 4,320.00 defect.
        self.assertIn("absent", self.lower)
        for term in ("unquot", "cannot quote", "can't quote"):
            if term in self.lower:
                break
        else:
            self.fail("nothing in the prose names the unquotable case")

    def test_it_forbids_reporting_a_confidence(self):
        self.assertIn("confidence", self.lower)

    def test_it_names_the_flag_the_rest_of_the_repo_spells_the_same_way(self):
        self.assertIn("REQUIRES_HUMAN_CONFIRMATION", self.prose)

    def test_it_says_to_leave_a_field_null_rather_than_fill_it(self):
        self.assertIn("missing_evidence", self.prose)

    def test_page_grouping_biases_toward_splitting(self):
        self.assertIn("split", self.lower)
        self.assertIn("merge", self.lower)

    def test_a_refused_value_may_not_be_carried_forward(self):
        # Measured failure, eval case G, cycles J and K. The gate nulled two
        # fields; the agent kept the figures it had computed and hand-fed them
        # to the next script, and all three artifacts reported them as settled.
        # The file already says a flagged record is a correct outcome — that is
        # a headed bullet and it was ignored twice, so this is not finding #10.
        # What it never said is that the refusal belongs to the *number*, not
        # to the record: a refused value goes into no input, artifact or answer.
        for term in ("refused", "refuses", "refusal"):
            if term in self.lower:
                break
        else:
            self.fail("nothing in the prose names a refused value")
        for term in ("carry", "carried", "carrying", "hand-feed", "by hand"):
            if term in self.lower:
                break
        else:
            self.fail(
                "the prose never forbids carrying a refused value forward. "
                "A rule about the record is not a rule about the number.")


class BothArtifactsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.body = body()
        cls.items = re.findall(r"^\s*- \[ \] (.+)$", cls.body, re.MULTILINE)
        cls.checklist = "\n".join(cls.items)

    def test_there_is_a_checklist(self):
        self.assertGreaterEqual(len(self.items), 5)

    def test_the_checklist_is_unchecked(self):
        self.assertNotIn("- [x]", self.body.lower())

    def test_the_checklist_covers_the_whole_run(self):
        for step in ("extracted/", "processed/", "out/family/", "out/senior/",
                     "out/senior/shared_log.jsonl"):
            with self.subTest(step=step):
                self.assertIn(step, self.checklist)

    def test_the_image_moves_only_after_the_record_is_written(self):
        positions = [self.checklist.index(step)
                     for step in ("extracted/", "processed/")]
        self.assertEqual(positions, sorted(positions),
                         "the page is moved before the record exists")

    def test_it_reads_her_language_rather_than_assuming(self):
        self.assertIn("HouseholdProfile", self.body)
        self.assertIn("never assume", self.body.lower())

    def test_it_addresses_her_directly(self):
        self.assertIn("second person", self.body.lower())

    def test_it_forbids_substituting_a_near_enough_language(self):
        # Measured failure, eval case G, cycle J: the profile said `hokkien`
        # and her copy came out as written Chinese. `daily-brief` and
        # `deadline-watch` both carry this ban; the file that ran did not, and
        # that is the whole of finding #15's first half.
        lower = prose_only(self.body).lower()
        self.assertIn("hokkien", lower)
        for term in ("substitut", "near-enough", "nearest"):
            if term in lower:
                break
        else:
            self.fail("nothing in the prose forbids a near-enough language")

    def test_a_read_aloud_script_is_labelled_with_the_language_on_the_page(self):
        # Narrowed 6 Aug 2026 by the cycle K re-run, which produced English
        # headed "(Read-aloud script for Hokkien speaker)". No substitution —
        # but the label names the language she *speaks*, and a household that
        # reads `en` and `zh` cannot tell from it which one it was handed.
        lower = prose_only(self.body).lower()
        self.assertIn("read-aloud", lower)
        for term in ("written in", "language of the page", "label it with"):
            if term in lower:
                break
        else:
            self.fail(
                "the read-aloud fallback is not required to name the language "
                "it is actually written in")

    def test_the_checklist_runs_the_confirmation_check_before_it_writes(self):
        # The flag reached neither artifact in two consecutive runs, and on the
        # third the artifact asserted its negation — finding #22. Naming the
        # flag in the checklist was not enough twice over, so the checklist now
        # names the script that answers the question, and it has to come before
        # the artifacts that quote it.
        lower = self.checklist.lower()
        self.assertIn("confirmations.py", lower)
        self.assertIn("confirm", lower)
        self.assertLess(lower.index("confirmations.py"), lower.index("out/family/"),
                        "the artifacts are written before the confirmation "
                        "check that they are supposed to quote")

    def test_the_prose_forbids_certifying_that_nobody_need_confirm(self):
        # The absence of a flag is not a finding. An artifact silent about
        # confirmation is correct; one certifying its absence is finding #22.
        lower = prose_only(self.body).lower()
        self.assertIn("no confirmation is needed", lower)

    def test_a_condition_is_never_inferred_from_a_letter(self):
        # Measured failure, eval case D, 6 Aug 2026: "your blood pressure
        # medicine" read off a drug name against an empty chronic_conditions.
        self.assertIn("chronic_conditions", self.body)


class NoNumberTheScriptDidNotProduceTests(unittest.TestCase):
    """Findings #20 and #21, both measured on the cycle M case G run — the
    best run this case has had, tool and answer both passing.

    They are one defect wearing two hats. #20 is a date the artifact invented
    beside a correct one; #21 is a claim about where a correct figure came
    from. Neither is caught by anything in `tests/`, because both live in
    prose the suite never reads, and neither is the old failure of writing a
    number *instead of* a script's — in both cases the script's output was in
    hand and right.
    """

    @classmethod
    def setUpClass(cls):
        cls.prose = prose_only(body())
        cls.lower = cls.prose.lower()

    def test_it_forbids_a_date_added_beside_a_correct_one(self):
        # "- [ ] If appealing: gather itemised bill and referral letter by
        #  25 August 2026" sat one line above the script's 27 August. Nothing
        # in the checklist distinguished the date that survives a replay from
        # the one that does not.
        for term in ("beside", "second date", "as well as"):
            if term in self.lower:
                break
        else:
            self.fail("the prose never names a date added beside a correct one")

    def test_it_names_the_shapes_an_invented_date_arrives_in(self):
        # A buffer does not feel like arithmetic, which is why the existing
        # rule did not catch it.
        for term in ("buffer", "lead time", "start gathering", "working target"):
            if term in self.lower:
                break
        else:
            self.fail(
                "no example of an invented date that is not a recomputation")

    def test_her_copy_may_not_say_the_letter_states_a_computed_figure(self):
        # "All of this is in the letter. They are not my numbers — they are
        # what the letter from Great Eastern says." The letter prints 1,220.00
        # and 860.00. It does not print the 360.00 balance.
        for term in ("worked out", "derived", "computed from"):
            if term in self.lower:
                break
        else:
            self.fail(
                "the prose gives her copy no way to attribute a figure to the "
                "script's arithmetic, so the only attribution on offer is to "
                "the page — which is false for every figure the script exists "
                "to produce")

    def test_the_provenance_rule_is_about_what_she_can_check(self):
        # The point is not bookkeeping. "The letter says so" is precisely the
        # claim the person being addressed cannot verify, because she is the
        # one who cannot read the letter.
        for term in ("check", "verify"):
            if term in self.lower:
                break
        else:
            self.fail("the provenance rule is stated without its reason")


class RefusalTests(unittest.TestCase):
    """SKILL.md is injected at invocation. It carries its own constraints."""

    @classmethod
    def setUpClass(cls):
        cls.body = prose_only(body())
        cls.lower = cls.body.lower()

    def test_has_an_explicit_does_not_section(self):
        self.assertIn("does not", self.lower)

    def test_never_computes_a_number_in_prose(self):
        self.assertIn("compute a number in prose", self.lower)

    def test_no_clinical_advice(self):
        self.assertIn("clinical", self.lower)

    def test_never_submits_and_handles_no_credential(self):
        for term in ("credential", "singpass"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_never_asserts_eligibility(self):
        self.assertIn("eligib", self.lower)

    def test_no_secret_shaped_content(self):
        # WorkBuddy security-scans plugins on install.
        self.assertIsNone(SECRET_SHAPES.search(self.body))


if __name__ == "__main__":
    unittest.main()
