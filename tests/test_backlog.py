"""Behaviour pinned for the backlog in LOOP-PROMPT.md.

The backlog is the one document that decides what happens next, and it is the
one document nothing checked. It has already been wrong twice in ways that cost
a cycle: it described `plugin.json` and `SKILL.md` as sitting safely on the
WorkBuddy box when no copy existed anywhere, and it carried a running test count
that went stale the moment a cycle added a test.

Both are the same failure as audit finding #5 — a document asserting something
about the code that is not true — so this file guards it the same way
`tests/test_skill_manifest.py` guards SKILL.md: **from both directions.**

  * a script named in a row marked Done must exist on disk;
  * a script named in any other row must **not** exist on disk.

The second is the one that earns its keep. A script can land and the backlog
never get updated, and then the next cycle picks up work that is already done —
which is exactly the shape of the ordering mistake that lost a cycle before.

Exactly one row may be Next, because a loop with two heads is a loop that
batches, and batching is what the cycle discipline exists to prevent.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOOP = REPO / "LOOP-PROMPT.md"
SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"
TOOLS = REPO / "tools"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plugin_manifest import read_text  # noqa: E402

# A closed vocabulary, for the same reason `insurer_decision` has one: a status
# nobody defined is a status that gets read as whatever the reader hoped.
STATUSES = {"Done", "Next", "Later", "Dropped"}

# | # | Item | Status |
ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*(\w+)\s*\|\s*$",
                 re.MULTILINE)

SCRIPT_MENTION = re.compile(r"\b(\w+\.py)\b")


def rows():
    """Backlog rows as (id, item, status), header and separator excluded."""
    out = []
    for identifier, item, status in ROW.findall(read_text(LOOP)):
        if status in STATUSES:
            out.append((identifier, item, status))
    return out


def exists(script):
    return (SCRIPTS / script).is_file() or (TOOLS / script).is_file()


class BacklogShapeTests(unittest.TestCase):

    def test_there_is_a_backlog_table(self):
        self.assertTrue(rows(), "no backlog rows with a recognised status")

    def test_every_status_is_from_the_closed_set(self):
        # Catches a row whose status column holds prose, which would otherwise
        # drop out of every check below without failing anything.
        table = re.findall(r"^\|\s*[^|]+\|\s*.+?\s*\|\s*([^|]+?)\s*\|\s*$",
                           read_text(LOOP), re.MULTILINE)
        for status in table:
            # The header row and the markdown separator beneath it, whatever
            # width the dashes happen to be written at.
            if status == "Status" or re.fullmatch(r"[:-]+", status):
                continue
            with self.subTest(status=status):
                self.assertIn(status, STATUSES)

    def test_exactly_one_row_is_next(self):
        nxt = [item for _, item, status in rows() if status == "Next"]
        self.assertEqual(len(nxt), 1,
                         f"a loop needs exactly one head, found {nxt}")

    def test_the_start_here_section_points_at_the_next_row(self):
        # Two places name what happens next: the Status column and the "Start
        # here" heading. They disagreed the first time this table was written,
        # in the same cycle that added the table.
        heading = re.search(r"^## Start here.*?item (\d+)", read_text(LOOP),
                            re.MULTILINE)
        self.assertIsNotNone(heading, "no 'Start here — ... item N' heading")
        nxt = [identifier for identifier, _, status in rows()
               if status == "Next"]
        self.assertEqual(
            [heading.group(1)], nxt,
            "the Start here section and the Next row disagree")

    def test_something_is_still_later(self):
        # A backlog with nothing Later is a backlog that stopped being written
        # down. If the work really is finished, delete this test deliberately.
        self.assertTrue(any(status == "Later" for _, _, status in rows()))


class BacklogTruthTests(unittest.TestCase):
    """Finding #5, applied to the backlog, guarded from both directions."""

    def test_scripts_in_done_rows_exist(self):
        for identifier, item, status in rows():
            if status != "Done":
                continue
            for script in SCRIPT_MENTION.findall(item):
                with self.subTest(row=identifier, script=script):
                    self.assertTrue(
                        exists(script),
                        f"row {identifier} is Done but {script} does not exist")

    def test_scripts_in_unfinished_rows_do_not_exist(self):
        for identifier, item, status in rows():
            if status in ("Done", "Dropped"):
                continue
            for script in SCRIPT_MENTION.findall(item):
                with self.subTest(row=identifier, script=script):
                    self.assertFalse(
                        exists(script),
                        f"{script} exists on disk but row {identifier} still "
                        f"says {status} — the backlog is behind the code")

    def test_every_script_on_disk_appears_in_a_done_row(self):
        # The third direction: a script that is in neither the backlog nor a
        # Done row is work nobody can account for.
        done = set()
        for _, item, status in rows():
            if status == "Done":
                done.update(SCRIPT_MENTION.findall(item))
        on_disk = {p.name for p in SCRIPTS.glob("*.py")
                   if not p.name.startswith("_")}
        self.assertEqual(on_disk - done, set(),
                         "scripts on disk that no Done row accounts for")


if __name__ == "__main__":
    unittest.main()
