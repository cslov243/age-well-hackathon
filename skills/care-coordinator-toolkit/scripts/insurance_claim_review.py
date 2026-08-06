#!/usr/bin/env python3
"""Review insurance claim letters: deadlines, amounts outstanding, evidence gaps.

Usage:
    python3 insurance_claim_review.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input:
    {
      "as_of": "2026-08-04",                 # optional, defaults to SG today
      "claims": [{
        "id": "claim-001",
        "insurer": "Great Eastern",          # evidence-gated
        "policy_reference": "GE-12345",      # identifier, not gated
        "incident_date": "2026-06-01",       # evidence-gated
        "submission_window_days": 90,        # evidence-gated
        "insurer_decision": "partially_paid",
        "decision_date": "2026-07-20",       # evidence-gated
        "appeal_window_days": 30,            # evidence-gated
        "amounts": {"billed": "4820.00",     # each evidence-gated
                    "insurer_paid": "3100.00",
                    "household_paid": "500.00"},
        "documents_required": ["original receipt", "discharge summary"],
        "documents_held": ["original receipt"],
        "evidence": {"insurer": "GREAT EASTERN LIFE ASSURANCE ...",
                     "amounts.billed": "Total hospital bill: SGD 4,820.00"}
      }]
    }

What this script does NOT do, by construction:

  * It never decides coverage. `insurer_decision` is a closed set read off the
    document — paid, partially_paid, rejected, pending, not_stated — and an
    unrecognised value is refused rather than mapped to the nearest one. There
    is no code path that can emit "you are covered". Whether a claim will be
    paid is the insurer's decision and nobody else's.
  * It never submits, logs in, or handles a credential. It prepares; the human
    acts.
  * It says nothing about the medical content of the claim.

Evidence rule (CLAUDE.md, docs/CONTRACTS.md): every deadline, amount and issuer
needs a verbatim snippet in `evidence` under its field path, **and the snippet
has to contain the value it is offered for** — see `_evidence.py`. A value with
no snippet, a blank one, or one quoting text that says something else is
nulled, listed in `missing_evidence`, and the claim is flagged
REQUIRES_HUMAN_CONFIRMATION. Arithmetic downstream of a nulled field is not
attempted. A field simply absent from the document is null without a flag —
"not found" is honest; "found, but unquotable" is not.

The containment half was added 6 August 2026, after a cold agent worked a
balance out by subtraction, quoted it against a line with no number in it, and
this script reported SGD 0.00 outstanding against a letter saying SGD 360.00.
`letter_record.py` refused the identical pair in the same run; both now call
the same functions.

Money is Decimal end to end. Every date and status derives from one resolved
`as_of`, never the wall clock, so any run replays to the same audit hash.

No network access. No filesystem access beyond the two paths passed in.
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
    VERBATIM_LIMIT,
    snippet_has_amount,
    snippet_has_date,
    snippet_has_days,
    snippet_has_issuer,
)

SG = timezone(timedelta(hours=8), name="+08:00")
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

DECISIONS = ("paid", "partially_paid", "rejected", "pending", "not_stated")
APPEALABLE = ("partially_paid", "rejected")
AMOUNT_KEYS = ("billed", "insurer_paid", "household_paid")
STATUSES = ("ok", "due_today", "overdue", "unknown")
FLAG = "REQUIRES_HUMAN_CONFIRMATION"

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

HANDOFF = ("Nothing here has been submitted, appealed or decided by this tool. "
           "Check the letter itself, and speak to the insurer or a family "
           "member, before anything is sent.")

EVIDENCE_RULE = (
    "every deadline, amount and issuer requires a verbatim snippet in "
    "'evidence' under its field path, and the snippet has to contain the "
    "value it is offered for. An asserted value with no snippet, a blank one, "
    "or one that quotes text saying something else is nulled and the claim is "
    "flagged " + FLAG
)
DECISION_RULE = (
    "insurer_decision is read off the document as one of " +
    ", ".join(DECISIONS) + "; this tool never assesses coverage itself"
)
OUTSTANDING_RULE = (
    "outstanding = billed - insurer_paid - household_paid, floored at zero; "
    "any excess is reported as refund_due instead of a negative outstanding"
)

LOG = logging.getLogger("insurance_claim_review")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

def _to_money(value, where):
    """Decimal money, or raise. Floats are refused, not coerced."""
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected an amount, got a boolean")
    if isinstance(value, float):
        raise InvalidInput(
            f"{where}: amount {value!r} is a binary float and cannot represent "
            f"money exactly; pass it as a JSON number parsed with "
            f"parse_float=Decimal, or as a string"
        )
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidInput(f"{where}: {value!r} is not a number")
    else:
        raise InvalidInput(f"{where}: expected a number, got {type(value).__name__}")

    if not amount.is_finite():
        raise InvalidInput(f"{where}: amount {value!r} is not finite")
    if amount < 0:
        raise InvalidInput(
            f"{where}: amount {amount} is negative; state the figure as the "
            f"letter states it"
        )
    if -amount.as_tuple().exponent > 2:
        raise InvalidInput(f"{where}: amount {amount} has more than two decimal places")
    return amount


def _to_whole_days(value, where):
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected a whole number of days")
    if isinstance(value, int):
        days = value
    else:
        if isinstance(value, float):
            raise InvalidInput(
                f"{where}: {value!r} is a binary float; pass a whole number "
                f"of days"
            )
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise InvalidInput(f"{where}: {value!r} is not a number")
        if not number.is_finite() or number != number.to_integral_value():
            raise InvalidInput(f"{where}: {value!r} is not a whole number of days")
        days = int(number)
    if days < 0:
        raise InvalidInput(f"{where}: {days} days is negative")
    return days


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD)"
        )


def _to_text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{where}: expected a non-empty string")
    return value.strip()


def _to_text_list(value, where):
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidInput(f"{where}: expected a list of strings")
    return [_to_text(item, f"{where}[{i}]") for i, item in enumerate(value)]


def _human_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _money_text(amount):
    return f"SGD {amount}"


# --------------------------------------------------------------------------
# the evidence gate
# --------------------------------------------------------------------------

class Gate:
    """Applies the evidence rule to one claim and records what failed it.

    A value survives only when its snippet exists, is not blank, **and
    contains the value it is offered for**. Anything else is dropped to None
    and recorded. A value that is simply absent is None without complaint.

    That last condition is audit finding #14. Without it, a balance worked out
    by subtraction and quoted against "The balance is payable by the
    policyholder" — a line with no number in it — was accepted, and the
    caregiver was told she owed SGD 0.00 against a letter saying SGD 360.00.
    The containment checks live in `_evidence.py` so that this script and
    `letter_record.py` cannot drift back apart.
    """

    def __init__(self, entry, evidence, where):
        self.entry = entry
        self.evidence = evidence
        self.where = where
        self.missing = []
        self.used = {}

    def _snippet(self, field):
        snippet = self.evidence.get(field)
        if not isinstance(snippet, str) or not snippet.strip():
            return None
        return snippet.strip()

    def _refuse(self, field, reason):
        self.missing.append(field)
        LOG.warning("%s.%s: %s — nulled and flagged", self.where, field, reason)
        return None

    def take(self, field, convert, contains, raw=None):
        value = self.entry.get(field) if raw is None else raw
        if value is None:
            return None
        # Converted before anything else, so a malformed value is refused
        # loudly rather than hidden behind the missing-evidence path.
        converted = convert(value, f"{self.where}.{field}")
        snippet = self._snippet(field)
        if snippet is None:
            return self._refuse(field, "nothing quoted for it")
        if not contains(snippet, converted):
            return self._refuse(
                field,
                f"{value!r} does not appear in the text quoted for it "
                f"({snippet!r}); the value and its evidence disagree, and the "
                f"evidence is the one that was on the page")
        self.used[field] = snippet
        return converted


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _resolve_as_of(document):
    raw = document.get("as_of")
    if raw is None:
        resolved = datetime.now(SG).date()
        LOG.info("as_of absent; resolved once to SG today %s", resolved.isoformat())
        return resolved
    return _to_date(raw, "as_of")


def _resolve_amounts(entry, gate, where):
    amounts = entry.get("amounts")
    if amounts is None:
        amounts = {}
    if not isinstance(amounts, dict):
        raise InvalidInput(f"{where}.amounts must be an object")
    unknown = sorted(set(amounts) - set(AMOUNT_KEYS))
    if unknown:
        raise InvalidInput(
            f"{where}.amounts has unrecognised keys: {', '.join(unknown)}. "
            f"Allowed: {', '.join(AMOUNT_KEYS)}"
        )
    resolved = {}
    for key in AMOUNT_KEYS:
        resolved[key] = gate.take(
            f"amounts.{key}", _to_money, snippet_has_amount,
            raw=amounts.get(key)
        )
    return resolved


def _resolve_claim(entry, index, as_of):
    where = f"claims[{index}]"
    if not isinstance(entry, dict):
        raise InvalidInput(f"{where} must be an object")

    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        raise InvalidInput(
            f"{where}: 'evidence' is required and must be an object mapping "
            f"field paths to verbatim snippets"
        )

    claim_id = _to_text(entry.get("id"), f"{where}.id")
    gate = Gate(entry, evidence, where)

    decision = entry.get("insurer_decision")
    if decision is None:
        decision = "not_stated"
    if decision not in DECISIONS:
        raise InvalidInput(
            f"{where}: insurer_decision {decision!r} is not one of "
            f"{', '.join(DECISIONS)}. This tool reports the insurer's stated "
            f"outcome and does not map free text onto the nearest one"
        )

    insurer = gate.take("insurer", _to_text, snippet_has_issuer)
    incident_date = gate.take("incident_date", _to_date, snippet_has_date)
    if incident_date is not None and incident_date > as_of:
        raise InvalidInput(
            f"{where}: incident_date {incident_date.isoformat()} is after "
            f"as_of {as_of.isoformat()}"
        )
    submission_window = gate.take("submission_window_days", _to_whole_days,
                                  snippet_has_days)
    decision_date = gate.take("decision_date", _to_date, snippet_has_date)
    if decision_date is not None and decision_date > as_of:
        raise InvalidInput(
            f"{where}: decision_date {decision_date.isoformat()} is after "
            f"as_of {as_of.isoformat()}"
        )
    appeal_window = gate.take("appeal_window_days", _to_whole_days,
                              snippet_has_days)
    amounts = _resolve_amounts(entry, gate, where)

    policy_reference = None
    if entry.get("policy_reference") is not None:
        policy_reference = _to_text(
            entry["policy_reference"], f"{where}.policy_reference"
        )

    return {
        "id": claim_id,
        "insurer": insurer,
        "policy_reference": policy_reference,
        "incident_date": incident_date,
        "submission_window_days": submission_window,
        "insurer_decision": decision,
        "decision_date": decision_date,
        "appeal_window_days": appeal_window,
        "amounts": amounts,
        "documents_required": _to_text_list(
            entry.get("documents_required"), f"{where}.documents_required"
        ),
        "documents_held": _to_text_list(
            entry.get("documents_held"), f"{where}.documents_held"
        ),
        "missing_evidence": gate.missing,
        "evidence": gate.used,
    }


def _resolve_claims(document, as_of):
    if "claims" not in document:
        raise InvalidInput("claims is required (use [] for none)")
    claims = document["claims"]
    if not isinstance(claims, list):
        raise InvalidInput("claims must be a list")

    resolved = []
    seen = set()
    for index, entry in enumerate(claims):
        claim = _resolve_claim(entry, index, as_of)
        if claim["id"] in seen:
            raise InvalidInput(
                f"claims[{index}]: duplicate claim id {claim['id']!r}"
            )
        seen.add(claim["id"])
        resolved.append(claim)
    return resolved


# --------------------------------------------------------------------------
# review — arithmetic only
# --------------------------------------------------------------------------

def _deadline(kind, start, window, as_of, basis_when_known, basis_when_not):
    if start is None or window is None:
        return {"kind": kind, "due_on": None, "days_remaining": None,
                "status": "unknown", "basis": basis_when_not}
    due_on = start + timedelta(days=window)
    days_remaining = (due_on - as_of).days
    if days_remaining > 0:
        status = "ok"
    elif days_remaining == 0:
        status = "due_today"
    else:
        status = "overdue"
    return {
        "kind": kind,
        "due_on": due_on.isoformat(),
        "days_remaining": days_remaining,
        "status": status,
        "basis": basis_when_known(due_on, window, start),
    }


def _review_one(claim, as_of):
    deadlines = [_deadline(
        "submission", claim["incident_date"], claim["submission_window_days"],
        as_of,
        lambda due, window, start: (
            f"{window} days from the incident date, {_human_date(start)}, "
            f"closing {_human_date(due)}"
        ),
        "the letter does not give both an incident date and a submission "
        "window with a quotable line, so no closing date is calculated",
    )]
    if claim["insurer_decision"] in APPEALABLE:
        deadlines.append(_deadline(
            "appeal", claim["decision_date"], claim["appeal_window_days"],
            as_of,
            lambda due, window, start: (
                f"{window} days from the insurer's decision date, "
                f"{_human_date(start)}, closing {_human_date(due)}"
            ),
            "the letter does not give both a decision date and an appeal "
            "window with a quotable line, so no closing date is calculated",
        ))

    billed = claim["amounts"]["billed"]
    # An amount the letter never mentioned is genuinely zero. An amount that
    # was asserted but could not be quoted is *unknown*, and subtracting zero
    # for it would overstate what the household still owes — a confident wrong
    # number, which is the one thing this script must never produce.
    unevidenced = [f for f in claim["missing_evidence"]
                   if f.startswith("amounts.")]
    if billed is None or unevidenced:
        outstanding = refund_due = None
    else:
        paid = (claim["amounts"]["insurer_paid"] or ZERO) + \
               (claim["amounts"]["household_paid"] or ZERO)
        net = (billed - paid).quantize(CENT)
        outstanding = net if net > 0 else ZERO
        refund_due = -net if net < 0 else ZERO

    held = {d.strip().casefold() for d in claim["documents_held"]}
    outstanding_docs = [d for d in claim["documents_required"]
                        if d.strip().casefold() not in held]

    flags = [FLAG] if claim["missing_evidence"] else []

    reviewed = {
        "id": claim["id"],
        "insurer": claim["insurer"],
        "policy_reference": claim["policy_reference"],
        "incident_date": claim["incident_date"].isoformat()
                         if claim["incident_date"] else None,
        "insurer_decision": claim["insurer_decision"],
        "decision_date": claim["decision_date"].isoformat()
                         if claim["decision_date"] else None,
        "amounts": {k: (str(v) if v is not None else None)
                    for k, v in claim["amounts"].items()},
        "outstanding": str(outstanding) if outstanding is not None else None,
        "refund_due": str(refund_due) if refund_due is not None else None,
        "deadlines": deadlines,
        "documents_outstanding": outstanding_docs,
        "missing_evidence": sorted(claim["missing_evidence"]),
        "evidence": claim["evidence"],
        "flags": flags,
    }
    reviewed["summary"] = _summarise(reviewed, as_of)
    return reviewed


DECISION_TEXT = {
    "paid": "The insurer records this claim as paid in full.",
    "partially_paid": "The insurer records this claim as partly paid.",
    "rejected": "The insurer records this claim as rejected.",
    "pending": "The insurer records this claim as still being assessed.",
    "not_stated": "The letter does not state an outcome for this claim.",
}


def _summarise(reviewed, as_of):
    """Plain sentences reporting what the letter says and what the arithmetic
    gives. No assessment of coverage, no advice, no medical content."""
    who = reviewed["insurer"] or "The insurer named on the letter"
    parts = [f"{who} — our reference {reviewed['id']}.",
             DECISION_TEXT[reviewed["insurer_decision"]]]

    bits = []
    if reviewed["amounts"]["billed"] is not None:
        bits.append(f"Billed {_money_text(reviewed['amounts']['billed'])}")
    if reviewed["amounts"]["insurer_paid"] is not None:
        bits.append(f"the letter states "
                    f"{_money_text(reviewed['amounts']['insurer_paid'])} "
                    f"payable by the insurer")
    if reviewed["amounts"]["household_paid"] is not None:
        bits.append(f"{_money_text(reviewed['amounts']['household_paid'])} "
                    f"already borne by the household")
    if bits:
        parts.append("; ".join(bits) + ".")

    if reviewed["outstanding"] is None:
        parts.append("At least one figure could not be quoted from the letter, "
                     "so no outstanding total is calculated here. Working one "
                     "out from the figures that could be read would understate "
                     "or overstate it, and this tool will not guess at money.")
    elif reviewed["refund_due"] != "0.00":
        parts.append(f"That is {_money_text(reviewed['refund_due'])} more "
                     f"received than billed.")
    else:
        parts.append(f"That leaves {_money_text(reviewed['outstanding'])} "
                     f"outstanding.")

    for item in reviewed["deadlines"]:
        label = "Submission window" if item["kind"] == "submission" else "Appeal window"
        if item["due_on"] is None:
            parts.append(f"{label}: {item['basis']}.")
        else:
            parts.append(
                f"{label}: {item['basis']}, which is {item['days_remaining']} "
                f"days from {_human_date(as_of)}."
            )

    if reviewed["documents_outstanding"]:
        parts.append("Still to gather: "
                     + ", ".join(reviewed["documents_outstanding"]) + ".")

    if reviewed["missing_evidence"]:
        parts.append(
            "These figures had no line in the letter that quotes them, and "
            "are left blank rather than guessed: "
            + ", ".join(reviewed["missing_evidence"])
            + ". A person needs to read the letter and confirm them. Until "
            "someone does, do not carry them forward by hand into anything "
            "else — a figure this tool refused is not a figure."
        )

    parts.append(HANDOFF)
    return " ".join(parts)


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    return {
        "as_of": result["as_of"],
        "currency": result["currency"],
        "claims_counted": result["claims_counted"],
        "claims_requiring_human_confirmation":
            result["claims_requiring_human_confirmation"],
        "conventions": result["conventions"],
        "claims": result["claims"],
    }


def audit_hash_of(result):
    """Hash resolved inputs *and* computed figures, so it cannot certify a
    contradiction. Excludes tool_run_id and issued_at so a replay reproduces it.
    """
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def review_claims(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")

    as_of = _resolve_as_of(document)
    claims = _resolve_claims(document, as_of)
    reviewed = [_review_one(c, as_of) for c in claims]

    needing_human = sum(1 for c in reviewed if FLAG in c["flags"])
    LOG.info("as_of %s: reviewed %d claim(s), %d requiring human confirmation",
             as_of.isoformat(), len(reviewed), needing_human)
    for entry in reviewed:
        LOG.info("%s: decision %s, outstanding %s, %s",
                 entry["id"], entry["insurer_decision"], entry["outstanding"],
                 ", ".join(f"{d['kind']}={d['status']}"
                           for d in entry["deadlines"]))

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "currency": "SGD",
        "claims_counted": len(reviewed),
        "claims_requiring_human_confirmation": needing_human,
        "conventions": {
            "evidence": EVIDENCE_RULE,
            "verbatim": VERBATIM_LIMIT,
            "decision": DECISION_RULE,
            "outstanding": OUTSTANDING_RULE,
            "decisions": list(DECISIONS),
            "statuses": list(STATUSES),
            "handoff": HANDOFF,
        },
        "claims": reviewed,
    }
    result["audit_hash"] = audit_hash_of(result)
    return result


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
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        result = review_claims(_read_input(args.input))
    except InvalidInput as exc:
        LOG.error("%s", exc)
        return 2

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is None:
        sys.stdout.write(payload + "\n")
    else:
        args.output.write_text(payload + "\n", encoding="utf-8")
        LOG.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
