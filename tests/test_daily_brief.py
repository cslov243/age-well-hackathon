"""Behaviour pinned for skills/daily-brief/SKILL.md.

The second skill, and the only one where the **senior artifact is the primary
one**. Every other skill writes for the family and then writes for her; this one
is the 8am briefing she hears, and the family copy is the secondary. That
inversion is the thing most likely to be quietly undone by a later edit, so it
is pinned structurally — by the order the two paths appear in the checklist —
rather than by a sentence saying it.

Two other properties worth a test, both of which a fluent edit would lose:

  * **a quiet day still produces both artifacts.** A brief that only arrives
    when something is wrong teaches her that its arrival is bad news.
  * **a `clinic_finder.py` distance is never called a walk.** It is a straight
    line over a snapshot; no route was computed and nothing here knows whether
    the way is step-free.

Following the direction set 6 August: pin structure and the handful of semantic
musts, not wording. This file checks that the scripts named exist, that the
chain is in invocation order, and that the checklist covers the whole run — the
things a substring test can actually establish.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills" / "daily-brief"
SKILL = SKILL_DIR / "SKILL.md"
TOOLKIT_SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    SECRET_SHAPES, parse_frontmatter, read_text, split_frontmatter)

SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
SCRIPT_MENTION = re.compile(r"\b(\w+\.py)\b")
FENCED = re.compile(r"```.*?```", re.DOTALL)

# Read, never invoked for their own sake: the brief reports what these already
# computed. Order is the order the body must first mention them.
CHAIN = ("medication_runout.py", "clinic_finder.py")

# Ratchet, not a target. Lower it when the file shrinks; do not raise it.
# Re-pointed 6 Aug 2026, 740 -> 830, paid for by a measured failure: eval case D
# wrote her brief in Mandarin when the profile said hokkien, and labelled her
# medicines with conditions the profile does not record. Both rules below are
# now stated explicitly. A budget is not worth more than that.
WORD_BUDGET = 830


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
            f"This file is injected on every scheduled run. Cut a sentence "
            f"rather than raising the number.")


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
        # Convention set 6 August: the routing clause is labelled so it is not
        # lost the next time the description is rewritten for length.
        self.assertIn("trigger:", self.fm["description"].lower())

    def test_description_covers_both_trigger_modes(self):
        # Whether an unattended scheduled run clears the permission dialog is
        # [UNKNOWN]. A description naming only the schedule would stop the
        # skill being selected when a caregiver simply asks for the brief.
        lower = self.fm["description"].lower()
        self.assertIn("scheduled", lower)
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


class SourceTests(unittest.TestCase):
    """It reports what other scripts computed. It computes nothing itself."""

    @classmethod
    def setUpClass(cls):
        cls.body = body()
        cls.named = set(SCRIPT_MENTION.findall(cls.body))

    def test_every_script_it_names_exists(self):
        for name in sorted(self.named):
            with self.subTest(script=name):
                self.assertTrue(
                    (TOOLKIT_SCRIPTS / name).is_file(),
                    f"SKILL.md names {name}, which is not in the toolkit")

    def test_it_names_every_script_it_reads_from(self):
        self.assertEqual(self.named, set(CHAIN))

    def test_the_sources_appear_in_order(self):
        positions = [self.body.index(name) for name in CHAIN]
        self.assertEqual(positions, sorted(positions),
                         f"scripts are not first mentioned in {CHAIN} order")

    def test_it_re_reads_no_document(self):
        # The whole reason a daily run costs almost nothing: it reasons over
        # structured records and never re-opens an image.
        lower = prose_only(self.body).lower()
        self.assertIn("extracted/", self.body)
        self.assertIn("no vision", lower)

    def test_it_says_paths_must_be_absolute(self):
        self.assertIn("absolute", self.body.lower())


class SeniorFirstTests(unittest.TestCase):
    """The inversion that makes this skill different from every other one."""

    @classmethod
    def setUpClass(cls):
        cls.body = body()
        cls.items = re.findall(r"^\s*- \[ \] (.+)$", cls.body, re.MULTILINE)
        cls.checklist = "\n".join(cls.items)

    def test_there_is_a_checklist(self):
        self.assertGreaterEqual(len(self.items), 4)

    def test_the_checklist_is_unchecked(self):
        self.assertNotIn("- [x]", self.body.lower())

    def test_the_senior_artifact_comes_first_in_the_checklist(self):
        # Structural, on purpose. Every other skill writes out/family/ first;
        # here the order is the product decision, and an edit that reorders
        # the steps has undone it whatever the surrounding prose still claims.
        senior = self.checklist.index("out/senior/")
        family = self.checklist.index("out/family/")
        self.assertLess(
            senior, family,
            "the family artifact is listed before the senior's. This is the "
            "one skill where she is briefed first.")

    def test_the_checklist_covers_the_whole_run(self):
        for step in ("out/senior/", "out/family/",
                     "out/senior/shared_log.jsonl"):
            with self.subTest(step=step):
                self.assertIn(step, self.checklist)

    def test_a_quiet_day_still_produces_both_artifacts(self):
        # A brief that appears only when something is wrong teaches her that
        # its arrival is bad news.
        self.assertIn("nothing due", prose_only(self.body).lower())

    def test_it_reads_her_language_rather_than_assuming(self):
        self.assertIn("HouseholdProfile", self.body)
        self.assertIn("never assume", self.body.lower())

    def test_it_addresses_her_directly(self):
        self.assertIn("second person", self.body.lower())

    def test_it_forbids_substituting_a_near_enough_language(self):
        # Measured failure, eval case D, 6 Aug 2026: profile said `hokkien`,
        # the agent wrote Mandarin and said nothing. CONTRACTS.md records that
        # Hokkien TTS is effectively unavailable, so the correct move is to
        # name the gap and ask — not to pick the nearest fluent language.
        lower = prose_only(body()).lower()
        self.assertIn("hokkien", lower)
        self.assertIn("mandarin", lower)

    def test_it_forbids_inferring_a_condition_from_a_medicine(self):
        # Same run: "your blood pressure medicine" is a diagnosis read off a
        # drug name and told to the patient, with an empty chronic_conditions.
        self.assertIn("chronic_conditions", body())


class DistanceTests(unittest.TestCase):
    """clinic_finder.py returns a straight line. It is not a walk."""

    @classmethod
    def setUpClass(cls):
        cls.lower = prose_only(body()).lower()

    def test_it_forbids_calling_the_distance_a_walk(self):
        self.assertIn("straight line", self.lower)
        self.assertIn("not a walk", self.lower)

    def test_it_says_no_route_was_computed(self):
        self.assertIn("no route", self.lower)


class RefusalTests(unittest.TestCase):
    """SKILL.md is injected at invocation. It carries its own constraints.

    Stated as a headed bulleted block rather than as sentences in the body —
    docs/AUDIT-FINDINGS.md #10 measured three agents obeying every bulleted
    refusal and ignoring every reporting rule buried in prose.
    """

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
