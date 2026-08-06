#!/usr/bin/env python3
"""Fetch external reference datasets into a dated snapshot. Human-run.

Usage:
    python3 fetch_references.py --out-dir <dir> [--as-of YYYY-MM-DD]
    python3 fetch_references.py --from-file <file.geojson> --out-dir <dir>

This is the snapshot fetcher — run by a person, never by a skill. Scripts may
reach the network as of 6 August 2026; this file remains how a *dated* reference
gets written, with credentials stripped and the fetch date recorded. No skill
invokes it. See docs/DECISIONS.md for why snapshots remain the default for
anything the demo depends on: WorkBuddy security-scans plugins on install, a demo
cannot depend on the venue's wifi, and `criteria as of 2026-08-03 — verify at
<URL>` is a claim you can reproduce months later in a way a live query is not.

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

A bad row and a misread file are different problems, and conflating them was a
real defect here: the first version refused the entire CHAS extract over a
single point 16 km south of Singapore's southernmost island, which meant one
upstream geocoding error blocked the connector permanently.

  * **A bad row is dropped**, with its reason recorded in the snapshot and its
    count in the manifest. Government extracts contain them. Never silently:
    a drop nobody can see is a clinic that quietly stopped existing.
  * **A misread file is refused whole.** One feature that is valid only when
    longitude and latitude are exchanged means the file was parsed in the wrong
    order, and the rows that happen to look plausible are no more trustworthy
    than the ones that do not.
  * **Too many rejects are refused whole** — above DEFAULT_MAX_REJECTED_RATIO,
    it is not a dirty dataset, it is a parsing mistake wearing one's clothes.
  * **An empty dataset is refused.** A snapshot with no clinics makes the next
    script say "there are no clinics near you", a wrong answer dressed as a
    fact.

Coordinates are stored as strings, preserving the source's exact decimal text,
for the same reason money is Decimal: nothing downstream should inherit binary
floating-point error it did not ask for.

No credentials. No API key. Nothing is submitted anywhere.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
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

# Verified against the live extract, 4 August 2026. The GeoJSON properties carry
# only {Name, Description}; every real field lives in an HTML attribute table
# inside Description, which _attributes_from_description unwraps.
NAME_KEYS = ("HCI_NAME", "CLINIC_NAME", "NAME", "name")
PHONE_KEYS = ("HCI_TEL", "TEL", "PHONE")
POSTAL_KEYS = ("POSTAL_CD", "POSTAL_CODE", "POSTCODE")
PROGRAMME_KEYS = ("CLINIC_PROGRAMME_CODE", "PROGRAMME_CODE")

# In order. Composed mechanically from labelled fields; nothing is inferred and
# every component survives verbatim in `attributes`.
ADDRESS_PARTS = ("BLK_HSE_NO", "STREET_NAME", "BUILDING_NAME")

# `Name` in this dataset is a KML export artifact — "kml_367", not a clinic.
# Accepting it reported 1,192 mapped names and would have sent a senior to
# "kml_367", which is the confident wrong answer this product exists to prevent.
PLACEHOLDER_NAME = re.compile(r"^kml[\s_-]*\d*$", re.IGNORECASE)

# The install-time security scan looks for these, and so does this script before
# it writes anything into the plugin tree.
SECRET_SHAPES = re.compile(
    r"(AWSAccessKeyId|x-amz-security-token|api[_-]?key|secret[_-]?key|"
    r"access[_-]?token|Signature=|password\s*[:=]|BEGIN\s+(RSA|OPENSSH|PRIVATE))",
    re.IGNORECASE)

TIMEOUT_SECONDS = 30

LOG = logging.getLogger("fetch_references")


class InvalidInput(ValueError):
    """Input the script refuses to guess at. Always fatal, never warned about."""


class RejectedRecord(Exception):
    """One unusable feature. Fatal for that record, not for the dataset.

    `swap_fixable` is the difference that matters. A point outside Singapore is
    a bad row in somebody else's database — real government extracts contain
    them, and dropping one is right. A point that would be *valid if longitude
    and latitude were exchanged* says something parsed the file wrongly, which
    makes every other row suspect however few are visibly broken.
    """

    def __init__(self, reason, where, swap_fixable=False):
        super().__init__(reason)
        self.reason = reason
        self.where = where
        self.swap_fixable = swap_fixable


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


def public_url(url):
    """A URL safe to write down: scheme, host and path, no query string.

    data.gov.sg hands back a presigned S3 link carrying AWSAccessKeyId, a
    Signature and an x-amz-security-token. Those are credentials, they expire,
    and they are useless as provenance — but written into the plugin payload
    they are exactly what the install-time security scan looks for.
    """
    if not isinstance(url, str):
        return url
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    "", ""))


class _AttributeTableParser(HTMLParser):
    """Pull <th>KEY</th><td>VALUE</td> pairs out of the Description table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes = {}
        self._cell = None
        self._buffer = []
        self._key = None

    def handle_starttag(self, tag, attrs):
        if tag in ("th", "td"):
            self._cell = tag
            self._buffer = []

    def handle_endtag(self, tag):
        if tag not in ("th", "td") or self._cell != tag:
            return
        text = "".join(self._buffer).strip()
        if tag == "th":
            self._key = text or None
        elif self._key is not None:
            # An empty cell is absent, not a value of "".
            self.attributes[self._key] = text or None
            self._key = None
        self._cell = None
        self._buffer = []

    def handle_data(self, data):
        if self._cell:
            self._buffer.append(data)


def _attributes_from_description(properties):
    """Unwrap the HTML attribute table, if there is one.

    The table is a serialisation of exactly these key/value pairs, so unwrapping
    loses nothing and spares every consumer a parser. Values are carried
    verbatim; nothing is renamed or interpreted here.
    """
    description = properties.get("Description")
    if not isinstance(description, str) or "<" not in description:
        return {}
    parser = _AttributeTableParser()
    try:
        parser.feed(description)
        parser.close()
    except Exception:  # a malformed cell is not a reason to lose the clinic
        LOG.warning("could not parse a Description table; leaving it verbatim")
        return {}
    parser.attributes.pop("Attributes", None)  # the table's own caption
    return parser.attributes


def _first_present(source, keys):
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _readable_name(attributes, properties):
    """A name, or None. Never a KML export artifact."""
    name = _first_present(attributes, NAME_KEYS) or _first_present(properties,
                                                                   NAME_KEYS)
    if name is None or PLACEHOLDER_NAME.match(name):
        return None
    return name


def _compose_address(attributes):
    """Join labelled address fields. Mechanical, not inferred.

    Every component stays in `attributes`, so nothing here is the only copy of
    anything, and a missing block or street yields None rather than a fragment
    that reads like a real address.
    """
    parts = [attributes.get(key) for key in ADDRESS_PARTS]
    parts = [p for p in parts if p]
    if not parts:
        return None
    line = " ".join(parts)
    unit = attributes.get("UNIT_NO")
    floor = attributes.get("FLOOR_NO")
    if floor and unit:
        line += f" #{floor}-{unit}"
    postal = _first_present(attributes, POSTAL_KEYS)
    if postal:
        line += f", Singapore {postal}"
    return line


def _in_bounds(longitude, latitude):
    return (LON_RANGE[0] <= longitude <= LON_RANGE[1]
            and LAT_RANGE[0] <= latitude <= LAT_RANGE[1])


def _clinic_from(feature, where):
    if not isinstance(feature, dict):
        raise RejectedRecord("feature is not an object", where)

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise RejectedRecord("geometry is missing or not an object", where)
    if geometry.get("type") != "Point":
        raise RejectedRecord(
            f"geometry type {geometry.get('type')!r} is not Point; nothing "
            f"here knows how to rank a line or a polygon by distance", where)

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise RejectedRecord("coordinates are not [longitude, latitude]", where)

    try:
        longitude = _to_coordinate(coordinates[0], f"{where}.coordinates[0]")
        latitude = _to_coordinate(coordinates[1], f"{where}.coordinates[1]")
    except InvalidInput as exc:
        raise RejectedRecord(str(exc), where)

    if not _in_bounds(longitude, latitude):
        # Would exchanging them put the point in Singapore? If so this is not a
        # bad row, it is a file that was read in the wrong order.
        swap_fixable = _in_bounds(latitude, longitude)
        which = ("longitude" if not LON_RANGE[0] <= longitude <= LON_RANGE[1]
                 else "latitude")
        value = longitude if which == "longitude" else latitude
        bounds = LON_RANGE if which == "longitude" else LAT_RANGE
        detail = (" — the coordinates are the wrong way round; GeoJSON is "
                  "[longitude, latitude]" if swap_fixable else "")
        raise RejectedRecord(
            f"{which} {value} is outside Singapore "
            f"({bounds[0]}..{bounds[1]}){detail}", where, swap_fixable)

    properties = feature.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise RejectedRecord("properties is not an object", where)

    attributes = _attributes_from_description(properties)
    # The HTML table is a serialisation of `attributes`; keeping both would
    # store every clinic twice, once unreadably.
    remainder = {k: v for k, v in properties.items()
                 if not (k == "Description" and attributes)}
    programmes = _first_present(attributes, PROGRAMME_KEYS)

    clinic = {
        "id": None,  # filled below, from content
        "longitude": str(longitude),
        "latitude": str(latitude),
        "name": _readable_name(attributes, properties),
        "address": _compose_address(attributes),
        "postal_code": _first_present(attributes, POSTAL_KEYS),
        "phone": _first_present(attributes, PHONE_KEYS),
        # A fact about the dataset. It says nothing about who qualifies.
        "programmes": ([p.strip() for p in programmes.split(",") if p.strip()]
                       if programmes else []),
        "attributes": attributes,
        "properties": remainder,
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
         "attributes": clinic["attributes"],
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

# A real government extract carries a few bad geocodes; the CHAS one has at
# least one point 16 km south of Singapore's southernmost island. Dropping those
# is right. Dropping a *lot* of them is not a dirty dataset, it is a parsing
# mistake wearing a dataset's clothes, and the difference has to be a number
# somebody chose on purpose rather than a feeling.
DEFAULT_MAX_REJECTED_RATIO = Decimal("0.02")

# How many rejects have to be swap-fixable before the whole file is treated as
# mis-ordered. One is enough: a correctly-ordered file does not contain a row
# that only makes sense reversed.
SWAP_FIXABLE_LIMIT = 0


def _refuse_if_systematic(rejected, total, max_rejected_ratio):
    """Tell a dirty dataset apart from a misread one, and refuse only the latter."""
    swapped = [bad for bad in rejected if bad.swap_fixable]
    if len(swapped) > SWAP_FIXABLE_LIMIT:
        raise InvalidInput(
            f"{len(swapped)} of {total} features are valid only if longitude "
            f"and latitude are exchanged, e.g. {swapped[0].where}: "
            f"{swapped[0].reason}. That is a coordinate order problem in the "
            f"whole file, not a bad row — refusing all of it, because the rows "
            f"that happen to look plausible are no more trustworthy than these")

    if not rejected:
        return
    ratio = Decimal(len(rejected)) / Decimal(total)
    if ratio > max_rejected_ratio:
        sample = "; ".join(f"{bad.where}: {bad.reason}" for bad in rejected[:3])
        raise InvalidInput(
            f"{len(rejected)} of {total} features rejected "
            f"({ratio:.1%}), above the {max_rejected_ratio:.1%} limit. That is "
            f"too many to call bad rows. Sample — {sample}")


def build_snapshot(geojson_text, as_of, source_url, dataset_id,
                   source_kind="dataset_download",
                   max_rejected_ratio=DEFAULT_MAX_REJECTED_RATIO):
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

    clinics, rejected = [], []
    for index, feature in enumerate(features):
        try:
            clinics.append(_clinic_from(feature, f"features[{index}]"))
        except RejectedRecord as bad:
            rejected.append(bad)

    _refuse_if_systematic(rejected, len(features), max_rejected_ratio)

    for bad in rejected:
        LOG.warning("dropped %s: %s", bad.where, bad.reason)

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
        "source_url": public_url(source_url),
        "source_kind": source_kind,
        "dataset_id": dataset_id,
        "attribution": ATTRIBUTION,
        "record_count": len(clinics),
        "features_in_source": len(features),
        "rejected_count": len(rejected),
        "rejected": [{"where": bad.where, "reason": bad.reason}
                     for bad in rejected],
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

    # Last check before bytes land in the plugin tree. The presigned download
    # URL carried AWS credentials once already, and a secret reaching this
    # directory is what gets a plugin rejected at install time rather than
    # caught in review.
    leak = SECRET_SHAPES.search(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    if leak is not None:
        raise InvalidInput(
            f"refusing to write: snapshot contains something credential-shaped "
            f"({leak.group(1)}). Nothing secret belongs in the plugin payload")

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
        "features_in_source": snapshot["features_in_source"],
        "rejected_count": snapshot["rejected_count"],
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
