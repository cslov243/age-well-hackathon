---
name: medication-watch
description: "Checks how many days of each medication remain and prepares a pharmacy cart draft for the ones running out. Use on the daily scheduled run, and whenever a caregiver or the senior asks how much medicine is left, when a refill is due, or what needs buying. Never orders, pays for, or advises on any medicine."
---

# Medication watch

Runs daily on a schedule, **and** on request. Whether an unattended run clears
WorkBuddy's permission dialog is not known, so every step below works
identically when a caregiver triggers it by asking.

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

**Do no arithmetic between the steps.** Not a day count, not a quantity, not a
subtotal. Every number in both artifacts is copied from a script's output.

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
- **Does not reach the network.**
- **Does not compute a number in prose.** If a figure is needed and no script
  produced it, say so and stop.
