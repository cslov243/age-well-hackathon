"""Behaviour pinned for tools/fetch_references.py.

This is the only file in the repo permitted to open a socket, so the tests are
arranged around that boundary rather than around the happy path:

  * the whole parse / validate / write path is exercised **offline**, against a
    fixture, so `python3 -m unittest discover -s tests` still runs with the
    network off — which is the property the README promises and a test executes;
  * the networking function is never called by the suite;
  * and a repo-wide guard asserts no skill script imports networking at all.
    "No network from any skill script, ever" is a CLAUDE.md hard constraint that
    until now lived only in prose.

The validation tests are where the value is. Two of them encode failure modes
that would produce a *plausible wrong answer* downstream rather than an error:

  * swapped coordinates. GeoJSON is [longitude, latitude]; getting it backwards
    puts every Singapore clinic in the Indian Ocean, and haversine will happily
    return a confident distance to it.
  * an empty dataset. A snapshot with no clinics makes the next script say
    "there are no clinics near you", which is a wrong answer dressed as a fact.

Both are refused at fetch time, because a bad snapshot written to disk is a bad
answer for every run until someone notices.
"""

import json
import re
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "fetch_references.py"
SKILL_SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"

sys.path.insert(0, str(REPO / "tools"))

import fetch_references as fr  # noqa: E402

# Two clinics in Singapore, [lon, lat] per RFC 7946. Property names are
# deliberately not the real ones: the CHAS schema is unverified in
# docs/DATA-SOURCES.md, and the fetcher must not depend on names nobody has
# confirmed.
FIXTURE = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [103.8558, 1.3329]},
         "properties": {"NAME": "Toa Payoh Clinic", "ADDR": "Blk 190"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [103.8198, 1.3521]},
         "properties": {"NAME": "Bishan Clinic", "ADDR": "Blk 505"}},
    ],
}

SOURCE = "https://example.invalid/chas.geojson"
DATASET = "d_548c33ea2d99e29ec63a7cc9edcccedc"


def build(payload=None, as_of="2026-08-04"):
    return fr.build_snapshot(json.dumps(payload or FIXTURE),
                             as_of=as_of, source_url=SOURCE,
                             dataset_id=DATASET)


class NetworkBoundaryTests(unittest.TestCase):
    """The hard constraint, finally enforced by something other than prose."""

    NETWORKING = re.compile(
        r"^\s*(?:import|from)\s+(urllib|http|socket|requests|ftplib|"
        r"telnetlib|smtplib|asyncio)\b", re.MULTILINE)

    def test_no_skill_script_imports_networking(self):
        for script in sorted(SKILL_SCRIPTS.glob("*.py")):
            with self.subTest(script=script.name):
                found = self.NETWORKING.search(
                    script.read_text(encoding="utf-8"))
                self.assertIsNone(
                    found,
                    f"{script.name} imports networking: {found.group(1) if found else ''}")

    def test_the_fetcher_is_not_in_the_plugin_tree(self):
        # It ships nowhere. A human runs it; no skill invokes it.
        self.assertTrue(TOOL.is_file(), f"missing {TOOL}")
        self.assertFalse((SKILL_SCRIPTS / TOOL.name).exists())

    def test_building_a_snapshot_needs_no_network(self):
        # If build_snapshot ever reaches for the wire, this fails loudly rather
        # than hanging on a socket in CI.
        original = fr.fetch
        fr.fetch = lambda *a, **k: self.fail("build_snapshot made a network call")
        try:
            build()
        finally:
            fr.fetch = original


class EnvelopeTests(unittest.TestCase):
    """The poll-download envelope: {code, data:{url}, errMsg}."""

    def test_extracts_the_download_url(self):
        self.assertEqual(
            fr.download_url_from({"code": 0, "data": {"url": SOURCE}}),
            SOURCE)

    def test_nonzero_code_is_a_failure_not_an_empty_result(self):
        with self.assertRaises(fr.InvalidInput):
            fr.download_url_from({"code": 1, "errMsg": "nope", "data": {}})

    def test_missing_code_is_refused(self):
        # Absent is not zero. A response without a code is not a success.
        with self.assertRaises(fr.InvalidInput):
            fr.download_url_from({"data": {"url": SOURCE}})

    def test_code_zero_without_a_url_is_refused(self):
        with self.assertRaises(fr.InvalidInput):
            fr.download_url_from({"code": 0, "data": {}})

    def test_envelope_must_be_an_object(self):
        for payload in ([], "ok", None, 0):
            with self.subTest(payload=payload):
                with self.assertRaises(fr.InvalidInput):
                    fr.download_url_from(payload)


class ValidationTests(unittest.TestCase):

    def test_rejects_a_non_featurecollection(self):
        with self.assertRaises(fr.InvalidInput):
            build({"type": "Feature", "features": []})

    def test_features_is_required_not_defaulted(self):
        # A misspelled key would otherwise write an empty snapshot and exit 0.
        with self.assertRaises(fr.InvalidInput):
            build({"type": "FeatureCollection"})

    def test_rejects_an_empty_dataset(self):
        # "There are no clinics near you" is a wrong answer dressed as a fact.
        with self.assertRaises(fr.InvalidInput):
            build({"type": "FeatureCollection", "features": []})

    def test_rejects_swapped_coordinates(self):
        swapped = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [1.3329, 103.8558]},
             "properties": {}}]}
        with self.assertRaises(fr.InvalidInput) as caught:
            build(swapped)
        self.assertIn("longitude", str(caught.exception).lower())

    def test_rejects_a_point_outside_singapore(self):
        far = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [0.0, 51.5]},
             "properties": {}}]}
        with self.assertRaises(fr.InvalidInput):
            build(far)

    def test_rejects_non_point_geometry(self):
        line = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [[103.8, 1.3], [103.9, 1.4]]},
             "properties": {}}]}
        with self.assertRaises(fr.InvalidInput):
            build(line)

    def test_rejects_a_null_geometry(self):
        null = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": None, "properties": {}}]}
        with self.assertRaises(fr.InvalidInput):
            build(null)

    def test_rejects_a_non_numeric_coordinate(self):
        bad = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": ["103.8", 1.33]},
             "properties": {}}]}
        with self.assertRaises(fr.InvalidInput):
            build(bad)

    def test_rejects_invalid_json(self):
        with self.assertRaises(fr.InvalidInput):
            fr.build_snapshot("{not json", as_of="2026-08-04",
                              source_url=SOURCE, dataset_id=DATASET)

    def test_rejects_a_bad_as_of(self):
        with self.assertRaises(fr.InvalidInput):
            build(as_of="4 August 2026")


def in_singapore(index):
    """A valid feature, nudged so every generated point is distinct."""
    offset = Decimal(index) / Decimal(10000)
    return {"type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [float(Decimal("103.80") + offset),
                                         float(Decimal("1.30") + offset)]},
            "properties": {"NAME": f"Clinic {index}"}}


def collection(features):
    return {"type": "FeatureCollection", "features": features}


class BadRecordTests(unittest.TestCase):
    """One bad row in a government dataset is not a reason to have no data.

    The CHAS extract really does contain a point 16 km south of Singapore's
    southernmost island. Refusing the whole file for it meant a single upstream
    geocoding error blocked the connector permanently — while a *systematic*
    error, like the whole file being [latitude, longitude], must still refuse
    everything. These tests pin the line between the two.
    """

    OUT_OF_BOUNDS = {
        "type": "Feature",
        "geometry": {"type": "Point",
                     "coordinates": [103.8558, 1.01626425482099]},
        "properties": {"NAME": "Somewhere at sea"}}

    def test_one_bad_record_is_dropped_and_the_rest_survive(self):
        snap = build(collection([in_singapore(i) for i in range(50)]
                                + [self.OUT_OF_BOUNDS]))
        self.assertEqual(snap["record_count"], 50)
        self.assertEqual(snap["rejected_count"], 1)
        self.assertNotIn("Somewhere at sea",
                         [c["name"] for c in snap["clinics"]])

    def test_the_drop_is_recorded_not_silent(self):
        snap = build(collection([in_singapore(i) for i in range(50)]
                                + [self.OUT_OF_BOUNDS]))
        self.assertTrue(snap["rejected"], "nothing recorded about the drop")
        reason = snap["rejected"][0]
        self.assertIn("latitude", reason["reason"].lower())
        self.assertIn("features[50]", reason["where"])

    def test_too_many_bad_records_still_refuses_everything(self):
        # A handful of bad geocodes is a dataset. A third of them is a parsing
        # mistake wearing a dataset's clothes.
        with self.assertRaises(fr.InvalidInput) as caught:
            build(collection([in_singapore(i) for i in range(10)]
                             + [self.OUT_OF_BOUNDS] * 5))
        self.assertIn("rejected", str(caught.exception).lower())

    def test_a_single_swapped_record_refuses_everything(self):
        # Swap-fixable is categorically different from out-of-range: it says
        # something parsed the file wrongly, so the other rows are not
        # trustworthy either, however few are visibly broken.
        swapped = {"type": "Feature",
                   "geometry": {"type": "Point",
                                "coordinates": [1.3329, 103.8558]},
                   "properties": {}}
        with self.assertRaises(fr.InvalidInput) as caught:
            build(collection([in_singapore(i) for i in range(200)] + [swapped]))
        self.assertIn("order", str(caught.exception).lower())

    def test_a_bad_record_does_not_change_the_ids_of_good_ones(self):
        good = [in_singapore(i) for i in range(50)]
        clean = build(collection(good))
        dirty = build(collection(good + [self.OUT_OF_BOUNDS]))
        self.assertEqual([c["id"] for c in clean["clinics"]],
                         [c["id"] for c in dirty["clinics"]])

    def test_the_content_hash_ignores_rejected_records(self):
        # The hash answers "did the clinics change". A row that never became a
        # clinic must not move it.
        good = [in_singapore(i) for i in range(50)]
        self.assertEqual(build(collection(good))["content_hash"],
                         build(collection(good + [self.OUT_OF_BOUNDS]))
                         ["content_hash"])

    def test_the_manifest_surfaces_the_rejected_count(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            snap = build(collection([in_singapore(i) for i in range(50)]
                                    + [self.OUT_OF_BOUNDS]))
            paths = fr.write_snapshot(snap, out)
            manifest = json.loads(
                next(p for p in paths if "manifest" in p.name)
                .read_text(encoding="utf-8"))
            self.assertEqual(manifest["rejected_count"], 1)


class SnapshotContentTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.snap = build()

    def test_record_count_matches(self):
        self.assertEqual(self.snap["record_count"], 2)
        self.assertEqual(len(self.snap["clinics"]), 2)

    def test_coordinates_are_strings_not_binary_floats(self):
        # Same reasoning as Decimal for money: the source's exact decimal text
        # survives the round trip, and nothing downstream inherits binary error
        # it did not ask for.
        for clinic in self.snap["clinics"]:
            with self.subTest(clinic=clinic["id"]):
                self.assertIsInstance(clinic["longitude"], str)
                self.assertIsInstance(clinic["latitude"], str)
        self.assertEqual(self.snap["clinics"][0]["longitude"].count("."), 1)

    def test_properties_are_carried_through_verbatim(self):
        # The CHAS schema is unverified. Renaming a field we have not seen is
        # guessing, so the source properties survive untouched.
        names = {json.dumps(c["properties"], sort_keys=True)
                 for c in self.snap["clinics"]}
        self.assertIn(json.dumps({"ADDR": "Blk 190", "NAME": "Toa Payoh Clinic"},
                                 sort_keys=True), names)

    def test_ids_are_content_derived_not_positional(self):
        # A positional id changes meaning when the upstream dataset reorders,
        # which would silently repoint every reference to a different clinic.
        reordered = {"type": "FeatureCollection",
                     "features": list(reversed(FIXTURE["features"]))}
        self.assertEqual([c["id"] for c in self.snap["clinics"]],
                         [c["id"] for c in build(reordered)["clinics"]])

    def test_clinics_are_sorted_deterministically(self):
        ids = [c["id"] for c in self.snap["clinics"]]
        self.assertEqual(ids, sorted(ids))

    def test_a_local_file_does_not_inherit_the_datasets_provenance(self):
        # The manifest carries a dataset_id even when --from-file was used, so
        # without this the snapshot would assert it came from data.gov.sg when
        # nothing verified that. Same rule as an unevidenced amount.
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "chas.geojson"
            src.write_text(json.dumps(FIXTURE), encoding="utf-8")
            out = Path(tmp) / "references"
            run = subprocess.run(
                [sys.executable, str(TOOL), "--from-file", str(src),
                 "--out-dir", str(out), "--as-of", "2026-08-04"],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            manifest = json.loads(
                (out / "chas-clinics-2026-08-04.manifest.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_kind"], "local_file")

    def test_source_kind_is_a_closed_set(self):
        with self.assertRaises(fr.InvalidInput):
            fr.build_snapshot(json.dumps(FIXTURE), as_of="2026-08-04",
                              source_url=SOURCE, dataset_id=DATASET,
                              source_kind="probably_fine")

    def test_singular_and_plural_read_correctly(self):
        # "1 tablets left over" shipped once. Tests do not read English, so
        # this one does.
        import logging
        one = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [103.8558, 1.3329]},
             "properties": {"MYSTERY": "x"}}]}
        with self.assertLogs("fetch_references", level=logging.WARNING) as logs:
            build(one)
        self.assertIn("1 of 1 clinics has no name", "\n".join(logs.output))

        two = {"type": "FeatureCollection", "features": [
            one["features"][0],
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [103.8198, 1.3521]},
             "properties": {"MYSTERY": "y"}}]}
        with self.assertLogs("fetch_references", level=logging.WARNING) as logs:
            build(two)
        self.assertIn("2 of 2 clinics have no name", "\n".join(logs.output))

    def test_carries_provenance_on_the_snapshot_itself(self):
        for field in ("source_url", "dataset_id", "as_of", "attribution"):
            with self.subTest(field=field):
                self.assertTrue(self.snap[field])
        self.assertIn("data.gov.sg", self.snap["attribution"])

    def test_content_hash_is_stable_across_runs(self):
        self.assertEqual(self.snap["content_hash"], build()["content_hash"])

    def test_content_hash_ignores_when_it_was_fetched(self):
        # Re-fetching unchanged data must produce the same hash, so the hash
        # answers "did the data change" rather than "did I run it again".
        later = build(as_of="2026-09-01")
        self.assertEqual(self.snap["content_hash"], later["content_hash"])
        self.assertNotEqual(self.snap["as_of"], later["as_of"])

    def test_content_hash_changes_when_a_clinic_changes(self):
        moved = json.loads(json.dumps(FIXTURE))
        moved["features"][0]["geometry"]["coordinates"] = [103.8, 1.3]
        self.assertNotEqual(self.snap["content_hash"],
                            build(moved)["content_hash"])

    def test_a_recognised_name_key_is_mapped(self):
        self.assertEqual(
            sorted(c["name"] for c in self.snap["clinics"]),
            ["Bishan Clinic", "Toa Payoh Clinic"])
        self.assertEqual(self.snap["clinics_without_mapped_name"], 0)

    def test_an_unrecognised_name_key_stays_null_and_is_counted(self):
        # The CHAS property schema is unverified. Until someone confirms it,
        # name stays null and the count says how many are waiting on that —
        # inventing a clinic name from an unconfirmed schema is the same class
        # of mistake as inventing a deadline.
        unknown = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [103.8558, 1.3329]},
             "properties": {"SOME_UNVERIFIED_KEY": "Toa Payoh Clinic"}}]}
        snap = build(unknown)
        self.assertIsNone(snap["clinics"][0]["name"])
        self.assertEqual(snap["clinics_without_mapped_name"], 1)
        # ...but the value is not lost, it is carried through verbatim.
        self.assertEqual(snap["clinics"][0]["properties"]["SOME_UNVERIFIED_KEY"],
                         "Toa Payoh Clinic")


class WriteTests(unittest.TestCase):

    def test_writes_a_dated_snapshot_and_a_manifest(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            written = fr.write_snapshot(build(), out)
            self.assertEqual(len(written), 2)
            for path in written:
                with self.subTest(path=path.name):
                    self.assertTrue(path.is_file())
                    json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(
                any("2026-08-04" in p.name for p in written),
                f"no dated filename in {[p.name for p in written]}")

    def test_refuses_to_overwrite_an_existing_snapshot(self):
        # Advancing state twice for one fetch is how a snapshot silently
        # becomes something other than what its manifest describes.
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            fr.write_snapshot(build(), out)
            with self.assertRaises(fr.InvalidInput):
                fr.write_snapshot(build(), out)

    def test_the_manifest_records_what_a_reader_needs(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = fr.write_snapshot(build(), out)
            manifest = json.loads(
                next(p for p in paths if "manifest" in p.name)
                .read_text(encoding="utf-8"))
            for field in ("as_of", "source_url", "dataset_id", "record_count",
                          "attribution", "content_hash", "snapshot_file"):
                with self.subTest(field=field):
                    self.assertIn(field, manifest)

    def test_written_files_are_utf8(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            for path in fr.write_snapshot(build(), out):
                path.read_text(encoding="utf-8")


class CommandLineTests(unittest.TestCase):
    """Runnable from a command line, with no network and no WorkBuddy."""

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args],
                              capture_output=True, text=True)

    def test_from_file_needs_no_network_and_exits_zero(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "chas.geojson"
            src.write_text(json.dumps(FIXTURE), encoding="utf-8")
            out = Path(tmp) / "references"
            run = self.run_tool("--from-file", str(src), "--out-dir", str(out),
                                "--as-of", "2026-08-04")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(list(out.glob("*.json"))), 2)

    def test_bad_input_exits_nonzero_without_writing(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.geojson"
            src.write_text('{"type": "FeatureCollection", "features": []}',
                           encoding="utf-8")
            out = Path(tmp) / "references"
            run = self.run_tool("--from-file", str(src), "--out-dir", str(out),
                                "--as-of", "2026-08-04")
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(list(out.glob("*.json")) if out.exists() else [])

    def test_out_dir_is_required_never_defaulted(self):
        # Every path is an argument; a relative default would write the
        # snapshot wherever the caller happened to be standing.
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "chas.geojson"
            src.write_text(json.dumps(FIXTURE), encoding="utf-8")
            self.assertNotEqual(self.run_tool("--from-file", str(src)).returncode,
                                0)

    def test_logs_go_to_stderr_and_never_into_the_snapshot(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "chas.geojson"
            src.write_text(json.dumps(FIXTURE), encoding="utf-8")
            out = Path(tmp) / "references"
            run = self.run_tool("--from-file", str(src), "--out-dir", str(out),
                                "--as-of", "2026-08-04")
            self.assertIn("INFO", run.stderr)
            for path in out.glob("*.json"):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
