#!/usr/bin/env python3
"""Draft a pharmacy cart from a run-out forecast. A person reviews it and pays.

Usage:
    python3 pharmacy_cart.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input:
    {
      "as_of": "2026-08-05",          # optional, defaults to SG today
      "forecast": { ... a medication_runout.py result, verbatim ... },
      "cover_days": 30,               # required: how many days to buy for
      "purchase": {                   # required; {} is legal
        "metformin-500": {
          "supply_channel": "general_sale",   # required within an entry
          "pack_size": 30,                    # optional
          "pack_price": "4.50",               # or unit_price, never both
          "currency": "SGD",                  # required with a price
          "source": "caregiver, 4 Aug 2026",  # required with a price
          "form_plural": "tablets"            # optional
        }
      },
      "pharmacy": {"name": "...", "deep_link": "https://..."}   # optional
    }

This script prepares. It does not buy. There is no code path that calls a
shop, authorises a payment, stores a card or holds any standing authority to
spend, and `requires_human_checkout` is a constant that no input can change.
An agent with the ability to spend an elderly person's money is the precise
harm this product is positioned against, so the boundary is structural rather
than a rule written down somewhere and hoped for.

Four things it refuses to do:

  * **Buy something that needed a prescription.** `supply_channel` is read
    from the caller, and an entry that does not state one is *unknown*, not
    general sale. Unknown never enters the cart. Defaulting that field is the
    single edit that would break this script's whole purpose.
  * **Invent a price.** A price exists only if the caller supplied one, with a
    currency and a stated source. One unpriced line suppresses the cart total
    entirely — not a partial sum, not an estimate. A confident wrong total is
    worse than no total, and the same conflation once turned SGD 1,220.00 into
    SGD 4,320.00 elsewhere in this repo.
  * **Recompute the forecast.** Dates and rates are copied from the
    `medication_runout.py` result. A second implementation of the same
    arithmetic is a second answer, and the two disagree eventually.
  * **Trust a forecast it has not checked.** The forecast's own `audit_hash`
    is recomputed using `medication_runout.audit_hash_of` — the same function
    that wrote it — and a mismatch is refused outright.

No network access. No filesystem access beyond the two paths passed in.
"""

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import medication_runout  # noqa: E402

SG = timezone(timedelta(hours=8), name="+08:00")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

REQUIRES_HUMAN_CHECKOUT = True

SUPPLY_CHANNELS = ("general_sale", "pharmacist_only", "prescription_only")

# Which statuses mean "buy this now". Read off the forecast, never recomputed.
DUE_STATUSES = ("order_now", "order_overdue", "no_supply")

FORECAST_STALE_AFTER_DAYS = 7

CENTS = Decimal("0.01")

KNOWN_KEYS = ("as_of", "forecast", "cover_days", "purchase", "pharmacy")
KNOWN_PURCHASE_KEYS = ("supply_channel", "pack_size", "pack_price",
                       "unit_price", "currency", "source", "form_plural")
KNOWN_PHARMACY_KEYS = ("name", "deep_link")

# Query-parameter shapes that carry a secret. A cart draft ships inside a
# family artifact and, via the plugin, onto a marketplace; no secrets in the
# payload is a hard constraint, so a link wearing one is refused rather than
# copied along.
CREDENTIAL_MARKERS = (
    "token", "signature", "password", "passwd", "secret", "otp=",
    "session", "apikey", "api_key", "access_key", "accesskey",
    "auth=", "authorization", "x-amz-", "credential",
)

CHECKOUT_RULE = (
    "this is a draft. Nothing is ordered, nothing is reserved and nothing is "
    "paid for. A person opens it, checks every line against the boxes in the "
    "cupboard, and pays for it themselves"
)
SUPPLY_CHANNEL_RULE = (
    "a medicine enters the cart only if the caller stated supply_channel "
    "general_sale for it. An entry with no supply_channel recorded is unknown, "
    "and unknown is excluded — never assumed to be something a person can buy "
    "off a shelf"
)
QUANTITY_RULE = (
    "units_needed = cover_days multiplied by the daily rate the forecast "
    "already computed, rounded up to a whole unit because half a tablet cannot "
    "be bought and rounding down leaves the last day short. Where a pack size "
    "is known, packs round up too and units_ordered is what those packs hold"
)
PRICE_RULE = (
    "a price appears only if the caller supplied one, with a currency and a "
    "stated source. Nothing is looked up, estimated or carried over from a "
    "previous run, and money is exact decimal arithmetic quantised to cents"
)
TOTAL_RULE = (
    "one unpriced line suppresses the total for the whole cart. A partial sum "
    "would understate the cost while looking like the cost, and a total nobody "
    "can check is worse than no total at all"
)
FRESHNESS_RULE = (
    "a forecast more than 7 days older than as_of is flagged stale and still "
    "used. Supply is consumed a day at a time, so an old forecast understates "
    "what is needed; the age travels with the answer rather than being lost"
)
EXCLUSION_RULE = (
    "every medicine in the forecast lands in exactly one of cart.items and "
    "excluded, each with a reason in plain words. Nothing is dropped quietly"
)

LOG = logging.getLogger("pharmacy_cart")


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
            f"represented exactly; pass it as a string")
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
            f"{where}: expected a number, got {type(value).__name__}")
    if not number.is_finite():
        raise InvalidInput(f"{where}: {what} {value!r} is not finite")
    return number


def _to_money(value, where):
    amount = _to_decimal(value, where, "an amount of money")
    if amount < 0:
        raise InvalidInput(
            f"{where}: {amount} is negative. A negative price is a data entry "
            f"mistake, not a discount this script knows how to apply")
    return amount


def _to_positive_whole(value, where):
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected a whole number, got a boolean")
    if isinstance(value, int):
        whole = value
    else:
        number = _to_decimal(value, where, "a whole number")
        if number != number.to_integral_value():
            raise InvalidInput(f"{where}: {number} is not a whole number")
        whole = int(number)
    if whole < 1:
        raise InvalidInput(f"{where}: {whole} must be at least 1")
    return whole


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD)")


def _to_text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{where}: expected a non-empty string")
    return value.strip()


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
    """'1 day' / '30 days'. The '1 tablets left over' bug, structurally."""
    return f"{number} " + (noun if number == 1 else (plural or noun + "s"))


# --------------------------------------------------------------------------
# the forecast this cart is built on
# --------------------------------------------------------------------------

def _resolve_forecast(document, as_of):
    """Take the forecast as given, and refuse one that has been edited."""
    forecast = document.get("forecast")
    if not isinstance(forecast, dict):
        raise InvalidInput(
            "forecast is required and must be a medication_runout.py result "
            "object, passed through verbatim")
    for key in ("as_of", "forecast", "not_forecast", "medications_digest",
                "conventions", "audit_hash"):
        if key not in forecast:
            raise InvalidInput(
                f"forecast has no {key!r}: this does not look like a "
                f"medication_runout.py result. This script consumes a forecast "
                f"rather than computing one, and there is nothing here to "
                f"consume")

    stored = forecast["audit_hash"]
    recomputed = medication_runout.audit_hash_of(forecast)
    if recomputed != stored:
        raise InvalidInput(
            f"forecast audit_hash does not match its contents (stored "
            f"{stored}, recomputed {recomputed}). The forecast has been edited "
            f"since it was produced — refusing to order medicine against it")

    forecast_as_of = _to_date(forecast["as_of"], "forecast.as_of")
    if forecast_as_of > as_of:
        raise InvalidInput(
            f"forecast is dated {forecast_as_of.isoformat()}, which is in the "
            f"future relative to as_of {as_of.isoformat()}. One of the two is "
            f"wrong and this cannot tell which")

    age_days = (as_of - forecast_as_of).days
    stale = age_days > FORECAST_STALE_AFTER_DAYS
    if stale:
        LOG.warning("forecast is %s old, past the %d-day window; using it and "
                    "flagging it", _count(age_days, "day"),
                    FORECAST_STALE_AFTER_DAYS)
    return forecast, forecast_as_of, age_days, stale


# --------------------------------------------------------------------------
# what the caller knows about buying each medicine
# --------------------------------------------------------------------------

def _resolve_purchase(document, known_ids):
    if "purchase" not in document:
        raise InvalidInput(
            "purchase is required (use {} for none). A misspelled key would "
            "otherwise leave every supply_channel unknown, empty the cart, and "
            "exit 0 looking like a household with nothing to order")
    purchase = document["purchase"]
    if not isinstance(purchase, dict):
        raise InvalidInput("purchase must be an object keyed by medication id")

    resolved = {}
    for med_id, entry in purchase.items():
        where = f"purchase[{med_id!r}]"
        if med_id not in known_ids:
            raise InvalidInput(
                f"{where}: no medication with that id is in the forecast. A "
                f"mistyped id would silently leave the real medicine with no "
                f"supply channel, which reads as 'nothing to buy'. Ids in the "
                f"forecast: {', '.join(sorted(known_ids))}")
        if not isinstance(entry, dict):
            raise InvalidInput(f"{where} must be an object")
        _reject_unknown(entry, KNOWN_PURCHASE_KEYS, where)

        if "supply_channel" not in entry:
            raise InvalidInput(
                f"{where}: 'supply_channel' is required and has no default. "
                f"Whether a medicine can be bought off a shelf is the one "
                f"thing this script must not guess at. Use one of "
                f"{', '.join(SUPPLY_CHANNELS)}, or leave the whole entry out "
                f"to say it is not known")
        channel = entry["supply_channel"]
        if channel not in SUPPLY_CHANNELS:
            raise InvalidInput(
                f"{where}: supply_channel {channel!r} is not one of "
                f"{', '.join(SUPPLY_CHANNELS)}. An unrecognised value is "
                f"refused, never mapped to the nearest one")

        row = {"supply_channel": channel, "pack_size": None,
               "form_plural": None, "price": None}
        if entry.get("form_plural") is not None:
            row["form_plural"] = _to_text(entry["form_plural"],
                                          f"{where}.form_plural")
        if entry.get("pack_size") is not None:
            row["pack_size"] = _to_positive_whole(entry["pack_size"],
                                                  f"{where}.pack_size")
        row["price"] = _resolve_price(entry, row["pack_size"], where)
        resolved[med_id] = row
    return resolved


def _resolve_price(entry, pack_size, where):
    has_pack = entry.get("pack_price") is not None
    has_unit = entry.get("unit_price") is not None
    if has_pack and has_unit:
        raise InvalidInput(
            f"{where}: pack_price and unit_price were both given. Which one "
            f"the cart should multiply is a guess, and the two answers differ "
            f"by the pack size — supply exactly one")
    if not has_pack and not has_unit:
        for field in ("currency", "source"):
            if entry.get(field) is not None:
                raise InvalidInput(
                    f"{where}: {field!r} was given with no price. A currency "
                    f"without an amount buys nothing and reads as though a "
                    f"price were recorded")
        return None
    if has_pack and pack_size is None:
        raise InvalidInput(
            f"{where}: pack_price was given without pack_size, so nothing "
            f"here says how many units a pack holds. The cart cannot turn a "
            f"pack price into a line total without inventing the pack")

    basis = "pack" if has_pack else "unit"
    amount = _to_money(entry[f"{basis}_price"], f"{where}.{basis}_price")
    if entry.get("currency") is None:
        raise InvalidInput(
            f"{where}: a price needs a currency. An unlabelled amount in a "
            f"family artifact is a number nobody can check")
    if entry.get("source") is None:
        raise InvalidInput(
            f"{where}: a price needs a 'source' saying where it came from. "
            f"This script looks nothing up, so an unsourced price is a price "
            f"somebody remembered")
    return {
        "basis": basis,
        "amount": amount,
        "currency": _to_text(entry["currency"], f"{where}.currency"),
        "source": _to_text(entry["source"], f"{where}.source"),
    }


def _resolve_pharmacy(document):
    if document.get("pharmacy") is None:
        return None
    block = document["pharmacy"]
    if not isinstance(block, dict):
        raise InvalidInput("pharmacy must be an object")
    _reject_unknown(block, KNOWN_PHARMACY_KEYS, "pharmacy")
    name = _to_text(block.get("name"), "pharmacy.name")

    link = None
    if block.get("deep_link") is not None:
        link = _to_text(block["deep_link"], "pharmacy.deep_link")
        lowered = link.lower()
        if not lowered.startswith("https://"):
            raise InvalidInput(
                f"pharmacy.deep_link {link!r} does not start with https://. "
                f"Only an https link is copied into an artifact a senior is "
                f"asked to open")
        if "@" in link.split("/", 3)[2]:
            raise InvalidInput(
                "pharmacy.deep_link carries userinfo before the host, which "
                "is a credential in a URL. Nothing credential-shaped is "
                "written into a cart draft")
        for marker in CREDENTIAL_MARKERS:
            if marker in lowered:
                raise InvalidInput(
                    f"pharmacy.deep_link contains {marker!r}, which is a "
                    f"credential shape. A cart draft ships inside the plugin "
                    f"payload, and no secret goes in there")
    # Copied verbatim into the output and never opened: this script makes no
    # request of any kind, and a person clicks the link or does not.
    return {"name": name, "deep_link": link}


# --------------------------------------------------------------------------
# building the cart — arithmetic only
# --------------------------------------------------------------------------

def _units_needed(units_per_day_text, cover_days, where):
    try:
        rate = Fraction(units_per_day_text)
    except (ValueError, ZeroDivisionError):
        raise InvalidInput(
            f"{where}: units_per_day {units_per_day_text!r} from the forecast "
            f"is not a number this can multiply")
    if rate <= 0:
        raise InvalidInput(f"{where}: units_per_day {rate} is not positive")
    exact = rate * cover_days
    # Rounded up, deliberately: the opposite of the floor the forecast uses.
    # A forecast that rounded up would claim supply she does not have; an
    # order that rounded down would leave her a dose short on the last day.
    return -((-exact.numerator) // exact.denominator)


def _cart_item(entry, terms, cover_days):
    where = f"forecast.forecast[{entry['id']!r}]"
    needed = _units_needed(entry["units_per_day"], cover_days, where)
    pack_size = terms["pack_size"]
    if pack_size is None:
        packs = None
        ordered = needed
    else:
        packs = -(-needed // pack_size)
        ordered = packs * pack_size

    price = terms["price"]
    line_total = None
    if price is not None:
        count = packs if price["basis"] == "pack" else ordered
        line_total = (price["amount"] * count).quantize(CENTS, ROUND_HALF_UP)

    item = {
        "id": entry["id"],
        "name": entry["name"],
        "form": entry["form"],
        "supply_channel": terms["supply_channel"],
        "status": entry["status"],
        "runs_out_on": entry["runs_out_on"],
        "order_by": entry["order_by"],
        "units_per_day": entry["units_per_day"],
        "cover_days": cover_days,
        "units_needed": needed,
        "pack_size": pack_size,
        "packs": packs,
        "units_ordered": ordered,
        "price": None if price is None else {
            "basis": price["basis"],
            "amount": str(price["amount"]),
            "currency": price["currency"],
            "source": price["source"],
        },
        "line_total": None if line_total is None else str(line_total),
    }
    item["summary"] = _item_summary(item, terms)
    return item


def _units(count, item, terms):
    plural = terms["form_plural"] or item["form"] + "s"
    return _count(count, item["form"], plural)


def _rate(item, terms):
    """'1 tablet a day', not a bare '1 a day' that reads as a dose."""
    plural = terms["form_plural"] or item["form"] + "s"
    text = item["units_per_day"]
    one = Fraction(text) == 1
    return f"{text} {item['form'] if one else plural}"


def _item_summary(item, terms):
    # The lead number is what she needs, never what the packs happen to hold.
    # "60 tablets to cover 30 days at 1 tablet a day" is arithmetic that
    # contradicts itself on the page, and a family reading it has no way to
    # tell which of the two numbers is the mistake.
    parts = [
        f"{item['name']}: {_units(item['units_needed'], item, terms)} needed "
        f"to cover {_count(item['cover_days'], 'day')} at "
        f"{_rate(item, terms)} a day, from "
        f"{_human_date(_to_date(item['runs_out_on'], 'runs_out_on'))} when the "
        f"supply on hand runs out."
    ]
    if item["packs"] is None:
        parts.append(
            "No pack size is recorded for it, so that is a count of loose "
            "units and somebody has to choose the pack.")
    else:
        parts.append(
            f"It is sold in packs of {_units(item['pack_size'], item, terms)}, "
            f"so that is {_count(item['packs'], 'pack')} — "
            f"{_units(item['units_ordered'], item, terms)} in all.")
    if item["price"] is None:
        parts.append("No price was supplied, so none is shown.")
    else:
        parts.append(
            f"{item['price']['currency']} {item['line_total']} at "
            f"{item['price']['currency']} {item['price']['amount']} a "
            f"{item['price']['basis']}, priced from: {item['price']['source']}.")
    parts.append("Nothing is ordered until a person checks this and pays.")
    return " ".join(parts)


EXCLUSION_ROUTES = {
    "prescription_only": "prescription_refill",
    "pharmacist_only": "pharmacy_counter",
    "supply_channel_unknown": "ask_caregiver",
    "no_forecast_quantity": "ask_caregiver",
    "not_due_yet": "later_cart",
}


def _excluded(entry, reason, detail):
    return {
        "id": entry["id"],
        "name": entry["name"],
        "reason": reason,
        "route": EXCLUSION_ROUTES[reason],
        "summary": f"{entry['name']}: {detail}",
    }


def _exclusion_detail(reason, entry):
    if reason == "prescription_only":
        return ("this needs a prescription, so it is not something to put in "
                "a shopping cart. It goes through the usual repeat "
                "prescription route with the clinic instead.")
    if reason == "pharmacist_only":
        return ("this is kept behind the counter and a pharmacist has to hand "
                "it over, so it is not bought online. Someone collects it in "
                "person.")
    if reason == "supply_channel_unknown":
        return ("no supply_channel is recorded for this, so nothing here "
                "knows whether it can be bought without a prescription. It is "
                "left out rather than guessed at — please record how this one "
                "is obtained.")
    if reason == "no_forecast_quantity":
        return ("this is taken as needed, so the forecast worked out no daily "
                "rate and there is no quantity to order. How much to buy is a "
                "question for a person.")
    return (f"there is still supply left. The forecast puts the order-by date "
            f"at {_human_date(_to_date(entry['order_by'], 'order_by'))}, so "
            f"this belongs in a later cart.")


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset of a result that the audit hash certifies."""
    canonical = {key: result[key] for key in (
        "as_of", "cover_days", "requires_human_checkout", "pharmacy",
        "conventions", "cart", "excluded", "counts", "summary")}
    # The forecast's audit_hash identifies the forecast; its tool_run_id
    # identifies one *run* of it. Re-running the forecaster on unchanged input
    # is not a different cart, so the run id is recorded in the output for
    # provenance and left out of the hash, exactly as this script's own is.
    canonical["forecast"] = {key: value
                             for key, value in result["forecast"].items()
                             if key != "tool_run_id"}
    return canonical


def audit_hash_of(result):
    """Hash resolved inputs *and* the computed cart, excluding tool_run_id and
    issued_at so replaying the same input reproduces the same hash."""
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _cart_summary(items, cart, excluded, pharmacy, cover_days,
                  age_days, stale):
    parts = []
    if items:
        where = (f" at {pharmacy['name']}" if pharmacy
                 else ", though no pharmacy is named on this draft")
        parts.append(
            f"{_count(len(items), 'medicine')} to order{where}, enough for "
            f"{_count(cover_days, 'day')}.")
    else:
        parts.append(
            "Nothing to order: no medicine in this forecast is both due and "
            "known to be buyable without a prescription.")
        if pharmacy is None:
            parts.append("There is no pharmacy on this draft.")
    if cart["total"] is not None:
        parts.append(f"Total {cart['currency']} {cart['total']}.")
    elif items:
        parts.append(f"No total is shown: {cart['total_suppressed_because']}")
    if excluded:
        by_reason = {}
        for row in excluded:
            by_reason.setdefault(row["reason"], []).append(row["name"])
        # In _REASON_PHRASE order, not alphabetical: the reasons a person has
        # to act on come before the ones that are only a note.
        for reason, phrase in _REASON_PHRASE.items():
            if reason in by_reason:
                parts.append(f"{phrase}: "
                             f"{', '.join(sorted(by_reason[reason]))}.")
    if stale:
        parts.append(
            f"The forecast behind this is {_count(age_days, 'day')} old, so "
            f"the amounts may understate what is needed — count the boxes "
            f"again before ordering.")
    parts.append(
        "This is a draft. Nothing has been ordered and nothing has been paid "
        "for; a person opens it, checks it and pays.")
    return " ".join(parts)


# Declaration order is the order these are read out in the summary: what
# needs a person's action first, what is only a note last.
_REASON_PHRASE = {
    "prescription_only": "Left out because they need a prescription",
    "pharmacist_only": "Left out because a pharmacist has to hand them over",
    "supply_channel_unknown":
        "Left out because how they are obtained is not recorded — "
        "no supply_channel",
    "no_forecast_quantity":
        "Left out because they are taken as needed, so no quantity was "
        "forecast",
    "not_due_yet": "Not due yet",
}


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_cart(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")
    _reject_unknown(document, KNOWN_KEYS, "input")

    if document.get("as_of") is None:
        as_of = datetime.now(SG).date()
        LOG.info("as_of absent; resolved once to SG today %s", as_of.isoformat())
    else:
        as_of = _to_date(document["as_of"], "as_of")

    if "cover_days" not in document:
        raise InvalidInput(
            "cover_days is required and has no default. How much medicine to "
            "buy is not something this script may pick on a household's behalf")
    cover_days = _to_positive_whole(document["cover_days"], "cover_days")

    forecast, forecast_as_of, age_days, stale = _resolve_forecast(
        document, as_of)

    due = list(forecast["forecast"])
    prn = list(forecast["not_forecast"])
    known_ids = {entry["id"] for entry in due} | {entry["id"] for entry in prn}
    terms_by_id = _resolve_purchase(document, known_ids)
    pharmacy = _resolve_pharmacy(document)

    items = []
    excluded = []

    for entry in prn:
        excluded.append(_excluded(
            entry, "no_forecast_quantity",
            _exclusion_detail("no_forecast_quantity", entry)))

    for entry in due:
        terms = terms_by_id.get(entry["id"])
        # Channel first, then timing: a prescription medicine is never in a
        # cart, and saying "not due yet" about one implies it will be later.
        if terms is None:
            reason = "supply_channel_unknown"
        elif terms["supply_channel"] != "general_sale":
            reason = terms["supply_channel"]
        elif entry["status"] not in DUE_STATUSES:
            reason = "not_due_yet"
        else:
            items.append(_cart_item(entry, terms, cover_days))
            continue
        excluded.append(_excluded(entry, reason,
                                  _exclusion_detail(reason, entry)))

    currencies = sorted({item["price"]["currency"]
                         for item in items if item["price"] is not None})
    if len(currencies) > 1:
        raise InvalidInput(
            f"the cart mixes currencies ({', '.join(currencies)}). Adding them "
            f"together would produce a total that is wrong in every one of "
            f"them; split the cart instead")

    unpriced = [item["id"] for item in items if item["line_total"] is None]
    if not items:
        total, suppressed = None, "the cart is empty, so there is nothing to add up"
    elif unpriced:
        total = None
        suppressed = (
            f"no price was supplied for {', '.join(unpriced)}, and a total "
            f"covering only the rest would understate the cost while looking "
            f"like the cost")
    else:
        total = str(sum((Decimal(item["line_total"]) for item in items),
                        Decimal("0")).quantize(CENTS, ROUND_HALF_UP))
        suppressed = None

    cart = {
        "currency": currencies[0] if currencies else None,
        "items": items,
        "total": total,
        "total_suppressed_because": suppressed,
    }

    LOG.info("as_of %s: %s in the cart, %s excluded, forecast %s (%s old)",
             as_of.isoformat(), _count(len(items), "medicine"),
             _count(len(excluded), "medicine"), forecast_as_of.isoformat(),
             _count(age_days, "day"))
    for row in excluded:
        LOG.info("excluded %s: %s -> %s", row["id"], row["reason"],
                 row["route"])

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "cover_days": cover_days,
        "requires_human_checkout": REQUIRES_HUMAN_CHECKOUT,
        "forecast": {
            "tool_run_id": forecast.get("tool_run_id"),
            "audit_hash": forecast["audit_hash"],
            "medications_digest": forecast["medications_digest"],
            "as_of": forecast_as_of.isoformat(),
            "age_days": age_days,
            "stale": stale,
        },
        "pharmacy": pharmacy,
        "conventions": {
            "checkout": CHECKOUT_RULE,
            "supply_channel": SUPPLY_CHANNEL_RULE,
            "quantity": QUANTITY_RULE,
            "price": PRICE_RULE,
            "total": TOTAL_RULE,
            "freshness": FRESHNESS_RULE,
            "exclusions": EXCLUSION_RULE,
            "supply_channels": list(SUPPLY_CHANNELS),
        },
        "cart": cart,
        "excluded": excluded,
        "counts": {
            "medications_in_forecast": len(due) + len(prn),
            "cart_items": len(items),
            "excluded": len(excluded),
        },
    }
    result["summary"] = _cart_summary(items, cart, excluded, pharmacy,
                                      cover_days, age_days, stale)
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
        result = build_cart(_read_input(args.input))
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
