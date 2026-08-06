---
name: care-coordinator-toolkit
description: "Runs deterministic Python scripts to calculate and produce exact numbers, dates, distances, and drafts for care tasks, ensuring all data is computed programmatically rather than in prose. trigger: when a date, a quantity, a distance, or an amount of money is about to appear in any artifact or reply, including when the figure looks simple enough to work out directly. examples: calculating medication supply days, reviewing insurer claims, splitting care costs, finding clinic distances, determining medication purchase terms, generating a pharmacy cart draft"
---

# Care coordinator toolkit

Six scripts. Between them they own **every number this expert reports.**

## The rule

**Never compute a number in prose.** Not a date difference, not a subtotal, not a
count of days, not a share of a bill — especially not when the arithmetic is
trivial, because that is when the check gets skipped.

If a number is needed and no script produced it, say so and stop. If a script
raises, report the error and the input that caused it. Never work around a
failure by hand.

## How to invoke

```
python3 scripts/medication_runout.py --input <input.json> [--output <output.json>]
python3 scripts/insurance_claim_review.py --input <input.json> [--output <output.json>]
python3 scripts/expense_split.py --input <input.json> [--output <output.json>]
python3 scripts/clinic_finder.py --input <input.json> [--output <output.json>]
python3 scripts/purchase_terms.py --input <input.json> [--output <output.json>]
python3 scripts/pharmacy_cart.py --input <input.json> [--output <output.json>]
```

Keep `scripts/` as written. **Angle brackets are placeholders for absolute
paths** — the working directory at invocation is not something you can rely on.
In full:

```
python3 scripts/medication_runout.py --input /care/household/medication.json --output /care/out/family/medication_forecast.json
```

| | |
|---|---|
| `--input` omitted | reads JSON from **stdin** |
| `--output` omitted | writes JSON to **stdout** |
| stderr | structured logs; read them only to explain a failure |
| exit 0 | success. Non-zero means the input was refused — nothing to salvage |

Nothing needs installing: Python 3 standard library only, no `pip` step, no
network fetch at import.

Every result carries `tool_run_id`, `issued_at` (`+08:00`) and an `audit_hash`
over the resolved inputs and computed output, excluding those two so a replay
reproduces it. **Quote the `audit_hash` in family artifacts** — it makes a
disputed number checkable months later.

## `medication_runout.py` — days of supply left

**Use when** a refill, a collection date, a pharmacy trip or "how much is left"
comes up, and on every scheduled medication check.

**Requires, no defaults:**

- `medications` — required even when `[]`. A misspelled key would otherwise exit
  0 having silently forecast nothing.
- `default_lead_time_days`.
- `count_basis` on every medication — whether the count day's doses were already
  taken. A bare tablet count cannot say this, and getting it wrong shifts every
  date by a day. **Ask the caregiver rather than assuming.**

**Source of truth:** `household/medication.json`. Counts come from a person
looking at the box, never from a previous forecast.

**Never** forecast an as-needed (`prn`) medicine — they appear in `not_forecast`
with a quantity and no dates. That would be a clinical judgement wearing
arithmetic clothing.

Supply is floored, never rounded up. Quote the script's `summary` sentence with
any run-out date: "7 days left" is ambiguous about whether today counts, and the
summary says which convention was used.

### Worked example

<!-- worked-example: medication_runout.py -->
```json
{
  "as_of": "2026-08-03",
  "default_lead_time_days": 7,
  "medications": [
    {
      "id": "metformin-500",
      "name": "Metformin 500mg",
      "form": "tablet",
      "quantity_on_hand": "15",
      "count_basis": "doses_on_count_day_pending",
      "schedule": {
        "mode": "fixed_daily",
        "units_per_dose": "1",
        "doses_per_day": 2
      }
    }
  ]
}
```

produces, in `forecast[0].summary`:

<!-- worked-example-output: medication_runout.py -->
```text
Metformin 500mg: 15 tablets counted on 3 Aug 2026, on the basis that that day's doses had not yet been taken. At 2 tablets a day, that is 7 days of doses in full: the last full day is 9 Aug 2026, and 10 Aug 2026 is the first day not covered. 1 tablet left over beyond the last full day. Order by 3 Aug 2026, allowing 7 days lead time.
```

Seven days, not eight. Quote the sentence, not a rounded retelling.

## `insurance_claim_review.py` — an insurer's letter

**Use when** an insurer's letter is triaged, a claim's status is asked about, and
on every scheduled deadline scan.

**Requires:** `claims`, even when `[]`.

**Source of truth:** the letter. Every deadline, every amount and the insurer's
name needs a **verbatim** snippet quoted under its field path in `evidence`. If
you cannot quote it, do not supply it — the script nulls the field, lists it in
`missing_evidence` and flags the claim `REQUIRES_HUMAN_CONFIRMATION`. That is the
correct outcome, not a failure.

| Looks alike | Is not |
|---|---|
| **Absent** — the letter never mentioned it | Zero is often right |
| **Present but unquotable** — you think you saw it | *Unknown.* Supplying a number here once produced a draft claiming SGD 4,320.00 owed when the figure was SGD 1,220.00 |

**Never** decide coverage. `insurer_decision` is a closed set read off the page —
`paid`, `partially_paid`, `rejected`, `pending`, `not_stated` — and an
unrecognised value is refused, not mapped to the nearest one. No code path can
say a claim will be paid; do not add one in prose.

## `expense_split.py` — dividing a care cost

**Use when** siblings settle up, a bill needs apportioning, or a family artifact
reports who owes what.

**Requires:** `members`, `expenses`, `split_rule` — one of `even`, `weighted`
(weights sum to 1) or `ratio` (normalised for you).

**Source of truth:** `household/profile.json` for the roster. A `paid_by` that
matches no member raises, rather than letting money vanish from the totals.

Shares sum exactly to the total. The stray cent goes one each, largest applied
weight first, ties by member id — quote `residual_rule` so nobody reverse-engineers
who absorbed it. Money is `Decimal`: pass amounts as **strings** (`"123.70"`),
never floats.

## `clinic_finder.py` — the nearest clinics to a point

**Use when** she asks where to go, or an artifact needs a place and a distance.

**Requires:** `snapshot_path`, an `origin` giving `longitude` **then** `latitude`
— GeoJSON order — and at least one of `limit` and `radius_metres`.

**Source of truth:** a dated snapshot under `references/`, written by a
person running `tools/fetch_references.py`. An edited one is refused; over 30
days old still answers, marked `stale`.

**Never call the distance a walk.** It is a straight line rounded to 10 m: no
route was worked out, and nothing says whether the way is step-free. Quote the
record's `summary`, which says so. `programmes` is a dataset fact and settles
nothing about any person.

## `purchase_terms.py` — how each medicine is obtained

**Use when** a cart is about to be drafted. It builds the `purchase` map
`pharmacy_cart.py` reads, from `household/medication.json`.

**Requires:** `medications`, even when `[]`.

**Never write this map by hand.** `supply_channel` is copied from the household
file, never inferred from a medicine's name. A medicine with none recorded is
**left out**, so the cart reports it unknown and asks — the one field where a
confident guess puts a prescription medicine in a shopping cart.

An optional `purchase` block carries `pack_size` and a price. A price needs a
`currency` **and** a `source`; recording one against a medicine with no channel
raises, rather than being accepted and never used.

## `pharmacy_cart.py` — a cart draft a person pays for

**Use when** a forecast says something runs out.

**Requires:** `forecast` — a `medication_runout.py` result passed **verbatim**;
its `audit_hash` is recomputed and a mismatch refused — plus `cover_days` and
`purchase` (even when `{}`).

**Never recompute the forecast** — copy its dates and rates. **Never check
out**, and never offer to: `requires_human_checkout` is always true.

`purchase[id].supply_channel` is `general_sale`, `pharmacist_only` or
`prescription_only`. **An id you leave out is unknown, and unknown is excluded** —
never called buyable. Prescription items go to the refill path.

**No invented price.** A price needs a `currency` and `source`. One unpriced
line suppresses the whole `total` — report none rather than a partial one.

## Finishing a run

A script result is not an artifact. Copy this checklist:

```
- [ ] 1. Invoke the script and read its JSON from stdout
- [ ] 2. Write the family artifact under out/family/ — figures, dates, audit_hash
- [ ] 3. Write the senior artifact under out/senior/ — same facts, her language
- [ ] 4. Append the disclosure line to out/senior/shared_log.jsonl
```

**Step 3 is the one that gets skipped.** Stopping after `out/family/` ships half
a run — the exact failure this product exists to prevent. If you cannot write the
senior artifact, say so; do not call the run complete.

Read her language from `HouseholdProfile`, never assume it. Large print, plain
words, every acronym expanded, second person. Step 4 appends one line to
`out/senior/shared_log.jsonl`: what was shared about her, with whom, when. Append
only.

## What this skill does not do

- **Does not submit.** It prepares; a person acts. No form filed, no portal
  touched, no message sent — and you never submit anything on its output.
- **Does not log in**, and handles no credential: no Singpass, no password, no
  OTP, not even one a user volunteers.
- **Does not make a clinical judgement** — no dose, diagnosis, or reading of a
  result. Medication work here is arithmetic about supply and nothing else.
- **Does not assert eligibility.** Nothing here decides who qualifies for
  anything.
- **Does not report a fact it cannot source.** A script may fetch; whatever it
  fetches is reported with its URL and retrieval time, and an unreachable source
  falls back to the dated snapshot marked stale, never to a guess.
- **Does not read or write outside the paths passed on the command line.**
