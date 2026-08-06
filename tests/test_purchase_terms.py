"""Behaviour pinned for scripts/purchase_terms.py.

This script exists to keep one decision away from the model: **whether a
medicine can be bought off a shelf.** `pharmacy_cart.py` already refuses to
guess it, but something has to build the `purchase` map it reads, and if that
something is a model transcribing a field by hand then the guard is only as good
as the transcription. A hallucinated `general_sale` puts a prescription medicine
in a shopping cart, and no downstream check can catch it, because the cart has
no way to know it was told a lie.

So the assertions that matter here are the refusals and the omissions, not the
happy path:

  * a medicine with no `supply_channel` recorded is **left out of the map**, and
    is never given one;
  * an unrecognised channel raises rather than being mapped to the nearest one;
  * a `purchase` block recorded against a medicine whose channel is unknown
    raises, because a price nobody will ever use is the "accepted but never
    used" pattern that has already cost this repo a cycle;
  * a price without a currency, or without a source, raises. This script looks
    nothing up, so an unsourced price is one somebody remembered.

The output feeds `pharmacy_cart.py` verbatim, so the last class round-trips the
two: whatever this emits, the cart must accept without a second opinion.
"""

import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "care-coordinator-toolkit" / "scripts"

sys.path.insert(0, str(SCRIPTS))

import medication_runout  # noqa: E402
import pharmacy_cart  # noqa: E402
import purchase_terms  # noqa: E402

InvalidInput = purchase_terms.InvalidInput


def med(mid="calcium-d", name="Calcium with vitamin D", form="tablet",
        quantity="60", channel="general_sale", buy=None, prn=False, **extra):
    """One MedicationRecord entry. `channel=None` means none was recorded."""
    entry = {"id": mid, "name": name, "form": form,
             "quantity_on_hand": quantity}
    if prn:
        entry["schedule"] = {"mode": "prn"}
    else:
        entry["schedule"] = {"mode": "fixed_daily",
                             "units_per_dose": "1", "doses_per_day": 1}
        entry["count_basis"] = "doses_on_count_day_pending"
    if channel is not None:
        entry["supply_channel"] = channel
    if buy is not None:
        entry["purchase"] = buy
    entry.update(extra)
    return entry


def document(*medications, **top):
    doc = {"as_of": "2026-08-05", "default_lead_time_days": 7,
           "medications": list(medications)}
    doc.update(top)
    return doc


def build(*medications, **top):
    return purchase_terms.build_terms(document(*medications, **top))


def priced(pack_size=60, pack_price="12.90", currency="SGD",
           source="caregiver checked the receipt, 4 Aug 2026"):
    block = {}
    if pack_size is not None:
        block["pack_size"] = pack_size
    if pack_price is not None:
        block["pack_price"] = pack_price
    if currency is not None:
        block["currency"] = currency
    if source is not None:
        block["source"] = source
    return block


class InputValidationTests(unittest.TestCase):

    def test_a_non_object_is_refused(self):
        for payload in ([], "medications", 7, None):
            with self.subTest(payload=payload):
                with self.assertRaises(InvalidInput):
                    purchase_terms.build_terms(payload)

    def test_medications_is_required_even_though_empty_is_legal(self):
        # A typo'd key would otherwise exit 0 having built an empty map, which
        # reads exactly like a household that records no supply channels.
        with self.assertRaises(InvalidInput) as caught:
            purchase_terms.build_terms({"default_lead_time_days": 7})
        self.assertIn("medications", str(caught.exception))

    def test_an_empty_medication_list_is_legal(self):
        result = purchase_terms.build_terms({"medications": []})
        self.assertEqual(result["purchase"], {})
        self.assertEqual(result["counts"]["medications"], 0)

    def test_medications_must_be_a_list(self):
        with self.assertRaises(InvalidInput):
            purchase_terms.build_terms({"medications": {"calcium-d": {}}})

    def test_a_medication_must_be_an_object(self):
        with self.assertRaises(InvalidInput):
            purchase_terms.build_terms({"medications": ["calcium-d"]})

    def test_id_is_required(self):
        entry = med()
        del entry["id"]
        with self.assertRaises(InvalidInput) as caught:
            build(entry)
        self.assertIn("id", str(caught.exception))

    def test_name_is_required(self):
        entry = med()
        del entry["name"]
        with self.assertRaises(InvalidInput) as caught:
            build(entry)
        self.assertIn("name", str(caught.exception))

    def test_a_duplicate_id_is_refused(self):
        # Two rows keyed the same silently lose one, and which one survives
        # depends on iteration order.
        with self.assertRaises(InvalidInput) as caught:
            build(med(mid="calcium-d"), med(mid="calcium-d", name="Other"))
        self.assertIn("calcium-d", str(caught.exception))

    def test_a_blank_id_is_refused(self):
        with self.assertRaises(InvalidInput):
            build(med(mid="   "))

    def test_unknown_top_level_keys_are_ignored_not_refused(self):
        # This script does not own household/medication.json. Refusing a key
        # medication_runout.py adds would break the two apart on the next
        # contract change.
        result = build(med(), some_future_field={"added": "later"})
        self.assertIn("calcium-d", result["purchase"])


class SupplyChannelTests(unittest.TestCase):
    """The one decision this script exists to take away from the model."""

    def test_a_recorded_channel_is_carried_through_verbatim(self):
        for channel in purchase_terms.SUPPLY_CHANNELS:
            with self.subTest(channel=channel):
                result = build(med(channel=channel))
                self.assertEqual(
                    result["purchase"]["calcium-d"]["supply_channel"], channel)

    def test_no_channel_recorded_means_left_out_of_the_map(self):
        result = build(med(channel=None))
        self.assertEqual(result["purchase"], {})

    def test_no_channel_recorded_is_never_given_one(self):
        # The whole point. Absent is unknown, and unknown is not general_sale.
        # Scoped to purchase and omitted: `conventions` names every channel on
        # purpose, and asserting over the whole document would pass only while
        # the vocabulary stayed undocumented.
        result = build(med(channel=None))
        blob = json.dumps([result["purchase"], result["omitted"]])
        for channel in purchase_terms.SUPPLY_CHANNELS:
            with self.subTest(channel=channel):
                self.assertNotIn(channel, blob)

    def test_an_omitted_medicine_is_listed_with_a_reason(self):
        result = build(med(channel=None))
        self.assertEqual(len(result["omitted"]), 1)
        row = result["omitted"][0]
        self.assertEqual(row["id"], "calcium-d")
        self.assertEqual(row["reason"], "no_supply_channel_recorded")
        self.assertIn("Calcium with vitamin D", row["summary"])

    def test_an_unrecognised_channel_raises(self):
        # Never mapped to the nearest one. "otc" is not general_sale.
        for channel in ("otc", "over_the_counter", "General Sale", "", "pom"):
            with self.subTest(channel=channel):
                with self.assertRaises(InvalidInput) as caught:
                    build(med(channel=channel))
                self.assertIn("supply_channel", str(caught.exception))

    def test_the_error_lists_the_permitted_channels(self):
        with self.assertRaises(InvalidInput) as caught:
            build(med(channel="otc"))
        for channel in purchase_terms.SUPPLY_CHANNELS:
            self.assertIn(channel, str(caught.exception))

    def test_a_non_string_channel_raises(self):
        for channel in (1, True, ["general_sale"]):
            with self.subTest(channel=channel):
                with self.assertRaises(InvalidInput):
                    build(med(channel=channel))

    def test_channels_match_the_carts_vocabulary_exactly(self):
        # Two copies of a closed vocabulary drift. If this ever fails, the two
        # scripts disagree about what a prescription is.
        self.assertEqual(purchase_terms.SUPPLY_CHANNELS,
                         pharmacy_cart.SUPPLY_CHANNELS)

    def test_a_prn_medicine_keeps_its_channel(self):
        # The cart excludes prn for want of a quantity, not for want of a
        # channel. Deciding that here would be this script second-guessing it.
        result = build(med(prn=True, channel="general_sale"))
        self.assertIn("calcium-d", result["purchase"])


class PurchaseBlockTests(unittest.TestCase):

    def test_a_purchase_block_without_a_channel_raises(self):
        # A price recorded against a medicine that can never enter the cart is
        # a value accepted and never used — the caregiver would never learn
        # their entry did nothing.
        with self.assertRaises(InvalidInput) as caught:
            build(med(channel=None, buy=priced()))
        self.assertIn("supply_channel", str(caught.exception))

    def test_an_unknown_key_inside_the_purchase_block_raises(self):
        # A typo here silently drops a price, and the cart then suppresses its
        # total for a reason nobody can see.
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=dict(priced(), pack_prize="12.90")))
        self.assertIn("pack_prize", str(caught.exception))

    def test_the_purchase_block_must_be_an_object(self):
        with self.assertRaises(InvalidInput):
            build(med(buy=["12.90"]))

    def test_pack_price_without_pack_size_raises(self):
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=priced(pack_size=None)))
        self.assertIn("pack_size", str(caught.exception))

    def test_pack_price_and_unit_price_together_raise(self):
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=dict(priced(), unit_price="0.215")))
        self.assertIn("unit_price", str(caught.exception))

    def test_a_price_without_a_currency_raises(self):
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=priced(currency=None)))
        self.assertIn("currency", str(caught.exception))

    def test_a_price_without_a_source_raises(self):
        # This script looks nothing up. An unsourced price is a remembered one.
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=priced(source=None)))
        self.assertIn("source", str(caught.exception))

    def test_a_currency_with_no_price_raises(self):
        with self.assertRaises(InvalidInput):
            build(med(buy={"currency": "SGD"}))

    def test_a_source_with_no_price_raises(self):
        with self.assertRaises(InvalidInput):
            build(med(buy={"source": "the receipt"}))

    def test_an_empty_purchase_block_raises(self):
        # It says nothing, and it took a caregiver an action to type.
        with self.assertRaises(InvalidInput):
            build(med(buy={}))

    def test_a_binary_float_price_is_refused_not_coerced(self):
        with self.assertRaises(InvalidInput) as caught:
            build(med(buy=priced(pack_price=12.90)))
        self.assertIn("string", str(caught.exception))

    def test_a_negative_price_is_refused(self):
        with self.assertRaises(InvalidInput):
            build(med(buy=priced(pack_price="-12.90")))

    def test_a_zero_pack_size_is_refused(self):
        with self.assertRaises(InvalidInput):
            build(med(buy=priced(pack_size=0)))

    def test_a_fractional_pack_size_is_refused(self):
        with self.assertRaises(InvalidInput):
            build(med(buy=priced(pack_size="60.5")))

    def test_a_priced_entry_carries_every_field_through(self):
        row = build(med(buy=priced()))["purchase"]["calcium-d"]
        self.assertEqual(row["pack_size"], 60)
        self.assertEqual(row["pack_price"], "12.90")
        self.assertEqual(row["currency"], "SGD")
        self.assertIn("receipt", row["source"])

    def test_a_unit_price_is_carried_through(self):
        row = build(med(buy={"unit_price": "0.215", "currency": "SGD",
                             "source": "the pharmacy shelf label"}))
        self.assertEqual(row["purchase"]["calcium-d"]["unit_price"], "0.215")

    def test_money_is_emitted_as_a_string_never_a_float(self):
        blob = json.dumps(build(med(buy=priced()))["purchase"])
        self.assertIn('"12.90"', blob)

    def test_a_medicine_with_no_purchase_block_still_gets_a_channel(self):
        # An unpriced entry is the normal case. The cart suppresses the total
        # and says so; that is correct, not a failure.
        row = build(med())["purchase"]["calcium-d"]
        self.assertEqual(row["supply_channel"], "general_sale")
        self.assertNotIn("pack_price", row)


class FormPluralTests(unittest.TestCase):

    def test_form_plural_is_carried_through_when_recorded(self):
        row = build(med(form="lozenge", form_plural="lozenges"))
        self.assertEqual(row["purchase"]["calcium-d"]["form_plural"],
                         "lozenges")

    def test_form_plural_is_omitted_when_not_recorded(self):
        # The cart falls back to form + "s" itself. Computing it here would put
        # the fallback in two places.
        row = build(med())["purchase"]["calcium-d"]
        self.assertNotIn("form_plural", row)


class OutputTests(unittest.TestCase):

    def test_the_envelope_is_present(self):
        result = build(med())
        for key in ("tool_run_id", "issued_at", "audit_hash"):
            with self.subTest(key=key):
                self.assertTrue(result[key])

    def test_issued_at_carries_the_singapore_offset(self):
        self.assertIn("+08:00", build(med())["issued_at"])

    def test_the_audit_hash_recomputes(self):
        result = build(med(buy=priced()))
        self.assertEqual(purchase_terms.audit_hash_of(result),
                         result["audit_hash"])

    def test_the_audit_hash_excludes_the_run_identity(self):
        # Replaying the same input reproduces the hash.
        first, second = build(med(buy=priced())), build(med(buy=priced()))
        self.assertNotEqual(first["tool_run_id"], second["tool_run_id"])
        self.assertEqual(first["audit_hash"], second["audit_hash"])

    def test_a_changed_channel_changes_the_hash(self):
        self.assertNotEqual(build(med(channel="general_sale"))["audit_hash"],
                            build(med(channel="prescription_only"))["audit_hash"])

    def test_counts_account_for_every_medication(self):
        result = build(med(mid="a"), med(mid="b", channel=None),
                       med(mid="c", channel="prescription_only"))
        counts = result["counts"]
        self.assertEqual(counts["medications"], 3)
        self.assertEqual(counts["with_terms"] + counts["omitted"],
                         counts["medications"])
        self.assertEqual(counts["with_terms"], 2)
        self.assertEqual(counts["omitted"], 1)

    def test_nothing_is_dropped_quietly(self):
        result = build(med(mid="a"), med(mid="b", channel=None))
        accounted = set(result["purchase"]) | {r["id"] for r in result["omitted"]}
        self.assertEqual(accounted, {"a", "b"})

    def test_conventions_state_the_rules_in_words(self):
        conventions = build(med())["conventions"]
        self.assertIn("supply_channel", json.dumps(conventions))
        self.assertEqual(conventions["supply_channels"],
                         list(purchase_terms.SUPPLY_CHANNELS))

    def test_as_of_is_echoed_when_given(self):
        self.assertEqual(build(med())["as_of"], "2026-08-05")

    def test_the_summary_names_what_was_left_out(self):
        result = build(med(mid="a", name="Calcium"),
                       med(mid="b", name="Amlodipine 5mg", channel=None))
        self.assertIn("Amlodipine 5mg", result["summary"])

    def test_the_summary_singularises(self):
        # "1 medicines" is the bug this repo has already shipped once. Pinned
        # on the defect, not on a phrasing: the sentence around it moved when
        # the channel wording was rewritten, and the assertion should not have.
        self.assertIn("for 1 medicine:", build(med())["summary"])
        for count in (1, 2):
            with self.subTest(count=count):
                summary = build(*[med(mid=str(i)) for i in range(count)])["summary"]
                self.assertNotIn("1 medicines", summary)
                self.assertNotIn("2 medicine:", summary)

    def test_one_omission_reads_in_the_singular(self):
        # "whether each needs a prescription, they stay" about a single
        # medicine. Found by reading the output while the suite was green.
        summary = build(med(mid="a"), med(mid="b", name="Amlodipine 5mg",
                                          channel=None))["summary"]
        self.assertIn("whether it needs a prescription, it stays", summary)

    def test_several_omissions_read_in_the_plural(self):
        summary = build(med(mid="a", name="Amlodipine", channel=None),
                        med(mid="b", name="Bisoprolol", channel=None))["summary"]
        self.assertIn("whether each needs a prescription, they stay", summary)

    def test_channels_are_described_in_words_not_enum_values(self):
        # "1 medicine prescription_only" is not a sentence. The enum is for
        # machines; the summary is read by a person.
        summary = build(med(mid="a", channel="general_sale"),
                        med(mid="b", channel="prescription_only"))["summary"]
        self.assertIn("buyable off a shelf", summary)
        self.assertIn("on prescription", summary)
        self.assertNotIn("prescription_only", summary)

    def test_every_channel_has_a_phrase(self):
        self.assertEqual(set(purchase_terms._CHANNEL_PHRASE),
                         set(purchase_terms.SUPPLY_CHANNELS))

    def test_the_summary_says_nothing_when_there_is_nothing(self):
        summary = purchase_terms.build_terms({"medications": []})["summary"]
        self.assertTrue(summary.strip())


class CommandLineTests(unittest.TestCase):

    SCRIPT = SCRIPTS / "purchase_terms.py"

    def run_script(self, payload, *args):
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            input=json.dumps(payload), capture_output=True, text=True)

    def test_reads_stdin_and_writes_stdout(self):
        run = self.run_script(document(med()))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("calcium-d", json.loads(run.stdout)["purchase"])

    def test_stdout_is_json_and_nothing_else(self):
        run = self.run_script(document(med()))
        json.loads(run.stdout)

    def test_logs_go_to_stderr_never_stdout(self):
        run = self.run_script(document(med()))
        self.assertNotIn("INFO", run.stdout)
        self.assertIn("INFO", run.stderr)

    def test_bad_input_exits_two_and_writes_no_json(self):
        run = self.run_script({"default_lead_time_days": 7})
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stdout.strip(), "")

    def test_writes_a_file_when_output_is_given(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "terms.json"
            run = self.run_script(document(med()), "--output", str(out))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("calcium-d",
                          json.loads(out.read_text(encoding="utf-8"))["purchase"])

    def test_runs_from_an_unrelated_working_directory(self):
        # The working directory at invocation is [UNKNOWN]. The sibling import
        # must not depend on it.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run(
                [sys.executable, str(self.SCRIPT)],
                input=json.dumps(document(med())), capture_output=True,
                text=True, cwd=tmp)
            self.assertEqual(run.returncode, 0, run.stderr)


class ChainTests(unittest.TestCase):
    """What this emits, pharmacy_cart.py must accept without a second opinion.

    This is the join `medication-watch` performs, and it is the only place the
    two scripts meet. If it breaks, the skill silently produces an empty cart.
    """

    def household(self):
        return document(
            med(mid="calcium-d", name="Calcium with vitamin D", quantity="6",
                channel="general_sale", buy=priced()),
            med(mid="metformin-500", name="Metformin 500mg", quantity="60",
                channel="prescription_only"),
            med(mid="amlodipine-5", name="Amlodipine 5mg", quantity="30",
                channel=None),
        )

    def test_the_map_drops_straight_into_the_cart(self):
        doc = self.household()
        terms = purchase_terms.build_terms(doc)
        forecast = medication_runout.forecast_runout(doc)
        cart = pharmacy_cart.build_cart({
            "as_of": "2026-08-05", "cover_days": 30,
            "forecast": forecast, "purchase": terms["purchase"]})
        self.assertEqual(cart["counts"]["cart_items"], 1)
        self.assertEqual(cart["cart"]["items"][0]["id"], "calcium-d")

    def test_an_unrecorded_channel_reaches_the_cart_as_excluded(self):
        doc = self.household()
        terms = purchase_terms.build_terms(doc)
        cart = pharmacy_cart.build_cart({
            "as_of": "2026-08-05", "cover_days": 30,
            "forecast": medication_runout.forecast_runout(doc),
            "purchase": terms["purchase"]})
        reasons = {row["id"]: row["reason"] for row in cart["excluded"]}
        self.assertEqual(reasons["amlodipine-5"], "supply_channel_unknown")
        self.assertEqual(reasons["metformin-500"], "prescription_only")

    def test_the_forecast_is_unchanged_by_the_new_fields(self):
        # supply_channel and purchase are additive: medication_runout.py neither
        # reads nor hashes them, so no existing consumer moves.
        rich = self.household()
        plain = document(*[{k: v for k, v in m.items()
                            if k not in ("supply_channel", "purchase")}
                           for m in rich["medications"]])
        self.assertEqual(medication_runout.forecast_runout(rich)["audit_hash"],
                         medication_runout.forecast_runout(plain)["audit_hash"])

    def test_a_priced_map_produces_a_total(self):
        doc = self.household()
        cart = pharmacy_cart.build_cart({
            "as_of": "2026-08-05", "cover_days": 30,
            "forecast": medication_runout.forecast_runout(doc),
            "purchase": purchase_terms.build_terms(doc)["purchase"]})
        self.assertIsNotNone(cart["cart"]["total"])
        self.assertEqual(cart["cart"]["currency"], "SGD")

    def test_an_unpriced_map_suppresses_the_total(self):
        doc = document(med(mid="calcium-d", quantity="6",
                           channel="general_sale"))
        cart = pharmacy_cart.build_cart({
            "as_of": "2026-08-05", "cover_days": 30,
            "forecast": medication_runout.forecast_runout(doc),
            "purchase": purchase_terms.build_terms(doc)["purchase"]})
        self.assertIsNone(cart["cart"]["total"])
        self.assertIn("calcium-d", cart["cart"]["total_suppressed_because"])


class NoNetworkTests(unittest.TestCase):

    def test_the_source_opens_no_socket(self):
        source = (SCRIPTS / "purchase_terms.py").read_text(encoding="utf-8")
        for term in ("socket", "urllib", "requests", "http.client", "urlopen"):
            with self.subTest(term=term):
                self.assertNotIn(term, source)

    def test_money_is_decimal_never_float(self):
        row = build(med(buy=priced()))["purchase"]["calcium-d"]
        self.assertEqual(Decimal(row["pack_price"]), Decimal("12.90"))


if __name__ == "__main__":
    unittest.main()
