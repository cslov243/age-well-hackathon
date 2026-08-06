#!/usr/bin/env python3
"""Answer one question for a whole run: does this need a person before anything
is sent?

Usage:
    python3 confirmations.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input:
    {
      "as_of": "2026-08-06",   # optional, defaults to SG today
      "records": [ ... letter_record.py results, verbatim ... ],
      "claims":  [ ... insurance_claim_review.py results, verbatim ... ]
    }

`records` and `claims` are **required keys even when the list is empty**. A run
that checked nothing and a run whose key was misspelled must not look alike:
the first is an answer about nothing, the second is silence wearing its
clothes.

Why this script exists
----------------------

Every other script in the toolkit answers "is *this* record clean?". Nothing
answered "does this run need a person?", so the model answered it — and on
6 August 2026 a family artifact certified `No human confirmation required` over
a record carrying `REQUIRES_HUMAN_CONFIRMATION`, because the other script in the
same run had returned `flags: []` legitimately. That is audit finding #22.

It is the split of labour failing on a status rather than on a number, and the
fix is the same one the project applies to numbers: if the answer is needed and
no script produced it, no answer gets written. **The artifacts quote
`sentence`; they do not compose one.**

Three things it refuses to do:

  * **Swallow a flag.** Any flag on any source produces an item, including a
    flag this script has never heard of. Fail-safe is the only safe direction:
    an unknown flag reading as "nothing to see" is the defect being fixed.
  * **Trust a source it has not checked.** Each input's `audit_hash` is
    recomputed with the function that wrote it, and a mismatch is refused —
    the same refusal `deadline_calendar.py` and `pharmacy_cart.py` apply.
  * **Certify beyond its scope.** It answers for the results it was handed and
    says how many those were. An output nobody passed is an output nobody
    checked, and `sentence` carries that count so a reader can tell the
    difference.

It invents no reason. A record says which of the four ways a snippet failed; a
claims review records only *that* one failed. Each item reports what its
producer knew and nothing more.

No network access. No filesystem access beyond the paths passed in.
"""

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import insurance_claim_review  # noqa: E402
import letter_record  # noqa: E402

SG = timezone(timedelta(hours=8), name="+08:00")

KNOWN_KEYS = ("as_of", "records", "claims")

# What each source must contain to be the result it claims to be.
RECORD_KEYS = ("as_of", "mode", "record", "missing_evidence",
               "evidence_problems", "summary", "audit_hash")
CLAIMS_KEYS = ("as_of", "claims", "claims_counted",
               "claims_requiring_human_confirmation", "audit_hash")

FLAG = "REQUIRES_HUMAN_CONFIRMATION"

# One plain-words ask per reason a producer can give. The reason is copied from
# the producer; only the sentence is ours.
ASKS = {
    "no_snippet": (
        "{field} was reported with nothing quoted from the page. A person must "
        "read {field} off the document itself."),
    "blank_snippet": (
        "The quotation offered for {field} was empty. A person must read "
        "{field} off the document itself."),
    "value_not_in_snippet": (
        "The value given for {field} does not appear in the text quoted as its "
        "evidence. A person must read {field} off the document, and check the "
        "wording it was taken from."),
    "nothing_evidenced": (
        "Nothing on this document could be quoted. A person must read the "
        "document itself."),
    "missing_evidence": (
        "{field} could not be quoted from the page. A person must read {field} "
        "off the document itself."),
}

UNKNOWN_FLAG_ASK = (
    "{tool} raised {flag}, which this script does not recognise. A person must "
    "look at {subject} before anything is sent.")

SCOPE_RULE = (
    "this answers for the results it was handed and for nothing else. "
    "sources_checked lists them and sentence carries the count, because an "
    "output that was never passed is an output that was never checked and a "
    "reader cannot see the difference from here"
)
FAIL_SAFE_RULE = (
    "any flag on any source produces an item, including a flag this script "
    "does not recognise. A flag it has never heard of is reported as needing a "
    "person rather than ignored: audit finding #22 was an artifact reading one "
    "script's empty flag list as the whole run's answer"
)
REASON_RULE = (
    "each item reports the reason its producer gave. letter_record.py "
    "distinguishes no_snippet, blank_snippet, value_not_in_snippet and "
    "nothing_evidenced; insurance_claim_review.py records only that a field "
    "could not be quoted, and its items say missing_evidence rather than "
    "guessing which"
)
QUOTING_RULE = (
    "sentence is written to be quoted verbatim into both artifacts. An "
    "artifact that composes its own confirmation status has taken the "
    "judgement back, which is the defect this script exists to remove"
)
HANDOFF_RULE = (
    "nothing here is submitted, sent, paid or confirmed. This says what a "
    "person must look at, and a person looks at it"
)

LOG = logging.getLogger("confirmations")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

def sg_today():
    return datetime.now(SG).date()


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(f"{where} is not a valid date: {value!r}") from exc


def _reject_unknown(mapping, known, where):
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        raise InvalidInput(
            f"{where} has unrecognised keys: {', '.join(unknown)}. "
            f"A misspelled key takes no effect and says nothing, which reads "
            f"downstream as a run with nothing to check. "
            f"Allowed: {', '.join(known)}")


def _require_list(document, key):
    if key not in document:
        raise InvalidInput(
            f"{key} is required, even when there is nothing to check — pass "
            f"[] to say so explicitly. An absent key and a misspelled one look "
            f"identical from here, and one of them means a whole set of flags "
            f"was never read")
    value = document[key]
    if not isinstance(value, list):
        raise InvalidInput(
            f"{key} must be a list of results passed through verbatim, or []")
    return value


# --------------------------------------------------------------------------
# the sources, taken as given and checked
# --------------------------------------------------------------------------

def _resolve_source(source, key, index, required_keys, hash_of, produced_by,
                    as_of):
    where = f"{key}[{index}]"
    if not isinstance(source, dict):
        raise InvalidInput(
            f"{where} must be a {produced_by} result object passed through "
            f"verbatim")
    for name in required_keys:
        if name not in source:
            raise InvalidInput(
                f"{where} has no {name!r}: this does not look like a "
                f"{produced_by} result. This script reads flags out of one "
                f"rather than deciding anything itself, and there is nothing "
                f"here to read")

    stored = source["audit_hash"]
    recomputed = hash_of(source)
    if recomputed != stored:
        raise InvalidInput(
            f"{where} audit_hash does not match its contents (stored {stored}, "
            f"recomputed {recomputed}). It has been edited since it was "
            f"produced — refusing to report on flags that may have been "
            f"edited out of it")

    source_as_of = _to_date(source["as_of"], f"{where}.as_of")
    if source_as_of > as_of:
        raise InvalidInput(
            f"{where} is dated {source_as_of.isoformat()}, which is in the "
            f"future relative to as_of {as_of.isoformat()}. One of the two is "
            f"wrong and this cannot tell which")

    return {
        "tool": produced_by,
        "tool_run_id": source.get("tool_run_id"),
        "audit_hash": stored,
        "as_of": source_as_of.isoformat(),
        "age_days": (as_of - source_as_of).days,
    }


def _item(tool, subject, source_audit_hash, field, reason, ask):
    return {
        "tool": tool,
        "subject": subject,
        "source_audit_hash": source_audit_hash,
        "field": field,
        "reason": reason,
        "ask": ask,
    }


def _unknown_flags(flags, tool, subject, source_audit_hash):
    """Every flag that is not the one whose fields we already itemise."""
    return [
        _item(tool, subject, source_audit_hash, None, "unrecognised_flag",
              UNKNOWN_FLAG_ASK.format(tool=tool, flag=flag, subject=subject))
        for flag in sorted(set(flags) - {FLAG})
    ]


def _items_from_record(source, checked):
    record = source["record"] or {}
    subject = record.get("id") or source.get("id") or "an unidentified letter"
    tool, digest = checked["tool"], checked["audit_hash"]

    reasons = {}
    for problem in source["evidence_problems"]:
        if isinstance(problem, dict) and "field" in problem:
            reasons[problem["field"]] = problem.get("reason", "missing_evidence")

    fields = sorted(set(source["missing_evidence"]) | set(reasons))
    items = []
    for field in fields:
        reason = reasons.get(field, "missing_evidence")
        template = ASKS.get(reason, ASKS["missing_evidence"])
        items.append(_item(tool, subject, digest, field, reason,
                           template.format(field=field)))

    items.extend(_unknown_flags(record.get("flags", ()), tool, subject, digest))
    return items


def _items_from_claims(source, checked):
    tool, digest = checked["tool"], checked["audit_hash"]
    items = []
    for claim in source["claims"]:
        subject = claim.get("id") or "an unidentified claim"
        for field in sorted(claim.get("missing_evidence", ())):
            items.append(_item(
                tool, subject, digest, field, "missing_evidence",
                ASKS["missing_evidence"].format(field=field)))
        items.extend(_unknown_flags(claim.get("flags", ()), tool, subject,
                                    digest))
    return items


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _count(number, noun, plural=None):
    word = noun if number == 1 else (plural or noun + "s")
    return f"{number} {word}"


def _sentence(items, checked):
    scope = _count(len(checked), "script output")
    if not items:
        return (f"Nothing in the {scope} checked needs a person before "
                f"anything is sent.")
    named = ", ".join(f"{item['field'] or item['reason']} on {item['subject']}"
                      for item in items)
    return (f"{_count(len(items), 'thing')} in the {scope} checked "
            f"{'needs' if len(items) == 1 else 'need'} a person before "
            f"anything is sent: {named}.")


def _summary(items, checked, sentence):
    lines = [sentence]
    if items:
        lines.append("Each one is a value a script would not certify:")
        for item in items:
            lines.append(f"  - {item['ask']} Raised by {item['tool']}.")
    lines.append(
        "Checked: " + (", ".join(
            f"{source['tool']} ({source['audit_hash']})" for source in checked)
            if checked else "no script output was passed to this run"))
    lines.append(
        "Nothing here has been submitted, sent, paid or confirmed by this "
        "tool. It says what a person must look at.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset a replay must reproduce.

    A source's own `tool_run_id` is excluded for the same reason this run's is:
    re-running `letter_record.py` on unchanged pages produces a new run id and
    the same `audit_hash`, and the confirmation answer is identical. Hashing
    the run id would make two identical answers hash differently, which is
    exactly the comparison audit finding #23 needs to be able to make.
    """
    canonical = {key: result[key] for key in (
        "as_of", "human_confirmation_required", "items", "items_counted",
        "sentence", "summary", "conventions")}
    canonical["sources_checked"] = [
        {k: v for k, v in source.items() if k != "tool_run_id"}
        for source in result["sources_checked"]]
    return canonical


def audit_hash_of(result):
    """Hash the sources checked and the answer given, excluding this run's ids.

    The answer is inside the hash on purpose: a replay that reproduced the
    inputs but not the verdict would certify a contradiction, which is the
    shape of the defect this script was written for.
    """
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the build
# --------------------------------------------------------------------------

def build_confirmations(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")
    _reject_unknown(document, KNOWN_KEYS, "input")

    if "as_of" in document and document["as_of"] is not None:
        as_of = _to_date(document["as_of"], "as_of")
    else:
        as_of = sg_today()
        LOG.info("as_of absent; resolved once to SG today %s", as_of.isoformat())

    records = _require_list(document, "records")
    claims = _require_list(document, "claims")

    checked, items = [], []
    for index, source in enumerate(records):
        resolved = _resolve_source(source, "records", index, RECORD_KEYS,
                                   letter_record.audit_hash_of,
                                   "letter_record.py", as_of)
        checked.append(resolved)
        items.extend(_items_from_record(source, resolved))
    for index, source in enumerate(claims):
        resolved = _resolve_source(source, "claims", index, CLAIMS_KEYS,
                                   insurance_claim_review.audit_hash_of,
                                   "insurance_claim_review.py", as_of)
        checked.append(resolved)
        items.extend(_items_from_claims(source, resolved))

    items.sort(key=lambda item: (item["tool"], item["subject"],
                                 item["field"] or "", item["reason"]))
    sentence = _sentence(items, checked)

    for item in items:
        LOG.info("%s needs a person: %s on %s (%s)", item["tool"],
                 item["field"] or item["reason"], item["subject"],
                 item["reason"])

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "human_confirmation_required": bool(items),
        "items": items,
        "items_counted": len(items),
        "sources_checked": checked,
        "sentence": sentence,
        "summary": _summary(items, checked, sentence),
        "conventions": {
            "scope": SCOPE_RULE,
            "fail_safe": FAIL_SAFE_RULE,
            "reasons": REASON_RULE,
            "quoting": QUOTING_RULE,
            "handoff": HANDOFF_RULE,
        },
    }
    result["audit_hash"] = audit_hash_of(result)
    return result


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def _read_input(path):
    text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"input is not valid JSON: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="path to the input JSON; stdin if omitted")
    parser.add_argument("--output", help="path to write JSON to; stdout if omitted")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(message)s")
    try:
        result = build_confirmations(_read_input(args.input))
    except InvalidInput as exc:
        LOG.error("%s", exc)
        return 2

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        LOG.info("wrote %s", args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
