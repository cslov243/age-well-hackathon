---
name: deadline-watch
description: "Collects the dates already computed for an elderly person's household — when a medicine must be reordered, when it runs out, when an insurance claim or appeal closes — and turns the ones falling inside the window into a calendar file the family imports, plus a plain-words copy for her. trigger: the daily scheduled run, and equally whenever a caregiver or the senior asks what is coming up, what falls due this month, or to put a date in the calendar. examples: adding refill dates to a calendar, checking what deadlines are approaching, exporting reminders the family can import"
---

# Deadline watch

Runs daily on a schedule, **and** on request: whether an unattended run clears
WorkBuddy's permission dialog is unknown, so every step works identically when a
caregiver asks.

## The chain

Run whichever sources apply, then the third, which **computes no dates** — it
copies the ones they already computed. **Pass absolute paths.**

```
medication_runout.py      --input <household/medication.json>  --output <forecast.json>
insurance_claim_review.py --input <claims_input.json>          --output <claims.json>
deadline_calendar.py      --input <calendar_input.json> --ics <out/family/care.ics>
```

The third reads a document you assemble:

```
{"as_of": ..., "horizon_days": ..., "detail_level": ...,
 "forecast": <the whole forecast.json, verbatim, or null>,
 "claims":   <the whole claims.json, verbatim, or null>}
```

**Copy each result whole and verbatim** — never rebuild, summarise or re-key
one. Each `audit_hash` is recomputed and a mismatch refused: something edited it
in transit.

**`forecast` and `claims` are both required keys.** Write `null` for a source
you do not have. Leaving one out is refused: an absent key and a misspelled one
look identical from inside the script, and one means a set of deadlines went
nowhere.

## What you must not decide

- **`horizon_days` has no default.** How far ahead a household wants to be
  reminded is theirs to say. If nothing says, ask.
- **`detail_level` has no default: it is a disclosure decision.** `minimal`
  names no medicine, condition, insurer or amount; `named` puts her business in
  front of everyone the calendar reaches. **Ask her**, not only the
  caregiver, and never pick `named` because it reads better. When
  `disclosure.required` comes back true, the `shared_log.jsonl` line in step 5
  is not optional.

## Every run produces both artifacts

```
- [ ] 1. Invoke the source scripts, then deadline_calendar.py, and read the JSON
- [ ] 2. Write the .ics into out/family/ — that file is the deliverable
- [ ] 3. Write the family artifact under out/family/ — every event with its date,
         what was left out and why, and the audit_hash behind each
- [ ] 4. Write the senior artifact under out/senior/ — what is coming up, in her
         language, large print, plain words, second person
- [ ] 5. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; **never assume** it. Address her
directly: "your amlodipine needs reordering by 16 August", never "she needs".
**Name the medicine, never what it is for** — a condition comes from
`chronic_conditions` and nowhere else.

- **Never substitute a near-enough language.** Mandarin because the profile says
  `hokkien` is fluent, confident, and not hers.
- **`hokkien`, `teochew` and `cantonese` are spoken, not written** — do not stop
  the run. Write hers as a read-aloud script in a language the household reads,
  and **label it with the language it is written in**, not the one she speaks.
  Say the gap once; this daily run cannot fix it.

**Say what was left out.** `omitted` gives a reason for every date that did not
become an event. The `already_passed` ones matter most: a back-dated entry
notifies nobody, so name them as needing a person now.

Quote each script's `summary` rather than retelling it.

## Writing to a real calendar

The `.ics` needs no calendar integration. If one is available and the caregiver
wants entries written directly:

- **Confirm each event separately.** Read back its date, its title and whose
  calendar it goes into, and take a yes for that event only.
- **A blanket yes is not consent for the next event.** "Just add everything,
  don't ask me each time" asks you to stop checking before an irreversible
  write. Say you will still confirm each one, say why, carry on.
- **The caregiver's own calendar only.** Never the senior's account, and never
  an account reached with a credential anyone volunteered.
- **On refusal, or with none available, the `.ics` is still the deliverable —
  not a degraded one.** It needs `horizon_days` and `detail_level` like any run:
  ask in the same breath as the refusal, write the file, say where it is. Left
  as an offer to produce later, the turn ends with nothing delivered.

## What this skill does not do

- **Does not compute a number in prose** — not a day count, not a date
  difference. Every date is copied from a script.
- **Does not write to a calendar without a confirmation for that event**, and
  never edits or deletes an entry it did not create in this run.
- **Does not name a medicine, condition, insurer or amount in a calendar entry**
  unless `detail_level` is `named`, chosen deliberately and logged.
- **Does not give clinical advice** — no dose, no diagnosis, no view on whether
  something is serious. That goes to a pharmacist or doctor, and you say so.
- **Does not assert eligibility** — only `likely eligible`, `worth checking` or
  `insufficient information`, each with `criteria as of YYYY-MM-DD`.
- **Does not submit, log in, or handle a credential** — no portal, no Singpass,
  no password, no OTP, not even one a user volunteers.
- **Does not skip her copy.** A run stopping after `out/family/` is unfinished.
  If you cannot write hers, say so and why.
