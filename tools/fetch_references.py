#!/usr/bin/env python3
"""Fetch external reference datasets into a dated snapshot. Human-run.

Usage:
    python3 fetch_references.py --out-dir <dir> [--as-of YYYY-MM-DD]
    python3 fetch_references.py --from-file <file.geojson> --out-dir <dir>

This is the **only file in the repo permitted to open a socket**, and no skill
invokes it. See docs/DECISIONS.md for why external data is snapshotted at build
time and never queried at runtime; the short version is that WorkBuddy
security-scans plugins on install, a demo cannot depend on the venue's wifi, and
`criteria as of 2026-08-03 — verify at <URL>` is only honest about a dated file.

It ships nowhere. It lives in tools/, outside the plugin tree, and the snapshot
it writes is what the skills read.

    --from-file skips the network entirely and reads a GeoJSON already on disk.
    That is how the tests exercise every line below except fetch(), and how the
    snapshot can be rebuilt on a machine with no connectivity.

Source: CHAS Clinics (MOH) via data.gov.sg, dataset
d_548c33ea2d99e29ec63a7cc9edcccedc. The poll-download endpoint returns
{code, data:{url}, errMsg}; `data.url` is the actual GeoJSON.

**The property schema of that dataset is unverified** (docs/DATA-SOURCES.md).
So this script does not guess at field names: it validates the geometry, which
is schema-independent, carries `properties` through verbatim, and maps a name
and address only from keys it recognises. Anything it cannot map stays null and
is counted in `clinics_without_mapped_name`, because inventing a clinic name
from an unconfirmed schema is the same class of mistake as inventing a deadline.

Two failure modes are refused rather than written, because both would produce a
plausible wrong answer downstream instead of an error:

  * Swapped coordinates. GeoJSON is [longitude, latitude]. Reversed, every
    Singapore clinic lands in the Indian Ocean and haversine returns a confident
    distance to it.
  * An empty dataset. A snapshot with no clinics makes the next script say
    "there are no clinics near you", which is a wrong answer dressed as a fact.

Coordinates are stored as strings, preserving the source's exact decimal text,
for the same reason money is Decimal: nothing downstream should inherit binary
floating-point error it did not ask for.

No credentials. No API key. Nothing is submitted anywhere.
"""

import argparse
import hashlib
import json
import logging
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SG = timezone(timedelta(hours=8), name="+08:00")

CHAS_DATASET_ID = "d_548c33ea2d99e29ec63a7cc9edcccedc"
POLL_DOWNLOAD = ("https://api-open.data.gov.sg/v1/public/api/datasets/"
                 "{dataset_id}/poll-download")

ATTRIBUTION = "Ministry of Health, CHAS Clinics, data.gov.sg"

# Singapore's bounding box, generous at the edges. Its only job is to catch a
# coordinate order mistake or a wholly wrong dataset, not to adjudicate borders.
LON_RANGE = (Decimal("103.55"), Decimal("104.15"))
LAT_RANGE = (Decimal("1.10"), Decimal("1.52"))

# Property keys worth trying for a display name. Unverified, hence the fallback
# to null rather than to a guess.
NAME_KEYS = ("NAME", "name", "HCI_NAME", "CLINIC_NAME", "Name")
ADDRESS_KEYS = ("ADDRESS", "address", "ADDR", "BLK_HSE_NO", "Address")

TIMEOUT_SECONDS = 30

LOG = logging.getLogger("fetch_references")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


# --------------------------------------------------------------------------
# the network boundary — the only function here that touches it
# --------------------------------------------------------------------------

def fetch(url):
    """GET a URL and return its body as text. The one socket in this repo."""
    LOG.info("fetching %s", url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "care-navigator-fetch-references/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


def download_url_from(envelope):
    """Pull `data.url` out of a poll-download response, or refuse.

    `code != 0` is a documented failure. Treating it as an empty result is how a
    rate-limit response becomes a snapshot with no clinics in it.
    """
    if not isinstance(envelope, dict):
        raise InvalidInput(
            f"poll-download: expected a JSON object, got "
            f"{type(envelope).__name__}")
    if "code" not in envelope:
        # Absent is not zero. A response with no code is not a success.
        raise InvalidInput("poll-download: response has no 'code' field")
    if envelope["code"] != 0:
        raise InvalidInput(
            f"poll-download: code {envelope['code']!r} "
            f"({envelope.get('errMsg') or 'no message'})")
    url = (envelope.get("data") or {}).get("url")
    if not url:
        raise InvalidInput("poll-download: code 0 but no data.url to fetch")
    return url


# --------------------------------------------------------------------------
# parsing and validation — everything below is exercised offline
# --------------------------------------------------------------------------

def _to_coordinate(value, where):
    """Exact Decimal from the source's own text. Strings are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise InvalidInput(
            f"{where}: coordinate {value!r} is not a JSON number")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        raise InvalidInput(f"{where}: coordinate {value!r} is not a number")
    if not number.is_finite():
        raise InvalidInput(f"{where}: coordinate {value!r} is not finite")
    return number


def _resolve_as_of(as_of):
    if isinstance(as_of, date):
        return as_of
    if not isinstance(as_of, str):
        raise InvalidInput("as_of must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(as_of.strip())
    except ValueError:
        raise InvalidInput(
            f"as_of: expected an ISO date string (YYYY-MM-DD), got {as_of!r}")


def _first_present(properties, keys):
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clinic_from(feature, where):
    if not isinstance(feature, dict):
        raise InvalidInput(f"{where}: expected an object")

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise InvalidInput(f"{where}: geometry is missing or not an object")
    if geometry.get("type") != "Point":
        raise InvalidInput(
            f"{where}: geometry type {geometry.get('type')!r} is not Point; "
            f"a clinic is a place, and nothing here knows how to rank a line "
            f"or a polygon by distance")

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise InvalidInput(f"{where}: coordinates must be [longitude, latitude]")

    longitude = _to_coordinate(coordinates[0], f"{where}.coordinates[0]")
    latitude = _to_coordinate(coordinates[1], f"{where}.coordinates[1]")

    if not LON_RANGE[0] <= longitude <= LON_RANGE[1]:
        raise InvalidInput(
            f"{where}: longitude {longitude} is outside Singapore "
            f"({LON_RANGE[0]}..{LON_RANGE[1]}). GeoJSON is "
            f"[longitude, latitude] — check the coordinate order before "
            f"anything ranks this by distance")
    if not LAT_RANGE[0] <= latitude <= LAT_RANGE[1]:
        raise InvalidInput(
            f"{where}: latitude {latitude} is outside Singapore "
            f"({LAT_RANGE[0]}..{LAT_RANGE[1]}); check the longitude/latitude "
            f"order")

    properties = feature.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise InvalidInput(f"{where}: properties must be an object")

    clinic = {
        "id": None,  # filled below, from content
        "longitude": str(longitude),
        "latitude": str(latitude),
        "name": _first_present(properties, NAME_KEYS),
        "address": _first_present(properties, ADDRESS_KEYS),
        "properties": properties,
    }
    clinic["id"] = _clinic_id(clinic)
    return clinic


def _clinic_id(clinic):
    """A content-derived id.

    Positional ids change meaning the moment the upstream dataset reorders,
    which would silently repoint every stored reference at a different clinic.
    """
    blob = json.dumps(
        {"longitude": clinic["longitude"], "latitude": clinic["latitude"],
         "properties": clinic["properties"]},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "clinic-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _content_hash(clinics):
    """Over the clinics only.

    Excludes as_of and the fetch time, so re-fetching unchanged data reproduces
    the hash. It answers "did the data change", not "did I run this again".
    """
    blob = json.dumps(clinics, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


SOURCE_KINDS = ("dataset_download", "local_file")


def build_snapshot(geojson_text, as_of, source_url, dataset_id,
                   source_kind="dataset_download"):
    """Validate a GeoJSON FeatureCollection into a ClinicSnapshot.

    `source_kind` keeps the manifest honest. A snapshot built from `--from-file`
    carries a `dataset_id` for the dataset it is *meant* to be, but nothing
    verified that the file came from there — so the manifest says which it was
    rather than letting a local file inherit the dataset's provenance.
    """
    if source_kind not in SOURCE_KINDS:
        raise InvalidInput(
            f"source_kind must be one of {SOURCE_KINDS}, got {source_kind!r}")
    resolved = _resolve_as_of(as_of)

    try:
        document = json.loads(geojson_text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise InvalidInput(f"source is not valid JSON ({exc})")

    if not isinstance(document, dict):
        raise InvalidInput("source must be a JSON object")
    if document.get("type") != "FeatureCollection":
        raise InvalidInput(
            f"expected a GeoJSON FeatureCollection, got "
            f"{document.get('type')!r}")
    if "features" not in document:
        # Required, not defaulted: a renamed key would otherwise write an empty
        # snapshot and exit 0.
        raise InvalidInput("source has no 'features' key")
    features = document["features"]
    if not isinstance(features, list):
        raise InvalidInput("'features' must be a list")
    if not features:
        raise InvalidInput(
            "source contains no features. A snapshot with no clinics makes "
            "every later run say 'there are no clinics near you', which is a "
            "wrong answer dressed as a fact — refusing to write it")

    clinics = [_clinic_from(feature, f"features[{i}]")
               for i, feature in enumerate(features)]

    seen = {}
    for clinic in clinics:
        if clinic["id"] in seen:
            LOG.warning("duplicate clinic dropped: %s", clinic["id"])
        seen[clinic["id"]] = clinic
    clinics = sorted(seen.values(), key=lambda c: c["id"])

    unmapped = sum(1 for c in clinics if c["name"] is None)
    if unmapped:
        LOG.warning(
            "%d of %d clinics %s no name under any known property key; names "
            "left null rather than guessed",
            unmapped, len(clinics), "has" if unmapped == 1 else "have")

    return {
        "record_type": "ClinicSnapshot",
        "as_of": resolved.isoformat(),
        "fetched_at": datetime.now(SG).isoformat(timespec="seconds"),
        "source_url": source_url,
        "source_kind": source_kind,
        "dataset_id": dataset_id,
        "attribution": ATTRIBUTION,
        "record_count": len(clinics),
        "clinics_without_mapped_name": unmapped,
        "coordinate_reference_system": "CRS84 (WGS 84, longitude/latitude)",
        "conventions": {
            "coordinates": ("stored as strings holding the source's exact "
                            "decimal text; never binary floats"),
            "ids": ("derived from clinic content, not position, so an upstream "
                    "reorder does not repoint them"),
            "content_hash": ("over the clinics only, excluding as_of and "
                             "fetched_at, so an unchanged re-fetch reproduces "
                             "it"),
            "bounds": (f"longitude {LON_RANGE[0]}..{LON_RANGE[1]}, latitude "
                       f"{LAT_RANGE[0]}..{LAT_RANGE[1]}; anything outside is "
                       "refused as a probable coordinate-order error"),
        },
        "content_hash": _content_hash(clinics),
        "clinics": clinics,
    }


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def write_snapshot(snapshot, out_dir):
    """Write the dated snapshot and its manifest. Never overwrites."""
    out_dir = Path(out_dir)
    stem = f"chas-clinics-{snapshot['as_of']}"
    snapshot_path = out_dir / f"{stem}.json"
    manifest_path = out_dir / f"{stem}.manifest.json"

    for path in (snapshot_path, manifest_path):
        if path.exists():
            raise InvalidInput(
                f"{path} already exists. Refusing to overwrite a snapshot: "
                f"delete it deliberately, or pass a different --as-of")

    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "record_type": "ClinicSnapshotManifest",
        "as_of": snapshot["as_of"],
        "fetched_at": snapshot["fetched_at"],
        "source_url": snapshot["source_url"],
        "source_kind": snapshot["source_kind"],
        "dataset_id": snapshot["dataset_id"],
        "attribution": snapshot["attribution"],
        "record_count": snapshot["record_count"],
        "clinics_without_mapped_name": snapshot["clinics_without_mapped_name"],
        "content_hash": snapshot["content_hash"],
        "snapshot_file": snapshot_path.name,
    }

    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    LOG.info("wrote %s (%d clinics)", snapshot_path, snapshot["record_count"])
    LOG.info("wrote %s", manifest_path)
    return [snapshot_path, manifest_path]


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="directory for the dated snapshot and manifest")
    parser.add_argument("--from-file", type=Path, default=None,
                        help="read GeoJSON from this file instead of the "
                             "network; skips every socket call")
    parser.add_argument("--dataset-id", default=CHAS_DATASET_ID,
                        help="data.gov.sg dataset id")
    parser.add_argument("--as-of", default=None,
                        help="snapshot date, ISO YYYY-MM-DD; today in SG if "
                             "omitted")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    as_of = args.as_of or datetime.now(SG).date().isoformat()

    try:
        if args.from_file is not None:
            if not args.from_file.is_file():
                raise InvalidInput(f"file not found: {args.from_file}")
            LOG.info("reading %s (no network)", args.from_file)
            text = args.from_file.read_text(encoding="utf-8")
            source_url = args.from_file.resolve().as_uri()
            source_kind = "local_file"
        else:
            poll = POLL_DOWNLOAD.format(dataset_id=args.dataset_id)
            source_url = download_url_from(json.loads(fetch(poll)))
            text = fetch(source_url)
            source_kind = "dataset_download"

        snapshot = build_snapshot(text, as_of=as_of, source_url=source_url,
                                  dataset_id=args.dataset_id,
                                  source_kind=source_kind)
        write_snapshot(snapshot, args.out_dir)
    except InvalidInput as exc:
        LOG.error("%s", exc)
        return 2
    except OSError as exc:
        # Network or filesystem. Neither is a reason to write a partial file.
        LOG.error("%s", exc)
        return 3

    LOG.info("snapshot %s covers %d clinics; %s",
             snapshot["as_of"], snapshot["record_count"],
             snapshot["content_hash"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
