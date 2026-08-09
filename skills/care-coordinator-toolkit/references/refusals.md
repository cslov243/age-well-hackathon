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
