"""Behaviour pinned for scripts/clinic_finder.py.

This script's failure mode is not an exception, it is a **plausible wrong
answer**. A haversine bug, a swapped coordinate pair or a silently stale
snapshot all produce a number that looks exactly like a right one, and it ends
up in a sentence telling an elderly woman how far she has to walk.

So the tests are arranged around the ways it can be confidently wrong:

  * a snapshot whose `content_hash` does not match its clinics — refused, not
    used, because a hand-edited snapshot is the one thing the fetcher's
    guarantees do not survive;
  * an origin with longitude and latitude exchanged, which puts the household
    somewhere off Sumatra and still returns a tidy ranked list;
  * a programme filter nobody spelled right, which would otherwise answer "no
    clinics near you" — a wrong answer dressed as a fact;
  * distance rounding that reorders the ranking, so the second-nearest clinic
    is presented as the nearest;
  * and the word "eligible" appearing anywhere in the output at all.

`programmes` is a fact recorded in a dataset. Nothing here decides who
qualifies for anything, and a test asserts the vocabulary never leaks in.
"""

import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
SCRIPT = (REPO / "skills" / "care-coordinator-toolkit" / "scripts"
          / "clinic_finder.py")

sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(REPO / "tools"))

import clinic_finder  # noqa: E402

ATTRIBUTION = "Ministry of Health, CHAS Clinics, data.gov.sg"

# Toa Payoh-ish. Every fixture point is placed relative to this one so the
# expected distances are readable rather than magic.
HOME_LON = "103.8500000"
HOME_LAT = "1.3320000"


def clinic(cid, longitude, latitude, *, name="A CLINIC", phone="61234567",
           address="1 SOMEWHERE ROAD, Singapore 123456",
           programmes=("CHAS",), postal_code="123456"):
    return {
        "id": cid,
        "longitude": longitude,
        "latitude": latitude,
        "name": name,
        "address": address,
        "postal_code": postal_code,
        "phone": phone,
        "programmes": list(programmes),
        "attributes": {},
        "properties": {},
    }


def snapshot(clinics, *, as_of="2026-08-04", content_hash=None,
             record_type="ClinicSnapshot"):
    body = {
        "record_type": record_type,
        "as_of": as_of,
        "fetched_at": f"{as_of}T09:00:00+08:00",
        "source_url": ("https://s3.ap-southeast-1.amazonaws.com/"
                       "blobs.data.gov.sg/d_548c.geojson"),
        "source_kind": "dataset_download",
        "dataset_id": "d_548c33ea2d99e29ec63a7cc9edcccedc",
        "attribution": ATTRIBUTION,
        "record_count": len(clinics),
        "features_in_source": len(clinics),
        "rejected_count": 0,
        "rejected": [],
        "clinics_without_mapped_name": 0,
        "coordinate_reference_system": "CRS84 (WGS 84, longitude/latitude)",
        "conventions": {},
        "clinics": clinics,
    }
    body["content_hash"] = (content_hash if content_hash is not None
                            else clinic_finder.content_hash_of(clinics))
    return body


class Fixture:
    """A temporary directory holding one snapshot file."""

    def __init__(self, case, clinics, **kwargs):
        self.dir = TemporaryDirectory()
        case.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "chas-clinics.json"
        self.body = snapshot(clinics, **kwargs)
        self.write(self.body)

    def write(self, body):
        self.path.write_text(json.dumps(body, ensure_ascii=False),
                             encoding="utf-8")


def request(fixture, **overrides):
    document = {
        "as_of": "2026-08-05",
        "snapshot_path": str(fixture.path),
        "origin": {"longitude": HOME_LON, "latitude": HOME_LAT,
                   "label": "Blk 123 Lorong 1 Toa Payoh"},
        "limit": 3,
    }
    document.update(overrides)
    return document


def run(fixture, **overrides):
    return clinic_finder.find_clinics(request(fixture, **overrides))


def one_clinic(case, **kwargs):
    return Fixture(case, [clinic("clinic-aaa", "103.8550000", "1.3320000",
                                 **kwargs)])


def texts(result):
    """Every string the script emits, so a vocabulary check can read all of it."""
    return json.dumps(result, ensure_ascii=False)


# --------------------------------------------------------------------------


class InputValidationTests(unittest.TestCase):

    def test_input_must_be_an_object(self):
        with self.assertRaises(clinic_finder.InvalidInput):
            clinic_finder.find_clinics([])

    def test_snapshot_path_is_required(self):
        fixture = one_clinic(self)
        document = request(fixture)
        del document["snapshot_path"]
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            clinic_finder.find_clinics(document)
        self.assertIn("snapshot_path", str(caught.exception))

    def test_a_missing_snapshot_file_is_refused_by_name(self):
        fixture = one_clinic(self)
        missing = fixture.path.parent / "not-here.json"
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, snapshot_path=str(missing))
        self.assertIn("not-here.json", str(caught.exception))

    def test_origin_is_required(self):
        fixture = one_clinic(self)
        document = request(fixture)
        del document["origin"]
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            clinic_finder.find_clinics(document)
        self.assertIn("origin", str(caught.exception))

    def test_origin_needs_both_coordinates(self):
        fixture = one_clinic(self)
        with self.assertRaises(clinic_finder.InvalidInput):
            run(fixture, origin={"longitude": HOME_LON})
        with self.assertRaises(clinic_finder.InvalidInput):
            run(fixture, origin={"latitude": HOME_LAT})

    def test_an_exchanged_origin_says_so_rather_than_just_out_of_range(self):
        # 1.332, 103.85 is off Sumatra. Ranking against it succeeds and returns
        # confident nonsense, so the message has to name the actual mistake.
        fixture = one_clinic(self)
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, origin={"longitude": HOME_LAT, "latitude": HOME_LON})
        message = str(caught.exception).lower()
        self.assertIn("exchang", message)

    def test_an_origin_outside_singapore_is_refused(self):
        fixture = one_clinic(self)
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, origin={"longitude": "100.5018", "latitude": "13.7563"})
        self.assertIn("outside", str(caught.exception))

    def test_a_binary_float_coordinate_is_refused_not_coerced(self):
        fixture = one_clinic(self)
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, origin={"longitude": 103.85, "latitude": 1.332})
        self.assertIn("float", str(caught.exception))

    def test_neither_limit_nor_radius_is_refused(self):
        fixture = one_clinic(self)
        document = request(fixture)
        del document["limit"]
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            clinic_finder.find_clinics(document)
        self.assertIn("radius_metres", str(caught.exception))

    def test_limit_must_be_a_positive_whole_number(self):
        fixture = one_clinic(self)
        for bad in (0, -1, "2.5", True):
            with self.subTest(limit=bad):
                with self.assertRaises(clinic_finder.InvalidInput):
                    run(fixture, limit=bad)

    def test_radius_must_be_positive(self):
        fixture = one_clinic(self)
        document = request(fixture)
        del document["limit"]
        for bad in ("0", "-50"):
            with self.subTest(radius=bad):
                with self.assertRaises(clinic_finder.InvalidInput):
                    clinic_finder.find_clinics(
                        dict(document, radius_metres=bad))

    def test_as_of_must_be_an_iso_date(self):
        fixture = one_clinic(self)
        with self.assertRaises(clinic_finder.InvalidInput):
            run(fixture, as_of="5 August 2026")


class SnapshotTests(unittest.TestCase):

    def test_a_tampered_snapshot_is_refused(self):
        fixture = one_clinic(self)
        body = fixture.body
        body["clinics"][0]["latitude"] = "1.4000000"
        fixture.write(body)
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture)
        self.assertIn("content_hash", str(caught.exception))

    def test_a_missing_content_hash_is_refused(self):
        fixture = one_clinic(self)
        body = fixture.body
        del body["content_hash"]
        fixture.write(body)
        with self.assertRaises(clinic_finder.InvalidInput):
            run(fixture)

    def test_the_wrong_record_type_is_refused(self):
        clinics = [clinic("clinic-aaa", "103.8550000", "1.3320000")]
        fixture = Fixture(self, clinics, record_type="MedicationRecord")
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture)
        self.assertIn("ClinicSnapshot", str(caught.exception))

    def test_a_snapshot_with_no_clinics_is_refused(self):
        fixture = Fixture(self, [])
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture)
        self.assertIn("no clinics", str(caught.exception))

    def test_a_missing_clinics_key_is_refused(self):
        fixture = one_clinic(self)
        body = fixture.body
        del body["clinics"]
        fixture.write(body)
        with self.assertRaises(clinic_finder.InvalidInput):
            run(fixture)

    def test_a_snapshot_that_is_not_json_is_refused(self):
        fixture = one_clinic(self)
        fixture.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture)
        self.assertIn("JSON", str(caught.exception))

    def test_a_snapshot_dated_after_as_of_is_refused(self):
        clinics = [clinic("clinic-aaa", "103.8550000", "1.3320000")]
        fixture = Fixture(self, clinics, as_of="2026-09-01")
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, as_of="2026-08-05")
        self.assertIn("future", str(caught.exception))

    def test_a_clinic_outside_singapore_is_refused_by_id(self):
        clinics = [clinic("clinic-bad", "103.8550000", "1.0162642")]
        fixture = Fixture(self, clinics)
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture)
        self.assertIn("clinic-bad", str(caught.exception))

    def test_thirty_days_is_fresh_and_thirty_one_is_stale(self):
        clinics = [clinic("clinic-aaa", "103.8550000", "1.3320000")]
        fresh = Fixture(self, clinics, as_of="2026-07-06")
        self.assertFalse(run(fresh, as_of="2026-08-05")["snapshot"]["stale"])
        stale = Fixture(self, clinics, as_of="2026-07-05")
        result = run(stale, as_of="2026-08-05")
        self.assertTrue(result["snapshot"]["stale"])
        self.assertEqual(result["snapshot"]["age_days"], 31)

    def test_a_stale_snapshot_is_still_used_and_still_answers(self):
        clinics = [clinic("clinic-aaa", "103.8550000", "1.3320000")]
        stale = Fixture(self, clinics, as_of="2026-01-01")
        result = run(stale, as_of="2026-08-05")
        self.assertEqual(len(result["nearest"]), 1)
        self.assertIn("as of", result["snapshot"]["citation"])

    def test_content_hash_agrees_with_the_fetcher_that_writes_it(self):
        # Two implementations of the same hash in two trees that must never
        # depend on each other: the plugin cannot import from tools/.
        import fetch_references

        clinics = [clinic("clinic-aaa", "103.8550000", "1.3320000"),
                   clinic("clinic-bbb", "103.8600000", "1.3330000")]
        self.assertEqual(clinic_finder.content_hash_of(clinics),
                         fetch_references._content_hash(clinics))


class HaversineTests(unittest.TestCase):

    def test_a_point_is_zero_metres_from_itself(self):
        self.assertEqual(
            clinic_finder.haversine_metres(Decimal("103.85"), Decimal("1.332"),
                                           Decimal("103.85"), Decimal("1.332")),
            0.0)

    def test_one_degree_of_latitude_is_about_111_kilometres(self):
        metres = clinic_finder.haversine_metres(
            Decimal("103.85"), Decimal("1.0"), Decimal("103.85"), Decimal("2.0"))
        self.assertAlmostEqual(metres, 111194.9, delta=1.0)

    def test_a_degree_of_longitude_shrinks_with_latitude(self):
        at_equator = clinic_finder.haversine_metres(
            Decimal("103.0"), Decimal("0.0"), Decimal("104.0"), Decimal("0.0"))
        near_singapore = clinic_finder.haversine_metres(
            Decimal("103.0"), Decimal("1.35"), Decimal("104.0"), Decimal("1.35"))
        self.assertLess(near_singapore, at_equator)
        self.assertAlmostEqual(near_singapore, 111164.0, delta=5.0)

    def test_distance_is_symmetric(self):
        forward = clinic_finder.haversine_metres(
            Decimal("103.85"), Decimal("1.332"),
            Decimal("103.90"), Decimal("1.360"))
        backward = clinic_finder.haversine_metres(
            Decimal("103.90"), Decimal("1.360"),
            Decimal("103.85"), Decimal("1.332"))
        self.assertEqual(forward, backward)

    def test_rounding_goes_to_the_nearest_ten_metres(self):
        for raw, expected in ((0.0, 0), (4.9, 0), (5.0, 10), (421.0, 420),
                              (424.999, 420), (425.0, 430), (1337.0, 1340)):
            with self.subTest(raw=raw):
                self.assertEqual(clinic_finder.round_to_10m(raw), expected)


class RankingTests(unittest.TestCase):

    def build(self):
        # Spaced east of home so distance grows with the letter.
        return Fixture(self, [
            clinic("clinic-ccc", "103.8590000", "1.3320000", name="FAR"),
            clinic("clinic-aaa", "103.8510000", "1.3320000", name="NEAR"),
            clinic("clinic-bbb", "103.8550000", "1.3320000", name="MIDDLE"),
        ])

    def test_results_are_ordered_nearest_first(self):
        result = run(self.build())
        self.assertEqual([c["name"] for c in result["nearest"]],
                         ["NEAR", "MIDDLE", "FAR"])

    def test_ranks_are_one_based_and_contiguous(self):
        result = run(self.build())
        self.assertEqual([c["rank"] for c in result["nearest"]], [1, 2, 3])

    def test_limit_truncates_after_ranking(self):
        result = run(self.build(), limit=2)
        self.assertEqual([c["name"] for c in result["nearest"]],
                         ["NEAR", "MIDDLE"])

    def test_a_limit_larger_than_the_snapshot_is_not_an_error(self):
        result = run(self.build(), limit=50)
        self.assertEqual(len(result["nearest"]), 3)

    def test_radius_excludes_and_counts_what_remains(self):
        document = request(self.build(), radius_metres="600")
        del document["limit"]
        result = clinic_finder.find_clinics(document)
        self.assertEqual([c["name"] for c in result["nearest"]],
                         ["NEAR", "MIDDLE"])
        self.assertEqual(result["clinics_within_radius"], 2)
        self.assertEqual(result["clinics_considered"], 3)

    def test_limit_and_radius_both_apply(self):
        result = run(self.build(), limit=1, radius_metres="600")
        self.assertEqual([c["name"] for c in result["nearest"]], ["NEAR"])
        self.assertEqual(result["clinics_within_radius"], 2)

    def test_ties_are_broken_by_id_so_the_order_is_stable(self):
        fixture = Fixture(self, [
            clinic("clinic-zzz", "103.8550000", "1.3320000", name="Z"),
            clinic("clinic-aaa", "103.8550000", "1.3320000", name="A"),
        ])
        self.assertEqual([c["name"] for c in run(fixture)["nearest"]],
                         ["A", "Z"])

    def test_rounding_never_reorders_the_ranking(self):
        # Both of these round to the same displayed distance. The nearer one
        # must still be presented first.
        fixture = Fixture(self, [
            clinic("clinic-zzz", "103.8501000", "1.3320000", name="NEARER"),
            clinic("clinic-aaa", "103.8501200", "1.3320000", name="FARTHER"),
        ])
        result = run(fixture)
        self.assertEqual([c["name"] for c in result["nearest"]],
                         ["NEARER", "FARTHER"])
        self.assertEqual(result["nearest"][0]["distance_metres"],
                         result["nearest"][1]["distance_metres"])

    def test_nothing_within_the_radius_reports_the_nearest_one_beyond_it(self):
        result = run(self.build(), radius_metres="10", limit=3)
        self.assertEqual(result["nearest"], [])
        beyond = result["nearest_beyond_radius"]
        self.assertEqual(beyond["name"], "NEAR")
        self.assertIn("nearest", result["summary"].lower())

    def test_the_radius_test_is_inclusive_and_uses_the_unrounded_distance(self):
        # NEAR sits at 111.19 m unrounded and displays as 110 m. A radius of
        # 111 must exclude it and 112 must keep it: the display rounding is not
        # allowed to decide membership in either direction.
        fixture = Fixture(self, [
            clinic("clinic-aaa", "103.8510000", "1.3320000", name="NEAR")])
        self.assertEqual(run(fixture, radius_metres="112")["nearest"][0]
                         ["distance_metres"], 110)
        self.assertEqual(run(fixture, radius_metres="111")["nearest"], [])

    def test_the_one_beyond_the_radius_is_not_ranked_first(self):
        result = run(self.build(), radius_metres="10")
        self.assertIsNone(result["nearest_beyond_radius"]["rank"])

    def test_a_misspelled_key_is_refused_rather_than_ignored(self):
        fixture = self.build()
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(fixture, radius=600)
        self.assertIn("radius_metres", str(caught.exception))

    def test_nearest_beyond_radius_is_null_when_something_was_found(self):
        result = run(self.build(), radius_metres="600")
        self.assertIsNone(result["nearest_beyond_radius"])

    def test_nearest_beyond_radius_is_null_when_no_radius_was_asked_for(self):
        result = run(self.build())
        self.assertIsNone(result["nearest_beyond_radius"])


class ProgrammeFilterTests(unittest.TestCase):

    def build(self):
        return Fixture(self, [
            clinic("clinic-aaa", "103.8510000", "1.3320000", name="NEAR",
                   programmes=("CDMP",)),
            clinic("clinic-bbb", "103.8550000", "1.3320000", name="MIDDLE",
                   programmes=("CHAS", "CDMP")),
        ])

    def test_the_filter_keeps_only_matching_clinics(self):
        result = run(self.build(), programme="CHAS")
        self.assertEqual([c["name"] for c in result["nearest"]], ["MIDDLE"])
        self.assertEqual(result["clinics_considered"], 1)

    def test_the_filter_is_case_insensitive(self):
        result = run(self.build(), programme="chas")
        self.assertEqual([c["name"] for c in result["nearest"]], ["MIDDLE"])

    def test_a_programme_nobody_has_is_refused_not_answered_with_nothing(self):
        with self.assertRaises(clinic_finder.InvalidInput) as caught:
            run(self.build(), programme="CHASS")
        message = str(caught.exception)
        self.assertIn("CHASS", message)
        self.assertIn("none", message.lower())


class OutputTests(unittest.TestCase):

    def build(self):
        return Fixture(self, [
            clinic("clinic-aaa", "103.8510000", "1.3320000", name="NEAR"),
            clinic("clinic-bbb", "103.8550000", "1.3320000", name="MIDDLE"),
        ])

    def test_the_envelope_is_present(self):
        result = run(self.build())
        for key in ("tool_run_id", "issued_at", "audit_hash"):
            self.assertIn(key, result)
        self.assertTrue(result["issued_at"].endswith("+08:00"))

    def test_the_audit_hash_replays(self):
        # Two identical snapshots in two different temporary directories. The
        # hash certifies the data, not where one machine kept the file.
        first, second = run(self.build()), run(self.build())
        self.assertNotEqual(first["snapshot"]["path"],
                            second["snapshot"]["path"])
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])
        self.assertEqual(first["audit_hash"], second["audit_hash"])
        self.assertEqual(clinic_finder.audit_hash_of(first),
                         first["audit_hash"])

    def test_the_audit_hash_covers_the_computed_distances(self):
        near = run(self.build())
        far = run(self.build(), origin={"longitude": "103.9000000",
                                        "latitude": "1.3320000",
                                        "label": "somewhere else"})
        self.assertNotEqual(near["audit_hash"], far["audit_hash"])

    def test_every_record_carries_the_snapshot_date_and_source(self):
        result = run(self.build())
        for record in result["nearest"]:
            self.assertEqual(record["snapshot_as_of"], "2026-08-04")
            self.assertTrue(record["source_url"].startswith("https://"))

    def test_the_citation_names_the_attribution_and_the_date(self):
        citation = run(self.build())["snapshot"]["citation"]
        self.assertIn(ATTRIBUTION, citation)
        self.assertIn("4 Aug 2026", citation)

    def test_conventions_say_straight_line_and_deny_a_route(self):
        conventions = run(self.build())["conventions"]
        blob = json.dumps(conventions).lower()
        self.assertIn("straight-line", blob)
        self.assertIn("not a walking distance", blob)
        self.assertIn("10 m", json.dumps(conventions))

    def test_every_clinic_summary_says_the_distance_is_not_a_route(self):
        for record in run(self.build())["nearest"]:
            self.assertIn("straight line", record["summary"])

    def test_the_eligibility_vocabulary_never_appears(self):
        blob = texts(run(self.build())).lower()
        for banned in ("likely eligible", "worth checking",
                       "insufficient information", "qualify", "eligib",
                       "subsid"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, blob)

    def test_programmes_are_reported_as_a_dataset_fact(self):
        record = run(self.build())["nearest"][0]
        self.assertEqual(record["programmes"], ["CHAS"])
        self.assertIn("dataset", record["summary"])

    def test_an_unnamed_clinic_does_not_render_as_none(self):
        fixture = Fixture(self, [
            clinic("clinic-aaa", "103.8510000", "1.3320000", name=None,
                   address=None, phone=None)])
        record = run(fixture)["nearest"][0]
        self.assertIsNone(record["name"])
        self.assertNotIn("None", record["summary"])
        self.assertIn("does not name", record["summary"])

    def test_a_missing_phone_is_not_invented(self):
        fixture = Fixture(self, [
            clinic("clinic-aaa", "103.8510000", "1.3320000", phone=None)])
        record = run(fixture)["nearest"][0]
        self.assertIsNone(record["phone"])
        self.assertNotIn("Phone", record["summary"])

    def test_the_summary_says_how_many_the_limit_left_out(self):
        # "the 1 nearest clinic" inside a radius holding 2 reads, in a family
        # artifact, as if there were only one.
        result = run(self.build(), limit=1, radius_metres="600")
        self.assertIn("2 clinics in all are within 600 m", result["summary"])

    def test_the_summary_does_not_claim_a_count_no_radius_was_asked_for(self):
        result = run(self.build(), limit=1)
        self.assertNotIn("in all are within", result["summary"])

    def test_the_summary_counts_what_was_actually_returned(self):
        result = run(self.build(), limit=1)
        self.assertIn("1 clinic", result["summary"])
        self.assertNotIn("1 clinics", result["summary"])


class CommandLineTests(unittest.TestCase):

    def invoke(self, document, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin if stdin is not None else json.dumps(document),
            capture_output=True, text=True)

    def build(self):
        return Fixture(self, [clinic("clinic-aaa", "103.8510000", "1.3320000")])

    def test_stdin_to_stdout(self):
        done = self.invoke(request(self.build()))
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(len(result["nearest"]), 1)

    def test_logs_go_to_stderr_and_never_into_the_json(self):
        done = self.invoke(request(self.build()))
        json.loads(done.stdout)          # would raise if a log leaked in
        self.assertIn("clinic_finder", done.stderr)

    def test_input_and_output_files_round_trip(self):
        with TemporaryDirectory() as work:
            in_path = Path(work) / "in.json"
            out_path = Path(work) / "out.json"
            in_path.write_text(json.dumps(request(self.build())),
                               encoding="utf-8")
            done = self.invoke(None, "--input", str(in_path),
                               "--output", str(out_path), stdin="")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "")
            result = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(result["nearest"][0]["rank"], 1)

    def test_bad_input_exits_non_zero_with_nothing_on_stdout(self):
        done = self.invoke({"origin": {}})
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("ERROR", done.stderr)

    def test_empty_stdin_is_refused(self):
        done = self.invoke(None, stdin="")
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
