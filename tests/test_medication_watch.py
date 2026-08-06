"""Behaviour pinned for skills/medication-watch/SKILL.md.

The first skill in the plugin, and the first file that has to describe a *chain*
rather than a single script. Two things can rot here that nothing else catches:

  * **the chain drifts from the scripts.** A skill that names a script which
    does not exist, or forgets one that does, produces a run that silently does
    half the work. `test_skill_manifest.py` guards the toolkit from both
    directions; this does the same for the skill that invokes it.
  * **a constraint gets stated in one runtime file and not another.** SKILL.md
    is injected at invocation. If the dual-output rule or the never-order rule
    lives only in the agent body, this skill can run without ever seeing it.

The word budget is a ratchet at the measured value, exactly as in
test_project_docs.py: this file is injected on every scheduled run, so its
length is paid for daily.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills" / "medication-watch"
SKILL = SKILL_DIR / "SKILL.md"
TOOLKIT_SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    SECRET_SHAPES, parse_frontmatter, read_text, split_frontmatter)

SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
SCRIPT_MENTION = re.compile(r"\b(\w+\.py)\b")
FENCED = re.compile(r"```.*?```", re.DOTALL)

# The scripts this skill chains, in the order it must invoke them. Order is
# load-bearing: the cart consumes what the other two produce.
CHAIN = ("purchase_terms.py", "medication_runout.py", "pharmacy_cart.py")

# Ratchet, not a target. Lower it when the file shrinks; do not raise it.
# Re-pointed 6 Aug 2026, 700 -> 730: the description gained a labelled
# `trigger:` clause naming both invocation modes. That is routing text the
# runtime selects on, not prose, so the budget absorbs it rather than the
# body losing a sentence to pay for it.
WORD_BUDGET = 730


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
        # The deterministic layer is shared and lives in one place. A second
        # copy of any of it here is how the two drift.
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

    def test_description_says_when_to_use_it(self):
        self.assertIn("when", self.fm["description"].lower())

    def test_description_covers_both_trigger_modes(self):
        # Whether an unattended scheduled run clears the permission dialog is
        # [UNKNOWN]. A description that only mentions the schedule would stop
        # the skill being selected when a caregiver simply asks.
        lower = self.fm["description"].lower()
        self.assertIn("scheduled", lower)
        self.assertIn("asks", lower)

    def test_description_is_third_person(self):
        # It is injected into a system prompt to decide selection; second
        # person there addresses nobody consistently.
        match = SECOND_PERSON.search(self.fm["description"])
        self.assertIsNone(
            match, f"description is second person at {match.group(0)!r}"
            if match else "")

    def test_description_is_within_the_length_limit(self):
        self.assertLessEqual(len(self.fm["description"]), 1024)

    def test_frontmatter_names_no_scripts(self):
        self.assertEqual(SCRIPT_MENTION.findall(self.fm_text), [])


class ChainTests(unittest.TestCase):
    """The skill's whole job is invoking three scripts in one order."""

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

    def test_it_names_every_script_in_the_chain(self):
        self.assertEqual(self.named, set(CHAIN))

    def test_the_chain_is_documented_in_invocation_order(self):
        # The cart consumes what the other two produce. Documented out of
        # order, it gets invoked out of order and refuses its own input.
        positions = [self.body.index(name) for name in CHAIN]
        self.assertEqual(positions, sorted(positions),
                         f"scripts are not first mentioned in {CHAIN} order")

    def test_it_says_the_forecast_is_passed_verbatim(self):
        # pharmacy_cart.py recomputes the forecast's audit_hash and refuses a
        # mismatch. A skill that rebuilds the object produces a refusal that
        # reads like bad input.
        lower = self.body.lower()
        self.assertIn("verbatim", lower)
        self.assertIn("audit_hash", self.body)

    def test_it_forbids_arithmetic_between_the_steps(self):
        self.assertIn("no arithmetic", self.body.lower())

    def test_it_says_paths_must_be_absolute(self):
        self.assertIn("absolute", self.body.lower())


class SupplyChannelTests(unittest.TestCase):
    """The one decision the model must never take."""

    @classmethod
    def setUpClass(cls):
        cls.body = prose_only(body())

    def test_it_forbids_supplying_a_channel(self):
        self.assertIn("supply_channel", self.body)
        self.assertIn("never", self.body.lower())

    def test_it_states_that_unknown_stays_out_of_the_cart(self):
        lower = self.body.lower()
        self.assertIn("unknown", lower)
        self.assertIn("prescription", lower)

    def test_it_says_cover_days_has_no_default(self):
        # How much to buy is a person's call, and a guessed 30 is a guess
        # nobody would see.
        self.assertIn("cover_days", self.body)
        self.assertIn("no default", self.body.lower())


class RunWorkflowTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.body = body()
        cls.items = re.findall(r"^\s*- \[ \] (.+)$", cls.body, re.MULTILINE)

    def test_there_is_a_checklist(self):
        self.assertGreaterEqual(len(self.items), 4)

    def test_the_checklist_covers_the_whole_run(self):
        joined = "\n".join(self.items)
        for step in ("out/family/", "out/senior/",
                     "out/senior/shared_log.jsonl"):
            with self.subTest(step=step):
                self.assertIn(step, joined)

    def test_the_checklist_is_unchecked(self):
        self.assertNotIn("- [x]", self.body.lower())

    def test_it_names_the_step_that_gets_skipped(self):
        # Dual output is the product thesis, and the senior half is the half
        # that goes missing.
        self.assertIn("out/senior/", self.body)
        self.assertIn("skipped", self.body.lower())

    def test_it_reads_her_language_rather_than_assuming(self):
        self.assertIn("HouseholdProfile", self.body)
        self.assertIn("never assume", self.body.lower())

    def test_it_addresses_her_directly(self):
        self.assertIn("second person", self.body.lower())


class RefusalTests(unittest.TestCase):
    """SKILL.md is injected at invocation. It carries its own constraints."""

    @classmethod
    def setUpClass(cls):
        cls.body = prose_only(body())
        cls.lower = cls.body.lower()

    def test_has_an_explicit_does_not_section(self):
        self.assertIn("does not", self.lower)

    def test_never_orders_and_never_pays(self):
        self.assertIn("requires_human_checkout", self.body)
        for term in ("does not order", "does not pay"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_no_clinical_advice(self):
        self.assertIn("clinical", self.lower)
        self.assertIn("dose", self.lower)

    def test_never_computes_a_number_in_prose(self):
        self.assertIn("compute a number in prose", self.lower)

    def test_never_submits_and_handles_no_credential(self):
        for term in ("credential", "singpass", "otp"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_prn_medicines_are_never_forecast(self):
        self.assertIn("prn", self.lower)

    def test_no_secret_shaped_content(self):
        # WorkBuddy security-scans plugins on install.
        self.assertIsNone(SECRET_SHAPES.search(self.body))


if __name__ == "__main__":
    unittest.main()
