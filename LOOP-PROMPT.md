# Loop prompt — paste this to start a Claude Code session

Read `CLAUDE.md` first, then the doc in `docs/` that matches what you're about
to touch. Do not skip this; WorkBuddy is not in your training data and the
published docs are wrong in at least one place.

You are working on Care Navigator. Submission is **9 August 2026**. Work in a
loop, one item at a time, smallest useful unit first.

## Each cycle

1. **Pick one item** from the backlog below — the highest one not done. Say
   which, and why it's next. If something in the repo makes you think the order
   is wrong, say so before starting.
2. **State your assumptions** about input format, edge cases, and environment
   before writing anything. If an assumption is load-bearing and you can't
   resolve it from the repo, stop and ask me rather than guessing.
3. **Write the test first**, as a plain `unittest` file that runs with
   `python -m unittest`. Pin the actual behaviour, including the boundary cases
   and the failure paths — not just the happy path. The existing scripts passed
   their "smoke tests" while being badly broken, because the tests only
   exercised inputs that worked.
4. **Write the implementation.** Standard library only. `Decimal` for money.
   `pathlib` for paths. Explicit `encoding='utf-8'` on every file open. Validate
   and early-exit at the top. Structured logging to stderr, JSON to stdout, never
   mixed. No network calls.
5. **Run the tests and show me the actual output.** Not a summary, not a claim
   that they pass — the terminal output. If you can't run them, say so plainly
   instead of asserting success.
6. **Review your own work before presenting it.** Specifically look for:
   off-by-one errors in date arithmetic, rounding that silently goes the wrong
   direction, values accepted but never used, state that can be written twice,
   and anything that fails quietly rather than loudly. Report what you found,
   including if the answer is nothing.
7. **Report:** what changed, what you assumed, what you did not do, and what
   this now makes possible. Then stop and wait for me.

Do not batch multiple backlog items into one cycle. Do not move on because
something looks easy.

## Standing rules

- **Never compute a number in prose.** If a value is needed and no script
  produced it, that's a missing script, not a thing to work out in your head.
- **Never assert eligibility.** Three permitted strings, listed in `CLAUDE.md`.
- **Never add a network call to a skill.** See `docs/DATA-SOURCES.md`.
- **Never write code that submits, logs in, or handles a credential.**
- If a change would alter a contract in `docs/CONTRACTS.md`, stop and flag it
  rather than quietly updating both sides.
- If you find a bug outside the current item, write it into
  `docs/AUDIT-FINDINGS.md` with a reproduction and keep going. Don't fix it in
  this cycle.

## State of the repo — read before picking an item

- **The audited scripts do not exist on this machine.** This repo was docs-only;
  the plugin described in `docs/AUDIT-FINDINGS.md` lives on the WorkBuddy box.
  Every backlog item is therefore **write-fresh**, using the audit findings as
  the spec for what the code must *not* do — not a patch to an existing file.
- Tests live in `tests/`, run with `python3 -m unittest discover -s tests`.
- Scripts live in `skills/care-coordinator-toolkit/scripts/`.

**Read `expense_split.py` before starting a new script and match its
conventions:** an `InvalidInput` exception for anything the script refuses to
guess at; `json.loads(..., parse_float=Decimal)` at the boundary; binary floats
rejected rather than coerced; exact `Fraction`s wherever a proportional division
could put a value on a rounding boundary; the `tool_run_id` / `issued_at`
`+08:00` envelope; and an audit hash over the computed output as well as the
resolved inputs, excluding `tool_run_id` and `issued_at` so a replay reproduces
it.

## Backlog, in order

Fixes first — the existing scripts are load-bearing and three of them are
wrong. Reproductions are in `docs/AUDIT-FINDINGS.md`.

1. ~~`expense_split.py` — apply the weights it currently ignores; `Decimal`
   throughout; deterministic residual-cent rule; fail loudly on an unmatched
   payer.~~ **Done** — `scripts/expense_split.py` + `tests/test_expense_split.py`,
   46 tests. Weights applied in `weighted` (must sum to 1) and `ratio`
   (normalised, both forms reported) modes; residual cents assigned largest
   weight first, ties by member id; unmatched `paid_by` raises.
2. `medication_runout.py` — `math.floor` not `round`; derive everything from a
   single resolved `as_of`; state the dose-boundary convention in the output
   text.
3. `deadline_window.py` — fix the `this_week` comparison.
4. Escalation cooldown — `last_notified_at` plus a cooldown window, per
   `docs/CONTRACTS.md`. Advancing the level and stamping the time happen in one
   write.
5. `household_profile.py` — merge instead of clobber, write a `.bak`, require an
   explicit path.

Then the missing pieces:

6. Evidence validator — enforce the null-if-no-snippet rule and the
   `REQUIRES_HUMAN_CONFIRMATION` flag. Small, and everything else leans on it.
7. `letter_dedupe.py` — content-hash idempotency for documents, with the
   split-on-conflict page grouping rule.
8. `verify_scheme.py` — the 30-day freshness check that `SKILL.md` already
   claims exists. Closed-vocabulary output only.
9. `tools/fetch_references.py` — offline snapshot fetcher, human-run, writes
   dated files plus a manifest into `references/`.

Then the skills themselves — `letter-triage`, `daily-brief`,
`medication-watch`, `scheme-radar`, `deadline-watch`, `family-dispatch`. Write
each so it works both scheduled and caregiver-triggered, because whether
unattended scheduled runs clear the permission dialog is still unknown.

## Start here — cycle 2, backlog item 2: `medication_runout.py`

Read `CLAUDE.md`, `docs/CONTRACTS.md` and `docs/AUDIT-FINDINGS.md` §2, then
begin.

Forecast when each medication runs out, from supply on hand and dose rate.

The findings it must not reproduce:

- `int(round(days_remaining))` used banker's rounding, so 15 and 17 tablets at
  2/day produced the **same** run-out date and 7.5 days rounded *up* to 8.
  **Never round supply up. Floor it.**
- Dates derived from `as_of` while escalation derived from the wall clock, so a
  historical `as_of` gave past dates with present-tense urgency and nothing
  replayed deterministically. **One resolved `as_of` at the top**, used for every
  date and every status. This is a `CONTRACTS.md` requirement, not just a bug.
- A bare day count is ambiguous about whether today's doses are already taken.
  **The output must state the convention in words**, e.g. `last dose on the
  evening of 9 Aug, assuming today's doses have been taken`.

**Hard boundary:** pure arithmetic. No clinical judgement anywhere — no dose
suggestions, no "you should", no interpretation of what running out means
medically. It reports a date and a supply count and hands off.

Before writing code, do not guess at these — flag or ask:

1. `docs/CONTRACTS.md` defines LetterRecord, TaskRecord and HouseholdProfile, but
   **there is no MedicationRecord**. `household/medication.json` is referenced in
   `CLAUDE.md` and specified nowhere. Proposing that shape is a contract change —
   surface it rather than quietly inventing one and building on it.
2. **The dose-boundary convention itself.** Whether `as_of`'s doses count as
   taken or still to be taken shifts every run-out date by a day. Pick a
   recommendation, say why, and get it confirmed.
3. **PRN / as-needed medications** with no fixed daily rate. Forecasting one is a
   clinical judgement wearing an arithmetic costume. Expected: excluded from the
   forecast and reported separately — but decide and say so.
4. **Refill lead time.** The number a caregiver acts on is "order by", not "runs
   out"; that needs a lead-time input, not a hardcoded assumption about how long
   a polyclinic repeat prescription takes.

Assumptions and open questions first, then the test file, then the
implementation.
