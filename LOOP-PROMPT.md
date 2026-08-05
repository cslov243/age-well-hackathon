# Loop prompt

Paste this to start a session. Read `CLAUDE.md` first, then the doc in `docs/`
that matches what you are about to touch.

Submission **9 August 2026**. Work in a loop, one item at a time, smallest useful
unit first. **Do not batch two backlog items into one cycle.**

## Each cycle

1. **Pick the `Next` row.** Say why it is next. If the repo makes you think the
   order is wrong, say so before starting.
2. **State your assumptions** about input format, edge cases and environment. If
   one is load-bearing and the repo cannot settle it, stop and ask.
3. **Write the test first** — plain `unittest`, run by `python3 -m unittest`. Pin
   boundary cases and failure paths, not the happy path. The original scripts
   passed their smoke tests while badly broken, because the tests only exercised
   inputs that worked.
4. **Write the implementation.** Conventions are in `CLAUDE.md`; follow them to
   the letter.
5. **Run the tests and show the actual terminal output.** Not a summary, not a
   claim. If you cannot run them, say so.
6. **Review before presenting.** Look for: off-by-one date arithmetic, rounding
   that goes the wrong way silently, values accepted but never used, state that
   can be written twice, anything that fails quietly. Report what you found,
   including if it was nothing.
7. **Report:** what changed, what you assumed, what you did not do, what this
   makes possible. Then stop and wait.

## Standing rules

- **Re-read `docs/WORKBUDDY-PLATFORM.md` every cycle that touches a script, a
  `SKILL.md`, an agent file or `plugin.json`.** Follow its formats to the letter.
  WorkBuddy is not in your training data and the published docs are wrong in at
  least one place, so there is nothing to fall back on when you guess.
- Anything tagged `[UNKNOWN]` is an open question. Write for both answers; never
  resolve one by assumption.
- **Never compute a number in prose.** No script produced it → that is a missing
  script, not a thing to work out in your head.
- **Never assert eligibility**, never add a network call to a skill, never write
  code that submits, logs in or handles a credential.
- A change that alters `docs/CONTRACTS.md` — **stop and flag it** rather than
  quietly updating both sides.
- A bug found outside the current item goes into `docs/AUDIT-FINDINGS.md` with a
  reproduction. Do not fix it in this cycle.
- **Adding a script means updating `SKILL.md` in the same cycle.** Two tests fail
  otherwise, deliberately.
- **Adding or removing a test means updating the count in `README.md` in the same
  cycle.** A test executes the README's own command and compares.
- Never weaken an assertion to make a cycle pass. If better wording breaks a
  pinned phrase, re-point the assertion and say so in the report.

## What is true right now

State that goes stale lives in exactly one place each: `CLAUDE.md` for what
exists, `README.md` for the test count, the table below for the order of work.
Do not restate any of them anywhere else.

- **Nothing described in `docs/AUDIT-FINDINGS.md` exists on this machine.** That
  audit ran against the plugin on the WorkBuddy box, which is gone. Every item
  below is **write-fresh**, using the findings as the spec for what the code must
  *not* do — never as a patch to an existing file.
- Tests: `python3 -m unittest discover -s tests`. **Never present a cycle with
  the count lower than it started.** The one skip is `avatars/expert.png`.
- The suite runs itself once in a subprocess, guarded by
  `CARE_NAVIGATOR_README_TEST_CHILD`. The child reports 2 skips, the parent 1.
  That is the guard working, not a second gap.
- Word budgets in `tests/test_project_docs.py` are a **ratchet at the measured
  value**. Editing these docs is zero-sum: a new sentence means removing one.
  Only `SKILL.md` and `README.md` grow, at 120 words per new script.
- Five test files guard prose against code — `test_plugin_manifest`,
  `test_skill_manifest`, `test_readme`, `test_backlog`, `test_project_docs`. Each
  checks **both** directions. Do not weaken them.

**Read the existing scripts before writing a new one and match their
conventions:** `InvalidInput` for anything the script refuses to guess at;
`json.loads(..., parse_float=Decimal)` at the boundary; binary floats rejected
rather than coerced; exact `Fraction`s on any rounding boundary; the
`tool_run_id` / `issued_at` / `audit_hash` envelope; a `conventions` block
stating each rule in words.

Two habits that have each caught a real bug:

- **A required key is not a defaulted one.** `medications`, `claims` and GeoJSON
  `features` are required even though `[]` is legal, because a typo'd key would
  otherwise exit 0 having silently processed nothing.
- **Absent differs from present-but-unusable.** Absent means the document never
  said it, and zero is often right. Present-but-unevidenced means *unknown*;
  substituting zero produced a draft reporting SGD 4,320.00 owed instead of
  SGD 1,220.00.

**Run the script and read its actual prose output before presenting a cycle.**
Both prose bugs found so far — `"1 tablets left over"` and the wrong money figure
above — passed the whole suite. Tests do not read English.

## Backlog

Order set 4 August 2026, after the pivot to connectors. Reasoning:
`docs/DECISIONS.md`.

| # | Item | Status |
|---|------|--------|
| 1 | `expense_split.py` | Done |
| 2 | `medication_runout.py` | Done |
| 3 | `insurance_claim_review.py` | Done |
| 4 | The manifest and the agent file | Done |
| 5 | The toolkit `SKILL.md` | Done |
| 6 | `README.md` | Done |
| 7 | `CLAUDE.md` cut to rules; `docs/DECISIONS.md` split out | Done |
| 8 | `SKILL.md` and the agent body cut to rules | Done |
| 9 | This file and `docs/*` restructured; the backlog guarded | Done |
| 10 | `fetch_references.py` — the only file permitted to open a socket | Done |
| 11 | `clinic_finder.py` — nearest CHAS clinic over the snapshot; haversine; distance rounded to 10 m; asserts nothing about eligibility | Done |
| 12 | `pharmacy_cart.py` — cart draft from a run-out forecast. No API call, no invented price, prescription-only items routed away from the cart | Next |
| 13 | `medication-watch` and `daily-brief` — the two skills that make the connectors visible | Later |
| 14 | `letter-triage` — the entry point for the core loop | Later |
| 15 | `deadline_window.py` — fix the `this_week` comparison | Later |
| 16 | Escalation cooldown — `last_notified_at` plus a window; advance the level and stamp the time in one write | Later |
| 17 | `household_profile.py` — merge instead of clobber, write a `.bak`, require an explicit path | Later |
| 18 | Shared evidence validator — one module instead of the two private copies | Later |
| 19 | `letter_dedupe.py` — content-hash idempotency, split-on-conflict page grouping | Later |
| 20 | `verify_scheme.py` — the 30-day freshness check. Closed-vocabulary output only | Later |
| 21 | `scheme-radar`, `deadline-watch`, `family-dispatch` | Later |
| 22 | Behavioural evaluations — `docs/AUDIT-FINDINGS.md` #8 | Dropped |

Items 10–12 are the pivot: the connectors are where the agent does something
concrete in the world *for the senior*, rather than for the family's paperwork.
Insurance and expense splitting are finished and **frozen** — no further cycles
unless a bug appears.

Write every skill so it works both scheduled and caregiver-triggered, because
whether unattended scheduled runs clear the permission dialog is `[UNKNOWN]`.

## Blocked on a human, not on a cycle

- `avatars/expert.png`, 1024×1024. Not stubbed on purpose.
- Whether a dragged PDF is readable natively with a vision-capable model — test a
  digitally-generated one *and* a scanned one, they differ.
- Whether a scheduled automation can carry Full Access, or stalls on the dialog.
- A native check of the `zh` strings in `plugin.json` before submission.

## Start here — cycle F, backlog item 12: `pharmacy_cart.py`

The second connector. `medication_runout.py` forecasts the run-out; this turns
one into a **cart draft a person reviews and pays for**, and nothing further.

Read `docs/CONTRACTS.md` → `MedicationRecord`, and `docs/DECISIONS.md` on
third-party commerce before writing a line of it.

- `python3 scripts/pharmacy_cart.py --input <in.json> [--output <out.json>]`.
- Consumes a `medication_runout.py` result. **It never recomputes a forecast** —
  a second implementation of the same arithmetic is a second answer.
- Output carries `requires_human_checkout: true`, line items, and a deep link
  that is a string in an artifact. **No API call, no payment, no stored card, no
  standing authority.**
- **No invented price.** A price exists only if a snapshot or the caregiver
  supplied one. Any price missing → the total is suppressed entirely, not
  estimated. A confident wrong total is worse than no total.
- **Prescription-only items never enter the cart.** They route to the refill
  path with a plain sentence saying why. This needs `supply_channel` on
  `MedicationRecord` — a **contract change: stop and flag it** before writing.
- `SKILL.md` and `README.md` gain a section in the same cycle.
