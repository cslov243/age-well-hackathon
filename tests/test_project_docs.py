"""Behaviour pinned for the project docs — CLAUDE.md and docs/DECISIONS.md.

Two things are guarded here, and neither was guarded before.

**Length.** These files grew into essays: nine docs, 14,389 words, of which
CLAUDE.md was 1,831 injected into every session and SKILL.md 1,570 injected at
skill selection. That is a comprehension cost before it is a token cost — a rule
buried in paragraph four of a rationale is a rule that gets skimmed. The budgets
below are deliberately tight. When one binds, the answer is to move the reasoning
into docs/DECISIONS.md, not to raise the number.

**Reach.** CLAUDE.md is where the hard constraints are decided, but it is not
read at runtime by anything. The agent body and SKILL.md are. Until now each of
the three files carried its own hand-maintained list, so a constraint could be
added to the design doc and never reach a runtime — the failure mode is a rule
everyone believes is enforced and nothing states. One list, checked against every
file that has to carry it.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_skill_manifest import scripts_on_disk  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
DECISIONS = REPO / "docs" / "DECISIONS.md"
AGENT = REPO / "agents" / "care-navigator.md"
SKILL = REPO / "skills" / "care-coordinator-toolkit" / "SKILL.md"

# These are a **ratchet set at the achieved value**, not aspirational targets.
#
# Aspirational numbers were tried first and failed twice: a budget picked before
# anyone knew the irreducible size of the rules is a number that gets relaxed the
# moment it binds, which teaches exactly the wrong habit. Each figure below is
# what the file actually measured once the reasoning had been moved into
# DECISIONS.md and the prose had been cut as far as it could go without deleting
# a rule.
#
# The consequence is deliberate: **editing these files is zero-sum.** Adding a
# sentence means removing one. If a genuinely new rule needs room, something
# below it has stopped being a rule, or the reasoning belongs in DECISIONS.md.
# Lower a number when a file shrinks; do not raise one.
#
# For the record, before the restructure: CLAUDE.md 1,831 words, SKILL.md 1,382,
# the agent body 1,327 — 4,540 down to 3,044.
#
# SKILL.md and the agent body matter twice over: both are injected into a model's
# context — the agent at expert selection, SKILL.md at invocation — so every word
# is paid for on every run that touches them.
#
# DECISIONS.md is the exception. It is a ceiling with room, not a ratchet,
# because recording a new settled decision is the file working as intended.
WORD_BUDGETS = {
    CLAUDE: 949,
    SKILL: 1002,
    AGENT: 1093,
    DECISIONS: 1600,
}

# SKILL.md is the one file that legitimately grows: test_skill_manifest.py fails
# if a script on disk is undocumented, so every new script must buy a section
# here. A flat ratchet would put those two rules in direct conflict the next time
# a script lands. Each script beyond the current three earns this much and no
# more — enough for a Use when / Requires / Source of truth / Never block, tight
# enough that it has to be written the way the existing three are.
WORDS_PER_ADDITIONAL_SCRIPT = 120
SCRIPTS_AT_RATCHET = 3

FENCED = re.compile(r"```.*?```", re.DOTALL)

# Every hard constraint, as the substring that proves it is stated. Lowercased
# before matching. This is the single source; the files below must all carry it.
HARD_CONSTRAINTS = (
    "never submit",
    "singpass",
    "credential",
    "clinical",
    "never compute",
    "network",
    "requires_human_confirmation",
    "verbatim",
    "out/family/",
    "out/senior/shared_log.jsonl",
)

# Carried in prose by every file a model actually reads. CLAUDE.md decides them;
# these two are where they reach a runtime.
CARRIERS = (CLAUDE, AGENT, SKILL)

# Reasoning that was moved out of CLAUDE.md. It is prepared Demo Day material,
# so losing it is expensive and silently losing it is worse.
DECISION_TOPICS = (
    "grab",            # third-party commerce, and the shape that is permitted
    "singpass",        # permanently out of scope, by design not by limitation
    "behavioural",     # audit finding #8 — decided, not built
)


def words(path):
    """Word count over prose, with fenced blocks removed.

    A directory tree or a JSON example is reference material, not prose a reader
    has to wade through, and counting it would push the budget the wrong way.
    """
    return len(FENCED.sub("", path.read_text(encoding="utf-8")).split())


class LengthTests(unittest.TestCase):
    """The complaint that started this: too wordy, no structure."""

    def test_prose_stays_within_budget(self):
        for path, budget in WORD_BUDGETS.items():
            with self.subTest(doc=path.name):
                self.assertTrue(path.is_file(), f"missing {path}")
                budget = self.budget_for(path, budget)
                count = words(path)
                self.assertLessEqual(
                    count, budget,
                    f"{path.name} is {count} words against a {budget} budget — "
                    f"move the reasoning to docs/DECISIONS.md rather than "
                    f"raising the budget")

    @staticmethod
    def budget_for(path, budget):
        """The SKILL.md budget grows with the number of scripts it must cover."""
        if path != SKILL:
            return budget
        extra = max(0, len(scripts_on_disk()) - SCRIPTS_AT_RATCHET)
        return budget + extra * WORDS_PER_ADDITIONAL_SCRIPT

    def test_claude_md_is_structured_not_an_essay(self):
        # Scannable means headings and tables. Prose under a heading is fine;
        # eight hundred words with three headings is what this replaces.
        text = CLAUDE.read_text(encoding="utf-8")
        headings = re.findall(r"^## ", text, re.MULTILINE)
        self.assertGreaterEqual(len(headings), 6, "too few sections to scan")
        self.assertIn("|", text, "no table anywhere in CLAUDE.md")

    def test_no_paragraph_runs_longer_than_a_screen(self):
        text = FENCED.sub("", CLAUDE.read_text(encoding="utf-8"))
        for block in text.split("\n\n"):
            if block.lstrip().startswith(("-", "|", "#", ">")):
                continue
            with self.subTest(block=block[:60]):
                self.assertLessEqual(
                    len(block.split()), 120,
                    "paragraph is longer than a screen; make it a list")


class HardConstraintReachTests(unittest.TestCase):
    """One list, checked against every file that has to carry it."""

    def test_every_constraint_is_stated_in_every_carrier(self):
        for path in CARRIERS:
            body = path.read_text(encoding="utf-8").lower()
            for constraint in HARD_CONSTRAINTS:
                with self.subTest(doc=path.name, constraint=constraint):
                    self.assertIn(
                        constraint, body,
                        f"{path.name} never states {constraint!r} — a "
                        f"constraint that does not reach a runtime file is not "
                        f"enforced, it is believed")

    def test_the_three_permitted_eligibility_strings_are_decided_here(self):
        body = CLAUDE.read_text(encoding="utf-8")
        for phrase in ("likely eligible", "worth checking",
                       "insufficient information"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_forbidden_eligibility_phrasing_is_named_as_forbidden(self):
        self.assertIn("you qualify", CLAUDE.read_text(encoding="utf-8").lower())


class DecisionsTests(unittest.TestCase):
    """Reasoning moved out of CLAUDE.md still has to exist somewhere."""

    def test_decisions_file_exists(self):
        self.assertTrue(DECISIONS.is_file(), f"missing {DECISIONS}")

    def test_it_covers_every_decision_moved_out_of_claude_md(self):
        body = DECISIONS.read_text(encoding="utf-8").lower()
        for topic in DECISION_TOPICS:
            with self.subTest(topic=topic):
                self.assertIn(topic, body)

    def test_claude_md_points_at_it(self):
        self.assertIn("docs/DECISIONS.md", CLAUDE.read_text(encoding="utf-8"))

    def test_it_records_a_decision_not_a_wish_list(self):
        # Each entry states what was decided. A file of open questions is a
        # backlog, and there is already one of those.
        body = DECISIONS.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(re.findall(r"^## ", body, re.MULTILINE)), 3)
        self.assertIn("Decided", body)


if __name__ == "__main__":
    unittest.main()
