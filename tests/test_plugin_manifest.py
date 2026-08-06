"""Behaviour pinned for .codebuddy-plugin/plugin.json and agents/care-navigator.md.

This cycle is prose, so these tests do the job the prose cannot do for itself:

  * the `plugin.json` schema is [VERIFIED] in docs/WORKBUDDY-PLATFORM.md, so it
    is pinned exactly — display fields are {en, zh} objects, `tags` and
    `quickPrompts` are arrays of {en, zh} objects and never arrays of strings;
  * every path the manifest names resolves to something that exists on disk.
    That is audit finding #5 — a manifest citing a file that isn't there —
    turned into a guard that runs on every commit;
  * `agentName` and the agent file's frontmatter `name` agree, so the wiring
    cannot drift;
  * the agent body carries each CLAUDE.md hard constraint. The scripts enforce
    their own share; the body is the only thing that carries the rest into
    runtime, so a body that quietly loses one is a regression worth failing on.

No PyYAML — stdlib only, like everything else here — so the frontmatter parser
below is deliberately minimal and refuses anything it does not understand
rather than guessing.
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / ".codebuddy-plugin" / "plugin.json"
AGENT = REPO / "agents" / "care-navigator.md"

# docs/WORKBUDDY-PLATFORM.md: "categoryId is one of twelve fixed categories".
# It names exactly one of them. The other eleven are [UNKNOWN] and are not
# guessed at here; this pins the only value ever read off a working plugin.
VERIFIED_CATEGORY_IDS = {"12-IndustryConsultant"}

BILINGUAL_FIELDS = ("displayName", "profession", "displayDescription",
                    "defaultInitPrompt")
BILINGUAL_ARRAYS = ("tags", "quickPrompts")

REQUIRED_KEYS = (
    "name", "version", "description", "author", "agents", "skills",
    "expertType", "agentName", "displayName", "profession",
    "displayDescription", "avatar", "categoryId", "defaultInitPrompt",
    "plugin", "tags", "quickPrompts",
)

# The three strings CLAUDE.md permits for eligibility, and nothing else.
PERMITTED_ELIGIBILITY = ("likely eligible", "worth checking",
                         "insufficient information")

# Shapes the WorkBuddy install-time security scan looks for. None of them have
# any business in a plugin payload file.
SECRET_SHAPES = re.compile(
    r"(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+[A-Za-z0-9]|"
    r"password\s*[:=]|BEGIN\s+(RSA|OPENSSH|PRIVATE))", re.IGNORECASE)


def read_text(path):
    """Read a payload file, normalising CRLF away.

    Payload files are checked out CRLF by .gitattributes on every platform, so
    tests must not care which side of that conversion they are running on.
    """
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def split_frontmatter(text):
    """Return (frontmatter_text, body) for a file that opens with a --- block."""
    if not text.startswith("---\n"):
        raise AssertionError("agent file must open with a YAML frontmatter "
                             "fence on its own first line")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise AssertionError("agent frontmatter is never closed")
    return text[4:end + 1], text[end + 5:]


def parse_frontmatter(text):
    """A deliberately small YAML subset: scalars, one level of nesting, and
    inline `[a, b]` lists. Anything else raises rather than being guessed at."""
    out = {}
    parent = None
    for lineno, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if ":" not in raw:
            raise AssertionError(f"frontmatter line {lineno} is not a mapping: "
                                 f"{raw!r}")
        key, _, value = raw.strip().partition(":")
        key, value = key.strip(), value.strip()
        if indent == 0:
            if value == "":
                out[key] = {}
                parent = key
            else:
                out[key] = _scalar(value)
                parent = None
        elif indent == 2 and parent is not None:
            out[parent][key] = _scalar(value)
        else:
            raise AssertionError(f"frontmatter line {lineno} has unsupported "
                                 f"indentation: {raw!r}")
    return out


def _scalar(value):
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",")]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def has_han(text):
    """True if the string contains at least one CJK ideograph."""
    return any("一" <= ch <= "鿿" for ch in text)


class ManifestFileTests(unittest.TestCase):
    """The manifest exists, in the directory the platform actually reads."""

    def test_manifest_directory_is_codebuddy_not_workbuddy(self):
        # WorkBuddy shares a codebase lineage with CodeBuddy; the dotted
        # directory kept the old name. Getting this wrong installs nothing.
        self.assertTrue(MANIFEST.exists(), f"missing {MANIFEST}")
        self.assertFalse((REPO / ".workbuddy-plugin").exists())

    def test_manifest_is_utf8_json(self):
        json.loads(MANIFEST.read_text(encoding="utf-8"))


class ManifestSchemaTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.m = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_required_keys_present(self):
        for key in REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.m)

    def test_no_unexpected_top_level_keys(self):
        # The schema is [VERIFIED] off a working plugin. A key nobody has seen
        # the loader accept is a guess, and guesses are what this repo forbids.
        self.assertEqual(set(self.m) - set(REQUIRED_KEYS), set())

    def test_display_fields_are_en_zh_objects(self):
        for field in BILINGUAL_FIELDS:
            with self.subTest(field=field):
                value = self.m[field]
                self.assertIsInstance(value, dict)
                self.assertEqual(set(value), {"en", "zh"})
                self.assertTrue(value["en"].strip())
                self.assertTrue(value["zh"].strip())

    def test_display_fields_are_not_bare_strings(self):
        for field in BILINGUAL_FIELDS:
            with self.subTest(field=field):
                self.assertNotIsInstance(self.m[field], str)

    def test_tags_and_quickprompts_are_object_arrays_not_string_arrays(self):
        for field in BILINGUAL_ARRAYS:
            with self.subTest(field=field):
                value = self.m[field]
                self.assertIsInstance(value, list)
                self.assertTrue(value, f"{field} must not be empty")
                for entry in value:
                    self.assertIsInstance(
                        entry, dict,
                        f"{field} entries are {{en, zh}} objects, not strings")
                    self.assertEqual(set(entry), {"en", "zh"})
                    self.assertTrue(entry["en"].strip())
                    self.assertTrue(entry["zh"].strip())

    def test_zh_strings_are_actually_chinese(self):
        # An untranslated zh field is worse than a missing one: it renders on
        # the marketplace card as though it were a translation.
        for field in BILINGUAL_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(has_han(self.m[field]["zh"]))
        for field in BILINGUAL_ARRAYS:
            for i, entry in enumerate(self.m[field]):
                with self.subTest(field=field, index=i):
                    self.assertTrue(has_han(entry["zh"]))

    def test_category_id_is_a_verified_value(self):
        self.assertIn(self.m["categoryId"], VERIFIED_CATEGORY_IDS)

    def test_expert_type_is_agent(self):
        self.assertEqual(self.m["expertType"], "agent")

    def test_version_is_semver(self):
        self.assertRegex(self.m["version"], r"^\d+\.\d+\.\d+$")

    def test_author_has_name_and_email(self):
        self.assertEqual(set(self.m["author"]), {"name", "email"})

    def test_plugin_and_name_agree(self):
        self.assertEqual(self.m["plugin"], self.m["name"])

    def test_no_secret_shaped_content(self):
        # WorkBuddy security-scans plugins on install.
        self.assertIsNone(SECRET_SHAPES.search(read_text(MANIFEST)))


class ManifestPathTests(unittest.TestCase):
    """Audit finding #5, turned into a guard: nothing may name a missing file."""

    @classmethod
    def setUpClass(cls):
        cls.m = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_agent_paths_resolve_to_files(self):
        for rel in self.m["agents"]:
            with self.subTest(path=rel):
                self.assertTrue(rel.startswith("./"))
                self.assertTrue((REPO / rel).is_file(), f"missing {rel}")

    def test_skill_paths_resolve_to_directories(self):
        for rel in self.m["skills"]:
            with self.subTest(path=rel):
                self.assertTrue(rel.startswith("./"))
                self.assertTrue((REPO / rel).is_dir(), f"missing {rel}")

    def test_declared_skills_match_the_skills_on_disk(self):
        declared = {Path(rel).name for rel in self.m["skills"]}
        on_disk = {p.name for p in (REPO / "skills").iterdir() if p.is_dir()}
        self.assertEqual(declared, on_disk)

    def test_avatar_path_is_declared_and_is_a_png(self):
        # The image itself is a human to-do: 1024x1024 PNG, binary content,
        # out of scope for a cycle. The path is pinned now so the file lands
        # in the one place the manifest points at.
        self.assertEqual(self.m["avatar"], "avatars/expert.png")

    def test_avatar_file_is_a_real_png_once_it_exists(self):
        avatar = REPO / self.m["avatar"]
        if not avatar.exists():
            self.skipTest("avatars/expert.png not yet supplied — human to-do")
        self.assertEqual(avatar.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class AgentFrontmatterTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = read_text(AGENT)
        cls.fm_text, cls.body = split_frontmatter(cls.text)
        cls.fm = parse_frontmatter(cls.fm_text)
        cls.m = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_frontmatter_keys(self):
        self.assertEqual(
            set(self.fm),
            {"name", "description", "displayName", "profession", "maxTurns",
             "skills"})

    def test_agent_name_matches_manifest_agentname(self):
        self.assertEqual(self.fm["name"], self.m["agentName"])

    def test_agent_name_matches_its_own_filename(self):
        self.assertEqual(self.fm["name"], AGENT.stem)

    def test_display_fields_match_the_manifest(self):
        for field in ("displayName", "profession"):
            with self.subTest(field=field):
                self.assertEqual(self.fm[field], self.m[field])

    def test_display_fields_are_en_zh_maps(self):
        for field in ("displayName", "profession"):
            with self.subTest(field=field):
                self.assertEqual(set(self.fm[field]), {"en", "zh"})

    def test_maxturns_is_a_positive_int(self):
        self.assertIsInstance(self.fm["maxTurns"], int)
        self.assertGreater(self.fm["maxTurns"], 0)

    def test_skills_wires_every_skill_in_the_plugin(self):
        # Was pinned to the toolkit alone, when it was the only skill. The
        # assertion that matters is not "which skill" but that the agent and
        # the manifest agree: a skill shipped in the plugin and left out of the
        # agent's `skills:` is installed, scanned, and never reachable.
        declared = [Path(rel).name for rel in self.m["skills"]]
        self.assertEqual(sorted(self.fm["skills"]), sorted(declared))
        self.assertIn("care-coordinator-toolkit", self.fm["skills"])

    def test_every_named_skill_exists_on_disk(self):
        for name in self.fm["skills"]:
            with self.subTest(skill=name):
                self.assertTrue((REPO / "skills" / name).is_dir())

    def test_description_is_an_activation_condition_not_a_summary(self):
        # It decides when the expert is selected, so it must describe the
        # user's situation, not the product's feature list.
        description = self.fm["description"]
        self.assertTrue(description.strip())
        self.assertTrue(
            any(cue in description.lower()
                for cue in ("when ", "someone ", "a user ", "a caregiver ")),
            f"description reads as a summary, not a trigger: {description!r}")


class AgentBodyTests(unittest.TestCase):
    """The body is the only thing carrying the CLAUDE.md hard constraints into
    runtime. Each one below is pinned so a later edit cannot quietly drop it."""

    @classmethod
    def setUpClass(cls):
        cls.body = split_frontmatter(read_text(AGENT))[1]
        cls.lower = cls.body.lower()

    def test_body_is_not_empty(self):
        self.assertGreater(len(self.body.split()), 200)

    def test_never_submit(self):
        self.assertIn("never submit", self.lower)

    def test_no_singpass_no_login_no_credential(self):
        for term in ("singpass", "log in", "credential"):
            with self.subTest(term=term):
                self.assertIn(term, self.lower)

    def test_no_clinical_advice(self):
        self.assertIn("clinical", self.lower)
        self.assertIn("lasting power of attorney", self.lower)

    def test_the_three_permitted_eligibility_strings_are_listed(self):
        for phrase in PERMITTED_ELIGIBILITY:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)

    def test_the_forbidden_eligibility_phrasing_is_named_as_forbidden(self):
        self.assertIn("you qualify", self.lower)

    def test_dated_criteria_provenance_string(self):
        self.assertIn("criteria as of YYYY-MM-DD", self.body)

    def test_evidence_rule_and_its_flag(self):
        self.assertIn("REQUIRES_HUMAN_CONFIRMATION", self.body)
        self.assertIn("verbatim", self.lower)

    def test_no_self_reported_confidence(self):
        self.assertIn("confidence", self.lower)

    def test_dual_output(self):
        self.assertIn("out/family/", self.body)
        self.assertIn("out/senior/", self.body)

    def test_disclosure_log_path(self):
        self.assertIn("out/senior/shared_log.jsonl", self.body)

    def test_nothing_in_the_workspace_may_be_deleted(self):
        # Finding #26, measured in the cycle P case G run. "No irreversible
        # action without confirmation" listed deleting among its examples and
        # the agent still ran `rm` on a filed record, because the thing it was
        # deleting did not read as an action *on her* — it read as clearing an
        # obstacle. The named directories close that reading.
        for name in ("extracted/", "processed/", "out/"):
            with self.subTest(directory=name):
                self.assertIn(name, self.body)
        self.assertIn("delete", self.lower)
        for term in ("refusing you is never", "refusal is never",
                     "never an invitation"):
            if term in self.lower:
                break
        else:
            self.fail(
                "the body forbids deletion but never says a script's refusal "
                "is not an invitation to remove what it objected to. That is "
                "the reasoning the run actually followed.")

    def test_addresses_the_senior_directly(self):
        self.assertIn("third person", self.lower)

    def test_language_comes_from_the_household_profile(self):
        self.assertIn("HouseholdProfile", self.body)

    def test_never_computes_a_number_in_prose(self):
        self.assertIn("never compute", self.lower)

    def test_a_number_added_beside_a_scripts_is_still_forbidden(self):
        # Finding #20, measured in the cycle M case G run. The agent had the
        # script's appeal deadline, wrote it correctly, and one line above it
        # wrote "gather ... by 25 August 2026" — a two-day buffer no script
        # produced. "Never compute a number in prose" was read as "never
        # compute the number the script computes", which leaves buffers, lead
        # times and "about a week" all feeling permitted. The normative copy
        # has to close that reading, because every skill inherits it.
        for term in ("beside", "in addition to", "as well as one"):
            if term in self.lower:
                break
        else:
            self.fail(
                "the body never forbids a number added *beside* a script's. "
                "A rule about replacing a figure is not a rule about adding "
                "one.")
        for term in ("buffer", "lead time", "working target"):
            if term in self.lower:
                break
        else:
            self.fail("no named example of an invented date that is not a "
                      "recomputation of a script's")

    def test_a_computed_figure_is_never_attributed_to_the_document(self):
        # Finding #21, same run. Her copy listed the outstanding balance and
        # said "they are what the letter from Great Eastern says". The letter
        # prints the billed and paid figures and never the balance — that is
        # the script's subtraction, and the whole reason the script exists.
        # False in the direction of extra confidence, and unverifiable by the
        # one person it is addressed to.
        for term in ("worked out", "derived from", "computed from"):
            if term in self.lower:
                break
        else:
            self.fail(
                "the body offers no way to say a figure was worked out from "
                "the page rather than printed on it, so the only provenance "
                "available to an artifact is the false one")

    def test_no_irreversible_action_without_confirmation(self):
        self.assertIn("irreversible", self.lower)

    def test_escalate_on_uncertainty(self):
        self.assertIn("escalate", self.lower)

    def test_no_secret_shaped_content(self):
        self.assertIsNone(SECRET_SHAPES.search(self.body))

    def test_body_names_only_scripts_that_exist(self):
        # Finding #5 from the other direction: the old SKILL.md cited
        # scripts/verify_scheme.py, which was never written.
        # scripts/ or tools/: the body has to be able to name the offline
        # fetcher in order to say that it never invokes it.
        scripts = REPO / "skills" / "care-coordinator-toolkit" / "scripts"
        tools = REPO / "tools"
        for named in re.findall(r"[\w/]*?(\w+\.py)", self.body):
            with self.subTest(script=named):
                self.assertTrue(
                    (scripts / named).is_file() or (tools / named).is_file(),
                    f"body names {named}, which exists in neither scripts/ "
                    f"nor tools/")


if __name__ == "__main__":
    unittest.main()
