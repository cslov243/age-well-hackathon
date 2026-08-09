---
name: medication-watch
description: 'Runs a sequence of three scripts (purchase terms, medication runout, and pharmacy cart) to check remaining medication supplies, determine purchase terms, and draft a pharmacy cart without performing any prose arithmetic or ordering items. Runs on the daily schedule, and use when the user asks "how much medicine is left", "when is a refill due", or "what do I need to buy"'
---

# Medication watch

Runs daily on a schedule, **and** on request. Whether an unattended run clears
WorkBuddy's permission dialog is not known, so every step below works
identically when a caregiver triggers it by asking. This produces a draft only. requires_human_checkout is always true — nothing here checks out, pays, or opens a shop, and nothing here gives clinical advice about the medicines themselves.

## The chain

Three scripts, in this order, all in `care-coordinator-toolkit` — its `SKILL.md`
holds the invocation contract. **Pass absolute paths**; the working directory is
not something you can rely on.

```
purchase_terms.py    --input <household/medication.json>  --output <terms.json>
medication_runout.py --input <household/medication.json>  --output <forecast.json>
pharmacy_cart.py     --input <cart_input.json>            --output <cart.json>
```

The first two read **the same file**. The third reads a document you assemble:

```
{"as_of": ..., "cover_days": ..., "pharmacy": ...,
 "forecast": <the whole forecast.json, verbatim>,
 "purchase": <the "purchase" object from terms.json, verbatim>}
```

**Copy both objects whole** — never rebuild, summarise, reorder or re-key
either. `pharmacy_cart.py` recomputes the forecast's `audit_hash` and refuses
one that has been touched; a refusal there means something edited it in
transit, not that the input needs adjusting.

If pharmacy_cart.py refuses on a mismatched audit_hash, do not patch the file and do not retry with the same cart_input.json. Re-run medication_runout.py fresh, rebuild cart_input.json from its new output, and start the cart step over.

**Do no arithmetic between the steps.** Not a day count, not a quantity, not a
subtotal. Every number in both artifacts is copied from a script's output.

### Worked example

Given `forecast.json` from `medication_runout.py`:

{"medications": [{"id": "metformin-500", "name": "Metformin 500mg",
  "days_left": 7, "order_by_date": "2026-08-09", "runs_out_on": "2026-08-16"}],
 "audit_hash": "f4a9c2e1b8d3a0..."}

and `terms.json` from `purchase_terms.py`:

{"purchase": {"metformin-500": {"supply_channel": "prescription_only", "pack_size": 90}}}

`cart_input.json` is assembled as:

{"as_of": "2026-08-09", "cover_days": 30, "pharmacy": "Guardian Pharmacy, Bedok Mall",
 "forecast": {"medications": [{"id": "metformin-500", "name": "Metformin 500mg",
   "days_left": 7, "order_by_date": "2026-08-09", "runs_out_on": "2026-08-16"}],
   "audit_hash": "f4a9c2e1b8d3a0..."},
 "purchase": {"metformin-500": {"supply_channel": "prescription_only", "pack_size": 90}}}

Note: `forecast` is `forecast.json` copied whole, including its `audit_hash`.
`purchase` is only the `"purchase"` object from `terms.json`, not the whole file.
A medicine present in `forecast` but absent from `purchase` is left out of this
object entirely — never zero-filled, never guessed from its name.

## What you must not decide

**`supply_channel` is never yours to supply.** `purchase_terms.py` reads it from
`household/medication.json` and leaves out any medicine with none recorded. A
medicine missing from the `purchase` map is *unknown*, and unknown stays out of
the cart. Never add an entry, never fill a gap, never infer a channel from a
medicine's name — getting this wrong puts a prescription medicine in a shopping
cart. When one is excluded as `supply_channel_unknown`, say so in the family
artifact and ask the caregiver to record it. That question is the fix.

**`cover_days` has no default.** How much to buy is a person's call. Take it
from the caregiver's request; if nothing says, ask, and do not run the cart
until you have an answer.

If cover_days is never answered, stop before invoking pharmacy_cart.py. Still write the family and senior artifacts for what the first two scripts produced — days left, run-out and order-by dates — and note plainly that the cart step is pending the caregiver's answer. A partial run is reported as partial, not silently completed short.

## Every run produces both artifacts

```
- [ ] 1. Invoke the three scripts and read their JSON from stdout
- [ ] 2. Write the family artifact under out/family/ — days left, run-out and
         order-by dates, the cart lines, the total, and every audit_hash
- [ ] 3. Write the senior artifact under out/senior/ — the same facts, in her
         language, large print, plain words, second person
- [ ] 4. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; never assume it. Address her
directly, in the second person: "you have six days of your calcium tablets
left", never "she has".

**Step 3 is the one that gets skipped.** A run stopping after `out/family/` is
unfinished, not merely terse. If you cannot write it, say so and say why.

Quote each script's `summary` rather than retelling it. "7 days left" is
ambiguous about whether today counts; the summary states the convention.

## What this skill does not do

- **Does not order and does not pay.** The cart is a draft.
  `requires_human_checkout` is always true, no code path can set it false, and
  nothing here opens a shop. A person checks every line and pays themselves.
- **Does not give clinical advice.** No dose, no diagnosis, no reading of a
  result, no comment on whether a medicine should still be taken — this is
  arithmetic about supply and nothing else. A question about the medicine
  itself goes to a pharmacist or a doctor, and you say so.
- **Does not forecast an as-needed medicine.** `prn` medicines carry no daily
  rate; they appear as excluded, with a quantity and no dates.
- **Does not submit, log in, or handle a credential** — no portal, no Singpass,
  no password, no OTP, not even one a user volunteers.
- **Does not compute a number in prose.** If a figure is needed and no script
  produced it, say so and stop.
