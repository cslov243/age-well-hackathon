#!/usr/bin/env python3
"""Split shared caregiving expenses between family members.

Usage:
    python3 expense_split.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input:
    {
      "as_of": "2026-08-04",                       # optional, defaults to SG today
      "members":  [{"id": "older-brother"}, {"id": "younger-sister"}],
      "expenses": [{"id": "e1", "amount": 123.70,
                    "paid_by": "older-brother",
                    "description": "GP visit",     # optional
                    "date": "2026-07-20"}],        # optional, must be <= as_of
      "split_rule": {"mode": "even"}
                 |  {"mode": "weighted", "weights": {...}}   # must sum to 1
                 |  {"mode": "ratio",    "weights": {...}}   # relative, normalised
    }

Money is Decimal end to end and is emitted as strings; a binary float amount is
rejected rather than silently rounded. Proportional division runs on exact
Fractions, so the floor boundary is never decided by accumulated error.

Residual cents (the stray cent in $123.70 across three siblings) go one each,
largest applied weight first, ties broken by member id ascending. Shares always
sum exactly to the total.

No network access. No filesystem access beyond the two paths passed in.
"""

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path

SG = timezone(timedelta(hours=8), name="+08:00")
CENT = Decimal("0.01")
MODES = ("even", "weighted", "ratio")
RESIDUAL_RULE = (
    "residual cents assigned one each, largest applied weight first, "
    "ties broken by member id ascending"
)

LOG = logging.getLogger("expense_split")


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
            f"{where}: amount {amount} is negative; refunds are not modelled here"
        )
    if -amount.as_tuple().exponent > 2:
        raise InvalidInput(
            f"{where}: amount {amount} has more than two decimal places"
        )
    return amount


def _to_weight(value, where):
    """Non-negative Decimal weight, or raise."""
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected a weight, got a boolean")
    if isinstance(value, float):
        raise InvalidInput(
            f"{where}: weight {value!r} is a binary float; pass it as a JSON "
            f"number parsed with parse_float=Decimal, or as a string"
        )
    if isinstance(value, Decimal):
        weight = value
    elif isinstance(value, int):
        weight = Decimal(value)
    elif isinstance(value, str):
        try:
            weight = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidInput(f"{where}: {value!r} is not a number")
    else:
        raise InvalidInput(f"{where}: expected a number, got {type(value).__name__}")

    if not weight.is_finite():
        raise InvalidInput(f"{where}: weight {value!r} is not finite")
    if weight < 0:
        raise InvalidInput(f"{where}: weight {weight} is negative")
    return weight


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD)"
        )


def _render_weight(frac):
    """Exact rendering of a normalised weight: decimal if it terminates, else n/d."""
    denominator = frac.denominator
    stripped = denominator
    for prime in (2, 5):
        while stripped % prime == 0:
            stripped //= prime
    if stripped != 1:
        return f"{frac.numerator}/{frac.denominator}"
    with localcontext() as ctx:
        ctx.prec = 100
        return str(Decimal(frac.numerator) / Decimal(denominator))


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


def _resolve_members(document):
    members = document.get("members")
    if not isinstance(members, list) or not members:
        raise InvalidInput("members must be a non-empty list")

    ids = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise InvalidInput(f"members[{index}] must be an object")
        member_id = member.get("id")
        if not isinstance(member_id, str) or not member_id.strip():
            raise InvalidInput(f"members[{index}] has no usable 'id'")
        member_id = member_id.strip()
        if member_id in ids:
            raise InvalidInput(f"members[{index}]: duplicate member id {member_id!r}")
        ids.append(member_id)
    return ids


def _resolve_expenses(document, member_ids, as_of):
    expenses = document.get("expenses")
    if expenses is None:
        expenses = []
    if not isinstance(expenses, list):
        raise InvalidInput("expenses must be a list")

    resolved = []
    seen_ids = set()
    for index, expense in enumerate(expenses):
        where = f"expenses[{index}]"
        if not isinstance(expense, dict):
            raise InvalidInput(f"{where} must be an object")

        expense_id = expense.get("id")
        if not isinstance(expense_id, str) or not expense_id.strip():
            raise InvalidInput(f"{where} has no usable 'id'")
        expense_id = expense_id.strip()
        if expense_id in seen_ids:
            raise InvalidInput(f"{where}: duplicate expense id {expense_id!r}")
        seen_ids.add(expense_id)

        if "amount" not in expense:
            raise InvalidInput(f"{where} has no 'amount'")
        amount = _to_money(expense["amount"], where)

        paid_by = expense.get("paid_by")
        if not isinstance(paid_by, str) or not paid_by.strip():
            raise InvalidInput(f"{where} has no 'paid_by'")
        paid_by = paid_by.strip()
        if paid_by not in member_ids:
            # The finding this guards: money counted into the total but
            # attributed to nobody, then quietly absent from every share.
            raise InvalidInput(
                f"{where}: paid_by {paid_by!r} matches no member "
                f"({', '.join(member_ids)}); refusing to split an expense "
                f"whose payer is unknown"
            )

        spent_on = None
        if expense.get("date") is not None:
            spent_on = _to_date(expense["date"], f"{where}.date")
            if spent_on > as_of:
                raise InvalidInput(
                    f"{where}: date {spent_on.isoformat()} is after as_of "
                    f"{as_of.isoformat()}"
                )

        resolved.append({
            "id": expense_id,
            "amount": amount,
            "paid_by": paid_by,
            "date": spent_on.isoformat() if spent_on else None,
        })
        # 'description' is accepted and deliberately not carried: nothing in
        # this script's output is line-item level. The family artifact renders
        # line items from the expense input it already holds.
    return resolved


def _resolve_weights(document, member_ids):
    """Return (mode, weights_as_given|None, {member_id: Fraction}, normalised)."""
    rule = document.get("split_rule")
    if not isinstance(rule, dict):
        raise InvalidInput("split_rule is required and must be an object")

    mode = rule.get("mode")
    if mode not in MODES:
        raise InvalidInput(
            f"split_rule.mode {mode!r} is not one of {', '.join(MODES)}"
        )

    if mode == "even":
        share = Fraction(1, len(member_ids))
        return mode, None, {mid: share for mid in member_ids}, True

    weights = rule.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise InvalidInput(f"split_rule.mode {mode!r} requires a 'weights' object")

    unknown = sorted(set(weights) - set(member_ids))
    if unknown:
        raise InvalidInput(
            f"split_rule.weights names non-members: {', '.join(unknown)}"
        )
    missing = [mid for mid in member_ids if mid not in weights]
    if missing:
        raise InvalidInput(
            f"split_rule.weights is missing members: {', '.join(missing)}"
        )

    as_given = {}
    for member_id in member_ids:
        as_given[member_id] = _to_weight(
            weights[member_id], f"split_rule.weights[{member_id!r}]"
        )

    total = sum(as_given.values())
    if mode == "weighted":
        if total != 1:
            raise InvalidInput(
                f"split_rule.weights sum to {total}, not 1. Use "
                f"mode 'ratio' for relative weights such as 2:1; 'weighted' "
                f"rejects them so a mistyped share cannot be silently rescaled"
            )
        applied = {mid: Fraction(w) for mid, w in as_given.items()}
        normalised = False
    else:
        if total <= 0:
            raise InvalidInput("split_rule.weights sum to 0; nothing to divide by")
        applied = {mid: Fraction(w) / Fraction(total)
                   for mid, w in as_given.items()}
        normalised = True

    rendered = {mid: str(w) for mid, w in as_given.items()}
    return mode, rendered, applied, normalised


# --------------------------------------------------------------------------
# allocation
# --------------------------------------------------------------------------

def _allocate(total, applied):
    """Split `total` by exact weights. Returns {member_id: (share, residual)}."""
    total_cents = int((total * 100).to_integral_exact())

    floors = {}
    for member_id, weight in applied.items():
        exact = Fraction(total_cents) * weight
        floors[member_id] = exact.numerator // exact.denominator

    residual = total_cents - sum(floors.values())
    if not 0 <= residual < max(len(applied), 1):
        raise AssertionError(
            f"residual {residual} outside [0, {len(applied)}); weights do not "
            f"sum to 1"
        )

    order = sorted(applied, key=lambda mid: (-applied[mid], mid))
    absorbed = {mid: 0 for mid in applied}
    for member_id in order[:residual]:
        floors[member_id] += 1
        absorbed[member_id] = 1

    return {
        mid: (Decimal(cents) * CENT, absorbed[mid])
        for mid, cents in floors.items()
    }


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset of a result that the audit hash certifies."""
    return {
        "as_of": result["as_of"],
        "currency": result["currency"],
        "total": result["total"],
        "expenses_counted": result["expenses_counted"],
        "expenses_digest": result["expenses_digest"],
        "split_rule": result["split_rule"],
        "residual_rule": result["residual_rule"],
        "residual_cents": result["residual_cents"],
        "splits": result["splits"],
    }


def audit_hash_of(result):
    """Hash inputs *and* computed shares, so it cannot certify a contradiction.

    Excludes tool_run_id and issued_at, so replaying the same input reproduces
    the same hash. Recomputable by anyone holding only the output.
    """
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _expenses_digest(expenses):
    rows = [
        {"id": e["id"], "amount": str(e["amount"]),
         "paid_by": e["paid_by"], "date": e["date"]}
        for e in sorted(expenses, key=lambda e: e["id"])
    ]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def split_expenses(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")

    as_of = _resolve_as_of(document)
    member_ids = _resolve_members(document)
    expenses = _resolve_expenses(document, member_ids, as_of)
    mode, weights_as_given, applied, normalised = _resolve_weights(
        document, member_ids
    )

    total = sum((e["amount"] for e in expenses), Decimal("0")).quantize(CENT)
    paid = {mid: Decimal("0") for mid in member_ids}
    for expense in expenses:
        paid[expense["paid_by"]] += expense["amount"]

    allocation = _allocate(total, applied)
    LOG.info("split %s across %d member(s) in mode %s; %d expense(s)",
             total, len(member_ids), mode, len(expenses))

    splits = []
    for member_id in member_ids:
        share, absorbed = allocation[member_id]
        splits.append({
            "member_id": member_id,
            "weight_applied": _render_weight(applied[member_id]),
            "share": str(share.quantize(CENT)),
            "paid": str(paid[member_id].quantize(CENT)),
            "balance": str((paid[member_id] - share).quantize(CENT)),
            "residual_cents_absorbed": absorbed,
        })

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "currency": "SGD",
        "total": str(total),
        "expenses_counted": len(expenses),
        "expenses_digest": _expenses_digest(expenses),
        "split_rule": {
            "mode": mode,
            "weights_as_given": weights_as_given,
            "weights_applied": {mid: _render_weight(w)
                                for mid, w in applied.items()},
            "normalised": normalised,
        },
        "residual_rule": RESIDUAL_RULE,
        "residual_cents": sum(s["residual_cents_absorbed"] for s in splits),
        "splits": splits,
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
        result = split_expenses(_read_input(args.input))
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
