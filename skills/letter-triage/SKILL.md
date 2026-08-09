---
name: letter-triage
description: 'Reads a government, clinic or insurer letter that has arrived for an elderly person, quotes its deadline, amount and issuer off the page, files one record per document, and writes a family summary and a plain-words copy for her. Use when a document arrives in the watched inbox folder, and when user sends a photo of a letter or asks "what does this letter say".'
---

# Letter triage

Runs when a document arrives in `inbox/`, **and** on request — a watched folder
may never fire unattended, so every step works on a photo handed to you.

This files a record and drafts two summaries — it never replies, submits, or logs in anywhere, and it never gives clinical advice about what a letter's contents mean for her health.

**You are the instrument here.** Reading the page is yours; every date, amount
and day count in either artifact is one a script produced.

## The chain

**Pass absolute paths.** Hash first, read second, file third:

```
letter_record.py          --input <check.json>  --records <extracted/>
                          ... you read the pages ...
letter_record.py          --input <record.json> --records <extracted/>
insurance_claim_review.py --input <claims_input.json> --output <claims.json>
confirmations.py          --input <confirm_input.json>
```

`mode` has no default. `"check"` hands over `source_files` alone and answers
whether these bytes are already filed. **`should_extract: false` means stop** —
a second reading files a record that competes with the first.

`"record"` then takes what you read, **and the check run's `audit_hash` as
`check_audit_hash`** — it recomputes the check and refuses a mismatch.
If it refuses on a mismatch, do not retry with the same record.json. Run check again on exactly the same source_files, take its new check_audit_hash, and rebuild record.json around that — never the old one
A letter
already filed is answered, not refused: nothing is written and the run is
finished. **Never delete or move a record in `extracted/`.** `doc_type` is one
of the seven in
`conventions.doc_types`; an unrecognised letter is `other`, never the nearest
match. Every key of `fields` is required — `issuer`, `issue_date`, `deadline`,
`amounts`, `required_action` — **`null` where the letter never said it.** When
`doc_type` is `insurance`, build the claim and run `insurance_claim_review.py`. If it refuses a field as unquotable, the rule is the same as letter_record.py's: leave it null, let the flag stand, and move on — never retype a value you believe is correct against the script's judgement.

### Worked example

A photo of an insurer's letter arrives. First, the check:

`check.json`:
```json
{"source_files": ["inbox/letter_20260809_1.jpg"]}
```
```
python3 letter_record.py --input check.json --records extracted/
```
Response: {"should_extract": true, "check_audit_hash": "b7e2f9..."}
(should_extract true means this letter hasn't been filed before — proceed to read it.)

You read the pages, then assemble record.json using check_audit_hash from the check response:

`record.json`:
```json
{"check_audit_hash": "b7e2f9...",
 "doc_type": "insurance",
 "evidence": {"deadline": "must be submitted by 27 Aug 2026",
              "amounts[0]": "SGD 1,220.00"},
 "fields": {"issuer": "Great Eastern",
            "issue_date": "2026-08-01",
            "deadline": "2026-08-27",
            "amounts": ["1220.00"],
            "required_action": "submit supporting documents"}}

python3 letter_record.py --input record.json --records extracted/
```

Since doc_type is "insurance", build claims_input.json from this record's fields
(verbatim — never rebuilt) and run insurance_claim_review.py, then confirmations.py
over every result the run produced.
## Quote it or leave it null

Every issuer, date and amount needs a **verbatim** snippet under its own field
path — `deadline`, `amounts[0]` — as the page prints it.

- **Absent** — the letter never mentioned it: `null`, no snippet. An honest
  answer, and no flag.
- **Present but unquotable** — you believe you saw it: *unknown*. The script
  nulls it, lists it in `missing_evidence`, flags `REQUIRES_HUMAN_CONFIRMATION`.

- **Never supply a value you cannot quote.** The script checks it appears in its
  snippet; a plausible figure against nearby text is refused.
- **Never report a confidence, and never soften one** — no percentage, no
  "fairly sure", no hedging. The quotation is the whole signal.
- **A value the script refused is not a value.** It is carried into no claim, no
  artifact and no answer, and never by hand into another script.
- **A flagged record is a correct outcome, not a failed run.** Whether a person
  is needed is confirmations.py's answer, not yours: quote its sentence **and
  every items[].ask** verbatim, and never write that no confirmation is needed
  unless it said so.

**Grouping pages is your call; the bias is to split.** Same issuer and date is
not one letter. Split on any conflicting date, amount or type: a duplicate costs
a notification, a merge costs a deadline.

## Every run produces both artifacts

```
- [ ] 1. Run the check. should_extract: false means stop — do not open the pages, do not run record. Quote the existing record's audit_hash from existing_record_path and finish the run."
- [ ] 2. Read the pages, then file into extracted/ with its check_audit_hash
- [ ] 3. Move the pages to processed/ — they are never re-read
- [ ] 4. Run confirmations.py over every result this run produced
- [ ] 5. Write the family artifact under out/family/ — the confirmations
         sentence quoted, what the letter wants, by when, its audit_hash
- [ ] 6. Write her copy under out/senior/ — what she must confirm, what it says,
         what happens next; her language, large print, plain words, second person
- [ ] 7. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; **never assume** it. Address her
directly, in the second person — "this letter asks you", never "she needs to".
Expand every acronym.

- **Never substitute a near-enough language.** Mandarin because the profile says
  `hokkien` is fluent, confident, and not hers.
- **`hokkien`, `teochew` and `cantonese` are spoken, not written** — do not stop
  the run. Write hers as a read-aloud script in a language the household reads,
  and **label it with the language it is written in**, not the one she speaks.
  Say the gap once.
- **Never say why a letter was sent to her.** A clinic's name is not a
  condition; those come from `chronic_conditions` alone.
- **Where a figure came from has two answers**: printed on the page, or
  worked out from what the page prints. Never tell her the letter says a
  number a script computed — the balance she owes is printed nowhere she can
  check.
- **Figures stay in digits** — words beside them, never instead: *SGD 1,220.00 —
  one thousand two hundred and twenty dollars*. Spelling one out made hers a
  thousand dollars wrong, in the copy nobody re-reads.

Quote the script's `summary` rather than retelling it.

## What this skill does not do

- **Does not compute a number in prose** — not a day count, not a total,
  however trivial it looks. **A second date beside a correct one is the same
  fault**: a buffer, a lead time. Say she should begin early, not which day.
- **Does not re-read a document it has already filed**, and does not open one
  before the check answers. No page leaves `inbox/` until its record is written.
- **Does not give clinical advice** — no dose, no diagnosis, no reading of a
  test result. Route to a pharmacist or doctor. Nothing touching a Lasting
  Power of Attorney.
- **Does not assert eligibility** — only `likely eligible`, `worth checking` or
  `insufficient information`, each with `criteria as of YYYY-MM-DD`.
- **Does not reply, submit, log in, or handle a credential** — no portal, no
  Singpass, no OTP, not even one volunteered. A person sends it.
- **Does not skip her copy.** Stopping after `out/family/` is an unfinished
  run; the letter is about her life.
