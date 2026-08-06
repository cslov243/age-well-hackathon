---
name: care-coordinator-toolkit
description: "Runs deterministic Python scripts to calculate and produce exact numbers, dates, distances, and drafts for care tasks, ensuring all data is computed programmatically rather than in prose. trigger: when a date, a quantity, a distance, or an amount of money is about to appear in any artifact or reply, including when the figure looks simple enough to work out directly. examples: calculating medication supply days, reviewing insurer claims, splitting care costs, finding clinic distances, determining medication purchase terms, generating a pharmacy cart draft"
---

# Care coordinator toolkit

Nine scripts. Between them they own **every number this expert reports**, and
whether a run needs a person.

## The rule

**Never compute a number in prose.** Not a date difference, not a subtotal, not a
count of days, not a share of a bill — especially not when the arithmetic is
trivial, because that is when the check gets skipped.

If a number is needed and no script produced it, say so and stop. If a script
raises, report the error and the input that caused it. Never work around a
failure by hand.

**A derivation is prose arithmetic even when the result came from a script.**
`30 days from 28 July = 27 August` printed beside a date `insurance_claim_review.py`
computed is a second calculation, done by you, that happens to agree today. If
the two ever disagree a reader has no way to tell which one is load-bearing.
Print the figure and the script that produced it, and never your own working.

Quoting a script's `summary` verbatim is not this, even where that summary
spells out how it got there — *"30 days from the insurer's decision date,
28 Jul 2026, closing 27 Aug 2026"* is `insurance_claim_review.py` showing its
own arithmetic, and it replays. Retyping that as a line of your own does not.

## How to invoke

```
python3 scripts/letter_record.py --input <input.json> --records <extracted/> [--output <output.json>]
python3 scripts/medication_runout.py --input <input.json> [--output <output.json>]
python3 scripts/insurance_claim_review.py --input <input.json> [--output <output.json>]
python3 scripts/expense_split.py --input <input.json> [--output <output.json>]
python3 scripts/clinic_finder.py --input <input.json> [--output <output.json>]
python3 scripts/purchase_terms.py --input <input.json> [--output <output.json>]
python3 scripts/pharmacy_cart.py --input <input.json> [--output <output.json>]
python3 scripts/deadline_calendar.py --input <input.json> --ics <calendar.ics> [--output <output.json>]
python3 scripts/confirmations.py --input <input.json> [--output <output.json>]
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

## `letter_record.py` — a letter turned into a record

**Use when** a document arrives, before and after the model reads it.

**Two modes, and `mode` has no default.** `check` hashes the pages and says
whether this document has been extracted before — that call comes **first**, and
a `should_extract` of false means stop, not read it again. `record` files the
extraction you then made.

**`record` refuses without `check_audit_hash`** — the `audit_hash` the `check`
run printed. It recomputes the check over the same bytes and the same records
directory and refuses a mismatch, so the value cannot be produced without having
made the call. This is a precondition rather than an instruction because the
instruction was skipped: audit finding #25. If it refuses, run `check` again on
exactly those `source_files` and read `should_extract` before anything else.

**A letter already filed is answered, not refused.** The call returns
`already_extracted: true` and `should_extract: false`, writes nothing, and names
the record that stands in `existing_record_path`. That is a finished run, not a
blocked one — quote that record and carry on. **Nothing in `extracted/` may be
deleted or moved to file a letter again**, whatever a refusal seems to invite: a
record is the only evidence a letter was ever read, and deleting one is an
irreversible act taken without a person.

**Requires in `record` mode:** `doc_type`, `evidence`, and every key of `fields`
— `issuer`, `issue_date`, `deadline`, `amounts`, `required_action` — present
even when the value is `null`. A field the letter never mentioned and a field
nobody looked for are the same JSON otherwise.

**Every deadline, date, issuer and amount needs a verbatim snippet**, quoted
under its own field path (`deadline`, `amounts[0]`). The script keeps a value
only when the snippet exists, is not blank, **and contains the value itself**.
Anything else is nulled, listed in `missing_evidence`, and the record is flagged
`REQUIRES_HUMAN_CONFIRMATION`.

| Looks alike | Is not |
|---|---|
| **Absent** — the letter never said it | `null`, no snippet, **no flag**. That is an honest answer |
| **Present but unquotable** — you believe you saw it | *Unknown.* Nulled and flagged. This is the case that once put SGD 4,320.00 in a draft against a letter reading SGD 1,220.00 |

**Do not report a confidence.** The script asks for a quotation and nothing
else; a number describing how sure you feel is highest exactly where it is least
deserved. One unquotable amount nulls the whole `amounts` list, because a list
with the bad entry dropped reads as complete.

**Grouping pages into one record is your call, and the bias is toward
splitting.** Issuer plus date is not enough — two letters from the same agency
on the same day merge into one and a deadline disappears. Split on any conflict.
A duplicate record costs a second notification; a merge costs the deadline.

`--records` is the `extracted/` directory. The script writes one file there,
named for the record, and writes nothing at all when the letter is already
filed.

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

**A claim's fields are exactly** `id`, `insurer`, `policy_reference`,
`incident_date`, `submission_window_days`, `insurer_decision`, `decision_date`,
`appeal_window_days`, `amounts`, `documents_required`, `documents_held`,
`evidence`. Any other key is refused and the error names these. Do not invent a
field to carry something the letter said — a key the script does not know reads
downstream as one the letter never mentioned.

**Source of truth:** the letter. Every deadline, every amount and the insurer's
name needs a **verbatim** snippet quoted under its field path in `evidence`. If
you cannot quote it, do not supply it — the script nulls the field, lists it in
`missing_evidence` and flags the claim `REQUIRES_HUMAN_CONFIRMATION`. That is the
correct outcome, not a failure.

**The snippet has to contain the value.** The same check `letter_record.py`
applies, from the same module: a date by day, month and year; an amount or a
window in days by the number itself; an insurer by every meaningful word of its
name. A figure quoted against *"The balance is payable by the policyholder"* is
refused, because that line has no number in it. Quoting nearby text does not
make a computed figure quotable.

**A value either script refused is not a value.** Do not hand it to the next
script by hand, do not carry it into an artifact, and do not report it as
settled. Say which fields need a person and what the letter would have to show.

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

## `deadline_calendar.py` — dates a person imports into a calendar

**Use when** a deadline needs to leave this repo and land somewhere she or the
family will actually see it.

**Requires:** `forecast` and `claims` — whole results passed **verbatim**, each
`audit_hash` recomputed and a mismatch refused — plus `horizon_days` and
`detail_level`. **Write `null` for a source you do not have**; the key itself is
required, because an absent key and a misspelled one are the same thing from
inside the script, and one of them scheduled nothing.

`--ics` is required and is the deliverable: the file goes in `out/family/` and a
person imports it. Nothing here writes to anyone's calendar.

**It copies dates and computes none.** They come from `order_by` and
`runs_out_on` in the forecast and `deadlines[].due_on` in the claims review.

**`detail_level` is a disclosure decision, not a formatting one.** A calendar is
read by everyone it is shared with.

| | |
|---|---|
| `minimal` | "Medication refill due" — no medicine, condition, insurer or amount. Two reminders on nearby days look identical **on purpose**; the family artifact says which is which |
| `named` | names the medicine or the insurer, **and is a disclosure** — `disclosure.required` comes back true and step 5 of the checklist below applies to it |

Ask which. Never pick `named` because it reads better.

**Nothing is dropped quietly.** Every date lands in `events` or in `omitted`
with a reason: `no_date`, `beyond_horizon`, or `already_passed`. Report the
`already_passed` ones to the caregiver in prose — a back-dated entry notifies
nobody, and that deadline needs a person today.

## `confirmations.py` — does this run need a person?

**Use when** a run is finished and before either artifact is written. Every
other script here answers *is this record clean*. This one answers *does this
run need a person*, which is a different question, and it is the question the
artifacts state an answer to.

**Requires:** `records` and `claims` — lists of whole results passed
**verbatim**, each `audit_hash` recomputed and a mismatch refused. Both keys are
required and `[]` is legal; an absent key means a whole set of flags was never
read.

**Quote `sentence` verbatim into both artifacts, and every `items[].ask` with
it.** Do not compose your own. Whether a person is needed is not a judgement you
make from the flag lists you happened to read — it is this script's output,
exactly as an amount is `expense_split.py`'s.

**The `ask` is the half that gets acted on, and the half that gets retold.**
`sentence` answers for the whole run; each `items[].ask` says what one person
must go and do about one field. Audit finding #24: an artifact quoted `sentence`
word for word and rewrote the `ask` beside it. The script had said *read the
deadline off the document, and check the wording it was taken from*; the artifact
said *verify the deadline calculation (30 days from 28 July = 27 August)*. **The
substitution ran the wrong way.** The letter's wording was the part that could
not be quoted — that is why the field was nulled — and the arithmetic was the one
part a script did deterministically and nobody needs to check. A person was sent
to audit a subtraction while the unquotable sentence went unread.

Every `ask` names a field and a document, because reading the document is always
what it wants. If yours names a calculation instead, you have rewritten it.

**A clean list from one script is not a clean run.** Audit finding #22: a
family artifact certified "No human confirmation required" over a record
flagged `REQUIRES_HUMAN_CONFIRMATION`, because the claim review in the same run
had returned `flags: []` legitimately. Pass every result the run produced. What
you do not pass is not checked, and `sentence` says how many were.

Any flag it does not recognise still comes back needing a person. That is
deliberate, and it is the only safe direction.

## Finishing a run

A script result is not an artifact. Copy this checklist:

```
- [ ] 1. Invoke the script and read its JSON from stdout
- [ ] 2. Run confirmations.py over every result this run produced
- [ ] 3. Write the family artifact under out/family/ — figures, dates,
         audit_hash, the confirmations sentence and every items[].ask verbatim
- [ ] 4. Write the senior artifact under out/senior/ — same facts, her language,
         every figure in digits exactly as the script printed it
- [ ] 5. Append the disclosure line to out/senior/shared_log.jsonl
```

**Never write that no confirmation is needed unless `confirmations.py` said
so.** The absence of a flag is not a finding. An artifact that says nothing
about confirmation is correct; one that certifies its absence without having
checked is the defect.

**Step 4 is the one that gets skipped.** Stopping after `out/family/` ships half
a run — the exact failure this product exists to prevent. If you cannot write the
senior artifact, say so; do not call the run complete.

Read her language from `HouseholdProfile`, never assume it. Large print, plain
words, every acronym expanded, second person. Step 5 appends one line to
`out/senior/shared_log.jsonl`: what was shared about her, with whom, when. Append
only.

**Never spell a figure out in place of its digits.** Words may go beside them,
never instead: *SGD 1,220.00 — one thousand two hundred and twenty dollars*.
Finding #27: a script returned `"1220.00"`, the family copy printed it, and hers
said *two thousand two hundred and twenty dollars*. Re-expressing is not
computing, so no rule caught it — and hers is the copy with no second reader.

## When a script refuses

A refusal is an answer, not a retry prompt. Every case below exits non-zero with
one line on stderr and **nothing on stdout** — the script declined to guess, and
the fix is upstream of it. The reason each is fatal rather than a warning is that
the alternative is a plausible wrong number in a letter about someone's care.

**The one rule that governs all of them: never make a refusal pass by changing
what the input means.** Renaming a key the script rejected, deleting the field it
objected to, or editing a snippet until it matches are all the same move, and
each turns a caught error into a silent wrong answer.

| What stderr says | What happened | What to do |
|---|---|---|
| `input file not found: <path>` | A relative path. The working directory at invocation is not something you can rely on. | Re-run with an absolute path. |
| `input has unrecognised keys: <key>. … Allowed: …` | A misspelled key. To `.get()` a typo and an absent key are identical, so it would have taken no effect and read downstream as *the letter never said it*. | Correct the spelling. **Never delete the key** — the value was meant to be there. |
| `<key> is required (use [] for none)` | A required key is not a defaulted one. `[]` is legal and means *none*; absent means *nobody looked*. | Send `[]` if there genuinely are none. |
| `default_lead_time_days is required…` | There is no safe hardcoded guess about how long a repeat prescription takes to arrive. | Ask the caregiver. Do not pick a number. |
| `expected an ISO date string (YYYY-MM-DD)` / `expected an amount as a string` | A shape the script will not coerce. | Fix the payload. Amounts are strings; dates are `YYYY-MM-DD`. |
| `<field> audit_hash does not match its contents (stored …, recomputed …)` | A result was edited between the script that produced it and the script consuming it. | Re-run the producer and copy its output **whole**. Never hand-edit a result, and never adjust the hash. |
| `snapshot not found: <path>` | A dated reference is missing. | A person refreshes it. Never fetch around it and never answer from memory. |

Two outcomes look like failures and are not:

- **`<value> does not appear in the text quoted for it … nulled and flagged`** —
  this is the evidence gate doing its job, and the run continues. The field is
  `null`, the record carries `REQUIRES_HUMAN_CONFIRMATION`, and a person reads
  that field off the document. **Do not edit the snippet to match, and do not
  substitute a value you can quote instead.** The quotation was the evidence; a
  value that disagrees with it is the one that is wrong.
- **`This document is already extracted — … This run is finished, not blocked.`**
  — exit 0, nothing written, no artifacts. The letter was filed by an earlier
  run. Quote that record and the `audit_hash` inside it. **Do not delete or move
  it to file the letter again**: it is the only evidence the letter was ever
  read, and a second record competes with it rather than corrects it.

Exit 0 with `REQUIRES_HUMAN_CONFIRMATION` in the flags is likewise a **successful
run that needs a person**, not a failed one. Report it as the finding it is.

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
