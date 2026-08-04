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

- **Re-read `docs/WORKBUDDY-PLATFORM.md` every cycle that touches a script, a
  `SKILL.md`, an agent file, or `plugin.json`, and follow its formats
  strictly — to the letter, not the spirit.** WorkBuddy is not in your training
  data and the published English docs are wrong in at least one place, so there
  is nothing to fall back on when you guess. In particular:
  - The script invocation contract is fixed:
    `python3 scripts/<name>.py --input <in.json> [--output <out.json>]`;
    `--input` absent → stdin, `--output` absent → stdout; every output object
    carries `tool_run_id` (uuid4) and `issued_at` (ISO 8601, `+08:00`); exit 0
    on success and raise on bad input.
  - **Take every path as an argument.** The working directory at WorkBuddy
    invocation time is `[UNKNOWN]`; a relative default will not resolve.
  - Skills are `SKILL.md` with YAML frontmatter. The docs saying `skill.yml`
    are **wrong** — do not follow them.
  - `plugin.json` display fields, `tags` and `quickPrompts` are `{en, zh}`
    objects, never bare strings.
  - The plugin tree is `.codebuddy-plugin/`, `agents/`, `skills/<name>/`
    (`SKILL.md` + `scripts/` + `references/` + `templates/`), `avatars/`,
    `README.md`. Put new files where that tree says, not where they feel
    natural.
  - Plugin-payload files are CRLF on the target machine. `.gitattributes`
    enforces this — do not hand-convert line endings or override it.
  - Anything the doc tags `[UNKNOWN]` is an open question. Write for both
    answers; never resolve one by assumption.
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

- **Nothing described in `docs/AUDIT-FINDINGS.md` exists on this machine.** That
  audit was run against the plugin on the WorkBuddy box, which is gone. Every
  backlog item is therefore **write-fresh**, using the audit findings as the
  spec for what the code must *not* do — not a patch to an existing file.
  Anything in this repo now was written here, in a cycle.
- Tests live in `tests/`, run with `python3 -m unittest discover -s tests`.
  **304 currently pass, with 1 skip. Never present a cycle with that number
  lower.** The skip is `avatars/expert.png`, which is a human to-do, not a gap
  a cycle can close — it turns green by itself once the file lands.
- **The suite runs itself once, in a subprocess.** `tests/test_readme.py`
  executes the test command the README prints, guarded against recursion by the
  `CARE_NAVIGATOR_README_TEST_CHILD` environment variable, so the wall-clock time
  is roughly double. The child run reports 2 skips; the parent reports 1. That is
  the guard working, not a second gap.
- **`README.md` states the total test count**, and a test executes the suite and
  compares. **Any cycle that changes the number of tests must update the README
  in the same cycle** — the number was printed on purpose rather than omitted,
  because it is the most useful figure in the file for a judge, and pinning it is
  what keeps it from ageing quietly.
- Scripts live in `skills/care-coordinator-toolkit/scripts/`. Three exist:
  `expense_split.py`, `medication_runout.py`, `insurance_claim_review.py`.
- **Of the plugin tree, `.codebuddy-plugin/plugin.json`, `agents/care-navigator.md`,
  `skills/care-coordinator-toolkit/SKILL.md` and its `scripts/` exist.** Written
  fresh in cycles 4 and 5 — no copy of the originals survived, git history and
  the whole of `~/Desktop` were searched. `README.md` landed in cycle 7.
  **Still missing: `avatars/expert.png`**, and it stays missing until a human
  supplies it. No `references/` or `templates/` yet; nothing needs them.
- Three test files guard the packaging, and all three are finding #5 turned into
  a guard. **Do not weaken any of them to make a cycle pass.**
  - `tests/test_plugin_manifest.py` — manifest schema, `{en, zh}` on every
    display field, `agentName` matching the agent frontmatter, every declared
    path resolving on disk, every `CLAUDE.md` hard constraint still present in
    the agent body.
  - `tests/test_skill_manifest.py` — every script named in `SKILL.md` exists
    **and** every script on disk is named there, so a new script cannot land
    undocumented; every invocation line matches the `[VERIFIED]` contract
    character for character; and the worked example is **executed**, its quoted
    output compared against what the script actually prints.
  - `tests/test_readme.py` — every script and repo path the README names exists
    on disk; the three things that do not exist yet may be named **only** inside
    a section that says they do not; the six skills may not be described as
    features; the printed test command is executed and the stated count checked
    against what that run reports.
- **When you add a script, `SKILL.md` must be updated in the same cycle.** That
  is not a style preference — `test_every_script_on_disk_is_documented` fails
  otherwise, deliberately.
- Assertions about what the body documents run against **prose with fenced code
  blocks stripped**. A key that appears only inside an example payload does not
  count as documented; that hole let a mutation through once already.
- The hard constraints now live in prose in **three** places —
  `agents/care-navigator.md`, `SKILL.md` and `README.md` — pinned by three
  separate test lists. Intentional (they are read at three different moments:
  expert selection, script invocation, and a person deciding whether to install
  or to believe us), but it is state written three times. Change all three, or
  none.

**Read the three existing scripts before starting a new one and match their
conventions:** an `InvalidInput` exception for anything the script refuses to
guess at; `json.loads(..., parse_float=Decimal)` at the boundary; binary floats
rejected rather than coerced; exact `Fraction`s wherever a division could put a
value on a rounding boundary; the `tool_run_id` / `issued_at` `+08:00` envelope;
a `conventions` block stating each rule in words; and an audit hash over the
computed output as well as the resolved inputs, excluding `tool_run_id` and
`issued_at` so a replay reproduces it.

Two habits that have each caught a real bug — keep both:

- **A required key is not the same as a defaulted one.** `medications` and
  `claims` are required even though `[]` is legal, because a typo'd key would
  otherwise exit 0 having silently processed nothing.
- **A value that is absent differs from a value that is present but
  unusable.** Absent means the document never said it, and zero is often the
  right reading. Present-but-unevidenced means *unknown*, and substituting zero
  produces a confident wrong number. `insurance_claim_review.py` shipped a draft
  reporting SGD 4,320.00 owed instead of SGD 1,220.00 on exactly this.

**Run the script and read its actual prose output before presenting a cycle.**
Both prose bugs found so far — `"1 tablets left over"`, and the wrong money
figure above — passed the whole test suite. Tests do not read English.

## Backlog, in order

### Done

- ~~`expense_split.py` — apply the weights it currently ignores; `Decimal`
  throughout; deterministic residual-cent rule; fail loudly on an unmatched
  payer.~~ `scripts/expense_split.py` + tests, **46 tests**. Weights applied in
  `weighted` (must sum to 1) and `ratio` (normalised, both forms reported)
  modes; residual cents assigned largest weight first, ties by member id;
  unmatched `paid_by` raises.
- ~~`medication_runout.py` — floor not round; one resolved `as_of`; state the
  dose-boundary convention in the output text.~~ `scripts/medication_runout.py`
  + tests, **76 tests**. Floor on exact `Fraction`s; `count_basis` a required
  input with no default; PRN excluded to `not_forecast`;
  `default_lead_time_days` required. `MedicationRecord` added to
  `docs/CONTRACTS.md`.
- ~~Insurance claims — `doc_type: "insurance"` plus a review script.~~
  `scripts/insurance_claim_review.py` + tests, **64 tests**. Submission and
  appeal windows, outstanding/refund arithmetic, documents still to gather,
  evidence-gated throughout. Deliberately **not** a seventh skill — it surfaces
  through `letter-triage` and `deadline-watch`, adding no trigger surface to
  collide with a marketplace skill. `InsuranceClaimRecord` in
  `docs/CONTRACTS.md`.

### Packaging — first, because none of it is in this repo

1. ~~**`.codebuddy-plugin/plugin.json` and `agents/care-navigator.md`.**~~ Done,
   cycle 4, **47 tests** in `tests/test_plugin_manifest.py`. Written fresh
   against the `[VERIFIED]` formats. `maxTurns: 50` is the doc's example value
   taken unchanged and is **still unverified**. The `zh` on
   `displayDescription`, `defaultInitPrompt` and `quickPrompts` **wants a native
   check before submission**; `照护领航员` and `家庭照护协调员` are verbatim from
   the verified example. The manifest references `avatars/expert.png` before it
   exists — deliberate, since omitting a `[VERIFIED]` schema key is the larger
   risk, and the test skips rather than fails until the file lands.
2. ~~**`skills/care-coordinator-toolkit/SKILL.md`**, scoped to the three scripts
   that exist and no others.~~ Done, cycle 5, **32 tests** in
   `tests/test_skill_manifest.py`. Frontmatter is `name` + `description` only.
   Script coverage is guarded in both directions; the worked example is executed
   rather than trusted, which is the "14 days left on the metformin" defect
   turned into a test. **Extend this file as each later script lands, never
   ahead of it** — and never in a later cycle than the script itself.
3. ~~**`README.md`** and `avatars/expert.png`.~~ `README.md` done, cycle 7,
   **29 tests** in `tests/test_readme.py`. Drift is guarded from both
   directions, the printed test command is executed rather than quoted, and the
   test count is stated and pinned. `avatars/expert.png` was **deliberately not
   stubbed** and remains the one human to-do: a generated placeholder passes
   silently, a skip stays visible.

Done out of order, cycle 6: **`SKILL.md` audited against Anthropic's
skill-authoring guidance and four defects fixed** — +10 tests, 275 total. The
file said "pass absolute paths" beside three examples that were not; the
`description` was second person, which degrades selection because it is injected
into a system prompt; the four-step run sequence was prose and is now a
checklist, with step 3 (the senior artifact) called out as the one that gets
skipped; and "will not do" / "does not" were mixed. Also added: a concrete
absolute-path invocation, and a line stating there is nothing to install.
**Finding #8 in `docs/AUDIT-FINDINGS.md` came out of that audit — read it before
item 4.**

### Before the script fixes, decide on evaluations

4. **Behavioural evaluations for `SKILL.md`** — `docs/AUDIT-FINDINGS.md` #8.
   Every test in this repo is structural: it checks that prose matches disk.
   Nothing checks whether a model given the skill reaches for the right script,
   or refuses when it should. Three scenarios are sketched in the finding. The
   in-WorkBuddy half cannot be tested at all now, so **decide explicitly whether
   this is worth building standalone before submission, or is a Demo Day answer
   rather than a cycle.** Do not silently skip it.

### Remaining script fixes

Reproductions are in `docs/AUDIT-FINDINGS.md`.

5. `deadline_window.py` — fix the `this_week` comparison.
6. Escalation cooldown — `last_notified_at` plus a cooldown window, per
   `docs/CONTRACTS.md`. Advancing the level and stamping the time happen in one
   write.
7. `household_profile.py` — merge instead of clobber, write a `.bak`, require an
   explicit path.

### Missing scripts

8. Evidence validator — enforce the null-if-no-snippet rule and the
   `REQUIRES_HUMAN_CONFIRMATION` flag as a shared module. `medication_runout.py`
   and `insurance_claim_review.py` each implement their own; this generalises
   them rather than adding a third copy.
9. `letter_dedupe.py` — content-hash idempotency for documents, with the
   split-on-conflict page grouping rule.
10. `verify_scheme.py` — the 30-day freshness check that the old `SKILL.md`
   claimed exists. Closed-vocabulary output only.
11. `tools/fetch_references.py` — offline snapshot fetcher, human-run, writes
    dated files plus a manifest into `references/`.

### Then the six skills

`letter-triage`, `daily-brief`, `medication-watch`, `scheme-radar`,
`deadline-watch`, `family-dispatch`. Write each so it works both scheduled and
caregiver-triggered, because whether unattended scheduled runs clear the
permission dialog is still unknown. **Add each script to `SKILL.md` as it
lands** — never ahead of it.

## Why the order changed — read this before questioning the backlog

The original order was fixes → missing scripts → skills last. That was correct
while `plugin.json`, `agents/care-navigator.md` and the toolkit `SKILL.md` were
assumed to be sitting on the WorkBuddy box. **Access lapsed after 3 August and
they are not in this repo.** The assumption the ordering rested on is dead.

Scripts nobody can install do not demo. The packaging is therefore **first**,
not last, and the backlog below reflects that.

The reason skills were deferred at all is still valid, but narrower than it
looks: audit finding #5 is a `SKILL.md` citing `scripts/verify_scheme.py`,
which does not exist. That forbids **a skill naming a script that isn't there.**
It does not forbid `plugin.json` or the agent file, which depend on no script
whatsoever, nor a `SKILL.md` scoped to the scripts that do exist. Write those;
extend the `SKILL.md` as each later script lands.

Two things that block on a human, not on a cycle:

- Whether a dragged PDF is readable natively with a vision-capable model
  selected — test a digitally-generated one *and* a scanned one, they differ.
- Whether a scheduled automation can carry Full Access, or stalls on the
  permission dialog. Until that is known, every scheduled skill must also work
  caregiver-triggered.

## Start here — cycle 8, backlog item 4: decide on behavioural evaluations

Packaging is finished. `docs/AUDIT-FINDINGS.md` #8 is the next item, and it is a
**decision item, not a coding item** — do not start writing an eval harness
before making the call and stating it.

Read finding #8 in full, then `skills/care-coordinator-toolkit/SKILL.md`, and
answer one question: is a standalone behavioural eval worth building before
9 August, or is it a Demo Day answer?

The facts that bear on it:

- Every test here is structural. 304 of them check that prose matches disk. None
  check whether a model given `SKILL.md` reaches for the right script, or refuses
  when it should.
- The real evaluation — does the WorkBuddy expert select the skill and invoke the
  script — **cannot be run at all now.** Access lapsed 3 August.
- What is buildable standalone is a harness that feeds a model the `SKILL.md`
  body plus a caregiver prompt and asserts on which script it reaches for. That
  needs a model, which means either a key or local Ollama, and it means a test
  suite that is no longer deterministic and no longer offline. Both are things
  this repo has deliberately not had.
- Three scenarios are already sketched in the finding, one per failure mode
  already seen: an unquotable amount, a "how many days left" question, and a
  request to submit or log in.

Whichever way it goes, **write the decision down** — in `docs/AUDIT-FINDINGS.md`
under #8 and in the backlog below — with the reasoning, so it is not relitigated
and so it is available as a prepared Demo Day answer. "We have no behavioural
evals and here is exactly why, and here is what we would build first" is a
respectable answer. Silence is not.

If the call is to build it, scope it to one scenario and keep it out of the
default suite: `python3 -m unittest discover -s tests` must stay offline,
deterministic and dependency-free, because that command is printed in `README.md`
and executed by a test.

If the call is not to build it, the next cycle is backlog item 5,
`deadline_window.py`.
