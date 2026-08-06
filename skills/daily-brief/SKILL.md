---
name: daily-brief
description: "Writes the morning brief an elderly person hears in her own language, and the family's copy of the same facts: what medicine is running low, what falls due today, and where to go if a visit is needed. trigger: the 8am scheduled run, and equally whenever a caregiver or the senior asks for today's brief, what is due today, or how things stand right now. examples: the daily 8am briefing, checking what needs attention today, reading her the morning summary"
---

# Daily brief

Runs at 8am on a schedule, **and** on request. Whether an unattended run clears
WorkBuddy's permission dialog is not known, so every step below works
identically when a caregiver asks.

**This is the one skill she hears first.** Everywhere else the family artifact
leads and hers follows; here it is the other way round, and the checklist is in
that order on purpose.

## What it reads

Structured records only. **It invokes no vision model and re-reads no
document** — that is what makes a daily run cost almost nothing.

- `extracted/` — one JSON per record, already extracted.
- The run-out forecast from `medication_runout.py`.
- `household/profile.json` for who she is and what she reads.
- `clinic_finder.py` output, only when the brief needs a place.

**Pass absolute paths.** The working directory at invocation is not something
to rely on.

**Do no arithmetic.** Every day count, date and amount is copied from a script's
output. If a figure is needed and no script produced it, say so and stop.

## Every run produces both artifacts

```
- [ ] 1. Read the profile and the structured records
- [ ] 2. Write her brief to out/senior/ — her language, large print, plain
         words, second person, every acronym expanded
- [ ] 3. Write the family copy to out/family/ — the same facts, plus the
         run ids and audit_hash behind each figure
- [ ] 4. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; **never assume** it. Address her
directly, in the second person: "you have six days of your calcium tablets
left", never "she has".

- **Never substitute a near-enough language.** Mandarin because the profile
  says `hokkien` is the failure this product exists to prevent: fluent,
  confident, and not her language.
- **`hokkien`, `teochew` and `cantonese` are spoken, not written, and no
  text-to-speech ships for them — do not stop the run over it.** Write her copy
  as a **read-aloud script for whoever is with her**: short spoken sentences,
  second person, in a language the household reads, labelled as that at the top.
  Say the gap once in the family copy, and do not raise it again daily. This run
  cannot fix it.
- **Never state why she takes a medicine.** Conditions come from
  `chronic_conditions` and nowhere else. Reading "amlodipine" and writing "your
  blood pressure medicine" is a diagnosis inferred from a drug name, told to the
  patient, with nothing to support it.

**A day with nothing due still produces both artifacts.** Say nothing needs
doing and say what is coming. A brief that arrives only when something is wrong
teaches her its arrival is bad news, and she will stop wanting it.

## How to report a figure

- **Quote the script's `summary` sentence.** Do not retell it. "7 days left" is
  ambiguous about whether today counts; the summary states the convention.
- **Give the family copy the `tool_run_id` and `audit_hash`** for every figure,
  so a number can be traced back to the run that produced it.
- **Name the date, not the interval.** "Order by 16 August" beats "in ten days",
  which is wrong by the time she rereads it.
- **Say what is unclear**, what would settle it, and who to ask — route it to a
  person rather than resolving it yourself.

## Distance is a straight line

`clinic_finder.py` measures point to point over a dated snapshot, rounded to
10 m. **It is not a walk, and no route was computed** — nothing here knows the
way, the crossings, or whether the entrance is step-free. Say "about 400 m
away", never "a five-minute walk". Tell her to call ahead.

## What this skill does not do

- **Does not compute a number in prose.** Not a day count, not a date
  difference, not a subtotal — especially not when the arithmetic looks trivial.
- **Does not give clinical advice** — no dose, no diagnosis, no reading of a
  result, no view on whether something is serious. A question about the medicine
  goes to a pharmacist or a doctor, and you say so.
- **Does not assert eligibility.** Only `likely eligible`, `worth checking` or
  `insufficient information`, and every scheme claim carries
  `criteria as of YYYY-MM-DD — verify at <URL>`. Never "you qualify".
- **Does not submit, log in, or handle a credential** — no portal, no Singpass,
  no password, no OTP, not even one a user volunteers.
- **Does not skip her copy.** A run stopping after `out/family/` is unfinished,
  not merely terse. If you cannot write hers, say so and why.
