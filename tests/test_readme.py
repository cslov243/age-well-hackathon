"""Behaviour pinned for README.md.

The README is the file most likely to drift into describing the intended
product rather than the built one. It is also a plugin payload file, read by
the install-time security scan. Both audiences are harmed by the same defect:
a sentence that is true of the plan and false of the disk.

Audit finding #5 was a `SKILL.md` citing `scripts/verify_scheme.py`, which was
never written. A README is finding #5 with a wider blast radius, so the
assertions here are the same shape as `tests/test_skill_manifest.py`: every
script and every repo path the README names exists on disk, and the handful
that legitimately do not yet exist may only be named in a section that says so.

What this file no longer does is police the README's wording. Constraint prose
is pinned in one place — the agent body, in `tests/test_plugin_manifest.py` —
because the same phrase asserted in four files makes every edit cost four.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
SKILL_DIR = REPO / "skills" / "care-coordinator-toolkit"
SCRIPTS = SKILL_DIR / "scripts"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    SECRET_SHAPES, read_text)
from test_skill_manifest import (  # noqa: E402
    INVOCATION, SCRIPT_MENTION, scripts_on_disk)

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


if __name__ == "__main__":
    unittest.main()
