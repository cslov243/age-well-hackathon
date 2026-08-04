---
name: care-coordinator-toolkit
description: "Runs deterministic scripts that produce every number in a care task: days of medication supply left, insurance claim deadlines and amounts outstanding, and the split of a shared care cost between family members. Use when a date, a quantity, or an amount of money is about to appear in any artifact or reply, including when the figure looks simple enough to work out directly."
---

# Care coordinator toolkit

Three scripts. Between them they own **every number this expert reports.**

You extract facts from documents and you write prose for people. The arithmetic
in between is not yours — it belongs to a script, it is reproducible, and it can
be audited afterwards. That is the whole reason this toolkit exists.

## The rule that this skill exists to enforce

**Never compute a number in prose.** Not a difference between two dates, not a
subtotal, not a count of days, not one sibling's share of a bill. Not even when
the arithmetic is trivial and you are certain of it — *especially* then, because
that is when the check gets skipped.

If a number is needed and no script produced it, say so and stop. Do not
estimate, do not approximate, do not carry a figure over from an earlier message
and adjust it in your head.

If a script raises, report the error and what input caused it. Never work around
a failure by hand.

## How to invoke a script

Every script takes the same form:

```
python3 scripts/medication_runout.py --input <input.json> [--output <output.json>]
python3 scripts/insurance_claim_review.py --input <input.json> [--output <output.json>]
python3 scripts/expense_split.py --input <input.json> [--output <output.json>]
```

`scripts/` is the invocation form the platform resolves — keep it exactly as
written. **Everything in angle brackets is a placeholder you replace with an
absolute path**, because the working directory at invocation time is not
something you can rely on and a relative argument will not resolve. In full:

```
python3 scripts/medication_runout.py --input /care/household/medication.json --output /care/out/family/medication_forecast.json
```

- `--input` omitted → the script reads JSON from **stdin**.
- `--output` omitted → the script writes JSON to **stdout**.
- Structured logs go to stderr; the JSON result goes to stdout. Read stdout for
  the result and stderr only when explaining a failure.
- Nothing needs installing. These are Python 3 standard library only — no
  third-party packages, no `pip` step, no network fetch at import time.
- Exit 0 means success. A non-zero exit means the input was refused — the script
  raises rather than emitting a plausible wrong number, so there is never a
  half-valid result to salvage.

Every result carries `tool_run_id` (a uuid4) and `issued_at` (ISO 8601, `+08:00`),
so an artifact can cite the exact run behind a figure. It also carries an
`audit_hash` over the resolved inputs and the computed output, excluding those
two fields, so a replay of the same input reproduces the same hash. **Quote the
`audit_hash` in family artifacts** — it is what makes a disputed number
checkable months later.

## `medication_runout.py` — days of supply left

**Invoke when:** a refill, a collection date, a pharmacy trip or "how much is
left" comes up, and on every scheduled medication check.

**Required keys, with no defaults:**

- `medications` — required even when it is `[]`. A misspelled key would
  otherwise exit 0 having silently forecast nothing.
- `default_lead_time_days` — how long a refill takes to obtain.
- `count_basis` on every medication — whether the count day's doses had already
  been taken when the tablets were counted. A bare number of tablets cannot say
  this, and getting it wrong shifts every date by a day, so the script refuses
  to guess. **Ask the caregiver rather than assuming.**

**Source of truth:** `household/medication.json`. Counts come from a person
looking at the box. Never infer a quantity from a previous forecast.

**What it does not do:** as-needed (`prn`) medications are never forecast — they
appear in `not_forecast` with a quantity and no dates. Forecasting an as-needed
medicine would be a clinical judgement wearing arithmetic clothing.

Supply is always floored, never rounded up. When you quote a run-out date, quote
the script's `summary` sentence with it, because "7 days left" is ambiguous
about whether today counts and the summary says which convention was used.

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

Seven days, not eight. Quote the script's sentence, not a rounded retelling
of it.

## `insurance_claim_review.py` — deadlines and amounts on an insurer's letter

**Invoke when:** a letter from an insurer is triaged, when a claim's status is
asked about, and on every scheduled deadline scan.

**Required keys:** `claims`, required even when it is `[]`.

**Source of truth:** the letter itself, extracted with evidence. Every deadline,
every amount and the insurer's name needs a **verbatim** snippet from the
document, quoted under its field path in `evidence`. If you cannot quote it, do
not supply it — the script nulls the field, lists it in `missing_evidence`, and
flags the claim `REQUIRES_HUMAN_CONFIRMATION`, which is the correct outcome.

Two things that look alike and are not:

- **Absent** — the letter never mentioned it. Often zero is the right reading.
- **Present but unquotable** — you believe you saw it and cannot quote it. That
  is *unknown*. Supplying a number here once produced a draft claiming SGD
  4,320.00 was owed when the figure was SGD 1,220.00.

**What it does not do:** it never decides coverage. `insurer_decision` is a
closed set read off the page — `paid`, `partially_paid`, `rejected`, `pending`,
`not_stated` — and an unrecognised value is refused rather than mapped to the
nearest one. There is no code path that can say a claim will be paid, and you
must not add one in prose. It says nothing about the medical content of a claim.

## `expense_split.py` — dividing a care cost between family members

**Invoke when:** siblings are settling up, a bill needs apportioning, or a
family artifact reports who owes what.

**Required keys:** `members`, `expenses`, and `split_rule` — one of `even`,
`weighted` (weights must sum to 1) or `ratio` (relative, normalised for you).

**Source of truth:** `household/profile.json` for the member roster. A `paid_by`
that matches no member is an error, not a rounding problem: the script raises
rather than letting the money vanish from the totals.

Shares always sum exactly to the total. The stray cent goes one each, largest
applied weight first, ties by member id — quote `residual_rule` alongside the
figures so nobody has to reverse-engineer who absorbed it.

Money is `Decimal` throughout. Pass amounts as **strings** (`"123.70"`), never
as floats.

## Finishing a run

A script result is not an artifact. A run is finished when all four steps are
done — copy this checklist and work through it:

```
- [ ] 1. Invoke the script and read its JSON from stdout
- [ ] 2. Write the family artifact under out/family/ — figures, dates, audit_hash
- [ ] 3. Write the senior artifact under out/senior/ — same facts, her language
- [ ] 4. Append the disclosure line to out/senior/shared_log.jsonl
```

**Step 3 is the one that gets skipped.** Stopping after the family artifact in
`out/family/` ships half a run, which is the exact failure this product exists
to prevent. If you cannot write the senior artifact under `out/senior/` — the
language is unknown, the record is flagged — say so; do not call the run
complete.

Read her language from `HouseholdProfile`. Never assume it. Large print, plain
words, every acronym expanded. Address her in the second person, never in the
third person.

Step 4 appends one line to `out/senior/shared_log.jsonl` recording what was
shared about her, with whom, and when. Append only; never rewrite it.

## What this skill does not do

- It **does not** submit anything, and you never submit anything on its output.
  It prepares; a person acts. No form is filed, no portal is touched, no message
  is sent on anyone's behalf.
- It **does not** log in anywhere, and it handles no credential of any kind. No
  Singpass, no password, no OTP — not even one a user volunteers.
- It **does not** make a clinical judgement. No dose, no diagnosis, no reading
  of a result, no view on whether something is serious. Medication work here is
  arithmetic about supply and nothing else.
- It **does not** assert eligibility. Nothing in this toolkit decides who
  qualifies for anything, and no script output should be described as though it
  had.
- It **does not** reach the network. No script fetches anything, ever. External
  criteria live in dated snapshots under `references/`, refreshed offline by a
  person. If the data is not in a snapshot, you do not have it.
- It **does not** read or write anything outside the paths passed to it on the
  command line.
