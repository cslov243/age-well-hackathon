#!/usr/bin/env python3
"""Rank the clinics in a dated snapshot by straight-line distance from a point.

Usage:
    python3 clinic_finder.py --input <input.json> [--output <output.json>]

--input omitted  -> read JSON from stdin.
--output omitted -> write JSON to stdout.

Input:
    {
      "as_of": "2026-08-05",            # optional, defaults to SG today
      "snapshot_path": "/care/references/chas-clinics-2026-08-04.json",
      "origin": {"longitude": "103.8500000",
                 "latitude": "1.3320000",
                 "label": "Blk 123 Lorong 1 Toa Payoh"},   # label optional
      "limit": 3,                       # at least one of limit / radius_metres
      "radius_metres": "600",
      "programme": "CHAS"               # optional filter, a dataset fact
    }

Every path is an argument. Nothing defaults to a location on disk, because the
working directory at invocation time is not something this can rely on.

This script reads a snapshot written offline by `tools/fetch_references.py`.
It makes no network call and imports nothing that could.

Three things it deliberately refuses to do:

  * **Assert anything about entitlement.** `programmes` is a fact recorded in a
    government dataset on a particular date. Whether any of it applies to any
    person is a question for a person, and no code path here has an opinion.
  * **Imply a route.** The distance is a great-circle line between two points.
    It is shorter than any walk, it ignores every road, stair and canal, and it
    says nothing about whether the way is step-free. Every summary says so in
    words, because a bare "420 m" in a senior-facing card reads as a walk.
  * **Trust a snapshot it has not checked.** The `content_hash` is recomputed
    over the clinics and compared. A hand-edited snapshot is refused outright:
    it is the one failure the fetcher's guarantees do not survive, and it would
    otherwise produce a confident distance to a coordinate nobody verified.

Distances are rounded to the nearest 10 m. Metre precision on a straight line
between two ~1e-7-degree coordinates is false precision, and false precision in
an artifact read by a family is a claim nobody can check.
"""

import argparse
import hashlib
import json
import logging
import math
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

SG = timezone(timedelta(hours=8), name="+08:00")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Duplicated from tools/fetch_references.py on purpose: a plugin script cannot
# import from tools/, which does not ship inside the plugin. The values are the
# same bounding box, and a clinic outside it is refused here as well as there.
LON_RANGE = (Decimal("103.55"), Decimal("104.15"))
LAT_RANGE = (Decimal("1.10"), Decimal("1.52"))

# Mean radius of the WGS 84 ellipsoid (IUGG R1).
EARTH_RADIUS_M = 6371008.8

DISTANCE_ROUNDING_M = 10
STALE_AFTER_DAYS = 30

DISTANCE_RULE = (
    "straight-line great-circle distance, rounded to the nearest 10 m. It is "
    "not a walking distance: no route was worked out, the walk is longer, and "
    "nothing here says whether the way is step-free"
)
RADIUS_RULE = (
    "the radius test is inclusive and applied to the unrounded distance, so a "
    "clinic is never admitted or excluded by the display rounding"
)
RANKING_RULE = (
    "ranked on the unrounded distance and tied by clinic id, so two clinics "
    "that display the same rounded distance keep a stable order"
)
COORDINATE_RULE = (
    "coordinates are carried as exact decimal strings and become binary floats "
    "only inside the trigonometry, which is the one place binary error is "
    "acceptable at this scale"
)
SPHERE_RULE = (
    "haversine on a sphere of radius 6371008.8 m, the mean radius of the WGS 84 "
    "ellipsoid. The sphere differs from the ellipsoid by under about half a "
    "percent, so past a few kilometres that error is larger than the 10 m "
    "rounding implies"
)
FRESHNESS_RULE = (
    "a snapshot more than 30 days older than as_of is flagged stale. It is "
    "still used, and every record carries the snapshot date, so the age of the "
    "data travels with the answer instead of being lost"
)
PROGRAMME_RULE = (
    "programmes are a fact recorded in the dataset on its as_of date. This "
    "script makes no judgement about any person's entitlement to anything, and "
    "nothing in this output should be read as one"
)

LOG = logging.getLogger("clinic_finder")


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
            f"represented exactly; pass it as a string"
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
            f"{where}: expected {what}, got {type(value).__name__}")
    if not number.is_finite():
        raise InvalidInput(f"{where}: {what} {value!r} is not finite")
    return number


def _to_date(value, where):
    if not isinstance(value, str):
        raise InvalidInput(f"{where}: expected an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidInput(
            f"{where}: {value!r} is not an ISO date (expected YYYY-MM-DD)")


def _to_count(value, where):
    if isinstance(value, bool):
        raise InvalidInput(f"{where}: expected a whole number, got a boolean")
    number = _to_decimal(value, where, "a whole number")
    if number != number.to_integral_value():
        raise InvalidInput(f"{where}: {number} is not a whole number")
    count = int(number)
    if count < 1:
        raise InvalidInput(f"{where}: {count} must be at least 1")
    return count


def _human_date(value):
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _count_phrase(number, noun):
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _in_singapore(longitude, latitude):
    return (LON_RANGE[0] <= longitude <= LON_RANGE[1]
            and LAT_RANGE[0] <= latitude <= LAT_RANGE[1])


# --------------------------------------------------------------------------
# distance
# --------------------------------------------------------------------------

def haversine_metres(lon_a, lat_a, lon_b, lat_b):
    """Great-circle distance in metres between two decimal degree pairs.

    Takes Decimals and converts to float here, and only here. At Singapore
    scale the binary error is far below the 10 m the answer is rounded to.
    """
    phi_a, phi_b = math.radians(float(lat_a)), math.radians(float(lat_b))
    d_phi = phi_b - phi_a
    d_lambda = math.radians(float(lon_b) - float(lon_a))

    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2)
    # Clamp: accumulated error can push `a` a hair outside [0, 1] for
    # near-identical or near-antipodal points, and asin would then raise.
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def round_to_10m(metres):
    """Nearest 10 m, halves away from zero. Returns an int, which is exact."""
    exact = Decimal(repr(metres))
    step = Decimal(DISTANCE_ROUNDING_M)
    return int((exact / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)
               * step)


# --------------------------------------------------------------------------
# the snapshot
# --------------------------------------------------------------------------

def content_hash_of(clinics):
    """Must reproduce tools/fetch_references.py `_content_hash` byte for byte.

    Two implementations in two trees that cannot import from each other. A test
    pins them together; if it ever fails, one of them changed and the other did
    not, and every snapshot in the field stops loading.
    """
    try:
        blob = json.dumps(clinics, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    except TypeError:
        raise InvalidInput(
            "snapshot clinics contain a value that is not plain JSON; the "
            "snapshot cannot be verified and is refused")
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_snapshot(path):
    path = Path(path)
    if not path.is_file():
        raise InvalidInput(f"snapshot not found: {path}")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"),
                              parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"{path}: snapshot is not valid JSON ({exc})")

    if not isinstance(snapshot, dict):
        raise InvalidInput(f"{path}: snapshot must be a JSON object")
    if snapshot.get("record_type") != "ClinicSnapshot":
        raise InvalidInput(
            f"{path}: expected record_type 'ClinicSnapshot', got "
            f"{snapshot.get('record_type')!r}")

    if "clinics" not in snapshot:
        # Required, not defaulted: a renamed key would otherwise answer "no
        # clinics near you" and exit 0.
        raise InvalidInput(f"{path}: snapshot has no 'clinics' key")
    clinics = snapshot["clinics"]
    if not isinstance(clinics, list):
        raise InvalidInput(f"{path}: 'clinics' must be a list")
    if not clinics:
        raise InvalidInput(
            f"{path}: snapshot contains no clinics. Ranking an empty list "
            f"produces 'there are none near you', which is a wrong answer "
            f"dressed as a fact")

    stored = snapshot.get("content_hash")
    if not isinstance(stored, str) or not stored:
        raise InvalidInput(
            f"{path}: snapshot has no content_hash, so nothing can vouch for "
            f"the coordinates in it")
    recomputed = content_hash_of(clinics)
    if recomputed != stored:
        raise InvalidInput(
            f"{path}: content_hash does not match the clinics it covers "
            f"(stored {stored}, recomputed {recomputed}). The snapshot has "
            f"been edited since it was fetched — refusing to measure distances "
            f"against it")
    return snapshot


def _clinic_point(entry, index):
    if not isinstance(entry, dict):
        raise InvalidInput(f"clinics[{index}] is not an object")
    cid = entry.get("id")
    if not isinstance(cid, str) or not cid:
        raise InvalidInput(f"clinics[{index}] has no id")
    longitude = _to_decimal(entry.get("longitude"),
                            f"{cid}.longitude", "a longitude")
    latitude = _to_decimal(entry.get("latitude"),
                           f"{cid}.latitude", "a latitude")
    if not _in_singapore(longitude, latitude):
        raise InvalidInput(
            f"{cid}: ({longitude}, {latitude}) is outside Singapore "
            f"(longitude {LON_RANGE[0]}..{LON_RANGE[1]}, latitude "
            f"{LAT_RANGE[0]}..{LAT_RANGE[1]}). The fetcher drops points like "
            f"this, so a snapshot carrying one was not written by it")
    return cid, longitude, latitude


# --------------------------------------------------------------------------
# validation of the request
# --------------------------------------------------------------------------

def _resolve_as_of(document):
    raw = document.get("as_of")
    if raw is None:
        resolved = datetime.now(SG).date()
        LOG.info("as_of absent; resolved once to SG today %s",
                 resolved.isoformat())
        return resolved
    return _to_date(raw, "as_of")


def _resolve_origin(document):
    origin = document.get("origin")
    if not isinstance(origin, dict):
        raise InvalidInput("origin is required and must be an object with a "
                           "longitude and a latitude")
    if "longitude" not in origin or "latitude" not in origin:
        raise InvalidInput(
            "origin needs both 'longitude' and 'latitude'; one alone cannot "
            "locate anything")
    longitude = _to_decimal(origin["longitude"], "origin.longitude",
                            "a longitude")
    latitude = _to_decimal(origin["latitude"], "origin.latitude", "a latitude")

    if not _in_singapore(longitude, latitude):
        if _in_singapore(latitude, longitude):
            raise InvalidInput(
                f"origin ({longitude}, {latitude}) is outside Singapore, but "
                f"({latitude}, {longitude}) is inside it — the two look "
                f"exchanged. GeoJSON order is longitude first. Ranking against "
                f"the swapped point would have returned a tidy list of "
                f"distances to the Indian Ocean")
        raise InvalidInput(
            f"origin ({longitude}, {latitude}) is outside Singapore "
            f"(longitude {LON_RANGE[0]}..{LON_RANGE[1]}, latitude "
            f"{LAT_RANGE[0]}..{LAT_RANGE[1]})")

    label = origin.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise InvalidInput("origin.label must be a non-empty string if given")
    return {"longitude": longitude, "latitude": latitude,
            "label": label.strip() if isinstance(label, str) else None}


def _resolve_selection(document):
    has_limit = document.get("limit") is not None
    has_radius = document.get("radius_metres") is not None
    if not has_limit and not has_radius:
        raise InvalidInput(
            "at least one of 'limit' and 'radius_metres' is required. Without "
            "either, the answer is the whole snapshot, which is not a question "
            "anybody asked")

    limit = _to_count(document["limit"], "limit") if has_limit else None

    radius = None
    if has_radius:
        radius = _to_decimal(document["radius_metres"], "radius_metres",
                             "a distance in metres")
        if radius <= 0:
            raise InvalidInput(
                f"radius_metres: {radius} must be greater than zero")
    return limit, radius


def _resolve_programme(document, clinics):
    raw = document.get("programme")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInput("programme must be a non-empty string if given")
    programme = raw.strip().upper()

    available = set()
    for entry in clinics:
        for code in entry.get("programmes") or []:
            if isinstance(code, str):
                available.add(code.strip().upper())
    if programme not in available:
        raise InvalidInput(
            f"programme {programme!r} appears on none of the "
            f"{len(clinics)} clinics in this snapshot. Filtering on it would "
            f"answer 'there are none near you', which is what a typo looks "
            f"like from the outside — refusing instead. Known codes: "
            f"{', '.join(sorted(available))}")
    return programme


# --------------------------------------------------------------------------
# prose
# --------------------------------------------------------------------------

def _origin_phrase(origin):
    return origin["label"] or "the point given"


def _distance_phrase(metres, origin):
    return (f"{metres} m from {_origin_phrase(origin)} in a straight line — "
            f"not a walking distance, and no route was worked out")


def _clinic_summary(entry, metres, origin, snapshot_as_of):
    name, address = entry.get("name"), entry.get("address")
    if name:
        opening = f"{name}, {address}." if address else f"{name}."
    elif address:
        opening = f"A clinic the dataset does not name, at {address}."
    else:
        opening = ("A clinic the dataset does not name and gives no address "
                   "for.")

    parts = [opening, _distance_phrase(metres, origin) + "."]
    phone = entry.get("phone")
    if phone:
        parts.append(f"Telephone {phone}.")
    programmes = entry.get("programmes") or []
    if programmes:
        parts.append(f"The dataset listed it under "
                     f"{', '.join(programmes)} as of "
                     f"{_human_date(snapshot_as_of)}.")
    return " ".join(parts)


def _top_summary(found, considered, within_count, snapshot_as_of, origin,
                 radius, beyond, stale, age_days):
    if found:
        head = (f"Nearest first, {_count_phrase(len(found), 'clinic')} listed "
                f"out of {considered} considered, in a snapshot dated "
                f"{_human_date(snapshot_as_of)}.")
        # A list of the four nearest, in a radius holding fourteen, is not
        # "the clinics near you" — say how many were left out rather than let
        # the artifact imply there were none.
        if within_count is not None and within_count > len(found):
            head += (f" {_count_phrase(within_count, 'clinic')} in all are "
                     f"within {radius} m of {_origin_phrase(origin)}.")
    else:
        head = (f"No clinic in this snapshot is within {radius} m of "
                f"{_origin_phrase(origin)}.")
        if beyond:
            head += (f" The nearest is {beyond['distance_metres']} m away in a "
                     f"straight line, which is farther than the radius asked "
                     f"for — farther, not absent.")

    parts = [head,
             "Distances are straight-line and rounded to the nearest 10 m; "
             "none of them is a walking route."]
    if stale:
        parts.append(f"This snapshot is {_count_phrase(age_days, 'day')} old, "
                     f"past the {STALE_AFTER_DAYS}-day freshness rule — "
                     f"re-fetch it before relying on the list.")
    return " ".join(parts)


# --------------------------------------------------------------------------
# audit hash
# --------------------------------------------------------------------------

def _canonical(result):
    canonical = {key: result[key] for key in (
        "as_of", "origin", "snapshot", "filter", "clinics_considered",
        "clinics_within_radius", "conventions", "nearest",
        "nearest_beyond_radius", "summary")}
    # The snapshot's *path* is where one machine happened to keep the file.
    # `content_hash` already identifies the data itself, and it identifies it
    # better: including the path would make the same snapshot, copied to a
    # different directory, fail to reproduce its own audit hash.
    canonical["snapshot"] = {key: value
                             for key, value in canonical["snapshot"].items()
                             if key != "path"}
    return canonical


def audit_hash_of(result):
    """Over the resolved inputs and the computed distances together.

    Excludes tool_run_id and issued_at, so replaying the same request against
    the same snapshot reproduces it.
    """
    blob = json.dumps(_canonical(result), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

KNOWN_KEYS = ("as_of", "snapshot_path", "origin", "limit", "radius_metres",
              "programme")


def find_clinics(document):
    if not isinstance(document, dict):
        raise InvalidInput("input must be a JSON object")

    # `radius` for `radius_metres` is the obvious typo, and it fails silently:
    # the caller gets an unfiltered list of the nearest N and no indication the
    # radius they asked for was never applied.
    unknown = sorted(set(document) - set(KNOWN_KEYS))
    if unknown:
        raise InvalidInput(
            f"unknown key(s) {', '.join(repr(k) for k in unknown)}. A "
            f"misspelled key takes no effect and says nothing, which looks "
            f"exactly like an answer. Known keys: {', '.join(KNOWN_KEYS)}")

    as_of = _resolve_as_of(document)
    if document.get("snapshot_path") is None:
        raise InvalidInput(
            "snapshot_path is required and has no default; the working "
            "directory at invocation time is not something this can rely on")
    snapshot_path = str(document["snapshot_path"])

    origin = _resolve_origin(document)
    limit, radius = _resolve_selection(document)

    snapshot = load_snapshot(snapshot_path)
    snapshot_as_of = _to_date(snapshot.get("as_of"), "snapshot.as_of")
    if snapshot_as_of > as_of:
        raise InvalidInput(
            f"snapshot is dated {snapshot_as_of.isoformat()}, which is in the "
            f"future relative to as_of {as_of.isoformat()}. One of the two is "
            f"wrong and this cannot tell which")
    age_days = (as_of - snapshot_as_of).days
    stale = age_days > STALE_AFTER_DAYS
    if stale:
        LOG.warning("snapshot %s is %d days old, past the %d-day freshness "
                    "rule; using it and flagging it",
                    snapshot_path, age_days, STALE_AFTER_DAYS)

    clinics = snapshot["clinics"]
    programme = _resolve_programme(document, clinics)

    measured = []
    for index, entry in enumerate(clinics):
        cid, longitude, latitude = _clinic_point(entry, index)
        if programme is not None:
            codes = {c.strip().upper() for c in (entry.get("programmes") or [])
                     if isinstance(c, str)}
            if programme not in codes:
                continue
        metres = haversine_metres(origin["longitude"], origin["latitude"],
                                  longitude, latitude)
        measured.append((metres, cid, entry, longitude, latitude))

    # Ranked on the raw distance, tied by id. Rounding happens for display
    # only, after the order is fixed, so it can never reorder anything.
    measured.sort(key=lambda row: (row[0], row[1]))
    considered = len(measured)

    def render(row, rank):
        metres, cid, entry, longitude, latitude = row
        rounded = round_to_10m(metres)
        return {
            "rank": rank,
            "id": cid,
            "name": entry.get("name"),
            "address": entry.get("address"),
            "postal_code": entry.get("postal_code"),
            "phone": entry.get("phone"),
            "programmes": list(entry.get("programmes") or []),
            "longitude": str(longitude),
            "latitude": str(latitude),
            "distance_metres": rounded,
            "distance_rounding_metres": DISTANCE_ROUNDING_M,
            "distance_basis": "straight line, not a walking route",
            "snapshot_as_of": snapshot_as_of.isoformat(),
            "source_url": snapshot.get("source_url"),
            "summary": _clinic_summary(entry, rounded, origin, snapshot_as_of),
        }

    if radius is None:
        within = measured
        within_count = None
    else:
        limit_m = float(radius)
        within = [row for row in measured if row[0] <= limit_m]
        within_count = len(within)

    selected = within[:limit] if limit is not None else within
    nearest = [render(row, rank) for rank, row in enumerate(selected, start=1)]

    beyond = None
    if not nearest and radius is not None and measured:
        # Rank is null, not 1: it is not first in a list, it is the thing that
        # did not make the list.
        beyond = render(measured[0], None)

    citation = (f"{snapshot.get('attribution')} — snapshot as of "
                f"{_human_date(snapshot_as_of)}, from "
                f"{snapshot.get('source_url')}")

    LOG.info("as_of %s: %s considered, %d returned, snapshot %s (%s old)",
             as_of.isoformat(), _count_phrase(considered, "clinic"),
             len(nearest), snapshot_as_of.isoformat(),
             _count_phrase(age_days, "day"))

    result = {
        "tool_run_id": str(uuid.uuid4()),
        "issued_at": datetime.now(SG).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "origin": {"longitude": str(origin["longitude"]),
                   "latitude": str(origin["latitude"]),
                   "label": origin["label"]},
        "snapshot": {
            "path": snapshot_path,
            "as_of": snapshot_as_of.isoformat(),
            "age_days": age_days,
            "stale": stale,
            "record_count": snapshot.get("record_count"),
            "source_url": snapshot.get("source_url"),
            "dataset_id": snapshot.get("dataset_id"),
            "attribution": snapshot.get("attribution"),
            "content_hash": snapshot.get("content_hash"),
            "citation": citation,
        },
        "filter": {
            "limit": limit,
            "radius_metres": str(radius) if radius is not None else None,
            "programme": programme,
        },
        "clinics_considered": considered,
        "clinics_within_radius": within_count,
        "conventions": {
            "distance": DISTANCE_RULE,
            "radius": RADIUS_RULE,
            "ranking": RANKING_RULE,
            "coordinates": COORDINATE_RULE,
            "earth_model": SPHERE_RULE,
            "freshness": FRESHNESS_RULE,
            "programmes": PROGRAMME_RULE,
        },
        "nearest": nearest,
        "nearest_beyond_radius": beyond,
        "summary": _top_summary(nearest, considered, within_count,
                                snapshot_as_of, origin, radius, beyond,
                                stale, age_days),
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
        result = find_clinics(_read_input(args.input))
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
