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
