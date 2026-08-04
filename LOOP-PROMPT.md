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

- **The audited scripts do not exist on this machine.** This repo was docs-only;
  the plugin described in `docs/AUDIT-FINDINGS.md` lives on the WorkBuddy box.
  Every backlog item is therefore **write-fresh**, using the audit findings as
  the spec for what the code must *not* do — not a patch to an existing file.
- Tests live in `tests/`, run with `python3 -m unittest discover -s tests`.
  **186 currently pass. Never present a cycle with that number lower.**
- Scripts live in `skills/care-coordinator-toolkit/scripts/`. Three exist:
  `expense_split.py`, `medication_runout.py`, `insurance_claim_review.py`.
- **Only `scripts/` exists of the plugin tree.** No `plugin.json`, no
  `SKILL.md`, no `agents/`, no `avatars/`, no `README.md` — see the risk note
  below before assuming they can still be copied off the WorkBuddy box.

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

1. **`.codebuddy-plugin/plugin.json` and `agents/care-navigator.md`.** Depend on
   no script; nothing has ever blocked them. Without them the plugin does not
   install and nothing above can be demonstrated. Formats are `[VERIFIED]` in
   `docs/WORKBUDDY-PLATFORM.md` — follow them exactly.
2. **`skills/care-coordinator-toolkit/SKILL.md`**, scoped to the three scripts
   that exist and no others. The body is a prompt: when to invoke each script,
   how, where the source of truth lives, and what the skill explicitly does
   **not** do. It carries the `CLAUDE.md` hard constraints into runtime, which
   nothing currently does. Ship a test asserting every script path named in
   `SKILL.md` exists on disk — that is audit finding #5 turned into a guard.
3. **`README.md`** and `avatars/expert.png`. A placeholder avatar is tolerated;
   binary content is out of scope for a cycle, so name it and move on.

### Remaining script fixes

Reproductions are in `docs/AUDIT-FINDINGS.md`.

4. `deadline_window.py` — fix the `this_week` comparison.
5. Escalation cooldown — `last_notified_at` plus a cooldown window, per
   `docs/CONTRACTS.md`. Advancing the level and stamping the time happen in one
   write.
6. `household_profile.py` — merge instead of clobber, write a `.bak`, require an
   explicit path.

### Missing scripts

7. Evidence validator — enforce the null-if-no-snippet rule and the
   `REQUIRES_HUMAN_CONFIRMATION` flag as a shared module. `medication_runout.py`
   and `insurance_claim_review.py` each implement their own; this generalises
   them rather than adding a third copy.
8. `letter_dedupe.py` — content-hash idempotency for documents, with the
   split-on-conflict page grouping rule.
9. `verify_scheme.py` — the 30-day freshness check that the old `SKILL.md`
   claimed exists. Closed-vocabulary output only.
10. `tools/fetch_references.py` — offline snapshot fetcher, human-run, writes
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

## Start here — cycle 4, backlog item 1: `plugin.json` and the agent file

Read `CLAUDE.md` and **all of `docs/WORKBUDDY-PLATFORM.md`**, then begin. Every
format below is tagged `[VERIFIED]` there — read off a working installed plugin.
Do not infer any of it from Claude Code or any other agent framework, and do not
follow the published English docs where the file says they are wrong.

Write two files:

- `.codebuddy-plugin/plugin.json` — note the directory name, it is
  `.codebuddy-plugin`, not `.workbuddy-plugin`.
- `agents/care-navigator.md` — YAML frontmatter, then a markdown body.

**Formats that are easy to get subtly wrong:**

- `displayName`, `profession`, `displayDescription` and `defaultInitPrompt` are
  `{en, zh}` objects. `tags` and `quickPrompts` are **arrays of `{en, zh}`
  objects**, not arrays of strings.
- `categoryId` is one of twelve fixed values; `12-IndustryConsultant` is the
  fallback for cross-domain personal advisory work.
- The agent's `description` is an **activation condition** — it decides when the
  expert gets selected — not a summary of what it does.
- `skills: [care-coordinator-toolkit]` is what wires the expert to its toolkit.
- The agent body is second person: persona, methodology, hard rules.

**The body is the point of this cycle.** The `CLAUDE.md` hard constraints
currently exist only as prose in a document no runtime reads. The scripts
enforce their own share; nothing carries the rest. The body must carry, at
minimum: prepare and hand off, never submit; no Singpass, no login, no
credential, ever; no clinical advice; never assert eligibility, and the exactly
three permitted strings; escalate on uncertainty; the evidence rule; dual
output on every skill; append every disclosure to `out/senior/shared_log.jsonl`;
address the senior directly and never in the third person; read language from
`HouseholdProfile` and never default it.

**No secrets in any of it** — WorkBuddy security-scans plugins on install and
flags exfiltration-shaped instructions.

Do not hand-convert line endings. `.gitattributes` handles CRLF.

**This cycle is mostly prose, so keep the test-first rule honest:** write
`tests/test_plugin_manifest.py` first. `plugin.json` is JSON and its schema is
verified, so pin it — required keys present, `{en, zh}` on every display field,
`tags`/`quickPrompts` as object arrays not string arrays, `categoryId` in the
allowed set, `agents`/`skills` paths resolving to files that actually exist,
`agentName` matching the agent file's frontmatter `name`. Parse the agent file's
frontmatter and assert the same. That test is what stops the next cycle
reintroducing finding #5 from the other direction.

Before writing, do not guess at these — flag or ask:

1. **Whether any copy of the old `plugin.json` survives** — a backup, a
   screenshot, anything. `categoryId`, the `zh` strings and `quickPrompts` are
   worth matching rather than reinventing if one exists.
2. **The `zh` translations.** Every display field needs one. Say plainly which
   you are confident in and which want a native check before submission — a
   machine-shaped `zh` string on the marketplace card is what a Tencent judge
   reads first.
3. **`maxTurns`.** The doc's example says 50, with no stated basis. Confirm or
   pick, and say which.
4. **The avatar.** `avatars/expert.png`, 1024×1024, placeholder tolerated. It
   cannot be generated in a cycle — name it as a human to-do rather than
   silently shipping a manifest pointing at a missing file, and decide whether
   the manifest should reference it before it exists.

Assumptions and open questions first, then the test file, then the two files.
