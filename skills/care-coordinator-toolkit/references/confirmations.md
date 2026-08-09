
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
