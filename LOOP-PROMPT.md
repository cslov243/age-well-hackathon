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
| 13a | `daily-brief` — nearest clinic and days-of-supply in the senior card | Done |
| 15 | `deadline-watch` — `deadline_calendar.py`, an `.ics` a person imports, and an optional confirmed calendar write | Done |
| 14 | `letter-triage` — `letter_record.py`, the evidence gate, and the entry point for the core loop | Done |

**That is the whole backlog, and it is done.** Three days to submission. Every
remaining item is either blocked on a human, listed below, or an open finding in
`docs/AUDIT-FINDINGS.md`. Everything else —
deadline windows, the escalation cooldown, profile merge, `verify_scheme.py`,
and the remaining two skills — is **cut**, not deferred, and must not be
re-added before 9 August. Their intended behaviour stays recorded in
`docs/AUDIT-FINDINGS.md` for whoever picks this up after Demo Day.

**Two items came off that cut list on 6 August**: the evidence validator and
letter dedupe. Both are inside `letter_record.py` rather than beside it, because
item 14 could not be built without them — the evidence rule says *a script
validates this*, and a `letter-triage` that let the model self-report its
evidence would have shipped the one hard constraint as prose. Dedupe is the same
script's other half: identity is what tells the model not to read a page twice.

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

## Start here — cycle R: what the artifacts say

**Cycles P and Q closed the `check` question for good.** `record` mode now
refuses without the `check` run's `audit_hash` and recomputes it rather than
trusting it, so skipping the call fails at the door instead of being discouraged
(#25). Cycle Q then had to undo the trap that built: refusing the *already
filed* case handed a cold agent one move, and it deleted the record (#26). The
comparison is now scoped to the case where a record would be written, and a
filed letter gets the idempotent answer — nothing written, the run finished.

**Two lessons, and the second is newer than the first.** Moving an answer out of
prose into a script closed #16, #22 and #25. Taking an error *away* closed #26:
the pressure was never a missing rule, it was a refusal with no completion path
behind it. When a script says no, look at what it leaves the caller able to do.

**The chain is now reliable and the artifacts are not.** Cycle Q ran all four
scripts in order for the first time, invented no date and no subtraction — and
wrote the wrong amount in the senior's copy. Read the cycle Q block in
`evals/RESULTS.md` before picking anything.

### How this order was set, 6 August 2026

Reranked after asking of each open finding: **would a more capable model at demo
time fix this?** The eval runs Haiku on purpose — `evals/CASES.md` step 3, *the
point is whether the instructions carry, not whether the model is clever* — so a
failure there is not evidence about the model. And nothing in `plugin.json` pins
a model: WorkBuddy's user picks one in the app, and the only documented
interaction is a toast when the choice lacks vision. A judge installs the plugin
and runs it on whatever they had selected. **"We will run a strong model" is not
a property this plugin can ship**, so it cannot be the answer to any finding
below.

That question sorts the backlog cleanly. A finding whose rule **is not written
anywhere** cannot be model-fixed — no model follows an instruction that is
absent. Those come first, and they turn out to be most of what is left.

Order is: cannot-be-model-fixed × visible in the demo artifact × cost.

### Done in cycle R, 7 August 2026 — items 1, 3 and 4 below

- **#24 — closed in prose.** The derivation rule and the `items[].ask` rule are
  now in `agents/care-navigator.md` (normative), the toolkit `SKILL.md` and
  `skills/letter-triage/SKILL.md`. Both carry the caveat that quoting a script's
  own `summary` verbatim is *not* the defect, even where that summary spells out
  its own arithmetic — without it the rule contradicts every skill that says to
  quote `summary`.
- **#19 — closed in code.** `DOCUMENT_KEYS` plus one `_reject_unknown` call in
  `insurance_claim_review.py`. A misspelled `as_of` now exits 2 naming the key
  and the allowed set, instead of exiting 0 against today's date.
- **#18 — closed both halves.** The two `daily-brief` bullets are in
  `skills/deadline-watch/SKILL.md` and pinned in `tests/test_deadline_watch.py`.
  That file is at its 946-word budget: **five sentences elsewhere were tightened
  to pay for them**, including one duplicate never-compute-a-date bullet already
  stated twice. Anything added there now has to buy its space the same way.
- **New: #29** — `expense_split.py`, `medication_runout.py` and
  `clinic_finder.py` still have #19's hole. Found while verifying this cycle,
  logged with a reproduction, not fixed.
- A **troubleshooting section** was added to the toolkit `SKILL.md` — every
  refusal a caller can hit, verified against the real stderr, and the two
  outcomes that look like failures and are not.

**Still open, in order: 2 (#27), then 5, 6, 7 below.**

1. ~~**#24**~~ — **DONE, cycle R.** Kept for the reasoning.
   **The `ask` is quoted as a sentence and paraphrased as a task.**
   Not a model slip, which is what it looked like at first read. `confirmations.py`
   emits a per-item `ask`, and **the checklist never names that field** — it says
   quote the `sentence`. A field the checklist does not mention is a field that
   gets retold, at any capability. The substitution also runs the wrong way: it
   sends a person to audit a subtraction a script did deterministically and
   leaves the unquotable sentence unread. Quote `ask` as well as `sentence`, and
   add to the toolkit rule that **a derivation is prose arithmetic even when the
   result came from a script** — `30 days from 28 July = 27 August` is invented
   reasoning beside a real date. Cycle Q's copy also composed *"everything in
   this letter is clear and certain"* beside a `null` deadline; same shape as
   #22, which closed by giving the flag a script.
2. **#27 — HIGH. Her copy spelled SGD 1,220.00 out as "two thousand two hundred
   and twenty dollars".** The one finding here where a stronger model genuinely
   helps — it is arithmetic-free re-expression and a good model mostly gets it
   right. Do the **cheap half only: digits beside the words.** One line in a
   skill file. Not the script that emits the spoken form; that is the design-pure
   fix and there is no time for it. It ranks this high despite being
   capability-shaped because it is the only measured defect **neither reader can
   catch** — the family copy and her copy disagree and nothing compares them, and
   she is the person who cannot check it against the letter.
3. ~~**#19**~~ — **DONE, cycle R.** The unknown-key hole one level up in `insurance_claim_review.py`.
   Two lines, the helper exists, no model touches it: a misspelled `as_of`
   resolves to today and every `days_remaining` and `overdue` in the output is
   computed from the wrong day, at exit 0, under a log line reading `as_of
   absent`. Right by coincidence today; wrong on any historical run.
4. ~~**#18**~~ — **DONE, cycle R.** `deadline-watch` had neither half of the language rule. The rule is
   **not in the file**, so capability is irrelevant. It is the skill that runs
   daily, and the failure mode is defaulting her language, which is the thing the
   product exists to prevent. Copy `daily-brief`'s wording, which is the only
   version measured to work.
5. **#23 + #28 + #11 — three decisions, one sitting.** All three are
   `docs/CONTRACTS.md` changes and therefore **stop-and-flag**; none is a cycle
   until answered. (a) Does `--output` stop being optional, and does a run get a
   directory of its own inside the workspace? Cycle Q sent every input through
   `/dev/stdin` and nothing survived the run, so two artifacts quote an
   `audit_hash` nothing on disk can replay. (b) Where does a review output go —
   it landed in `extracted/`. (c) Which `HouseholdProfile` path is canonical:
   `household/profile.json` or `out/household_profile.json`.
6. **#21's remaining half — the offer, not the ban.** Open three cycles. Her copy
   still does not say the balance was worked out from the page. Genuinely
   capability-shaped and the least likely to bite in a controlled demo. **Do only
   if 1–4 are done and the eval is clean.**
7. **#13 — LOW, ship as is.** `deadline-watch` does not reliably win the route
   for a calendar request. Not worth a cycle before 9 August.

**Then re-run case G and read the artifacts — both of them, side by side.**
Every defect in this case for six cycles has been invisible in the JSON and
plain in the prose, and #27 was invisible in the family copy too. **Diff every
figure in `out/senior/` against the record and the claim review by eye.**

Every script on disk is frozen except for #19's one check.

### The answer to give a judge

The pitch is *this agent cannot invent a deadline*. If asked what happens on a
weaker model, **"we run a good one" concedes the claim.** The answer is that
every number comes from a script and the evidence gate is Python — true today,
and the reason the remaining gaps must be in prose polish rather than in the
enforcement path.
