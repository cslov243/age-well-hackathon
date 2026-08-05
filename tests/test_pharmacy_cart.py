"""Behaviour pinned for scripts/pharmacy_cart.py.

This script sits closer to a real-world harm than anything else in the repo.
It is the one that touches money and medicine at the same time, so the tests
are arranged around the four ways it could do damage rather than around the
happy path:

  * **Buying something that needed a prescription.** A medicine whose supply
    channel nobody recorded is *unknown*, and unknown never enters the cart.
    Defaulting an absent field to `general_sale` is the single change that
    would turn this script into the thing the product is positioned against,
    so the absent case is tested harder than either stated case.
  * **A confident wrong total.** One unpriced line suppresses the total
    entirely. Not a partial sum, not an estimate, not a "from" price. Mixed
    currencies are refused outright rather than added together.
  * **Checking out.** `requires_human_checkout` is a constant. No input can
    make it false, and nothing here calls anything.
  * **Ordering against a forecast that was edited.** The forecast's own audit
    hash is recomputed with `medication_runout.audit_hash_of` and compared —
    the same refusal `clinic_finder.py` applies to an edited snapshot.

The forecasts used below are produced by actually running
`medication_runout.forecast_runout`, never hand-written, so no test can pass
against a hash this file forged for itself.
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
          / "pharmacy_cart.py")

sys.path.insert(0, str(SCRIPT.parent))

import medication_runout  # noqa: E402
import pharmacy_cart  # noqa: E402

AS_OF = "2026-08-05"


def med(mid="metformin-500", *, name=None, quantity="60", doses_per_day=2,
        units_per_dose="1", form="tablet", lead_time_days=None,
        counted_on=None, prn=False):
    entry = {
        "id": mid,
        "name": name or mid,
        "form": form,
        "quantity_on_hand": quantity,
    }
    if prn:
        entry["schedule"] = {"mode": "prn"}
        return entry
    entry["schedule"] = {"mode": "fixed_daily",
                         "units_per_dose": units_per_dose,
                         "doses_per_day": doses_per_day}
    entry["count_basis"] = "doses_on_count_day_pending"
    if lead_time_days is not None:
        entry["lead_time_days"] = lead_time_days
    if counted_on is not None:
        entry["counted_on"] = counted_on
    return entry


def forecast_of(*medications, as_of=AS_OF, lead_time=7):
    """A real medication_runout.py result, hash and all."""
    return medication_runout.forecast_runout({
        "as_of": as_of,
        "default_lead_time_days": lead_time,
        "medications": list(medications),
    })


def buy(channel="general_sale", **extra):
    entry = {"supply_channel": channel}
    entry.update(extra)
    return entry


def request(forecast, purchase=None, *, cover_days=30, as_of=AS_OF, **extra):
    document = {
        "as_of": as_of,
        "forecast": forecast,
        "cover_days": cover_days,
        "purchase": {} if purchase is None else purchase,
    }
    document.update(extra)
    return document


def roundtrip(document):
    """Through JSON, the way the script actually receives it."""
    return json.loads(json.dumps(document), parse_float=Decimal)


def build(document):
    return pharmacy_cart.build_cart(roundtrip(document))


# A medicine that is due, general sale, priced, in packs of 30.
def simple():
    forecast = forecast_of(med(quantity="4", name="Metformin 500mg"))
    return request(forecast, {"metformin-500": buy(
        pack_size=30, pack_price="4.50", currency="SGD",
        source="caregiver, 4 Aug 2026")})


class InputValidationTests(unittest.TestCase):

    def test_a_non_object_is_refused(self):
        with self.assertRaises(pharmacy_cart.InvalidInput):
            pharmacy_cart.build_cart([])

    def test_an_unknown_top_level_key_is_refused(self):
        document = simple()
        document["cover_dayz"] = 30
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("cover_dayz", str(caught.exception))

    def test_forecast_is_required(self):
        document = simple()
        del document["forecast"]
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_purchase_is_required_even_when_empty(self):
        document = simple()
        del document["purchase"]
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("purchase", str(caught.exception))

    def test_an_empty_purchase_map_is_legal_and_carts_nothing(self):
        result = build(request(forecast_of(med(quantity="4")), {}))
        self.assertEqual(result["cart"]["items"], [])
        self.assertEqual(result["excluded"][0]["reason"],
                         "supply_channel_unknown")

    def test_cover_days_is_required(self):
        document = simple()
        del document["cover_days"]
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("cover_days", str(caught.exception))

    def test_cover_days_of_zero_is_refused(self):
        document = simple()
        document["cover_days"] = 0
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_cover_days_must_be_whole(self):
        document = simple()
        document["cover_days"] = "2.5"
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_a_purchase_id_matching_no_medication_is_refused(self):
        document = simple()
        document["purchase"]["metfromin-500"] = buy()
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("metfromin-500", str(caught.exception))

    def test_an_unknown_key_inside_a_purchase_entry_is_refused(self):
        document = simple()
        document["purchase"]["metformin-500"]["packsize"] = 30
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("packsize", str(caught.exception))

    def test_supply_channel_is_required_inside_a_purchase_entry(self):
        document = simple()
        del document["purchase"]["metformin-500"]["supply_channel"]
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("supply_channel", str(caught.exception))

    def test_an_unrecognised_supply_channel_is_refused_not_mapped(self):
        document = simple()
        document["purchase"]["metformin-500"]["supply_channel"] = "otc"
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("otc", str(caught.exception))

    def test_the_three_supply_channels_are_the_whole_vocabulary(self):
        self.assertEqual(
            set(pharmacy_cart.SUPPLY_CHANNELS),
            {"general_sale", "pharmacist_only", "prescription_only"})


class ForecastTests(unittest.TestCase):

    def test_an_edited_forecast_is_refused(self):
        forecast = forecast_of(med(quantity="4"))
        forecast["forecast"][0]["runs_out_on"] = "2026-09-30"
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(request(forecast, {"metformin-500": buy()}))
        self.assertIn("audit_hash", str(caught.exception))

    def test_a_forecast_with_no_audit_hash_is_refused(self):
        forecast = forecast_of(med(quantity="4"))
        del forecast["audit_hash"]
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(request(forecast, {"metformin-500": buy()}))

    def test_an_unedited_forecast_is_accepted(self):
        result = build(simple())
        self.assertEqual(len(result["cart"]["items"]), 1)

    def test_the_forecast_hash_is_recomputed_with_the_forecasters_own_code(self):
        # Not a copy of the algorithm: the same function, so the two can never
        # drift into disagreeing about what a forecast's hash is.
        forecast = forecast_of(med(quantity="4"))
        self.assertEqual(medication_runout.audit_hash_of(forecast),
                         forecast["audit_hash"])

    def test_a_forecast_dated_after_as_of_is_refused(self):
        forecast = forecast_of(med(quantity="4"), as_of="2026-08-20")
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(request(forecast, {"metformin-500": buy()}))
        self.assertIn("future", str(caught.exception))

    def test_a_forecast_older_than_the_window_is_flagged_and_still_used(self):
        forecast = forecast_of(med(quantity="400"), as_of="2026-07-01")
        result = build(request(forecast, {"metformin-500": buy()}))
        self.assertTrue(result["forecast"]["stale"])
        self.assertEqual(result["forecast"]["age_days"], 35)
        self.assertIn("35 days", result["summary"])

    def test_a_fresh_forecast_is_not_flagged(self):
        result = build(simple())
        self.assertFalse(result["forecast"]["stale"])
        self.assertEqual(result["forecast"]["age_days"], 0)

    def test_the_forecast_is_never_recomputed(self):
        # The dates in the cart are the forecast's dates, character for
        # character. A second implementation of the same arithmetic is a
        # second answer, and the two would disagree eventually.
        document = simple()
        forecast = document["forecast"]
        result = build(document)
        item = result["cart"]["items"][0]
        self.assertEqual(item["runs_out_on"],
                         forecast["forecast"][0]["runs_out_on"])
        self.assertEqual(item["order_by"], forecast["forecast"][0]["order_by"])
        self.assertEqual(item["status"], forecast["forecast"][0]["status"])

    def test_a_forecast_that_is_not_a_runout_result_is_refused(self):
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(request({"medications": []}, {}))


class SupplyChannelTests(unittest.TestCase):
    """The tests that stop a prescription medicine being bought online."""

    def test_a_prescription_only_item_never_enters_the_cart(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy("prescription_only")}))
        self.assertEqual(result["cart"]["items"], [])
        excluded = result["excluded"][0]
        self.assertEqual(excluded["reason"], "prescription_only")
        self.assertEqual(excluded["route"], "prescription_refill")

    def test_a_prescription_only_item_says_why_in_plain_words(self):
        result = build(request(
            forecast_of(med(quantity="4", name="Metformin 500mg")),
            {"metformin-500": buy("prescription_only")}))
        summary = result["excluded"][0]["summary"]
        self.assertIn("prescription", summary)
        self.assertIn("Metformin 500mg", summary)

    def test_a_pharmacist_only_item_never_enters_the_cart(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy("pharmacist_only")}))
        self.assertEqual(result["cart"]["items"], [])
        self.assertEqual(result["excluded"][0]["route"], "pharmacy_counter")

    def test_an_unrecorded_supply_channel_excludes_rather_than_assumes(self):
        # The whole cycle turns on this one. An absent field is unknown, and
        # unknown is not general sale.
        result = build(request(forecast_of(med(quantity="4")), {}))
        self.assertEqual(result["cart"]["items"], [])
        excluded = result["excluded"][0]
        self.assertEqual(excluded["reason"], "supply_channel_unknown")
        self.assertEqual(excluded["route"], "ask_caregiver")

    def test_an_unrecorded_channel_is_not_silently_dropped(self):
        result = build(request(forecast_of(med(quantity="4")), {}))
        self.assertIn("supply_channel", result["excluded"][0]["summary"])
        self.assertIn("not recorded", result["summary"])

    def test_a_price_does_not_rescue_a_prescription_item(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy("prescription_only", pack_size=30,
                                  pack_price="4.50", currency="SGD",
                                  source="caregiver")}))
        self.assertEqual(result["cart"]["items"], [])
        self.assertIsNone(result["cart"]["total"])

    def test_the_channel_is_reported_on_every_cart_item(self):
        result = build(simple())
        self.assertEqual(result["cart"]["items"][0]["supply_channel"],
                         "general_sale")


class SelectionTests(unittest.TestCase):

    def test_an_item_not_yet_due_is_excluded_with_its_order_by_date(self):
        forecast = forecast_of(med(quantity="400"))
        result = build(request(forecast, {"metformin-500": buy()}))
        self.assertEqual(result["cart"]["items"], [])
        excluded = result["excluded"][0]
        self.assertEqual(excluded["reason"], "not_due_yet")
        self.assertEqual(excluded["route"], "later_cart")
        # The date is the forecast's, rendered for a person to read — not a
        # second calculation of the same thing.
        self.assertEqual(forecast["forecast"][0]["order_by"], "2027-02-14")
        self.assertIn("14 Feb 2027", excluded["summary"])

    def test_an_overdue_item_is_carted(self):
        result = build(request(
            forecast_of(med(quantity="4", counted_on="2026-07-01")),
            {"metformin-500": buy()}))
        self.assertEqual(len(result["cart"]["items"]), 1)
        self.assertEqual(result["cart"]["items"][0]["status"], "no_supply")

    def test_a_prn_medicine_is_excluded_for_want_of_a_quantity(self):
        # PRN has no fixed daily rate, so nothing computed how many she needs.
        # Inventing one here is the same defect as inventing a price.
        result = build(request(
            forecast_of(med("paracetamol-500", prn=True)),
            {"paracetamol-500": buy()}))
        self.assertEqual(result["cart"]["items"], [])
        self.assertEqual(result["excluded"][0]["reason"],
                         "no_forecast_quantity")

    def test_a_prescription_channel_beats_not_due_yet(self):
        result = build(request(
            forecast_of(med(quantity="400")),
            {"metformin-500": buy("prescription_only")}))
        self.assertEqual(result["excluded"][0]["reason"], "prescription_only")

    def test_every_medication_lands_in_exactly_one_list(self):
        forecast = forecast_of(
            med("a", quantity="4"), med("b", quantity="400"),
            med("c", quantity="4"), med("d", prn=True))
        result = build(request(forecast, {
            "a": buy(), "b": buy(), "c": buy("prescription_only")}))
        ids = ([item["id"] for item in result["cart"]["items"]]
               + [row["id"] for row in result["excluded"]])
        self.assertEqual(sorted(ids), ["a", "b", "c", "d"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_counts_block_adds_up(self):
        forecast = forecast_of(med("a", quantity="4"), med("b", prn=True))
        result = build(request(forecast, {"a": buy()}))
        counts = result["counts"]
        self.assertEqual(counts["medications_in_forecast"], 2)
        self.assertEqual(counts["cart_items"] + counts["excluded"], 2)


class QuantityTests(unittest.TestCase):

    def test_units_needed_covers_the_requested_days(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy()}, cover_days=30))
        self.assertEqual(result["cart"]["items"][0]["units_needed"], 60)

    def test_a_fractional_daily_rate_rounds_the_quantity_up(self):
        # Half a tablet three times a day is 1.5 a day; five days is 7.5
        # tablets. She cannot buy half a tablet, and rounding down leaves her
        # a dose short on the last day.
        result = build(request(
            forecast_of(med(quantity="4", units_per_dose="0.5",
                            doses_per_day=3)),
            {"metformin-500": buy()}, cover_days=5))
        self.assertEqual(result["cart"]["items"][0]["units_needed"], 8)

    def test_an_exact_quantity_is_not_rounded_up_a_further_unit(self):
        result = build(request(
            forecast_of(med(quantity="4", doses_per_day=1)),
            {"metformin-500": buy()}, cover_days=10))
        self.assertEqual(result["cart"]["items"][0]["units_needed"], 10)

    def test_packs_round_up_and_the_order_is_stated_in_units(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy(pack_size=28)}, cover_days=30))
        item = result["cart"]["items"][0]
        self.assertEqual(item["units_needed"], 60)
        self.assertEqual(item["packs"], 3)
        self.assertEqual(item["units_ordered"], 84)

    def test_an_unknown_pack_size_orders_units_and_says_so(self):
        result = build(request(
            forecast_of(med(quantity="4")), {"metformin-500": buy()}))
        item = result["cart"]["items"][0]
        self.assertIsNone(item["pack_size"])
        self.assertIsNone(item["packs"])
        self.assertEqual(item["units_ordered"], item["units_needed"])
        self.assertIn("pack size", item["summary"])

    def test_a_pack_size_of_zero_is_refused(self):
        document = simple()
        document["purchase"]["metformin-500"]["pack_size"] = 0
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_a_fractional_pack_size_is_refused(self):
        document = simple()
        document["purchase"]["metformin-500"]["pack_size"] = "1.5"
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)


class PriceTests(unittest.TestCase):

    def test_a_pack_price_multiplies_by_packs_not_units(self):
        result = build(simple())          # 60 needed, packs of 30 at 4.50
        item = result["cart"]["items"][0]
        self.assertEqual(item["packs"], 2)
        self.assertEqual(item["line_total"], "9.00")
        self.assertEqual(result["cart"]["total"], "9.00")

    def test_a_unit_price_multiplies_by_units_ordered(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy(unit_price="0.15", currency="SGD",
                                  source="caregiver")}, cover_days=30))
        self.assertEqual(result["cart"]["items"][0]["line_total"], "9.00")

    def test_money_is_never_a_binary_float(self):
        document = simple()
        document["purchase"]["metformin-500"]["pack_price"] = 4.5
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            pharmacy_cart.build_cart(document)
        self.assertIn("float", str(caught.exception))

    def test_a_line_total_is_quantized_to_cents_half_up(self):
        result = build(request(
            forecast_of(med(quantity="4")),
            {"metformin-500": buy(unit_price="0.155", currency="SGD",
                                  source="caregiver")}, cover_days=15))
        # 30 units at 0.155 is 4.65 exactly.
        self.assertEqual(result["cart"]["items"][0]["line_total"], "4.65")

    def test_one_missing_price_suppresses_the_whole_total(self):
        forecast = forecast_of(med("a", quantity="4"), med("b", quantity="4"))
        result = build(request(forecast, {
            "a": buy(unit_price="0.15", currency="SGD", source="caregiver"),
            "b": buy()}))
        self.assertEqual(len(result["cart"]["items"]), 2)
        self.assertIsNone(result["cart"]["total"])
        self.assertIn("b", result["cart"]["total_suppressed_because"])

    def test_a_suppressed_total_is_not_a_partial_sum(self):
        forecast = forecast_of(med("a", quantity="4"), med("b", quantity="4"))
        result = build(request(forecast, {
            "a": buy(unit_price="0.15", currency="SGD", source="caregiver"),
            "b": buy()}))
        serialised = json.dumps(result)
        self.assertNotIn("4.50", serialised)
        self.assertIn("no price", result["summary"])

    def test_an_unpriced_item_still_appears_in_the_cart(self):
        result = build(request(
            forecast_of(med(quantity="4")), {"metformin-500": buy()}))
        self.assertEqual(len(result["cart"]["items"]), 1)
        self.assertIsNone(result["cart"]["items"][0]["price"])
        self.assertIsNone(result["cart"]["items"][0]["line_total"])

    def test_a_price_without_a_source_is_refused(self):
        document = simple()
        del document["purchase"]["metformin-500"]["source"]
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("source", str(caught.exception))

    def test_a_price_without_a_currency_is_refused(self):
        document = simple()
        del document["purchase"]["metformin-500"]["currency"]
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_two_currencies_are_refused_rather_than_added(self):
        forecast = forecast_of(med("a", quantity="4"), med("b", quantity="4"))
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(request(forecast, {
                "a": buy(unit_price="0.15", currency="SGD",
                         source="caregiver"),
                "b": buy(unit_price="0.15", currency="MYR",
                         source="caregiver")}))
        self.assertIn("MYR", str(caught.exception))

    def test_both_price_kinds_at_once_are_refused(self):
        document = simple()
        document["purchase"]["metformin-500"]["unit_price"] = "0.15"
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("unit_price", str(caught.exception))

    def test_a_pack_price_without_a_pack_size_is_refused(self):
        document = simple()
        del document["purchase"]["metformin-500"]["pack_size"]
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("pack_size", str(caught.exception))

    def test_a_negative_price_is_refused(self):
        document = simple()
        document["purchase"]["metformin-500"]["pack_price"] = "-4.50"
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_an_empty_cart_has_no_total_and_says_why(self):
        result = build(request(forecast_of(med(quantity="400")),
                               {"metformin-500": buy()}))
        self.assertIsNone(result["cart"]["total"])
        self.assertIsNone(result["cart"]["currency"])
        self.assertIn("empty", result["cart"]["total_suppressed_because"])


class CheckoutTests(unittest.TestCase):

    def test_requires_human_checkout_is_true(self):
        result = build(simple())
        self.assertIs(result["requires_human_checkout"], True)

    def test_requires_human_checkout_is_true_on_an_empty_cart_too(self):
        result = build(request(forecast_of(med(quantity="400")), {}))
        self.assertIs(result["requires_human_checkout"], True)

    def test_it_is_a_boolean_not_the_string_true(self):
        result = build(simple())
        self.assertIsInstance(result["requires_human_checkout"], bool)

    def test_nothing_in_the_source_places_an_order(self):
        source = SCRIPT.read_text(encoding="utf-8").lower()
        for banned in ("checkout(", "def pay", "def order(", "submit("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, source)

    def test_the_output_says_in_words_that_a_person_pays(self):
        result = build(simple())
        self.assertIn("pays", result["conventions"]["checkout"])


class PharmacyLinkTests(unittest.TestCase):

    def test_the_deep_link_is_copied_verbatim(self):
        document = simple()
        link = "https://pharmacy.example.sg/cart?ref=care-navigator"
        document["pharmacy"] = {"name": "Example Pharmacy", "deep_link": link}
        result = build(document)
        self.assertEqual(result["pharmacy"]["deep_link"], link)

    def test_a_missing_pharmacy_is_legal_and_reported_as_null(self):
        result = build(simple())
        self.assertIsNone(result["pharmacy"])
        self.assertIn("no pharmacy", result["summary"])

    def test_a_pharmacy_without_a_link_is_legal(self):
        document = simple()
        document["pharmacy"] = {"name": "Example Pharmacy"}
        result = build(document)
        self.assertIsNone(result["pharmacy"]["deep_link"])

    def test_a_pharmacy_without_a_name_is_refused(self):
        document = simple()
        document["pharmacy"] = {"deep_link": "https://example.sg/"}
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_a_plain_http_link_is_refused(self):
        document = simple()
        document["pharmacy"] = {"name": "P", "deep_link": "http://example.sg/"}
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("https", str(caught.exception))

    def test_a_javascript_link_is_refused(self):
        document = simple()
        document["pharmacy"] = {"name": "P",
                                "deep_link": "javascript:alert(1)"}
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_a_link_carrying_a_token_is_refused(self):
        document = simple()
        document["pharmacy"] = {
            "name": "P",
            "deep_link": "https://example.sg/cart?session_token=abc123"}
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("credential", str(caught.exception))

    def test_a_link_carrying_userinfo_is_refused(self):
        document = simple()
        document["pharmacy"] = {
            "name": "P", "deep_link": "https://user:pw@example.sg/cart"}
        with self.assertRaises(pharmacy_cart.InvalidInput):
            build(document)

    def test_an_unknown_key_in_the_pharmacy_block_is_refused(self):
        document = simple()
        document["pharmacy"] = {"name": "P", "card_number": "4111"}
        with self.assertRaises(pharmacy_cart.InvalidInput) as caught:
            build(document)
        self.assertIn("card_number", str(caught.exception))


class OutputTests(unittest.TestCase):

    def setUp(self):
        self.result = build(simple())

    def test_the_envelope_is_present(self):
        for key in ("tool_run_id", "issued_at", "audit_hash"):
            with self.subTest(key=key):
                self.assertIn(key, self.result)
        self.assertIn("+08:00", self.result["issued_at"])

    def test_the_audit_hash_replays(self):
        again = build(simple())
        self.assertNotEqual(self.result["tool_run_id"], again["tool_run_id"])
        self.assertEqual(self.result["audit_hash"], again["audit_hash"])

    def test_the_audit_hash_changes_when_the_cover_changes(self):
        other = build(request(
            simple()["forecast"],
            simple()["purchase"], cover_days=60))
        self.assertNotEqual(self.result["audit_hash"], other["audit_hash"])

    def test_the_audit_hash_covers_the_forecast_it_was_built_on(self):
        self.assertIn(self.result["forecast"]["audit_hash"],
                      json.dumps(pharmacy_cart._canonical(self.result)))

    def test_the_result_is_json_serialisable(self):
        json.dumps(self.result, ensure_ascii=False)

    def test_no_number_in_the_output_is_a_binary_float(self):
        def walk(node):
            if isinstance(node, float):
                self.fail(f"binary float in output: {node!r}")
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            if isinstance(node, list):
                for value in node:
                    walk(value)
        walk(self.result)

    def test_the_eligibility_vocabulary_never_appears(self):
        serialised = json.dumps(self.result, ensure_ascii=False).lower()
        for banned in ("likely eligible", "worth checking",
                       "insufficient information", "qualify", "eligib",
                       "subsid"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, serialised)

    def test_no_clinical_language_appears(self):
        serialised = json.dumps(self.result, ensure_ascii=False).lower()
        for banned in ("dose adjust", "you should take", "safe to",
                       "diagnos", "prescrib"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, serialised)

    def test_every_cart_item_summary_names_the_medicine_and_the_cover(self):
        item = self.result["cart"]["items"][0]
        self.assertIn("Metformin 500mg", item["summary"])
        self.assertIn("30 days", item["summary"])

    def test_the_summary_leads_with_what_is_needed_not_what_the_pack_holds(self):
        # "60 tablets to cover 30 days at 1 tablet a day" is a sentence whose
        # own arithmetic does not work, and a reader cannot tell which of the
        # two numbers is the wrong one.
        item = self.result["cart"]["items"][0]
        self.assertEqual(item["units_needed"], 60)
        self.assertEqual(item["units_ordered"], 60)
        self.assertIn("60 tablets needed to cover 30 days", item["summary"])

    def test_the_daily_rate_carries_its_unit(self):
        # A bare "at 2 a day" reads as a number of doses, not of tablets.
        self.assertIn("at 2 tablets a day",
                      self.result["cart"]["items"][0]["summary"])

    def test_a_daily_rate_of_one_is_singular(self):
        result = build(request(
            forecast_of(med(quantity="4", doses_per_day=1,
                            name="Amlodipine 5mg")),
            {"metformin-500": buy()}))
        summary = result["cart"]["items"][0]["summary"]
        self.assertIn("at 1 tablet a day", summary)
        self.assertNotIn("1 tablets", summary)

    def test_the_summary_reads_the_reasons_that_need_action_first(self):
        forecast = forecast_of(med("a", quantity="400", name="Alpha"),
                               med("b", quantity="4", name="Beta"))
        result = build(request(forecast, {
            "a": buy(), "b": buy("prescription_only")}))
        summary = result["summary"]
        self.assertLess(summary.index("prescription"), summary.index("Not due"))

    def test_a_single_day_of_cover_is_not_written_as_one_days(self):
        document = simple()
        document["cover_days"] = 1
        result = build(document)
        self.assertNotIn("1 days", json.dumps(result))

    def test_a_single_pack_is_not_written_as_one_packs(self):
        document = simple()
        document["cover_days"] = 10
        result = build(document)
        self.assertEqual(result["cart"]["items"][0]["packs"], 1)
        self.assertNotIn("1 packs", json.dumps(result))

    def test_the_conventions_block_states_each_rule_in_words(self):
        for key in ("quantity", "price", "total", "supply_channel",
                    "checkout", "freshness"):
            with self.subTest(key=key):
                self.assertGreater(len(self.result["conventions"][key]), 40)


class CommandLineTests(unittest.TestCase):

    def invoke(self, document, *args, stdin=None):
        payload = "" if stdin is not None else json.dumps(document)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin if stdin is not None else payload,
            capture_output=True, text=True)

    def test_stdin_to_stdout(self):
        done = self.invoke(simple())
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertIs(result["requires_human_checkout"], True)

    def test_logs_go_to_stderr_and_never_into_the_json(self):
        done = self.invoke(simple())
        json.loads(done.stdout)
        self.assertIn("INFO", done.stderr)

    def test_input_and_output_files(self):
        with TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "in.json"
            out_path = Path(tmp) / "out.json"
            in_path.write_text(json.dumps(simple()), encoding="utf-8")
            done = self.invoke(None, "--input", str(in_path),
                               "--output", str(out_path), stdin="")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "")
            result = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(result["cart"]["total"], "9.00")

    def test_bad_input_exits_non_zero_with_nothing_on_stdout(self):
        done = self.invoke({"cover_days": 30})
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("ERROR", done.stderr)

    def test_empty_stdin_is_refused(self):
        done = self.invoke(None, stdin="")
        self.assertEqual(done.returncode, 2)


class NoNetworkTests(unittest.TestCase):

    def test_the_script_imports_nothing_that_reaches_the_network(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for banned in ("urllib", "socket", "http.client", "requests",
                       "ssl", "smtplib"):
            with self.subTest(banned=banned):
                self.assertNotIn(f"import {banned}", source)


if __name__ == "__main__":
    unittest.main()
