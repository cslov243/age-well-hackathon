# Care Navigator — project context

Agentic caregiver assistant for elderly Singaporeans and the family who support
them. A **WorkBuddy plugin** (Tencent WorkBuddy desktop agent) for the Tencent
"Age Well" hackathon, AI Agent track.

**Submission 9 August 2026. Demo Day 16 August.** WorkBuddy access lapsed after
3 August — everything must be testable from the command line, with no WorkBuddy
and no network.

## Read before you write

| File | Read it when |
|------|--------------|
| `docs/WORKBUDDY-PLATFORM.md` | Any skill, agent or `plugin.json`. Not in your training data — do not guess its formats. |
| `docs/CONTRACTS.md` | Any record type or script I/O. |
| `docs/AUDIT-FINDINGS.md` | Any script in `skills/care-coordinator-toolkit/scripts/`. |
| `docs/DATA-SOURCES.md` | Any external data. **Read before writing networking code.** |
| `docs/DECISIONS.md` | Before relitigating scope or preparing a Demo Day answer. |
| `evals/CASES.md` | Finishing any cycle that touched a skill, the agent or a script. Runs in Claude Code by hand, never in the test suite. |

## The core loop

A document lands in a watched folder → the agent extracts it **once** →
deterministic Python scripts reason over the structured record → **two**
artifacts, one for the family and one for the senior in her own language.

## Split of labour — the central design rule

The model does exactly two things: **extraction from images**, and **writing
human-facing prose**. Everything else is a Python script the skill invokes.

**If a number is needed and no script produced it, stop and say so.
Never compute in prose.**

## Users

The **senior is the primary user** — every behaviour must reach her. The
caregiver is the operator, since WorkBuddy runs on their desktop. The point is
that she stops being cut out of decisions about her own life.

- Address her **directly**, never in the third person.
- Language comes from `HouseholdProfile` — never assumed, never defaulted to
  Mandarin or English.

## Hard constraints — non-negotiable

| Constraint | What it forbids |
|---|---|
| **Prepare and hand off; never submit** | No Singpass, no portal login, no credential handling — not even an OTP a user volunteers. The human is the actuator. |
| **No irreversible action without explicit human confirmation** | Sending, spending, deleting, disclosing. A prepared cart she reviews and pays for herself is the furthest this goes. |
| **No clinical advice** | No lab results, diagnoses or dosing. Nothing touching a Lasting Power of Attorney. |
| **Never assert eligibility** | Exactly three strings: `likely eligible`, `worth checking`, `insufficient information`. Never "you qualify". Every scheme claim renders `criteria as of YYYY-MM-DD — verify at <URL>`. |
| **Escalate on uncertainty** | Say what is unclear, route to a human. A confident wrong "your CHAS auto-renewed" costs real subsidies. |
| **Evidence rule** | Every deadline, amount and issuer needs a **verbatim** snippet. No snippet → `null` → flagged `REQUIRES_HUMAN_CONFIRMATION`. A script validates this; the model never self-reports confidence. |
| **Dual output on every skill** | Family artifact in `out/family/`, senior artifact in `out/senior/`. One without the other is an unfinished run. |
| **Every disclosure is logged** | One appended line in `out/senior/shared_log.jsonl` — what, with whom, when. Append-only. |
| **Every external fact carries its source** | A script may fetch. Whatever it fetches renders the URL and the retrieval time, exactly as a snapshot renders its date. Unreachable source → fall back to the dated snapshot, flagged stale, never to a guess. **The test suite still runs fully offline.** |
| **No secrets in any `SKILL.md`** | WorkBuddy security-scans plugins on install. |

**Absent ≠ unevidenced.** Absent means the document never said it, and zero is
often right. Present-but-unquotable means *unknown*, and substituting zero
produces a confident wrong number.

## Workspace layout

```
/care/
  inbox/          documents drop here
  processed/      images after extraction, never re-read
  extracted/      one JSON per record, id-named
  household/      profile.json, medication.json
  references/     dated scheme criteria snapshots
  out/family/     dashboards, reports, spreadsheets
  out/senior/     audio briefs, large-print cards, shared_log.jsonl
  scripts/        deterministic logic
```

**One JSON file per record.** Never six skills mutating a shared array.

## Skills

| Skill | Trigger | Built? |
|-------|---------|--------|
| `letter-triage` | on file arrival | No |
| `daily-brief` | scheduled 8am | No |
| `medication-watch` | scheduled daily | **Yes** |
| `scheme-radar` | scheduled weekly | No |
| `deadline-watch` | scheduled daily | No |
| `family-dispatch` | event-driven | No |

`letter-triage` also handles `doc_type: "insurance"` via
`insurance_claim_review.py` — deliberately not a seventh skill.

Whether unattended scheduled runs clear WorkBuddy's permission dialog is
**[UNKNOWN]**. Write every scheduled skill so it also works caregiver-triggered.

## What exists

Six scripts, the manifest, the agent, the toolkit `SKILL.md`, the
`medication-watch` skill, the README. Backlog: `LOOP-PROMPT.md`.

- `python3 -m unittest discover -s tests` runs everything.
- The one skip is `avatars/expert.png`, a **human to-do**. Not stubbed: a
  placeholder passes silently, a skip stays visible.
- **`agents/care-navigator.md` is the normative copy of the hard constraints**,
  and the only one a test pins. `SKILL.md` carries the ones that bear on
  invoking a script; the README explains them to a reader. Those two are prose
  and may be edited freely — do not add tests that pin their wording.

## Code conventions

- **Python 3, standard library only.** No pandas, openpyxl or Pillow. Emit CSV.
- **`Decimal` for all money**, never `float`. Exact `Fraction`s wherever a
  division could land on a rounding boundary.
- **Explicit `encoding='utf-8'` on every file open.** Target is Windows; a bare
  `open()` raises on the first Chinese or Tamil artifact.
- **`pathlib`**, never string concatenation.
- **Take every path as an argument.** Working directory at invocation is
  `[UNKNOWN]`; relative defaults do not resolve.
- **Validate and early-exit at the top.** Raise `InvalidInput` on anything the
  script would otherwise guess at.
- **A required key is not a defaulted one.** `medications`, `claims`, `members`
  are required even when `[]` is legal — a typo'd key would otherwise exit 0
  having silently processed nothing.
- **Envelope on every output:** `tool_run_id` (uuid4), `issued_at` (`+08:00`),
  `audit_hash` over resolved inputs and computed output, excluding those two.
- Structured logging to stderr; JSON to stdout. Never mixed.
- **Run the script and read its prose output** before presenting work. Both prose
  bugs so far passed the whole suite. Tests do not read English.
