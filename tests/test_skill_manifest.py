"""Behaviour pinned for skills/care-coordinator-toolkit/SKILL.md.

`SKILL.md` is a prompt, and a prompt cannot be unit-tested for whether it reads
well. What it *can* be tested for is whether it tells the truth about the code
sitting next to it, which is precisely where the previous one failed:

  * it cited `scripts/verify_scheme.py`, which was never written
    (docs/AUDIT-FINDINGS.md #5);
  * its worked example claimed "14 days left on the metformin" while the
    script's own example yielded 7.

Both are documentation drifting away from behaviour, and both are checkable. So
this file asserts, in order of how much each has already cost:

  * every script the body names exists on disk, and every script on disk is
    named by the body — drift is caught from both directions;
  * every invocation line matches the fixed contract in
    docs/WORKBUDDY-PLATFORM.md, character for character;
  * the worked example is **executed**, and its quoted output must be what the
    script actually prints. A worked example that can go stale silently is the
    exact defect this replaces.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills" / "care-coordinator-toolkit"
SKILL = SKILL_DIR / "SKILL.md"
SCRIPTS = SKILL_DIR / "scripts"
TOOLS = REPO / "tools"
AGENT = REPO / "agents" / "care-navigator.md"
MANIFEST = REPO / ".codebuddy-plugin" / "plugin.json"

# `unittest discover` puts tests/ on the path; `python3 -m unittest
# tests.test_skill_manifest` does not. Work under either runner.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import (  # noqa: E402
    SECRET_SHAPES, parse_frontmatter, read_text, split_frontmatter)

# docs/WORKBUDDY-PLATFORM.md, "Script invocation contract [VERIFIED]".
#
# An argument is either an angle-bracket placeholder or a concrete absolute
# path. Relative argument paths are rejected: the working directory at
# invocation time is [UNKNOWN], so a relative path is a latent failure, and a
# file that shows one while telling the model to use absolute paths is worse
# than one that says nothing.
ARGUMENT = r"(?:<[^<>]+>|/[^\s<>]+)"
# `--output` is optional, and the two forms are spelled differently: the
# placeholder form carries the square brackets that mark it optional, the
# concrete form does not. Accepting a mismatched bracket would defeat the point
# of checking the contract character for character.
INVOCATION = re.compile(
    rf"^python3 scripts/(\w+\.py) --input {ARGUMENT}"
    rf"(?: \[--output <[^<>]+>\]| --output /[^\s<>]+)?$")
ABSOLUTE_ARGUMENT = re.compile(r"--input /[^\s<>]+")

SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)

SCRIPT_MENTION = re.compile(r"\b(\w+\.py)\b")

EXAMPLE_INPUT = re.compile(
    r"<!-- worked-example:\s*(\S+?)\s*-->\s*```json\n(.*?)\n```",
    re.DOTALL)
EXAMPLE_OUTPUT = re.compile(
    r"<!-- worked-example-output:\s*(\S+?)\s*-->\s*```text\n(.*?)\n```",
    re.DOTALL)


FENCED = re.compile(r"```.*?```", re.DOTALL)


def prose_only(body):
    """Body with fenced code blocks removed.

    A key that appears only inside an example payload is not documentation —
    the model reads the prose to decide what to send. Without this, a worked
    example silently satisfies every "is it documented" assertion below.
    """
    return FENCED.sub("", body)


def scripts_on_disk():
    return {p.name for p in SCRIPTS.glob("*.py") if not p.name.startswith("_")}


class SkillFileTests(unittest.TestCase):

    def test_skill_md_exists_not_skill_yml(self):
        # The published English docs say `skill.yml`. They are wrong.
        self.assertTrue(SKILL.exists(), f"missing {SKILL}")
        self.assertFalse((SKILL_DIR / "skill.yml").exists())
        self.assertFalse((SKILL_DIR / "skill.yaml").exists())

    def test_lives_in_the_skill_directory_the_manifest_declares(self):
        declared = json.loads(MANIFEST.read_text(encoding="utf-8"))["skills"]
        self.assertIn(f"./skills/{SKILL_DIR.name}", declared)


class SkillFrontmatterTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fm_text, cls.body = split_frontmatter(read_text(SKILL))
        cls.fm = parse_frontmatter(cls.fm_text)

    def test_frontmatter_is_minimal(self):
        # docs/WORKBUDDY-PLATFORM.md: "frontmatter is minimal".
        self.assertEqual(set(self.fm), {"name", "description"})

    def test_name_matches_the_directory(self):
        self.assertEqual(self.fm["name"], SKILL_DIR.name)

    def test_name_matches_the_agent_skills_wiring(self):
        agent_fm = parse_frontmatter(split_frontmatter(read_text(AGENT))[0])
        self.assertIn(self.fm["name"], agent_fm["skills"])

    def test_description_says_what_it_provides_and_when_to_use_it(self):
        description = self.fm["description"]
        self.assertTrue(description.strip())
        self.assertIn("when", description.lower())

    def test_description_is_third_person(self):
        # The description is injected into a system prompt to decide whether
        # this skill is selected at all. Second person there addresses nobody
        # consistently and degrades selection.
        match = SECOND_PERSON.search(self.fm["description"])
        self.assertIsNone(
            match, f"description is second person at {match.group(0)!r}"
            if match else "")

    def test_description_is_within_the_length_limit(self):
        self.assertLessEqual(len(self.fm["description"]), 1024)

    def test_frontmatter_names_no_scripts(self):
        # Script names belong in the body, where the on-disk check reaches them.
        self.assertEqual(SCRIPT_MENTION.findall(self.fm_text), [])


class ScriptCoverageTests(unittest.TestCase):
    """Finding #5, guarded from both directions."""

    @classmethod
    def setUpClass(cls):
        cls.body = split_frontmatter(read_text(SKILL))[1]
        cls.named = set(SCRIPT_MENTION.findall(cls.body))

    def test_every_script_named_in_the_body_exists(self):
        # scripts/ or tools/. SKILL.md has to be able to name the offline
        # fetcher in order to say that no skill invokes it.
        for name in sorted(self.named):
            with self.subTest(script=name):
                self.assertTrue(
                    (SCRIPTS / name).is_file() or (TOOLS / name).is_file(),
                    f"SKILL.md names {name}, which exists in neither "
                    f"scripts/ nor tools/")

    def test_every_script_on_disk_is_documented(self):
        # The other direction: a script that lands undocumented is a script the
        # model will never invoke.
        self.assertEqual(scripts_on_disk() - self.named, set())

    def test_names_no_script_that_was_only_ever_promised(self):
        self.assertNotIn("verify_scheme.py", self.named)

    def test_agent_body_and_skill_body_name_the_same_scripts(self):
        agent_body = split_frontmatter(read_text(AGENT))[1]
        self.assertEqual(set(SCRIPT_MENTION.findall(agent_body)), self.named)


class InvocationContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.body = split_frontmatter(read_text(SKILL))[1]
        cls.lines = [line.strip().strip("`")
                     for line in cls.body.split("\n")
                     if "python3" in line]

    def test_there_is_an_invocation_line_for_every_script(self):
        invoked = set()
        for line in self.lines:
            match = INVOCATION.match(line)
            if match:
                invoked.add(match.group(1))
        self.assertEqual(invoked, scripts_on_disk())

    def test_every_python3_line_matches_the_verified_contract(self):
        for line in self.lines:
            with self.subTest(line=line):
                self.assertRegex(line, INVOCATION)

    def test_no_bare_python_invocation(self):
        # Whether WorkBuddy resolves `python` or `python3` on Windows is
        # [UNKNOWN]; the established convention across every script is python3
        # and this file must not quietly introduce a second form.
        self.assertNotRegex(self.body, r"(?<!\w)python (?!is\b)")

    def test_documents_the_stdin_and_stdout_fallbacks(self):
        self.assertIn("stdin", self.body)
        self.assertIn("stdout", self.body)

    def test_documents_the_run_envelope(self):
        self.assertIn("tool_run_id", self.body)
        self.assertIn("issued_at", self.body)
        self.assertIn("audit_hash", self.body)

    def test_says_paths_must_be_absolute(self):
        # The working directory at invocation time is [UNKNOWN].
        self.assertIn("absolute", self.body.lower())

    def test_shows_at_least_one_concrete_absolute_invocation(self):
        # Saying "use absolute paths" beside an example that isn't one is a
        # contradiction the model resolves by copying the example.
        self.assertTrue(
            any(ABSOLUTE_ARGUMENT.search(line) for line in self.lines),
            "every invocation shown is a placeholder; show a real one")

    def test_no_invocation_passes_a_relative_argument(self):
        for line in self.lines:
            with self.subTest(line=line):
                argument = line.split("--input ", 1)[-1].split()[0]
                self.assertTrue(
                    argument.startswith(("<", "/")),
                    f"relative --input path: {argument}")


class RequiredInputTests(unittest.TestCase):
    """A required key that reads as optional is how a run exits 0 having done
    nothing. Each of these is required with no default."""

    @classmethod
    def setUpClass(cls):
        cls.prose = prose_only(split_frontmatter(read_text(SKILL))[1])

    def test_required_keys_are_documented_in_prose(self):
        for key in ("medications", "claims", "members", "expenses",
                    "count_basis", "default_lead_time_days", "split_rule"):
            with self.subTest(key=key):
                self.assertIn(key, self.prose)

    def test_absent_versus_unevidenced_is_explained(self):
        # SGD 4,320.00 instead of SGD 1,220.00 came from conflating these.
        self.assertIn("REQUIRES_HUMAN_CONFIRMATION", self.prose)
        self.assertIn("verbatim", self.prose.lower())


class RunWorkflowTests(unittest.TestCase):
    """A run is not finished when the script exits.

    Script result -> family artifact -> senior artifact -> disclosure log is a
    four-step sequence, and stopping after step two ships the family half alone,
    which is the specific failure this product is built against. Prose spread
    across two sections is how a step gets skipped; a checklist is not.
    """

    @classmethod
    def setUpClass(cls):
        cls.body = split_frontmatter(read_text(SKILL))[1]
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
        # A pre-ticked checklist is decoration. It must arrive empty so it can
        # be copied and worked through.
        self.assertNotIn("- [x]", self.body.lower())


class TerminologyTests(unittest.TestCase):
    """One term per concept. Mixed vocabulary is harder to follow and makes a
    refusal read as a preference."""

    @classmethod
    def setUpClass(cls):
        cls.lower = split_frontmatter(read_text(SKILL))[1].lower()

    def test_refusals_use_one_phrasing(self):
        self.assertFalse("will not do" in self.lower,
                         "mixes 'will not do' with 'does not'")

    def test_scripts_are_invoked_not_called_or_run(self):
        for synonym in ("call the script", "execute the script"):
            with self.subTest(synonym=synonym):
                self.assertFalse(synonym in self.lower,
                                 f"use 'invoke', not {synonym!r}")


class DependencyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.lower = prose_only(split_frontmatter(read_text(SKILL))[1]).lower()

    def test_states_there_is_nothing_to_install(self):
        # The install-time security scanner flags dependency steps, and the
        # interpreter on the target machine is [UNKNOWN]. Say plainly that
        # neither is a concern here.
        for term in ("standard library", "install"):
            with self.subTest(term=term):
                self.assertTrue(term in self.lower,
                                f"body never mentions {term!r}")


class RefusalTests(unittest.TestCase):
    """The skill body is read at invocation time. It carries the constraints
    that bear on invoking a script; it must not soften any of them."""

    @classmethod
    def setUpClass(cls):
        cls.body = prose_only(split_frontmatter(read_text(SKILL))[1])
        cls.lower = cls.body.lower()

    def test_has_an_explicit_does_not_section(self):
        self.assertIn("does not", self.lower)

    def test_never_computes_a_number_in_prose(self):
        self.assertIn("never compute", self.lower)

    def test_no_network(self):
        self.assertIn("network", self.lower)

    def test_never_submits_and_handles_no_credential(self):
        for term in ("never submit", "credential", "singpass"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_no_clinical_judgement(self):
        self.assertIn("clinical", self.lower)

    def test_dual_output_and_the_disclosure_log(self):
        self.assertIn("out/family/", self.body)
        self.assertIn("out/senior/shared_log.jsonl", self.body)

    def test_no_secret_shaped_content(self):
        # WorkBuddy security-scans on install, and a file of paths and command
        # lines is what that scanner reads most closely.
        self.assertIsNone(SECRET_SHAPES.search(self.body))


class WorkedExampleTests(unittest.TestCase):
    """The example is executed, not trusted.

    The previous SKILL.md said "14 days left on the metformin" while the script
    yielded 7, and nothing caught it because nothing ran it.
    """

    @classmethod
    def setUpClass(cls):
        cls.body = split_frontmatter(read_text(SKILL))[1]
        cls.inputs = dict((m[0], m[1]) for m in EXAMPLE_INPUT.findall(cls.body))
        cls.outputs = dict((m[0], m[1])
                           for m in EXAMPLE_OUTPUT.findall(cls.body))

    def test_there_is_at_least_one_worked_example(self):
        self.assertTrue(self.inputs)

    def test_every_example_input_has_a_paired_output(self):
        self.assertEqual(set(self.inputs), set(self.outputs))

    def test_every_example_names_a_real_script(self):
        for name in self.inputs:
            with self.subTest(script=name):
                self.assertTrue((SCRIPTS / name).is_file())

    def test_every_example_input_is_valid_json(self):
        for name, payload in self.inputs.items():
            with self.subTest(script=name):
                json.loads(payload)

    def test_examples_reproduce_the_documented_output(self):
        for name, payload in self.inputs.items():
            with self.subTest(script=name):
                run = subprocess.run(
                    [sys.executable, str(SCRIPTS / name)],
                    input=payload, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)
                expected = self.outputs[name].strip()
                # An empty expected block would make assertIn below vacuous —
                # a worked example that passes by saying nothing.
                self.assertGreater(len(expected), 40)
                self.assertIn(
                    expected, json.dumps(result, ensure_ascii=False),
                    f"SKILL.md quotes output {name} does not produce")

    def test_examples_keep_stdout_and_stderr_separate(self):
        for name, payload in self.inputs.items():
            with self.subTest(script=name):
                run = subprocess.run(
                    [sys.executable, str(SCRIPTS / name)],
                    input=payload, capture_output=True, text=True)
                json.loads(run.stdout)  # stdout is JSON and nothing else


if __name__ == "__main__":
    unittest.main()
