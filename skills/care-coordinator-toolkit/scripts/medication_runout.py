#!/usr/bin/env python3
"""Forecast when each medication runs out, from supply on hand and dose rate.

Usage:
    python3 medication_runout.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input (MedicationRecord, see docs/CONTRACTS.md):
    {
      "as_of": "2026-08-03",              # optional, defaults to SG today
      "default_lead_time_days": 7,        # required, integer >= 0
      "medications": [
        {"id": "metformin-500",
         "name": "Metformin 500mg",
         "form": "tablet",
         "form_plural": "tablets",        # optional, defaults to form + "s"
         "quantity_on_hand": "15",
         "counted_on": "2026-08-03",      # optional, defaults to as_of
         "count_basis": "doses_on_count_day_pending",   # required, no default
         "schedule": {"mode": "fixed_daily",
                      "units_per_dose": "1", "doses_per_day": 2},
         "lead_time_days": 5},            # optional, overrides the default
        {"id": "paracetamol-500", "name": "Paracetamol 500mg",
         "form": "tablet", "quantity_on_hand": "12",
         "schedule": {"mode": "prn"}}     # as-needed: never forecast
      ]
    }

This script is pure arithmetic. It reports a date and a supply count and hands
off. It makes no clinical judgement of any kind: no dose suggestions, no
interpretation of what running out means, no urgency language.

Three defects from docs/AUDIT-FINDINGS.md section 2 are structurally excluded:

  * Supply is floored, never rounded. `int(round(...))` made 15 and 17 tablets
    at 2/day share a run-out date and rounded 7.5 days up to 8. Division runs
    on exact Fractions so the floor boundary is never decided by accumulated
    binary error.
  * Every date and every status derives from one `as_of`, resolved once at the
    top. The wall clock is read only for `issued_at`, which the audit hash
    excludes, so any run replays exactly.
  * A bare day count cannot say whether the count day's doses were already
    taken, so `count_basis` is a required input with no default, and every
    summary states the convention in words.

PRN medications have no fixed daily rate. Forecasting one would be clinical
judgement in arithmetic clothing, so they are excluded from `forecast` and
listed in `not_forecast` with their quantity and no dates.

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

MODES = ("fixed_daily", "prn")
COUNT_BASES = ("doses_on_count_day_taken", "doses_on_count_day_pending")
STATUSES = ("ok", "order_now", "order_overdue", "no_supply")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

FLOOR_RULE = (
    "days_of_supply = floor(quantity_on_hand / units_per_day), computed on "
    "exact fractions; supply is never rounded up. leftover_units is what "
    "remains beyond the last full day and buys no further full day"
)
ORDER_BY_RULE = (
    "order_by = runs_out_on minus lead_time_days, where runs_out_on is the "
    "first day the supply on hand does not fully cover"
)
DAYS_REMAINING_RULE = (
    "full_dose_days_remaining counts days from as_of (or from "
    "coverage_starts_on, whichever is later) through last_full_dose_day "
    "inclusive, and is 0 once the supply is exhausted"
)
COUNT_BASIS_RULE = {
    "doses_on_count_day_taken":
        "quantity_on_hand was counted after that day's doses were taken, so "
        "coverage_starts_on is the day after counted_on",
    "doses_on_count_day_pending":
        "quantity_on_hand was counted before that day's doses were taken, so "
        "coverage_starts_on is counted_on itself",
}

LOG = logging.getLogger("medication_runout")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

def _to_decimal(value, where, what):
    """Exact Decimal, or raise. Floats are refused, not coerced."""
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected {what}, got a boolean")
    if isinstance(value, float):
        raise InvalidInput(
            f"{where}: {what} {value!r} is a binary float and cannot be "
            f"represented exactly; pass it as a JSON number parsed with "
            f"parse_float=Decimal, or as a string"
        )
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidInput(f"{where}: {value!r} is not a number")
    else:
        raise InvalidInput(
            f"{where}: expected a number, got {type(value).__name__}"
        )
    if not number.is_finite():
        raise InvalidInput(f"{where}: {what} {value!r} is not finite")
    return number


def _to_quantity(value, where):
    number = _to_decimal(value, where, "a quantity")
    if number < 0:
        raise InvalidInput(f"{where}: quantity {number} is negative")
    return number


def _to_rate(value, where):
    number = _to_decimal(value, where, "a rate")
    if number <= 0:
        raise InvalidInput(f"{where}: {number} must be greater than zero")
    return number


def _to_whole_days(value, where):
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected a whole number of days")
    if isinstance(value, int):
        days = value
    else:
        number = _to_decimal(value, where, "a number of days")
        if number != number.to_integral_value():
            raise InvalidInput(
                f"{where}: {number} is not a whole number of days"
            )
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


def _render_exact(frac):
    """Exact rendering of a Fraction: decimal if it terminates, else n/d."""
    stripped = frac.denominator
    for prime in (2, 5):
        while stripped % prime == 0:
            stripped //= prime
    if stripped != 1:
        return f"{frac.numerator}/{frac.denominator}"
    with localcontext() as ctx:
        ctx.prec = 100
        text = str(Decimal(frac.numerator) / Decimal(frac.denominator))
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _human_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _units(quantity, med):
    """'1 tablet' / '15 tablets'. Takes a Fraction or a Decimal."""
    return f"{_render_exact(Fraction(quantity))} " + (
        med["form"] if quantity == 1 else med["form_plural"]
    )


def _days(count):
    return f"{count} " + ("day" if count == 1 else "days")


def _reject_unused(entry, where, fields, because):
    for field in fields:
        if field in entry:
            raise InvalidInput(
                f"{where}: {field!r} is not used {because}; remove it rather "
                f"than leave a value that looks like it takes effect"
            )


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


def _resolve_default_lead_time(document):
    if "default_lead_time_days" not in document:
        raise InvalidInput(
            "default_lead_time_days is required. There is no safe hardcoded "
            "assumption about how long a repeat prescription takes to arrive, "
            "so the caller must state it"
        )
    return _to_whole_days(
        document["default_lead_time_days"], "default_lead_time_days"
    )


def _resolve_schedule(entry, where):
    schedule = entry.get("schedule")
    if not isinstance(schedule, dict):
        raise InvalidInput(f"{where}: 'schedule' is required and must be an object")
    mode = schedule.get("mode")
    if mode not in MODES:
        raise InvalidInput(
            f"{where}: schedule.mode {mode!r} is not one of {', '.join(MODES)}"
        )
    return schedule, mode


def _resolve_medications(document, as_of, default_lead_time):
    # Required key, not defaulted to empty: a typo'd key would otherwise
    # forecast nothing, exit 0, and look like a household with no medication.
    if "medications" not in document:
        raise InvalidInput("medications is required (use [] for none)")
    medications = document["medications"]
    if not isinstance(medications, list):
        raise InvalidInput("medications must be a list")

    resolved = []
    seen = set()
    for index, entry in enumerate(medications):
        where = f"medications[{index}]"
        if not isinstance(entry, dict):
            raise InvalidInput(f"{where} must be an object")

        med_id = _to_text(entry.get("id"), f"{where}.id")
        if med_id in seen:
            raise InvalidInput(f"{where}: duplicate medication id {med_id!r}")
        seen.add(med_id)

        name = _to_text(entry.get("name"), f"{where}.name")
        form = _to_text(entry.get("form"), f"{where}.form")
        form_plural = (
            _to_text(entry["form_plural"], f"{where}.form_plural")
            if entry.get("form_plural") is not None else form + "s"
        )
        quantity = _to_quantity(
            entry.get("quantity_on_hand"), f"{where}.quantity_on_hand"
        )

        schedule, mode = _resolve_schedule(entry, where)

        common = {
            "id": med_id, "name": name, "form": form,
            "form_plural": form_plural, "quantity_on_hand": quantity,
            "mode": mode,
        }

        if mode == "prn":
            # Anything that only makes sense for a forecast must be refused
            # here, not silently dropped: a caregiver who supplies a lead time
            # expects an order-by date and would never get one.
            _reject_unused(
                entry, where, ("counted_on", "count_basis", "lead_time_days"),
                "for a prn medication, which is never forecast",
            )
            _reject_unused(
                schedule, f"{where}.schedule",
                ("units_per_dose", "doses_per_day"),
                "for a prn medication, which has no fixed daily rate",
            )
            resolved.append(common)
            continue

        if "count_basis" not in entry:
            raise InvalidInput(
                f"{where}: 'count_basis' is required and has no default. "
                f"Whether the count day's doses were already taken shifts "
                f"every run-out date by one day. Use one of "
                f"{', '.join(COUNT_BASES)}"
            )
        count_basis = entry["count_basis"]
        if count_basis not in COUNT_BASES:
            raise InvalidInput(
                f"{where}: count_basis {count_basis!r} is not one of "
                f"{', '.join(COUNT_BASES)}"
            )

        counted_on = as_of
        if entry.get("counted_on") is not None:
            counted_on = _to_date(entry["counted_on"], f"{where}.counted_on")
            if counted_on > as_of:
                raise InvalidInput(
                    f"{where}: counted_on {counted_on.isoformat()} is after "
                    f"as_of {as_of.isoformat()}"
                )

        if "units_per_dose" not in schedule:
            raise InvalidInput(f"{where}.schedule has no 'units_per_dose'")
        if "doses_per_day" not in schedule:
            raise InvalidInput(f"{where}.schedule has no 'doses_per_day'")
        units_per_dose = _to_rate(
            schedule["units_per_dose"], f"{where}.schedule.units_per_dose"
        )
        doses_per_day = _to_rate(
            schedule["doses_per_day"], f"{where}.schedule.doses_per_day"
        )

        if entry.get("lead_time_days") is not None:
            lead_time = _to_whole_days(
                entry["lead_time_days"], f"{where}.lead_time_days"
            )
            lead_time_source = "medication"
        else:
            lead_time = default_lead_time
            lead_time_source = "default"

        common.update({
            "counted_on": counted_on,
            "count_basis": count_basis,
            "units_per_dose": units_per_dose,
            "doses_per_day": doses_per_day,
            "lead_time_days": lead_time,
            "lead_time_source": lead_time_source,
        })
        resolved.append(common)
    return resolved


# --------------------------------------------------------------------------
# forecasting — pure arithmetic
# --------------------------------------------------------------------------

def _forecast_one(med, as_of):
    units_per_day = Fraction(med["units_per_dose"]) * Fraction(med["doses_per_day"])
    quantity = Fraction(med["quantity_on_hand"])

    exact_days = quantity / units_per_day
    days_of_supply = exact_days.numerator // exact_days.denominator
    leftover = quantity - days_of_supply * units_per_day

    if med["count_basis"] == "doses_on_count_day_taken":
        coverage_starts_on = med["counted_on"] + timedelta(days=1)
    else:
        coverage_starts_on = med["counted_on"]

    # The supply covers coverage_starts_on .. last_full_dose_day inclusive.
    # With no supply at all, last_full_dose_day sits one day before coverage
    # starts and runs_out_on lands on the start day itself.
    last_full_dose_day = coverage_starts_on + timedelta(days=days_of_supply - 1)
    runs_out_on = coverage_starts_on + timedelta(days=days_of_supply)
    order_by = runs_out_on - timedelta(days=med["lead_time_days"])

    counted_from = max(as_of, coverage_starts_on)
    remaining = (last_full_dose_day - counted_from).days + 1
    full_dose_days_remaining = max(0, remaining)

    if runs_out_on <= as_of:
        status = "no_supply"
    elif order_by < as_of:
        status = "order_overdue"
    elif order_by == as_of:
        status = "order_now"
    else:
        status = "ok"

    return {
        "id": med["id"],
        "name": med["name"],
        "form": med["form"],
        "quantity_on_hand": str(med["quantity_on_hand"]),
        "counted_on": med["counted_on"].isoformat(),
        "count_basis": med["count_basis"],
        "units_per_day": _render_exact(units_per_day),
        "coverage_starts_on": coverage_starts_on.isoformat(),
        "days_of_supply": days_of_supply,
        "leftover_units": _render_exact(leftover),
        "last_full_dose_day": last_full_dose_day.isoformat(),
        "runs_out_on": runs_out_on.isoformat(),
        "full_dose_days_remaining": full_dose_days_remaining,
        "lead_time_days": med["lead_time_days"],
        "lead_time_source": med["lead_time_source"],
        "order_by": order_by.isoformat(),
        "status": status,
        "summary": _summarise(med, units_per_day, leftover, days_of_supply,
                              last_full_dose_day, runs_out_on, order_by,
                              status),
    }


def _summarise(med, units_per_day, leftover, days_of_supply,
               last_full_dose_day, runs_out_on, order_by, status):
    """Plain sentences that state the boundary convention rather than imply it.

    Facts only. What to do about them is not this script's business.
    """
    basis = (
        "had already been taken"
        if med["count_basis"] == "doses_on_count_day_taken"
        else "had not yet been taken"
    )
    parts = [
        f"{med['name']}: {_units(med['quantity_on_hand'], med)} counted on "
        f"{_human_date(med['counted_on'])}, on the basis that that day's "
        f"doses {basis}."
    ]
    rate = f"At {_units(units_per_day, med)} a day"
    if status == "no_supply":
        parts.append(
            f"{rate}, that supply covered {_days(days_of_supply)} in full and "
            f"no full days of doses remain as of {_human_date(runs_out_on)}."
        )
    else:
        parts.append(
            f"{rate}, that is {_days(days_of_supply)} of doses in full: the "
            f"last full day is {_human_date(last_full_dose_day)}, and "
            f"{_human_date(runs_out_on)} is the first day not covered."
        )
    if leftover > 0:
        parts.append(
            f"{_units(leftover, med)} left over beyond the last full day."
        )
    parts.append(
        f"Order by {_human_date(order_by)}, allowing "
        f"{_days(med['lead_time_days'])} lead time."
    )
    return " ".join(parts)


def _not_forecast_one(med):
    return {
        "id": med["id"],
        "name": med["name"],
        "form": med["form"],
        "quantity_on_hand": str(med["quantity_on_hand"]),
        "reason": "prn_no_fixed_rate",
        "summary": (
            f"{med['name']}: {_units(med['quantity_on_hand'], med)} on hand, "
            f"taken as needed. With no fixed daily rate there is no run-out "
            f"date to calculate, so none is forecast."
        ),
    }


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset of a result that the audit hash certifies."""
    return {
        "as_of": result["as_of"],
        "default_lead_time_days": result["default_lead_time_days"],
        "medications_counted": result["medications_counted"],
        "medications_digest": result["medications_digest"],
        "conventions": result["conventions"],
        "forecast": result["forecast"],
        "not_forecast": result["not_forecast"],
    }


def audit_hash_of(result):
    """Hash resolved inputs *and* computed dates, so it cannot certify a
    contradiction.

    Excludes tool_run_id and issued_at, so replaying the same input reproduces
    the same hash. Recomputable by anyone holding only the output.
    """
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _medications_digest(medications):
    rows = []
    for med in sorted(medications, key=lambda m: m["id"]):
        row = {
            "id": med["id"], "name": med["name"], "form": med["form"],
            "form_plural": med["form_plural"], "mode": med["mode"],
            "quantity_on_hand": str(med["quantity_on_hand"]),
        }
        if med["mode"] == "fixed_daily":
            row.update({
                "counted_on": med["counted_on"].isoformat(),
                "count_basis": med["count_basis"],
                "units_per_dose": str(med["units_per_dose"]),
                "doses_per_day": str(med["doses_per_day"]),
                "lead_time_days": med["lead_time_days"],
            })
        rows.append(row)
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def forecast_runout(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")

    as_of = _resolve_as_of(document)
    default_lead_time = _resolve_default_lead_time(document)
    medications = _resolve_medications(document, as_of, default_lead_time)

    forecast = [_forecast_one(m, as_of)
                for m in medications if m["mode"] == "fixed_daily"]
    not_forecast = [_not_forecast_one(m)
                    for m in medications if m["mode"] == "prn"]

    LOG.info("as_of %s: forecast %d medication(s), excluded %d as prn",
             as_of.isoformat(), len(forecast), len(not_forecast))
    for entry in forecast:
        LOG.info("%s: %s, last full day %s, order by %s",
                 entry["id"], entry["status"],
                 entry["last_full_dose_day"], entry["order_by"])

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "default_lead_time_days": default_lead_time,
        "medications_counted": len(medications),
        "medications_digest": _medications_digest(medications),
        "conventions": {
            "supply_rounding": FLOOR_RULE,
            "order_by": ORDER_BY_RULE,
            "days_remaining": DAYS_REMAINING_RULE,
            "count_basis": COUNT_BASIS_RULE,
            "statuses": list(STATUSES),
        },
        "forecast": forecast,
        "not_forecast": not_forecast,
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
        result = forecast_runout(_read_input(args.input))
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
