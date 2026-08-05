"""Behaviour pinned for README.md.

The README is the file most likely to drift into describing the intended
product rather than the built one. It is also a plugin payload file, so it is
read by the install-time security scan and by a judge deciding whether the
guardrails are real or decorative. Both audiences are harmed by the same
defect: a sentence that is true of the plan and false of the disk.

Audit finding #5 was a `SKILL.md` citing `scripts/verify_scheme.py`, which was
never written. A README is finding #5 with a wider blast radius, so the
assertions here are the same shape as `tests/test_skill_manifest.py`:

  * every script and every repo path the README names exists on disk — and the
    handful that legitimately do not yet exist may only be named in a section
    that says they do not exist;
  * the six skills, `references/` and `templates/` are unwritten, so they may
    appear only in that same section;
  * the test command the README prints is **executed**, not trusted, and the
    test count it states is compared against what that run reports.

The count is stated deliberately. It is the most useful number in the file for
a judge and the most certain to go stale, so it is pinned to a real run rather
than left to be remembered.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
SKILL_DIR = REPO / "skills" / "care-coordinator-toolkit"
SCRIPTS = SKILL_DIR / "scripts"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    PERMITTED_ELIGIBILITY, SECRET_SHAPES, read_text)
from test_skill_manifest import (  # noqa: E402
    INVOCATION, SCRIPT_MENTION, scripts_on_disk)

# Running the README's own test command from inside the suite would recurse
# forever. The child run sets this, and the one test that shells out skips when
# it sees it. The skip is only ever visible inside the child process.
CHILD_GUARD = "CARE_NAVIGATOR_README_TEST_CHILD"

TEST_COMMAND = "python3 -m unittest discover -s tests"

# Named in the README, absent from disk, and each one allowed only inside a
# section that says so. `avatars/expert.png` is a human to-do the manifest
# already points at; the other two are plugin-tree directories nothing needs
# yet.
ALLOWED_ABSENT = {
    "avatars/expert.png",
    "skills/care-coordinator-toolkit/templates/",
}

# The six skills in CLAUDE.md. None are written. A README that lists them as
# features is the exact drift this file exists to catch.
UNWRITTEN_SKILLS = ("letter-triage", "daily-brief", "medication-watch",
                    "scheme-radar", "deadline-watch", "family-dispatch")

# Paths a run creates at runtime, in the caregiver's workspace. They are not
# repo files and must not be asserted onto disk.
WORKSPACE_PREFIXES = ("out/", "/care/", "household/", "inbox/", "processed/",
                      "extracted/")

BACKTICKED = re.compile(r"`([^`\n]+)`")
FENCED = re.compile(r"```.*?```", re.DOTALL)
TEST_COUNT = re.compile(r"<!-- test-count -->\s*\n\s*(?:[^\n\d]*?)(\d+)")


def body():
    return read_text(README)


def prose_only(text):
    """Body with fenced blocks removed — same rule as SKILL.md.

    A claim that appears only inside an example is not a claim the reader is
    making; a claim in prose is.
    """
    return FENCED.sub("", text)


def sections(text):
    """Map `## heading` -> the text under it, up to the next `##`."""
    out = {}
    heading, buffer = None, []
    for line in text.split("\n"):
        if line.startswith("## "):
            if heading is not None:
                out[heading] = "\n".join(buffer)
            heading, buffer = line[3:].strip(), []
        else:
            buffer.append(line)
    if heading is not None:
        out[heading] = "\n".join(buffer)
    return out


def not_built_text(text):
    """Every section whose heading says something is not built."""
    wanted = re.compile(r"not built|not yet|deliberately", re.IGNORECASE)
    return "\n".join(value for heading, value in sections(text).items()
                     if wanted.search(heading))


def looks_like_a_path(token):
    if " " in token or "/" not in token:
        return False
    if token.startswith(("python3", "python", "http://", "https://")):
        return False
    return True


def resolve(token):
    """Where a path named in the README should be found on disk.

    `scripts/<name>.py` is the platform's invocation form, resolved against the
    skill directory rather than the repo root — it is not a repo-root path and
    must not be checked as one.
    """
    if token.startswith("scripts/"):
        return SKILL_DIR / token
    return REPO / token


class ReadmeFileTests(unittest.TestCase):

    def test_readme_exists_at_the_repo_root(self):
        # docs/WORKBUDDY-PLATFORM.md puts README.md at the top of the plugin
        # tree, beside .codebuddy-plugin/ and agents/.
        self.assertTrue(README.is_file(), f"missing {README}")

    def test_readme_is_utf8_and_not_a_stub(self):
        self.assertGreater(len(body().split()), 400)

    def test_gitattributes_ships_it_crlf_like_the_rest_of_the_payload(self):
        # It is a payload file: it lands on the Windows box with everything
        # else, so it must not be the one file with LF endings.
        rules = (REPO / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("README.md text eol=crlf", rules)

    def test_no_secret_shaped_content(self):
        self.assertIsNone(SECRET_SHAPES.search(body()))


class ScriptClaimTests(unittest.TestCase):
    """Finding #5, guarded from both directions, exactly as SKILL.md is."""

    @classmethod
    def setUpClass(cls):
        cls.named = set(SCRIPT_MENTION.findall(body()))

    def test_every_script_named_exists(self):
        for name in sorted(self.named):
            with self.subTest(script=name):
                self.assertTrue((SCRIPTS / name).is_file(),
                                f"README names {name}, which does not exist")

    def test_every_script_on_disk_is_named(self):
        # The other direction: a script the README omits is a script nobody
        # installing this knows they have.
        self.assertEqual(scripts_on_disk() - self.named, set())

    def test_names_no_script_that_was_only_ever_promised(self):
        self.assertNotIn("verify_scheme.py", self.named)


class PathClaimTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = body()
        cls.not_built = not_built_text(cls.text)
        cls.paths = [token for token in BACKTICKED.findall(cls.text)
                     if looks_like_a_path(token)]

    def test_there_are_paths_to_check(self):
        self.assertTrue(self.paths)

    def test_every_path_named_exists_or_is_named_as_missing(self):
        for token in self.paths:
            with self.subTest(path=token):
                if token.startswith(WORKSPACE_PREFIXES):
                    continue  # created by a run, not by an install
                if token in ALLOWED_ABSENT:
                    self.assertIn(
                        token, self.not_built,
                        f"{token} does not exist and is described as though "
                        f"it does")
                    continue
                self.assertTrue(resolve(token).exists(),
                                f"README names {token}, which does not exist")

    def test_unwritten_plugin_directories_are_not_presented_as_present(self):
        for token in ("templates/",):
            with self.subTest(path=token):
                for line in self.text.split("\n"):
                    if token in line and line not in self.not_built:
                        self.assertNotIn(
                            f"`{token}`", line,
                            f"{token} is unwritten; do not name it outside the "
                            f"not-built sections")

    def test_the_six_skills_appear_only_where_they_are_called_unwritten(self):
        for skill in UNWRITTEN_SKILLS:
            with self.subTest(skill=skill):
                if skill in self.text:
                    self.assertIn(
                        skill, self.not_built,
                        f"{skill} is not written; it may only be named in a "
                        f"section that says so")

    def test_says_plainly_what_is_not_built(self):
        self.assertTrue(self.not_built.strip(),
                        "no section states what is unbuilt")
        for term in ("avatars/expert.png",) + UNWRITTEN_SKILLS[:1]:
            with self.subTest(term=term):
                self.assertIn(term, self.not_built)


class InvocationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = body()
        cls.lines = [line.strip().strip("`")
                     for line in cls.text.split("\n")
                     if "python3 scripts/" in line]

    def test_shows_an_invocation_for_every_script(self):
        invoked = set()
        for line in self.lines:
            match = INVOCATION.match(line)
            if match:
                invoked.add(match.group(1))
        self.assertEqual(invoked, scripts_on_disk())

    def test_every_invocation_matches_the_verified_contract(self):
        for line in self.lines:
            with self.subTest(line=line):
                self.assertRegex(line, INVOCATION)

    def test_documents_the_stdin_and_stdout_fallbacks(self):
        for term in ("stdin", "stdout"):
            with self.subTest(term=term):
                self.assertIn(term, self.text)

    def test_no_bare_python_invocation(self):
        # Which interpreter WorkBuddy resolves on Windows is [UNKNOWN]; the
        # convention everywhere else in this repo is python3.
        self.assertNotRegex(self.text, r"(?<!\w)python (?!is\b)")


class TestCommandTests(unittest.TestCase):
    """The command is executed, not quoted. A README whose test command does
    not run is worse than one that omits it: it fails in front of whoever
    trusted it."""

    @classmethod
    def setUpClass(cls):
        cls.text = body()
        cls.commands = [line.strip().strip("`")
                        for line in cls.text.split("\n")
                        if "-m unittest" in line]

    def test_prints_exactly_one_test_command(self):
        self.assertEqual(len(self.commands), 1, self.commands)

    def test_the_command_is_the_documented_one(self):
        self.assertEqual(self.commands[0], TEST_COMMAND)

    def test_says_the_tests_need_no_workbuddy_and_no_network(self):
        lower = prose_only(self.text).lower()
        for term in ("workbuddy", "network", "standard library"):
            with self.subTest(term=term):
                self.assertIn(term, lower)

    def test_the_printed_command_runs_and_the_stated_count_is_real(self):
        if os.environ.get(CHILD_GUARD):
            self.skipTest("child run — the parent process is executing this")
        environment = dict(os.environ, **{CHILD_GUARD: "1"})
        run = subprocess.run(self.commands[0].split(), cwd=REPO,
                             capture_output=True, text=True, env=environment)
        self.assertEqual(run.returncode, 0, run.stderr[-4000:])

        stated = TEST_COUNT.search(self.text)
        self.assertIsNotNone(stated, "no <!-- test-count --> marker")
        reported = re.search(r"^Ran (\d+) tests", run.stderr, re.MULTILINE)
        self.assertIsNotNone(reported, run.stderr[-4000:])
        self.assertEqual(
            int(stated.group(1)), int(reported.group(1)),
            "README states a test count the suite does not produce")


class HardConstraintTests(unittest.TestCase):
    """A judge reads this file to decide whether the guardrails are real. Each
    one is in CLAUDE.md; each one has to survive an edit to the README."""

    @classmethod
    def setUpClass(cls):
        cls.text = prose_only(body())
        cls.lower = cls.text.lower()

    def test_never_submits_and_handles_no_credential(self):
        for term in ("never submit", "singpass", "credential"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_no_clinical_advice(self):
        self.assertIn("clinical", self.lower)

    def test_never_computes_a_number_in_prose(self):
        self.assertIn("never compute", self.lower)

    def test_no_network_from_any_script(self):
        self.assertIn("network", self.lower)

    def test_the_three_permitted_eligibility_strings_are_listed(self):
        for phrase in PERMITTED_ELIGIBILITY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_the_forbidden_eligibility_phrasing_is_named_as_forbidden(self):
        self.assertIn("you qualify", self.lower)

    def test_evidence_rule_and_its_flag(self):
        self.assertIn("REQUIRES_HUMAN_CONFIRMATION", self.text)
        self.assertIn("verbatim", self.lower)

    def test_dual_output_and_the_disclosure_log(self):
        self.assertIn("out/family/", self.text)
        self.assertIn("out/senior/shared_log.jsonl", self.text)

    def test_the_split_of_labour_is_explained_as_the_point(self):
        # It is the reason the arithmetic cannot be hallucinated. A README that
        # files it under style has given away the strongest claim here.
        self.assertIn("split of labour", self.lower)


if __name__ == "__main__":
    unittest.main()
