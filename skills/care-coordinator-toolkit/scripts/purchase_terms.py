"""Turn household/medication.json into the `purchase` map pharmacy_cart.py reads.

    python3 purchase_terms.py --input <medication.json> [--output <out.json>]

Input is a MedicationRecord document — the same file `medication_runout.py`
reads, unchanged. Output is a map keyed by medication id:

    {
      "purchase": {
        "calcium-d": {
          "supply_channel": "general_sale",   # copied, never inferred
          "pack_size": 60,                    # only if recorded
          "pack_price": "12.90",
          "currency": "SGD",
          "source": "caregiver checked the receipt, 4 Aug 2026"
        }
      },
      "omitted": [ {"id": "amlodipine-5", "reason": "no_supply_channel_recorded"} ]
    }

**Why this is a script and not a paragraph in a SKILL.md.** `pharmacy_cart.py`
refuses to guess whether a medicine can be bought off a shelf, but something has
to hand it the answer. If that something is a model transcribing a field by
hand, the guard is worth exactly as much as the transcription — and a
hallucinated `general_sale` puts a prescription medicine in a shopping cart with
nothing downstream able to notice, because the cart cannot tell a copied value
from an invented one.

So this script copies. It refuses to:

  * **Invent a supply channel.** No `supply_channel` recorded means the
    medicine is left out of the map entirely. `pharmacy_cart.py` then reports
    it as `supply_channel_unknown` and asks the caregiver. Absent is unknown,
    and unknown is never general sale.
  * **Map a near miss.** `otc` is not `general_sale`. An unrecognised channel
    raises rather than being rounded to the nearest legal value.
  * **Accept a price it cannot attribute.** A price needs a currency and a
    stated source. Nothing here looks anything up.
  * **Take a fact from anywhere but the file it was given.** No network, no
    snapshot, no memory of a previous run.

It computes nothing. There is no arithmetic in this file at all — quantities,
packs and totals are `pharmacy_cart.py`'s work, and doing any of it here would
put the same sum in two places.
"""

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SG = timezone(timedelta(hours=8), name="+08:00")

# Closed vocabulary, shared with pharmacy_cart.py. A test asserts the two are
# identical: two copies of a closed set drift, and a drift here means the
# scripts disagree about what a prescription is.
SUPPLY_CHANNELS = ("general_sale", "pharmacist_only", "prescription_only")

# Keys permitted inside a medication's optional `purchase` block. A typo here
# silently drops a price, and the cart then suppresses its total for a reason
# nobody can trace back to a misspelling.
KNOWN_PURCHASE_KEYS = ("pack_size", "pack_price", "unit_price",
                       "currency", "source")

PRICE_KEYS = ("pack_price", "unit_price")

CHANNEL_RULE = (
    "supply_channel is copied from household/medication.json and never "
    "inferred. A medicine with none recorded is left out of this map "
    "altogether, so pharmacy_cart.py reports it as unknown and asks a person, "
    "rather than being told it can be bought off a shelf"
)
PRICE_RULE = (
    "a price is carried through only with a currency and a stated source. "
    "Nothing is looked up, estimated, or remembered from a previous run, and "
    "money stays an exact decimal string"
)
OMISSION_RULE = (
    "every medication in the file lands in exactly one of purchase and "
    "omitted. Nothing is dropped quietly"
)
ARITHMETIC_RULE = (
    "this script computes nothing. Quantities, pack counts and totals are "
    "pharmacy_cart.py's work, and duplicating any of it here would put the "
    "same sum in two places"
)

LOG = logging.getLogger("purchase_terms")


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
            raise InvalidInput(
                f"{where}: {number} is not a whole number. A pack holds a "
                f"whole number of units")
        whole = int(number)
    if whole < 1:
        raise InvalidInput(f"{where}: {whole} must be at least 1")
    return whole


def _to_text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{where}: expected a non-empty string")
    return value.strip()


def _reject_unknown(mapping, known, where):
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        raise InvalidInput(
            f"{where}: unrecognised key(s) {', '.join(unknown)}. Permitted: "
            f"{', '.join(known)}. A misspelled key here would be accepted and "
            f"never used, and nobody would learn their entry did nothing")


# --------------------------------------------------------------------------
# one medication
# --------------------------------------------------------------------------

def _channel_of(entry, where):
    """The recorded supply channel, or None if none was recorded."""
    if "supply_channel" not in entry:
        return None
    channel = entry["supply_channel"]
    if not isinstance(channel, str):
        raise InvalidInput(
            f"{where}: supply_channel must be a string, got "
            f"{type(channel).__name__}")
    if channel not in SUPPLY_CHANNELS:
        raise InvalidInput(
            f"{where}: supply_channel {channel!r} is not one of "
            f"{', '.join(SUPPLY_CHANNELS)}. It is not mapped to the nearest "
            f"one — getting this wrong puts a prescription medicine in a "
            f"shopping cart. Correct it in household/medication.json, or "
            f"remove it to say the channel is not known")
    return channel


def _price_of(block, where):
    """The priced part of a purchase block, or {} if it carries no price."""
    given = [key for key in PRICE_KEYS if block.get(key) is not None]
    if len(given) > 1:
        raise InvalidInput(
            f"{where}: pack_price and unit_price were both given. Two prices "
            f"for one medicine is a contradiction this script will not pick a "
            f"winner in — record whichever one the caregiver actually saw")

    has_currency = block.get("currency") is not None
    has_source = block.get("source") is not None

    if not given:
        if has_currency or has_source:
            raise InvalidInput(
                f"{where}: a currency or source was recorded with no price to "
                f"attach it to. Add pack_price or unit_price, or remove them")
        return {}

    key = given[0]
    if not has_currency:
        raise InvalidInput(
            f"{where}: {key} was given without a currency. An amount with no "
            f"currency is not a price")
    if not has_source:
        raise InvalidInput(
            f"{where}: {key} was given without a source. This script looks "
            f"nothing up, so a price with no stated source is one somebody "
            f"remembered — say where it came from, or leave the price out")

    priced = {key: str(_to_money(block[key], f"{where}.{key}")),
              "currency": _to_text(block["currency"], f"{where}.currency"),
              "source": _to_text(block["source"], f"{where}.source")}

    if key == "pack_price" and block.get("pack_size") is None:
        raise InvalidInput(
            f"{where}: pack_price was given without pack_size, so nothing "
            f"says how many units that price buys")
    return priced


def _terms_of(entry, channel, where):
    """The purchase-map row for one medication. `channel` is already validated."""
    row = {"supply_channel": channel}

    if entry.get("form_plural") is not None:
        # Carried through only when recorded. pharmacy_cart.py falls back to
        # form + "s" itself; computing the fallback here would put it in two
        # places and let the two disagree.
        row["form_plural"] = _to_text(entry["form_plural"],
                                      f"{where}.form_plural")

    block = entry.get("purchase")
    if block is None:
        return row
    if not isinstance(block, dict):
        raise InvalidInput(
            f"{where}.purchase: expected an object, got "
            f"{type(block).__name__}")
    _reject_unknown(block, KNOWN_PURCHASE_KEYS, f"{where}.purchase")
    if not block:
        raise InvalidInput(
            f"{where}.purchase: the block is empty. It says nothing, and it "
            f"took somebody an action to type — remove it, or record what "
            f"they meant to")

    if block.get("pack_size") is not None:
        row["pack_size"] = _to_positive_whole(block["pack_size"],
                                              f"{where}.purchase.pack_size")
    row.update(_price_of(block, f"{where}.purchase"))
    return row


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _count(number, noun, plural=None):
    """'1 medicine' / '3 medicines'. The '1 tablets left over' bug, structurally."""
    return f"{number} " + (noun if number == 1 else (plural or noun + "s"))


# How each channel reads in a sentence. The enum values are for machines;
# "prescription_only medicines" is not a thing anyone says out loud.
_CHANNEL_PHRASE = {
    "general_sale": "buyable off a shelf",
    "pharmacist_only": "handed over by a pharmacist",
    "prescription_only": "on prescription",
}


def _omission_summary(name):
    return (f"{name}: nothing in household/medication.json records how this is "
            f"obtained, so it is left out of the purchase map rather than "
            f"assumed to be something a person can buy off a shelf. A "
            f"caregiver has to say whether it needs a prescription.")


def _summary(rows, omitted, by_channel):
    if not rows and not omitted:
        return ("No medications are recorded in this file, so there are no "
                "purchase terms to build.")

    parts = []
    if rows:
        described = ", ".join(
            f"{len(by_channel[channel])} {_CHANNEL_PHRASE[channel]}"
            for channel in SUPPLY_CHANNELS if by_channel.get(channel))
        parts.append(
            f"Purchase terms for {_count(len(rows), 'medicine')}: {described}.")
    else:
        parts.append(
            "No purchase terms could be built: no medication in this file "
            "records how it is obtained.")

    if omitted:
        names = ", ".join(sorted(row["name"] for row in omitted))
        # One omission or several changes every pronoun in the sentence.
        tail = ("it needs a prescription, it stays" if len(omitted) == 1
                else "each needs a prescription, they stay")
        parts.append(
            f"Left out because no supply_channel is recorded: {names}. "
            f"Until a caregiver says whether {tail} out of any cart.")

    parts.append(
        "This map says what each medicine is and how it is bought. It orders "
        "nothing and prices nothing that was not written down.")
    return " ".join(parts)


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    """The subset of a result that the audit hash certifies."""
    return {key: result[key] for key in (
        "as_of", "conventions", "purchase", "omitted", "counts", "summary")}


def audit_hash_of(result):
    """Hash resolved inputs *and* the computed map, excluding tool_run_id and
    issued_at so replaying the same input reproduces the same hash."""
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_terms(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")

    # Unknown top-level keys are deliberately *not* rejected. This script does
    # not own household/medication.json — medication_runout.py does — and
    # refusing a field that file gains would break the two apart on the next
    # additive contract change.
    if "medications" not in document:
        raise InvalidInput(
            "'medications' is required and has no default, even when the list "
            "is empty. A misspelled key would otherwise exit 0 having built an "
            "empty map, which reads exactly like a household that records no "
            "supply channels")
    medications = document["medications"]
    if not isinstance(medications, list):
        raise InvalidInput(
            f"'medications' must be a list, got {type(medications).__name__}")

    as_of = document.get("as_of")
    if as_of is not None:
        as_of = _to_text(as_of, "as_of")

    purchase, omitted, by_channel, seen = {}, [], {}, set()
    for index, entry in enumerate(medications):
        where = f"medications[{index}]"
        if not isinstance(entry, dict):
            raise InvalidInput(
                f"{where}: expected an object, got {type(entry).__name__}")
        if "id" not in entry:
            raise InvalidInput(f"{where}: 'id' is required")
        mid = _to_text(entry["id"], f"{where}.id")
        if mid in seen:
            raise InvalidInput(
                f"{where}: duplicate id {mid!r}. Two rows keyed the same lose "
                f"one silently, and which one survives depends on the order "
                f"they happen to be read in")
        seen.add(mid)
        if "name" not in entry:
            raise InvalidInput(
                f"{where}: 'name' is required — an omitted medicine has to be "
                f"nameable in a sentence to a caregiver")
        name = _to_text(entry["name"], f"{where}.name")

        channel = _channel_of(entry, where)
        if channel is None:
            if entry.get("purchase") is not None:
                raise InvalidInput(
                    f"{where}: a purchase block was recorded but no "
                    f"supply_channel. Without a channel this medicine never "
                    f"enters a cart, so the price would be accepted and never "
                    f"used — record the supply_channel, or remove the price")
            omitted.append({"id": mid, "name": name,
                            "reason": "no_supply_channel_recorded",
                            "summary": _omission_summary(name)})
            continue

        purchase[mid] = _terms_of(entry, channel, where)
        by_channel.setdefault(channel, []).append(mid)

    LOG.info("%d medication(s): %d with terms, %d omitted for want of a "
             "supply_channel", len(medications), len(purchase), len(omitted))
    for row in omitted:
        LOG.info("omitted %s: %s", row["id"], row["reason"])

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of,
        "conventions": {
            "supply_channel": CHANNEL_RULE,
            "price": PRICE_RULE,
            "omission": OMISSION_RULE,
            "arithmetic": ARITHMETIC_RULE,
            "supply_channels": list(SUPPLY_CHANNELS),
        },
        "purchase": purchase,
        "omitted": omitted,
        "counts": {
            "medications": len(medications),
            "with_terms": len(purchase),
            "omitted": len(omitted),
        },
        "summary": _summary(purchase, omitted, by_channel),
    }
    result["audit_hash"] = audit_hash_of(result)
    return result


def _read_input(path):
    text = (sys.stdin.read() if path is None
            else Path(path).read_text(encoding="utf-8"))
    if not text.strip():
        raise InvalidInput("no input: expected a MedicationRecord JSON object")
    try:
        return json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"input is not valid JSON: {exc}")


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
        result = build_terms(_read_input(args.input))
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
    raise SystemExit(main())
