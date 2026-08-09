
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
