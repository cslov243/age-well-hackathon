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
7. **Run the behavioural evaluation** — `evals/CASES.md`. Spawn one cold cheap
   subagent per case, grade the three axes, append a dated block to
   `evals/RESULTS.md`. This is the only check that reads English, and every
   defect it has found so far passed the whole unittest suite. Skip it only if
   the cycle touched no skill file, no agent file and no script.
8. **Report:** what changed, what you assumed, what you did not do, what this
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
- **Never assert eligibility**, and never write code that submits, logs in or
  handles a credential. A script may fetch, but every fetched fact renders its
  URL and retrieval time, and the test suite stays offline.
- A change that alters `docs/CONTRACTS.md` — **stop and flag it** rather than
  quietly updating both sides.
- A bug found outside the current item goes into `docs/AUDIT-FINDINGS.md` with a
  reproduction. Do not fix it in this cycle.
- **Adding a script means updating `SKILL.md` in the same cycle.** Two tests fail
  otherwise, deliberately.
- Never weaken an assertion to make a cycle pass.

## What is true right now

State that goes stale lives in exactly one place each: `CLAUDE.md` for what
exists, `README.md` for the test count, the table below for the order of work.
Do not restate any of them anywhere else.

- **Nothing described in `docs/AUDIT-FINDINGS.md` exists on this machine.** That
  audit ran against the plugin on the WorkBuddy box, which is gone. Every item
  below is **write-fresh**, using the findings as the spec for what the code must
  *not* do — never as a patch to an existing file.
- Tests: `python3 -m unittest discover -s tests`. The one skip is
  `avatars/expert.png`.
- Three test files guard prose against code — `test_plugin_manifest`,
  `test_skill_manifest`, `test_readme`. They check that every script and path
  named on disk exists and that documented invocations and worked examples
  actually run. They no longer police wording: constraint prose is pinned in
  **one** place, the agent body, and nowhere else. Do not re-add phrase pins to
  the README or a `SKILL.md`.

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
| 10 | `fetch_references.py` — the snapshot fetcher, run by a person | Done |
| 11 | `clinic_finder.py` — nearest CHAS clinic over the snapshot; haversine; distance rounded to 10 m; asserts nothing about eligibility | Done |
| 12 | `pharmacy_cart.py` — cart draft from a run-out forecast. No API call, no invented price, prescription-only items routed away from the cart | Done |
| 13 | `purchase_terms.py` and the `medication-watch` skill — the chain that makes the connectors visible | Done |
| 13a | `daily-brief` — nearest clinic and days-of-supply in the senior card | Next |
| 14 | `letter-triage` — the entry point for the core loop | Later |

**That is the whole backlog.** Four days to submission, and the demo has no
entry point: nothing extracts a letter and nothing reaches the senior. 13a and
14 are the two items that make the pitch true on stage. Everything else —
deadline windows, the escalation cooldown, profile merge, the shared evidence
validator, letter dedupe, `verify_scheme.py`, and the remaining three skills —
is **cut**, not deferred, and must not be re-added before 9 August. Their
intended behaviour stays recorded in `docs/AUDIT-FINDINGS.md` for whoever picks
this up after Demo Day.

Items 10–13 were the pivot: the connectors are where the agent does something
concrete in the world *for the senior*, rather than for the family's paperwork.
Every script now on disk is **frozen** — no further cycles unless a bug appears.

Write every skill so it works both scheduled and caregiver-triggered, because
whether unattended scheduled runs clear the permission dialog is `[UNKNOWN]`.

## Blocked on a human, not on a cycle

- `avatars/expert.png`, 1024×1024. Not stubbed on purpose.
- Whether a dragged PDF is readable natively with a vision-capable model — test a
  digitally-generated one *and* a scanned one, they differ.
- Whether a scheduled automation can carry Full Access, or stalls on the dialog.
- A native check of the `zh` strings in `plugin.json` before submission.

## Start here — cycle H, backlog item 13a: `daily-brief`

The second skill, and the one the senior actually hears. `medication-watch`
tells her what is running out; this is the 8am briefing that reaches her whether
or not anything is wrong.

Re-read `docs/WORKBUDDY-PLATFORM.md` first. Skill format is not in your training
data and the published docs are wrong in at least one place.

- Scheduled 8am, **and** caregiver-triggered. Whether an unattended run clears
  the permission dialog is `[UNKNOWN]`; write for both answers.
- **Senior-facing first.** The family artifact is the secondary one here, which
  is the reverse of every other skill. Address her directly, second person.
- **Consumes structured records only** — `extracted/`, the forecast, the profile.
  It re-reads no document and invokes no vision model, which is what makes a
  daily run cost almost nothing.
- `clinic_finder.py` supplies the place and distance when one is needed. **Never
  call it a walk** — it is a straight line and no route was computed.
- A day with nothing due still produces both artifacts. A brief that appears
  only when something is wrong teaches her that its arrival is bad news.
- Append one line to `out/senior/shared_log.jsonl`.
- Follow `skills/medication-watch/SKILL.md` for shape — same frontmatter rules,
  same checklist, its own word budget in `tests/test_daily_brief.py`.
