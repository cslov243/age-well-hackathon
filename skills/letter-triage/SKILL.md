---
name: letter-triage
description: "Reads a government, clinic or insurer letter that has arrived for an elderly person, quotes its deadline, amount and issuer off the page, files one record per document, and writes a family summary and a plain-words copy for her. trigger: a document arriving in the watched inbox folder, and equally whenever a caregiver or the senior sends a photo of a letter or asks what one says. examples: reading a CHAS renewal letter, explaining an insurer's claim decision, checking what a letter is asking for and by when"
---

# Letter triage

Runs when a document arrives in `inbox/`, **and** on request — a watched folder
may never fire unattended, so every step works on a photo handed to you.

**You are the instrument here.** Reading the page is yours; every date, amount
and day count in either artifact is one a script produced.

## The chain

**Pass absolute paths.** Hash first, read second, file third:

```
letter_record.py          --input <check.json>  --records <extracted/>
                          ... you read the pages ...
letter_record.py          --input <record.json> --records <extracted/>
insurance_claim_review.py --input <claims_input.json> --output <claims.json>
```

`mode` has no default. `"check"` hands over `source_files` alone and answers
whether these bytes are already filed. **`should_extract: false` means stop** —
a second reading buys a record that competes with the first rather than
correcting it. Do not open the image before that answer comes back.

`"record"` then takes what you read. `doc_type` is one of the seven in
`conventions.doc_types`; an unrecognised letter is `other`, never the nearest
match. Every key of `fields` is required — `issuer`, `issue_date`, `deadline`,
`amounts`, `required_action` — **`null` where the letter never said it.** When
`doc_type` is `insurance`, build the claim and run `insurance_claim_review.py`.

## Quote it or leave it null

Every issuer, date and amount needs a **verbatim** snippet under its own field
path — `deadline`, `amounts[0]` — exactly as the page prints it.

- **Absent** — the letter never mentioned it: `null`, no snippet. An honest
  answer, and no flag.
- **Present but unquotable** — you believe you saw it: *unknown*. The script
  nulls it, lists it in `missing_evidence`, flags `REQUIRES_HUMAN_CONFIRMATION`.

- **Never supply a value you cannot quote.** The script checks the value appears
  in its snippet; a plausible figure against nearby text is refused.
- **Never report a confidence, and never soften one** — no percentage, no
  "fairly sure", no "appears to say". The quotation is the whole signal.
- **A value the script refused is not a value.** The refusal belongs to the
  number, not the record. It is carried into no claim, no artifact and no
  answer, and never by hand into another script.
- **A flagged record is a correct outcome, not a failed run.** Name the flag in
  both artifacts and your answer, say which fields need a person and what the
  letter would have to show to settle them.

**Grouping pages is your call; the bias is to split.** Same issuer and date is
not one letter. Split on any conflicting date, amount or type: a duplicate costs
a notification, a merge a deadline.

## Every run produces both artifacts

```
- [ ] 1. Check, read the pages, then file into extracted/ and read the JSON
- [ ] 2. Move the pages to processed/ — they are never re-read
- [ ] 3. Write the family artifact under out/family/ — every flag, what the
         letter wants, by when, what was left null, its audit_hash
- [ ] 4. Write her copy under out/senior/ — what she must confirm, what it says,
         what happens next; her language, large print, plain words, second person
- [ ] 5. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; **never assume** it. Address her
directly, in the second person — "this letter asks you to send three receipts",
never "she needs to". Expand every acronym.

- **Never substitute a near-enough language.** Mandarin because the profile says
  `hokkien` is fluent, confident, and not hers.
- **`hokkien`, `teochew` and `cantonese` are spoken, not written** — do not stop
  the run. Write hers as a read-aloud script in a language the household reads,
  and **label it with the language it is written in**, not the one she speaks: "read-aloud script, in English". Say the gap
  once.
- **Never say why a letter was sent to her.** A clinic's name is not a
  condition; those come from `chronic_conditions` alone.
- **Where a figure came from has two answers**: printed on the page, or
  worked out from what the page prints. Never tell her the letter says a
  number a script computed — the balance she owes is printed nowhere she can
  check.

Quote the script's `summary` rather than retelling it.

## What this skill does not do

- **Does not compute a number in prose** — not a day count, not a total, not
  how long is left, however trivial it looks. **A second date beside a correct
  one is the same fault** — a buffer, a lead time, a day to start gathering by.
  Say she should begin early; do not name a day.
- **Does not re-read a document it has already filed**, and does not open one
  again before the check answers. It moves no page out of `inbox/` until its
  record is written.
- **Does not give clinical advice** — no dose, no diagnosis, no reading of a
  test result. Route to a pharmacist or doctor. Nothing touching a Lasting Power
  of Attorney.
- **Does not assert eligibility** — only `likely eligible`, `worth checking` or
  `insufficient information`, each with `criteria as of YYYY-MM-DD`. A renewal
  letter arriving is not a decision that anything was renewed.
- **Does not reply, submit, log in, or handle a credential** — no portal, no
  Singpass, no OTP, not even one a user volunteers. A person sends it.
- **Does not skip her copy.** Stopping after `out/family/` is an unfinished
  run; the letter is about her life.
