#!/usr/bin/env python3
"""Turn what a vision model read off a letter into a record on disk.

Usage:
    python3 letter_record.py --input <input.json> --records <extracted/> \
        [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.
--records is required: the directory holding one JSON file per letter. It is
read in both modes and written in only one.

Input:
    {
      "as_of": "2026-08-06",              # optional, defaults to SG today
      "mode": "check",                    # required: check | record
      "source_files": ["/care/inbox/p1.jpg", ...],   # required, in page order

      # required in "record" mode, refused in "check" mode:
      "doc_type": "insurance",
      "fields":   {"issuer": ..., "issue_date": ..., "deadline": ...,
                   "amounts": [...], "required_action": ...},
      "evidence": {"issuer": "...", "deadline": "...", "amounts[0]": "..."}
    }

**Two modes, because the order matters and costs money.** `check` hashes the
pages and says whether this document has been extracted before. It is the call
made *before* the vision model runs. `record` takes the extraction and files
it. Running `record` on a document already in `extracted/` writes nothing and
says so: a second record does not correct the first, it competes with it.

Every key in `fields` is required even when the value is null. A field the
model never considered and a field it considered and found nothing for produce
identical JSON otherwise, and only one of them is an answer.

## The evidence gate, which is the whole point

Every `issuer`, `issue_date`, `deadline` and amount must be quotable. A value
survives only when its snippet exists, is not blank, **and actually contains
the value it is evidence for**. Anything else is nulled, listed in
`missing_evidence`, and the record is flagged REQUIRES_HUMAN_CONFIRMATION.

  * **Absent** — the field is null and there is no snippet. The letter never
    said it. No flag: that is an honest answer and flagging it would teach a
    caregiver to ignore flags.
  * **Present but unquotable** — the model believes it saw a number and cannot
    show where. That is *unknown*, and it is the case that once produced a
    draft claiming SGD 4,320.00 owed against a letter reading SGD 1,220.00.

The containment check is weak on purpose and cannot be strong: there is no
document text here to diff a snippet against, only an image the model already
looked at. It catches a number quoted against text that says a different
number, which is what confabulation on a familiar-looking form looks like. It
does not catch a snippet invented wholesale. Nothing here can.

The model never reports a confidence score. Vision confidence peaks exactly
where it is least deserved, and absence of a quotable snippet is the only
uncertainty signal on offer.

## Identity

Each page is hashed by its bytes; the record's `content_hash` covers all of
them in the order given, so re-scanning the same letter under a new filename is
the same letter and a re-ordered pair of pages is not. Grouping pages into one
record is the model's call, and the contract biases toward splitting: a
duplicate record costs an annoying second notification, a false merge silently
eats a deadline.

Nothing here reads an image, submits anything, or moves a file. It writes one
JSON file into the directory it was given.

No network access. No filesystem access beyond the paths passed in.
"""

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _evidence import (  # noqa: E402
    MONTHS,
    VERBATIM_LIMIT,
    snippet_has_amount,
    snippet_has_date,
    snippet_has_issuer,
)

SG = timezone(timedelta(hours=8), name="+08:00")

FLAG = "REQUIRES_HUMAN_CONFIRMATION"

KNOWN_KEYS = ("as_of", "mode", "source_files", "doc_type", "fields",
              "evidence")

EXTRACTION_KEYS = ("doc_type", "fields", "evidence")

MODES = ("check", "record")

DOC_TYPES = ("chas", "appointment", "hdb", "medication", "bill", "insurance",
             "other")

FIELD_KEYS = ("issuer", "issue_date", "deadline", "amounts",
              "required_action")

# The fields a claim about the world is made in. `required_action` is the
# model's plain-language reading of what to do, not a figure read off a page.
GATED_FIELDS = ("issuer", "issue_date", "deadline")

PROBLEM_REASONS = ("no_snippet", "blank_snippet", "value_not_in_snippet",
                   "nothing_evidenced")

EVIDENCE_RULE = (
    "issuer, issue_date, deadline and every amount survive only with a "
    "snippet that exists, is not blank, and contains the value it is evidence "
    "for. Anything else is nulled and listed in missing_evidence, and the "
    "record is flagged " + FLAG + ". A field the letter never mentioned is "
    "null with no snippet and no flag: absent is an answer, unquotable is not"
)
IDENTITY_RULE = (
    "content_hash covers every page's bytes in the order given, so the same "
    "scan under a new filename is the same letter and a re-ordered pair of "
    "pages is not. The id is derived from that hash and from nothing else"
)
IDEMPOTENCY_RULE = (
    "a content_hash already present in the records directory is a no-op: "
    "nothing is written and the existing record stands. Re-extracting costs "
    "another vision call and produces a second record that competes with the "
    "first rather than correcting it"
)
SPLITTING_RULE = (
    "which pages form one letter is the model's call, and the bias is toward "
    "splitting. A duplicate record costs an annoying second notification; a "
    "false merge silently eats a deadline"
)
HANDOFF_RULE = (
    "nothing here is answered, submitted, paid or filed with anyone. This "
    "writes one JSON file into the directory it was given, and the letter "
    "itself is still a person's to act on"
)

LOG = logging.getLogger("letter_record")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

def _reject_unknown(mapping, known, where):
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        raise InvalidInput(
            f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"A misspelled key takes no effect and says nothing, which looks "
            f"exactly like an answer. Known keys: {', '.join(known)}")


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD). "
            f"Reformat it here rather than downstream — the snippet keeps "
            f"whatever the letter printed")


def _to_amount(value, where):
    if isinstance(value, float):
        raise InvalidInput(
            f"{where}: amount {value!r} is a binary float and cannot represent "
            f"money exactly. Pass it as a string, or read the JSON with "
            f"parse_float=Decimal")
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise InvalidInput(f"{where}: expected an amount as a string")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise InvalidInput(f"{where}: {value!r} is not a number")
    if amount < 0:
        raise InvalidInput(
            f"{where}: {value!r} is negative. A letter's amounts are what it "
            f"asks for; a direction of travel is worked out downstream")
    return amount


def _human_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _count(number, noun, plural=None):
    return f"{number} " + (noun if number == 1 else (plural or noun + "s"))


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

class Gate:
    """Decides, per field, whether the extraction may keep it."""

    def __init__(self, evidence):
        self.evidence = evidence
        self.missing = []
        self.problems = []

    def _fail(self, field, reason, detail):
        self.missing.append(field)
        self.problems.append({"field": field, "reason": reason,
                              "detail": detail})

    def check(self, field, contains):
        """True when the field's snippet supports it. Records why when not."""
        if field not in self.evidence:
            self._fail(field, "no_snippet",
                       f"{field} was extracted with nothing quoted for it. "
                       f"Without a snippet there is no way to tell a reading "
                       f"from a recollection")
            return False
        snippet = self.evidence[field]
        if not isinstance(snippet, str):
            raise InvalidInput(
                f"evidence[{field!r}] must be the text quoted from the letter")
        if not snippet.strip():
            self._fail(field, "blank_snippet",
                       f"{field} was quoted with an empty snippet, which is "
                       f"the same as none at all")
            return False
        if not contains(snippet):
            self._fail(field, "value_not_in_snippet",
                       f"{field} does not appear in the text quoted for it: "
                       f"{snippet.strip()!r}. The value and its evidence "
                       f"disagree, and the evidence is the one that was on "
                       f"the page")
            return False
        return True

    def nothing_evidenced(self):
        self.problems.append({
            "field": "record", "reason": "nothing_evidenced",
            "detail": "no issuer, date or amount could be quoted from this "
                      "document. That is what an unreadable scan looks like, "
                      "and it must not pass as a letter with nothing in it"})


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def _hash_pages(raw, where="source_files"):
    if not isinstance(raw, list):
        raise InvalidInput(f"{where} must be a list of paths, in page order")
    if not raw:
        raise InvalidInput(
            f"{where} must name at least one file. A record with no pages has "
            f"no identity and nothing to point a human back at")
    seen, pages = set(), []
    for index, entry in enumerate(raw):
        if not isinstance(entry, str):
            raise InvalidInput(f"{where}[{index}] must be a path")
        path = Path(entry)
        if not path.is_file():
            raise InvalidInput(f"{where}[{index}]: file not found: {entry}")
        if entry in seen:
            raise InvalidInput(
                f"{where}[{index}]: {entry} is listed twice. A page counted "
                f"twice changes the record's identity and nothing else")
        seen.add(entry)
        payload = path.read_bytes()
        pages.append({
            "path": entry,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        })
    blob = "\n".join(f"{page['sha256']}:{page['bytes']}" for page in pages)
    content_hash = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return pages, content_hash


def _scan_records(records_dir, content_hash):
    """Find an existing record for these bytes, and say what could not be read."""
    if not records_dir.is_dir():
        raise InvalidInput(
            f"records directory not found: {records_dir}. Create it before "
            f"filing anything into it — a typo here would file every letter "
            f"of this run somewhere nobody reads")
    existing, unreadable, scanned = None, [], 0
    for path in sorted(records_dir.glob("*.json")):
        scanned += 1
        try:
            stored = json.loads(path.read_text(encoding="utf-8"),
                                parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            unreadable.append(path.name)
            continue
        record = stored.get("record") if isinstance(stored, dict) else None
        if isinstance(record, dict) and record.get("content_hash") == content_hash:
            existing = existing or str(path)
    return existing, unreadable, scanned


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset a replay must reproduce.

    `extracted_at` is this run's clock, exactly as `issued_at` is, and both are
    excluded so the same pages and the same extraction hash the same tomorrow.
    """
    canonical = {key: result[key] for key in (
        "as_of", "mode", "content_hash", "id", "pages", "conventions",
        "already_extracted", "missing_evidence", "evidence_problems",
        "summary")}
    record = result["record"]
    canonical["record"] = (
        None if record is None
        else {k: v for k, v in record.items() if k != "extracted_at"})
    return canonical


def audit_hash_of(result):
    """Hash the resolved pages and the gated record, excluding this run's ids."""
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _summary(mode, record, gate, already, existing, unreadable, pages):
    parts = []
    page_count = _count(len(pages), "page")

    if already:
        parts.append(
            f"This document is already extracted — {page_count} hashing to a "
            f"record filed at {existing}. Nothing was written and nothing was "
            f"re-read.")
    elif mode == "check":
        parts.append(
            f"{page_count} not seen before. Extract it, then file it with "
            f"mode 'record'.")
    else:
        kept = [name for name in GATED_FIELDS if record[name] is not None]
        if record["amounts"]:
            kept.append("amounts")
        article = "an" if record["doc_type"][0] in "aeiou" else "a"
        parts.append(
            f"Filed {page_count} as {record['id']}, {article} "
            f"{record['doc_type']} letter.")
        if kept:
            parts.append("Quotable and kept: " + ", ".join(kept) + ".")
        else:
            parts.append("Nothing on this page could be quoted.")

    if gate.missing:
        parts.append(
            f"{_count(len(gate.missing), 'field')} could not be quoted and "
            f"{'was' if len(gate.missing) == 1 else 'were'} left null rather "
            f"than guessed at: {', '.join(gate.missing)}. Someone has to open "
            f"the letter and confirm "
            f"{'it' if len(gate.missing) == 1 else 'them'}.")
    elif record is not None and FLAG in record["flags"]:
        parts.append(
            "Nothing in this document could be quoted at all, so it is flagged "
            "for a person to confirm rather than filed as a letter with "
            "nothing in it.")

    if unreadable:
        parts.append(
            f"{_count(len(unreadable), 'file')} in the records directory could "
            f"not be read ({', '.join(unreadable)}), so a duplicate hiding in "
            f"{'it' if len(unreadable) == 1 else 'them'} would not have been "
            f"noticed.")

    parts.append("Nothing has been answered, submitted or filed with anyone.")
    return " ".join(part for part in parts if part)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_record(document, records_dir):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")
    _reject_unknown(document, KNOWN_KEYS, "input")
    records_dir = Path(records_dir)

    if document.get("as_of") is None:
        as_of = datetime.now(SG).date()
        LOG.info("as_of absent; resolved once to SG today %s", as_of.isoformat())
    else:
        as_of = _to_date(document["as_of"], "as_of")

    if "mode" not in document:
        raise InvalidInput(
            "mode is required and has no default: 'check' asks whether this "
            "document has been extracted before, 'record' files an extraction "
            "that has already happened. Guessing between them either wastes a "
            "vision call or discards one")
    mode = document["mode"]
    if mode not in MODES:
        raise InvalidInput(
            f"mode {mode!r} is not one of {', '.join(MODES)}")

    if "source_files" not in document:
        raise InvalidInput(
            "source_files is required: it is what the record's identity is "
            "made of, in page order")
    pages, content_hash = _hash_pages(document["source_files"])

    supplied = [key for key in EXTRACTION_KEYS if key in document]
    if mode == "check":
        if supplied:
            raise InvalidInput(
                f"mode 'check' asks whether this document needs extracting, "
                f"but {', '.join(supplied)} came with it — the extraction has "
                f"already happened, so the question is moot. This is more "
                f"likely a mode typo than a real check; use 'record'")
    else:
        for key in EXTRACTION_KEYS:
            if key not in document:
                raise InvalidInput(
                    f"{key} is required in mode 'record'. Filing an extraction "
                    f"without it would write a record shaped like a letter "
                    f"nobody read")

    existing, unreadable, scanned = _scan_records(records_dir, content_hash)
    already = existing is not None
    record_id = "letter-" + content_hash.split(":", 1)[1][:16]

    gate = Gate({})
    record = None
    if mode == "record" and not already:
        record = _gated_record(document, gate, record_id, content_hash, pages,
                               as_of)

    if already:
        LOG.info("%s already extracted as %s; writing nothing", record_id,
                 existing)
    for name in unreadable:
        LOG.warning("could not read %s in %s", name, records_dir)

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "mode": mode,
        "content_hash": content_hash,
        "id": record_id,
        "pages": pages,
        "records_dir": str(records_dir),
        "records_scanned": scanned,
        "records_unreadable": unreadable,
        "already_extracted": already,
        "existing_record_path": existing,
        "should_extract": not already,
        "record": record,
        "record_path": None,
        "missing_evidence": sorted(gate.missing),
        "evidence_problems": gate.problems,
        "conventions": {
            "evidence": EVIDENCE_RULE,
            "verbatim_limit": VERBATIM_LIMIT,
            "identity": IDENTITY_RULE,
            "idempotency": IDEMPOTENCY_RULE,
            "splitting": SPLITTING_RULE,
            "handoff": HANDOFF_RULE,
            "modes": list(MODES),
            "doc_types": list(DOC_TYPES),
            "gated_fields": list(GATED_FIELDS) + ["amounts[i]"],
            "problem_reasons": list(PROBLEM_REASONS),
        },
    }
    if record is not None:
        record["extracted_at"] = result["issued_at"]
        result["record_path"] = str(records_dir / f"{record_id}.json")
    result["summary"] = _summary(mode, record, gate, already, existing,
                                 unreadable, pages)
    result["audit_hash"] = audit_hash_of(result)

    # The write lives here, beside the scan that decided it was safe. Splitting
    # them would let a caller check for a duplicate and file anyway.
    if result["record_path"] is not None:
        Path(result["record_path"]).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str)
            + "\n", encoding="utf-8")
        LOG.info("wrote %s", result["record_path"])
    return result


def _gated_record(document, gate, record_id, content_hash, pages, as_of):
    doc_type = document["doc_type"]
    if doc_type not in DOC_TYPES:
        raise InvalidInput(
            f"doc_type {doc_type!r} is not one of {', '.join(DOC_TYPES)}. An "
            f"unrecognised type is refused rather than mapped to the nearest "
            f"one: 'other' exists for exactly this")

    fields = document["fields"]
    evidence = document["evidence"]
    if not isinstance(fields, dict) or not isinstance(evidence, dict):
        raise InvalidInput("fields and evidence must both be objects")
    _reject_unknown(fields, FIELD_KEYS, "fields")
    for key in FIELD_KEYS:
        if key not in fields:
            raise InvalidInput(
                f"fields.{key} is required even when the letter never "
                f"mentioned it — pass null to say so. An absent key and a "
                f"field nobody looked for are the same JSON")

    raw_amounts = fields["amounts"]
    if raw_amounts is not None and not isinstance(raw_amounts, list):
        raise InvalidInput("fields.amounts must be a list of amounts, or null")
    amount_count = 0 if raw_amounts is None else len(raw_amounts)

    allowed = set(GATED_FIELDS) | {f"amounts[{i}]" for i in range(amount_count)}
    unknown = sorted(set(evidence) - allowed)
    if unknown:
        raise InvalidInput(
            f"evidence names {', '.join(repr(k) for k in unknown)}, which is "
            f"nothing this record gates. A snippet filed under a name nothing "
            f"reads is a snippet nobody checks, and it reads like diligence. "
            f"Gated here: {', '.join(sorted(allowed)) or 'nothing'}")

    gate.evidence = evidence

    issuer = fields["issuer"]
    if issuer is not None:
        if not isinstance(issuer, str) or not issuer.strip():
            raise InvalidInput("fields.issuer must be a name, or null")
        if not gate.check("issuer",
                          lambda snippet: snippet_has_issuer(snippet, issuer)):
            issuer = None

    dates = {}
    for key in ("issue_date", "deadline"):
        value = fields[key]
        if value is None:
            dates[key] = None
            continue
        parsed = _to_date(value, f"fields.{key}")
        if key == "issue_date" and parsed > as_of:
            raise InvalidInput(
                f"fields.issue_date {value} is in the future relative to "
                f"as_of {as_of.isoformat()}. One of the two is wrong and this "
                f"cannot tell which")
        if gate.check(key, lambda snippet, p=parsed: snippet_has_date(snippet, p)):
            dates[key] = parsed.isoformat()
        else:
            dates[key] = None

    amounts = None
    if raw_amounts is not None:
        kept, refused = [], False
        for index, raw in enumerate(raw_amounts):
            amount = _to_amount(raw, f"fields.amounts[{index}]")
            if gate.check(f"amounts[{index}]",
                          lambda snippet, a=amount: snippet_has_amount(snippet, a)):
                kept.append(str(raw).strip())
            else:
                refused = True
        # One unquotable amount nulls the whole list. A list with the
        # unquotable entry quietly dropped reads as a complete set of figures.
        amounts = None if refused else kept

    action = fields["required_action"]
    if action is not None and not isinstance(action, str):
        raise InvalidInput("fields.required_action must be plain text, or null")

    flags = []
    if gate.missing:
        flags.append(FLAG)
    elif not any([issuer, dates["issue_date"], dates["deadline"], amounts]):
        gate.nothing_evidenced()
        flags.append(FLAG)

    return {
        "id": record_id,
        "content_hash": content_hash,
        "source_files": [page["path"] for page in pages],
        "doc_type": doc_type,
        "issuer": issuer,
        "issue_date": dates["issue_date"],
        "deadline": dates["deadline"],
        "amounts": amounts,
        "required_action": action,
        "evidence": dict(evidence),
        "extracted_at": None,
        "flags": flags,
    }


def _read_input(path):
    if path is None:
        text = sys.stdin.read()
        source = "<stdin>"
    else:
        source = str(path)
        if not path.is_file():
            raise InvalidInput(f"input file not found: {source}")
        text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise InvalidInput(f"{source}: empty input")
    try:
        return json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"{source}: not valid JSON ({exc})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None,
                        help="input JSON file; stdin if omitted")
    parser.add_argument("--output", type=Path, default=None,
                        help="output JSON file; stdout if omitted")
    parser.add_argument("--records", type=Path, required=True,
                        help="the extracted/ directory, one JSON per letter")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        result = build_record(_read_input(args.input), args.records)
    except InvalidInput as exc:
        LOG.error("%s", exc)
        return 2

    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output is None:
        sys.stdout.write(payload + "\n")
    else:
        args.output.write_text(payload + "\n", encoding="utf-8")
        LOG.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
