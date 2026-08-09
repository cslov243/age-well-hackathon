---
name: care-coordinator-toolkit
description: "Runs deterministic Python scripts to calculate and produce exact numbers, dates, distances, and drafts for care tasks, e.g. medication supply, appointments, transport distances. Use when user says a date, a quantity, a distance, or an amount of money is about to appear in any artifact or reply, to compute data programmatically rather than in prose."
---

# Care coordinator toolkit

These scripts own every number this expert reports, and whether a run needs a person. The senior may use this app herself to monitor her own health situation, or a caregiver may run it on her behalf — both are 'a run.' The senior artifact is written for her either way: plain words, large print, second person, read from HouseholdProfile.

HouseholdProfile is household/profile.json — the household roster and the senior's language/format preferences, read by every step that writes to her.

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

## Which script, and where to read more

| Script | Use when | Requires | Reference |
|---|---|---|---|
| `letter_record.py` | a document arrives, before and after the model reads it | `mode`, and in `record` mode: `doc_type`, `evidence`, every `fields` key | `references/scripts/letter_record.md` |
| `medication_runout.py` | a refill, collection date, pharmacy trip, or "how much is left" comes up | `medications` (even `[]`), `default_lead_time_days`, `count_basis` per medication | `references/scripts/medication_runout.md` |
| `insurance_claim_review.py` | an insurer's letter is triaged, or a claim's status is asked about | `claims` (even `[]`), verbatim snippets for every deadline/amount | `references/scripts/insurance_claim_review.md` |
| `expense_split.py` | siblings settle up, or a bill needs apportioning | `members`, `expenses`, `split_rule` | `references/scripts/expense_split.md` |
| `clinic_finder.py` | she asks where to go, or an artifact needs a place and a distance | `snapshot_path`, `origin` (longitude, latitude), `limit` or `radius_metres` | `references/scripts/clinic_finder.md` |
| `purchase_terms.py` | a cart is about to be drafted | `medications` (even `[]`) | `references/scripts/purchase_terms.md` |
| `pharmacy_cart.py` | a forecast says something runs out | `forecast` (verbatim), `cover_days`, `purchase` (even `{}`) | `references/scripts/pharmacy_cart.md` |
| `deadline_calendar.py` | a deadline needs to leave this repo and land somewhere she or the family will see it | `forecast`, `claims` (verbatim), `horizon_days`, `detail_level` | `references/scripts/deadline_calendar.md` |
| `confirmations.py` | a run is finished, before either artifact is written | `records`, `claims` (verbatim lists, `[]` legal) | `references/scripts/confirmations.md` |

**If a script exits non-zero**, its refusal is documented in `references/refusals.md` — read that before deciding how to respond. Do not improvise a workaround for a refusal.

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
