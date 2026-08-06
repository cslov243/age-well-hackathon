#!/usr/bin/env python3
"""Turn dates other scripts already computed into calendar events and an .ics.

Usage:
    python3 deadline_calendar.py --input <input.json> --ics <calendar.ics> \
        [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.
--ics is required: the calendar file is the deliverable, not a side effect.

Input:
    {
      "as_of": "2026-08-06",        # optional, defaults to SG today
      "horizon_days": 30,           # required: how far ahead to look
      "detail_level": "minimal",    # required: minimal | named
      "forecast": { ... a medication_runout.py result, verbatim ... },
      "claims":   { ... an insurance_claim_review.py result, verbatim ... }
    }

`forecast` and `claims` are **required keys even when there is nothing to pass**
— write `null` to say so explicitly. A key that is merely absent is
indistinguishable from a key that was misspelled, and a run that silently
scheduled nothing exits 0 looking exactly like a run that had nothing to
schedule.

`horizon_days` and `detail_level` have no defaults. How far ahead a household
wants to be reminded, and how much of an elderly person's business goes onto a
calendar other people can read, are a person's calls and not this script's.

**It computes no dates.** Every date is copied from `order_by` and `runs_out_on`
in the forecast, or from `deadlines[].due_on` in the claims review. There is no
date arithmetic here beyond one subtraction — `(date - as_of).days` — used to
decide whether something falls inside the horizon.

That subtraction is the whole point of the script's existence. Audit finding #3
records the old `deadline_window.py` testing `(due - remind_on).days <= 7`,
which compares the reminder window to itself and is therefore true for a
deadline 58 days away, forever. Proximity here is measured against `as_of` and
nothing else.

Three things it refuses to do:

  * **Trust a source it has not checked.** Each input's own `audit_hash` is
    recomputed with the function that wrote it, and a mismatch is refused —
    the same refusal `pharmacy_cart.py` applies to an edited forecast.
  * **Disclose by default.** A calendar is a shared surface. At
    `detail_level: "minimal"` no event names a medicine, a condition, an
    insurer or an amount; the title says a refill is due and the details stay
    in the family brief. `"named"` is a real disclosure and says so, in
    `disclosure`, so a line can be written to `shared_log.jsonl`.
  * **Drop a deadline quietly.** Every date the sources offer lands in either
    `events` or `omitted`, each with a reason in plain words.

Nothing here writes to a calendar. It writes a file a person imports.

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
import medication_runout  # noqa: E402

SG = timezone(timedelta(hours=8), name="+08:00")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

KNOWN_KEYS = ("as_of", "horizon_days", "detail_level", "forecast", "claims")

DETAIL_LEVELS = ("minimal", "named")

KINDS = ("medication_order_by", "medication_runs_out",
         "claim_submission", "claim_appeal")

OMISSION_REASONS = ("no_date", "already_passed", "beyond_horizon")

PRODID = "-//Care Navigator//deadline_calendar//EN"
UID_DOMAIN = "care-navigator"

# What the sources must contain to be the results they claim to be.
FORECAST_KEYS = ("as_of", "forecast", "not_forecast", "medications_digest",
                 "conventions", "audit_hash")
CLAIMS_KEYS = ("as_of", "claims", "claims_counted", "conventions",
               "audit_hash")

COPYING_RULE = (
    "every date is copied from the source that computed it — order_by and "
    "runs_out_on from the forecast, deadlines[].due_on from the claims review. "
    "This script computes no date, and a second implementation of the same "
    "arithmetic would be a second answer that eventually disagrees"
)
PROXIMITY_RULE = (
    "an event is scheduled when 0 <= (date - as_of).days <= horizon_days. "
    "Proximity is measured against as_of and never against the reminder window, "
    "which is the defect recorded as audit finding #3: comparing the window to "
    "itself made a deadline 58 days away read as due this week, every day"
)
DETAIL_RULE = (
    "at detail_level 'minimal' no event names a medicine, condition, insurer or "
    "amount; the calendar says something is due and the family brief says what. "
    "'named' puts her business on a surface other people can read, so it is "
    "recorded as a disclosure rather than treated as a formatting preference"
)
OMISSION_RULE = (
    "every date the sources offer lands in exactly one of events and omitted, "
    "each with a reason in plain words. A deadline already past is omitted "
    "rather than back-dated into a calendar, where it would never notify anyone"
)
UID_RULE = (
    "each event's uid is derived from the source audit_hash, the kind, the "
    "source id and the date, so re-running this on unchanged inputs produces "
    "the same uids and a second import updates the entries instead of "
    "duplicating them"
)
HANDOFF_RULE = (
    "nothing here is ordered, submitted, paid or written to anyone's calendar. "
    "This produces a file a person imports, and any calendar write beyond that "
    "is a separate action a person confirms one event at a time"
)

LOG = logging.getLogger("deadline_calendar")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD)")


def _to_positive_whole(value, where):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInput(f"{where}: expected a whole number of days")
    if value < 1:
        raise InvalidInput(
            f"{where}: {value} is not a horizon. A calendar that looks no days "
            f"ahead has nothing to put in it")
    return value


def _reject_unknown(mapping, known, where):
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        raise InvalidInput(
            f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"A misspelled key takes no effect and says nothing, which looks "
            f"exactly like an answer. Known keys: {', '.join(known)}")


def _human_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _count(number, noun, plural=None):
    return f"{number} " + (noun if number == 1 else (plural or noun + "s"))


# --------------------------------------------------------------------------
# the sources these events are copied from
# --------------------------------------------------------------------------

def _resolve_source(document, key, required_keys, hash_of, produced_by, as_of):
    """Take a source result as given, and refuse one that has been edited."""
    if key not in document:
        raise InvalidInput(
            f"{key} is required, even when there is none — pass null to say so "
            f"explicitly. An absent key and a misspelled key look identical "
            f"from here, and one of them means a whole set of deadlines was "
            f"silently scheduled into nothing")
    source = document[key]
    if source is None:
        return None
    if not isinstance(source, dict):
        raise InvalidInput(
            f"{key} must be a {produced_by} result object passed through "
            f"verbatim, or null")
    for name in required_keys:
        if name not in source:
            raise InvalidInput(
                f"{key} has no {name!r}: this does not look like a "
                f"{produced_by} result. This script copies dates out of one "
                f"rather than computing them, and there is nothing here to "
                f"copy")

    stored = source["audit_hash"]
    recomputed = hash_of(source)
    if recomputed != stored:
        raise InvalidInput(
            f"{key} audit_hash does not match its contents (stored {stored}, "
            f"recomputed {recomputed}). It has been edited since it was "
            f"produced — refusing to put its dates in anyone's calendar")

    source_as_of = _to_date(source["as_of"], f"{key}.as_of")
    if source_as_of > as_of:
        raise InvalidInput(
            f"{key} is dated {source_as_of.isoformat()}, which is in the "
            f"future relative to as_of {as_of.isoformat()}. One of the two is "
            f"wrong and this cannot tell which")

    return {
        "result": source,
        "as_of": source_as_of,
        "age_days": (as_of - source_as_of).days,
    }


def _source_record(resolved, tool):
    if resolved is None:
        return None
    return {
        "tool": tool,
        "tool_run_id": resolved["result"].get("tool_run_id"),
        "audit_hash": resolved["result"]["audit_hash"],
        "as_of": resolved["as_of"].isoformat(),
        "age_days": resolved["age_days"],
    }


# --------------------------------------------------------------------------
# titles and bodies — the only place detail_level has any effect
# --------------------------------------------------------------------------

SUFFIX = " — Care Navigator"

MINIMAL_TITLES = {
    "medication_order_by": "Medication refill due",
    "medication_runs_out": "Medication runs out",
    "claim_submission": "Insurance paperwork due",
    "claim_appeal": "Insurance appeal window closes",
}

DISCLOSES = {
    "medication_order_by": ["medication_name"],
    "medication_runs_out": ["medication_name"],
    "claim_submission": ["insurer", "claim_reference"],
    "claim_appeal": ["insurer", "claim_reference"],
}


def _title(kind, detail_level, name):
    if detail_level == "minimal":
        return MINIMAL_TITLES[kind] + SUFFIX
    if kind == "medication_order_by":
        return f"Order {name}" + SUFFIX
    if kind == "medication_runs_out":
        return f"{name} runs out" + SUFFIX
    if kind == "claim_submission":
        return f"{name} — submission deadline" + SUFFIX
    return f"{name} — appeal deadline" + SUFFIX


def _body(detail_level, source_record):
    parts = []
    if detail_level == "minimal":
        parts.append(
            "Prepared by Care Navigator. This entry deliberately does not say "
            "what it is about: a calendar is read by everyone it is shared "
            "with. The details are in the family brief.")
    else:
        parts.append(
            "Prepared by Care Navigator. The full details are in the family "
            "brief.")
    parts.append(
        "Nothing has been ordered, submitted or paid, and nothing will be "
        "until a person does it.")
    parts.append(
        f"Source: {source_record['tool']} run {source_record['tool_run_id']}, "
        f"audit {source_record['audit_hash']}, as at "
        f"{_human_date(date.fromisoformat(source_record['as_of']))}.")
    return " ".join(parts)


def _uid(source_record, kind, source_id, starts_on):
    blob = "|".join([source_record["audit_hash"], kind, source_id, starts_on])
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return f"{digest}@{UID_DOMAIN}"


def _event(kind, source_id, starts_on, name, detail_level, source_record,
           as_of):
    return {
        "uid": _uid(source_record, kind, source_id, starts_on.isoformat()),
        "kind": kind,
        "starts_on": starts_on.isoformat(),
        "days_away": (starts_on - as_of).days,
        "title": _title(kind, detail_level, name),
        "body": _body(detail_level, source_record),
        "source_tool": source_record["tool"],
        "source_id": source_id,
        "source_tool_run_id": source_record["tool_run_id"],
        "source_audit_hash": source_record["audit_hash"],
        "discloses": DISCLOSES[kind] if detail_level == "named" else [],
    }


def _omitted(kind, source_id, starts_on, reason, detail):
    return {
        "kind": kind,
        "source_id": source_id,
        "starts_on": starts_on.isoformat() if starts_on else None,
        "reason": reason,
        "detail": detail,
    }


# --------------------------------------------------------------------------
# selection — the one subtraction in the script
# --------------------------------------------------------------------------

def _place(kind, source_id, raw_date, name, detail_level, source_record,
           as_of, horizon_days, events, omitted, where):
    """Put one candidate date in exactly one of events and omitted."""
    if raw_date is None:
        omitted.append(_omitted(
            kind, source_id, None, "no_date",
            "the source has no date for this — it could not be quoted from "
            "the document, so there is nothing to put in a calendar"))
        return
    when = _to_date(raw_date, where)
    days_away = (when - as_of).days
    if days_away < 0:
        omitted.append(_omitted(
            kind, source_id, when, "already_passed",
            f"{_human_date(when)} is {_count(-days_away, 'day')} ago. A "
            f"back-dated entry never notifies anyone; this needs a person "
            f"today, not a calendar"))
        return
    if days_away > horizon_days:
        omitted.append(_omitted(
            kind, source_id, when, "beyond_horizon",
            f"{_human_date(when)} is {_count(days_away, 'day')} away, past "
            f"the {_count(horizon_days, 'day')} horizon asked for"))
        return
    events.append(_event(kind, source_id, when, name, detail_level,
                         source_record, as_of))


def _collect_medication(resolved, record, detail_level, as_of, horizon_days,
                        events, omitted):
    if resolved is None:
        return
    for index, entry in enumerate(resolved["result"]["forecast"]):
        where = f"forecast.forecast[{index}]"
        name = entry.get("name") or entry["id"]
        _place("medication_order_by", entry["id"], entry.get("order_by"), name,
               detail_level, record, as_of, horizon_days, events, omitted,
               f"{where}.order_by")
        _place("medication_runs_out", entry["id"], entry.get("runs_out_on"),
               name, detail_level, record, as_of, horizon_days, events,
               omitted, f"{where}.runs_out_on")
    # not_forecast is the prn list: no rate, so no run-out date exists to copy.
    # It is not a deadline that was dropped, so it is not an omission either.


def _collect_claims(resolved, record, detail_level, as_of, horizon_days,
                    events, omitted):
    if resolved is None:
        return
    for index, claim in enumerate(resolved["result"]["claims"]):
        insurer = claim.get("insurer") or "Insurance"
        name = f"{insurer} claim {claim['id']}"
        for position, deadline in enumerate(claim.get("deadlines", [])):
            kind = ("claim_submission" if deadline["kind"] == "submission"
                    else "claim_appeal")
            _place(kind, claim["id"], deadline.get("due_on"), name,
                   detail_level, record, as_of, horizon_days, events, omitted,
                   f"claims.claims[{index}].deadlines[{position}].due_on")


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset of a result that the audit hash certifies.

    The .ics path is not in here: the same calendar written to two places is
    the same calendar. A source's tool_run_id identifies one *run* of it and is
    excluded for the same reason this script's own is.
    """
    canonical = {key: result[key] for key in (
        "as_of", "horizon_days", "detail_level", "conventions", "events",
        "omitted", "counts", "disclosure", "summary")}
    canonical["sources"] = {
        name: (None if source is None
               else {k: v for k, v in source.items() if k != "tool_run_id"})
        for name, source in result["sources"].items()}
    return canonical


def audit_hash_of(result):
    """Hash resolved inputs *and* the computed events, excluding tool_run_id
    and issued_at so replaying the same input reproduces the same hash."""
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _calendar_summary(events, omitted, as_of, horizon_days, detail_level):
    parts = []
    if events:
        first = min(event["starts_on"] for event in events)
        parts.append(
            f"{_count(len(events), 'reminder')} for the "
            f"{_count(horizon_days, 'day')} from {_human_date(as_of)}, the "
            f"first on {_human_date(date.fromisoformat(first))}.")
    else:
        parts.append(
            f"Nothing falls due in the {_count(horizon_days, 'day')} from "
            f"{_human_date(as_of)}, so the calendar file is empty.")

    if detail_level == "minimal":
        parts.append(
            "No entry names a medicine, a condition or an insurer: a shared "
            "calendar is read by everyone it is shared with.")
    else:
        parts.append(
            "Entries name what each reminder is about, which discloses it to "
            "everyone the calendar is shared with. Log it.")

    passed = [row for row in omitted if row["reason"] == "already_passed"]
    if passed:
        parts.append(
            f"{_count(len(passed), 'deadline')} already passed and "
            f"{'is' if len(passed) == 1 else 'are'} not in the file — a "
            f"back-dated entry notifies nobody. Someone needs to look at "
            f"{'that one' if len(passed) == 1 else 'those'} today.")

    unknown = [row for row in omitted if row["reason"] == "no_date"]
    if unknown:
        parts.append(
            f"{_count(len(unknown), 'deadline')} had no date to copy, so "
            f"{'it is' if len(unknown) == 1 else 'they are'} left out rather "
            f"than guessed at.")

    parts.append(
        "Import the file yourself. Nothing has been written to anyone's "
        "calendar, ordered, submitted or paid.")
    return " ".join(parts)


# --------------------------------------------------------------------------
# the .ics itself
# --------------------------------------------------------------------------

def _escape(text):
    return (text.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n"))


def _fold(line):
    """RFC 5545 folding: no physical line over 75 octets, never mid-character."""
    physical = []
    current = b""
    for character in line:
        encoded = character.encode("utf-8")
        if len(current) + len(encoded) > 75:
            physical.append(current.decode("utf-8"))
            current = b" " + encoded
        else:
            current += encoded
    physical.append(current.decode("utf-8"))
    return "\r\n".join(physical)


def _stamp(issued_at):
    moment = datetime.fromisoformat(issued_at).astimezone(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def render_ics(result):
    """A calendar file a person imports. All-day events, one per reminder."""
    stamp = _stamp(result["issued_at"])
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in result["events"]:
        starts = date.fromisoformat(event["starts_on"])
        # DTEND is exclusive for an all-day event: the day after the deadline.
        ends = starts + timedelta(days=1)
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{starts.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{ends.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(event['title'])}",
            f"DESCRIPTION:{_escape(event['body'])}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_calendar(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")
    _reject_unknown(document, KNOWN_KEYS, "input")

    if document.get("as_of") is None:
        as_of = datetime.now(SG).date()
        LOG.info("as_of absent; resolved once to SG today %s", as_of.isoformat())
    else:
        as_of = _to_date(document["as_of"], "as_of")

    if "horizon_days" not in document:
        raise InvalidInput(
            "horizon_days is required and has no default. How far ahead a "
            "household wants to be reminded is not something this script may "
            "pick on its behalf")
    horizon_days = _to_positive_whole(document["horizon_days"], "horizon_days")

    if "detail_level" not in document:
        raise InvalidInput(
            "detail_level is required and has no default. How much of her "
            "business goes onto a calendar other people can read is her call, "
            "and defaulting it would make that call for her")
    detail_level = document["detail_level"]
    if detail_level not in DETAIL_LEVELS:
        raise InvalidInput(
            f"detail_level {detail_level!r} is not one of "
            f"{', '.join(DETAIL_LEVELS)}")

    forecast = _resolve_source(
        document, "forecast", FORECAST_KEYS, medication_runout.audit_hash_of,
        "medication_runout.py", as_of)
    claims = _resolve_source(
        document, "claims", CLAIMS_KEYS, insurance_claim_review.audit_hash_of,
        "insurance_claim_review.py", as_of)

    sources = {
        "forecast": _source_record(forecast, "medication_runout.py"),
        "claims": _source_record(claims, "insurance_claim_review.py"),
    }

    events, omitted = [], []
    _collect_medication(forecast, sources["forecast"], detail_level, as_of,
                        horizon_days, events, omitted)
    _collect_claims(claims, sources["claims"], detail_level, as_of,
                    horizon_days, events, omitted)

    events.sort(key=lambda event: (event["starts_on"], event["kind"],
                                   event["source_id"]))
    omitted.sort(key=lambda row: (row["starts_on"] or "9999-12-31",
                                  row["kind"], row["source_id"]))

    disclosed = sorted({item for event in events for item in event["discloses"]})

    LOG.info("as_of %s, horizon %s, detail %s: %s scheduled, %s omitted",
             as_of.isoformat(), _count(horizon_days, "day"), detail_level,
             _count(len(events), "event"), _count(len(omitted), "date"))
    for row in omitted:
        LOG.info("omitted %s for %s: %s", row["kind"], row["source_id"],
                 row["reason"])

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "detail_level": detail_level,
        "sources": sources,
        "conventions": {
            "copying": COPYING_RULE,
            "proximity": PROXIMITY_RULE,
            "detail": DETAIL_RULE,
            "omissions": OMISSION_RULE,
            "uid": UID_RULE,
            "handoff": HANDOFF_RULE,
            "detail_levels": list(DETAIL_LEVELS),
            "kinds": list(KINDS),
            "omission_reasons": list(OMISSION_REASONS),
        },
        "events": events,
        "omitted": omitted,
        "counts": {
            "dates_considered": len(events) + len(omitted),
            "events": len(events),
            "omitted": len(omitted),
        },
        "disclosure": {
            "required": bool(disclosed),
            "discloses": disclosed,
            "note": (
                "these entries name her business on a calendar other people "
                "can read; append a line to out/senior/shared_log.jsonl saying "
                "what went where and who can see it"
                if disclosed else
                "no entry names a medicine, a condition, an insurer or an "
                "amount, so importing this file discloses nothing"),
        },
    }
    result["summary"] = _calendar_summary(events, omitted, as_of, horizon_days,
                                          detail_level)
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
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"{source}: not valid JSON ({exc})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=None,
                        help="input JSON file; stdin if omitted")
    parser.add_argument("--output", type=Path, default=None,
                        help="output JSON file; stdout if omitted")
    parser.add_argument("--ics", type=Path, required=True,
                        help="where to write the calendar file a person imports")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        result = build_calendar(_read_input(args.input))
        args.ics.write_text(render_ics(result), encoding="utf-8")
    except InvalidInput as exc:
        LOG.error("%s", exc)
        return 2

    result["written_to"] = str(args.ics)
    LOG.info("wrote %s", args.ics)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is None:
        sys.stdout.write(payload + "\n")
    else:
        args.output.write_text(payload + "\n", encoding="utf-8")
        LOG.info("wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
