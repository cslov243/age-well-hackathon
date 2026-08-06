---
name: letter-triage
description: "Reads a government, clinic or insurer letter that has arrived for an elderly person, quotes the deadline, amount and issuer straight off the page, files one record per document, and writes both a family summary and a plain-words copy for her. trigger: a document arriving in the watched inbox folder, and equally whenever a caregiver or the senior sends a photo of a letter or asks what a letter says or what it wants doing. examples: reading a CHAS renewal letter, explaining an insurer's claim decision, checking what a letter is asking for and by when"
---

# Letter triage

Runs when a document arrives in `inbox/`, **and** on request. Whether a watched
folder fires unattended is not known, so every step below works identically when
a caregiver hands you a photo and asks what it says.

**This is the only skill where you are the instrument.** Reading the page is
yours. Every date, amount and day count after that comes from a script.

## The chain

**Pass absolute paths.** Hash first, read second, file third:

```
letter_record.py          --input <check.json>  --records <extracted/>
                          ... you read the pages ...
letter_record.py          --input <record.json> --records <extracted/>
insurance_claim_review.py --input <claims_input.json> --output <claims.json>
```

`mode` has no default. `"check"` hands over `source_files` and nothing else, and
answers whether these bytes are already filed. **`should_extract: false` means
stop** — the letter has a record already, and reading it again buys a second
record that competes with the first rather than correcting it. Do not open the
image before that answer comes back.

`"record"` then takes what you read. `doc_type` is one of the seven in
`conventions.doc_types`; an unrecognised letter is `other`, never the nearest
match. Every key of `fields` is required — `issuer`, `issue_date`, `deadline`,
`amounts`, `required_action` — **`null` where the letter never said it.** A field
you never looked for and a field with nothing to find are the same JSON.

When `doc_type` is `insurance`, build the claim from the record and run
`insurance_claim_review.py`. That is not a separate skill and does not need one.

## Quote it or leave it null

Every issuer, date and amount needs a **verbatim** snippet, quoted under its own
field path — `deadline`, `amounts[0]` — exactly as the page prints it.

| Looks alike | Is not |
|---|---|
| **Absent** — the letter never mentioned it | `null`, no snippet. That is an honest answer and carries no flag |
| **Present but unquotable** — you believe you saw it | *Unknown.* The script nulls it, lists it in `missing_evidence` and flags the record `REQUIRES_HUMAN_CONFIRMATION` |

- **Never supply a value you cannot quote.** The script checks that the value
  appears in the snippet, so a plausible figure against nearby text is refused,
  not accepted. Supplying one once put SGD 4,320.00 in a draft against a letter
  that read SGD 1,220.00.
- **Never report a confidence, and never soften one in prose.** Not a
  percentage, not "fairly sure", not "appears to say". Your confidence is
  highest exactly where the form is familiar and the reading is invented. The
  quotation is the whole signal.
- **A flagged record is a correct outcome, not a failed run.** Say plainly which
  fields need a person and what the letter would have to show to settle them.

**Grouping pages is your call, and the bias is to split.** Same issuer and same
date is not one letter — two notices from one agency on one day merge into a
single record and a deadline vanishes. Split on any conflicting date, amount or
type. A duplicate costs a second notification; a merge costs the deadline.

## Every run produces both artifacts

```
- [ ] 1. Check, read the pages, then file into extracted/ and read the JSON
- [ ] 2. Move the pages to processed/ — they are never re-read
- [ ] 3. Write the family artifact under out/family/ — what the letter wants, by
         when, what was left null and why, and the audit_hash behind it
- [ ] 4. Write the senior artifact under out/senior/ — what it says and what
         happens next, in her language, large print, plain words, second person
- [ ] 5. Append the disclosure line to out/senior/shared_log.jsonl
```

Read her language from `HouseholdProfile`; **never assume** it. Address her
directly: "this letter asks you to send three receipts by 15 September", never
"she needs to". If the profile names a spoken-only language, write hers as a
read-aloud script and say so once. Expand every acronym.

**Never say why a letter was sent to her.** A clinic's name is not a condition;
conditions come from `chronic_conditions` and nowhere else.

Quote the script's `summary` rather than retelling it.

## What this skill does not do

- **Does not compute a number in prose** — not a day count, not a total, not
  how long is left. That is a script's job even when it looks trivial.
- **Does not fill a gap.** An unquotable field stays null and flagged. A best
  guess dressed as a reading is what this loop exists to prevent.
- **Does not re-read a document it has already filed**, and does not move a
  page out of `inbox/` until its record is written.
- **Does not give clinical advice** — no dose, no diagnosis, no reading of a
  test result. That goes to a pharmacist or a doctor, and you say so. Nothing
  touching a Lasting Power of Attorney.
- **Does not assert eligibility** — only `likely eligible`, `worth checking` or
  `insufficient information`, each with `criteria as of YYYY-MM-DD`. A renewal
  letter arriving is not a decision that anything was renewed.
- **Does not reply, submit, log in, or handle a credential** — no portal, no
  Singpass, no password, no OTP, not even one a user volunteers. It prepares the
  answer; a person sends it.
- **Does not skip her copy.** A run stopping after `out/family/` is unfinished.
  The letter is about her life; she reads it first.
