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
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
DECISIONS = REPO / "docs" / "DECISIONS.md"
AGENT = REPO / "agents" / "care-navigator.md"
SKILL = REPO / "skills" / "care-coordinator-toolkit" / "SKILL.md"

# Budgets, not targets. Prose that outgrows one belongs in DECISIONS.md.
#
# These are a ratchet. CLAUDE.md was 1,831 words before the restructure; the
# budget was first set at 900 and raised **once**, to 975, after the reasoning
# had already been moved into DECISIONS.md and what remained was tables and
# one-line rules. It was raised because 900 was picked before anyone knew the
# irreducible size of the rules, not because the file earned more room.
#
# Do not raise it again to fit new prose. Either the prose is a rule, in which
# case something else here has stopped being one, or it is reasoning, and
# reasoning goes in DECISIONS.md.
WORD_BUDGETS = {
    CLAUDE: 975,
    DECISIONS: 1600,
}

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
                count = words(path)
                self.assertLessEqual(
                    count, budget,
                    f"{path.name} is {count} words against a {budget} budget — "
                    f"move the reasoning to docs/DECISIONS.md rather than "
                    f"raising the budget")

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
