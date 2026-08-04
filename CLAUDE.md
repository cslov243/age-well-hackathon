# Care Navigator — project context

Agentic caregiver assistant for elderly Singaporeans and the family who support
them. Built as a **WorkBuddy plugin** (Tencent WorkBuddy desktop agent), for the
Tencent "Age Well" hackathon, AI Agent track.

- **Submission: 9 August 2026.** Demo Day 16 August 2026.
- WorkBuddy access may lapse after 3 August. Assume you are writing code that
  cannot be interactively tested inside WorkBuddy. Everything must be testable
  standalone from the command line.

## Reference docs in this repo

Read these before writing anything in the relevant area:

| File | Read it when |
|------|--------------|
| `docs/WORKBUDDY-PLATFORM.md` | Writing or changing any skill, agent, or `plugin.json`. WorkBuddy is not in your training data; do not guess its formats. |
| `docs/CONTRACTS.md` | Writing or consuming any record type or script I/O. |
| `docs/AUDIT-FINDINGS.md` | Touching any existing script in `skills/care-coordinator-toolkit/scripts/`. Several have confirmed bugs. |
| `docs/DATA-SOURCES.md` | Adding any external data — clinic locations, routing, weather. **Read before writing any networking code**, because the answer is that scripts do not make network calls. |

## The core loop

A government or healthcare document lands in a watched folder → the agent
extracts it **once** → deterministic Python scripts reason over the structured
record → **two** artifacts are produced, one for the family and one for the
senior in her own language.

## Split of labour — this is the central design rule

The model does exactly two things: **extraction from images**, and **writing
human-facing prose**.

Everything else is a Python script the skill invokes: run-out forecasting,
deadline scanning, the escalation ladder, expense splitting, deduplication,
profile I/O. This is not a style preference. It is what makes "the agent cannot
hallucinate a deadline" a true claim rather than a hope, and it keeps token cost
near zero on the scheduled skills.

**If a number is needed and no script produced it, stop and say so. Never
compute in prose.**

## Users

The **senior is the primary user** — every behaviour must reach her. The
caregiver is the operator, since WorkBuddy runs on their desktop, but the senior
has her own channel via the Telegram bot (it accepts photos, so she can
photograph a letter herself).

The pitch: the point isn't doing things for her, it's that she stops being cut
out of decisions about her own life. Today she hands letters to her son and
learns afterwards what was decided. An agent that explains a letter to her, in
the language she thinks in, *before* the family acts, restores agency rather
than convenience.

Consequence for code and prose: address the senior directly, never in the third
person. Language is read from `HouseholdProfile` — never assumed, never
defaulted to Mandarin or English.

## Hard constraints — non-negotiable

- **Prepare and hand off; never submit.** No Singpass automation, no portal
  logins, no credential handling, ever. There is no submission API for HealthHub
  or CHAS, and automating national digital identity for vulnerable users is
  precisely the scam pattern. The human is the actuator.
- **No irreversible action without explicit human confirmation.**
- **No clinical advice.** No interpretation of lab results, diagnoses, or dosing
  decisions. Nothing touching a Lasting Power of Attorney.
- **Never assert eligibility.** Permitted vocabulary is exactly three strings:
  `likely eligible`, `worth checking`, `insufficient information`. Never "you
  qualify". Every scheme claim renders as
  `criteria as of YYYY-MM-DD — verify at <URL>`.
- **Escalate on uncertainty.** A confident wrong "your CHAS auto-renewed" costs
  real subsidies. Say what is unclear and route to a human.
- **Evidence rule.** Every extracted deadline, amount, and issuer requires a
  verbatim source snippet from the document. No snippet → field is `null` →
  record flagged `REQUIRES_HUMAN_CONFIRMATION`. A script validates this; the
  model does not self-report a confidence number, because vision confidence is
  highest exactly when it is confabulating a familiar-looking form.
- **Dual output on every skill**: a family artifact and a senior artifact.
- **Every disclosure appends to `out/senior/shared_log.jsonl`** — an append-only
  record of what was shared about her, with what and with whom.
- **No secrets in any `SKILL.md`.** WorkBuddy security-scans plugins on install
  and flags exfiltration-shaped instructions.

Tencent's own documentation states that experts are AI role-play assistance,
distinct from legally qualified professional services, and that medical, legal
and financial decisions should involve a professional. These guardrails align
with the platform vendor's stated position, not just ours.

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

| Skill | Trigger | Notes |
|-------|---------|-------|
| `letter-triage` | on file arrival | Hash, dedupe, extract with evidence, write LetterRecord, emit TaskRecord, move image to `processed/`. |
| `daily-brief` | scheduled 8am | Senior-facing. Consumes structured records only — nearly free. |
| `medication-watch` | scheduled daily | Script forecasts run-out. Pure arithmetic. No clinical judgement anywhere. |
| `scheme-radar` | scheduled weekly | Matches profile against CHAS, EASE, SMF, HCG, CTG, PioneerDAS using a dated snapshot in `references/`. |
| `deadline-watch` | scheduled daily | Scans open tasks, applies escalation ladder **with cooldown**. |
| `family-dispatch` | event-driven | Routes tasks, claim/decline, sibling expense split. |

`letter-triage` also handles `doc_type: "insurance"` — insurer letters run
through the same extract-with-evidence path and are reasoned over by
`insurance_claim_review.py`. Deliberately not a seventh skill: a separate skill
would add a trigger surface for a marketplace commerce skill to collide with,
and the claim needs the same evidence rule, dual output and disclosure log as
every other letter.

### What actually exists, as of 4 August 2026

**The plugin packaging is gone.** `plugin.json`, `agents/care-navigator.md` and
the toolkit `SKILL.md` were only ever on the WorkBuddy box, and access lapsed
after 3 August. Treat them as lost unless someone produces a copy. This repo
contains scripts, tests and docs — **nothing installable**.

Written and tested here, all standalone from the command line:

| | Tests |
|---|---|
| `scripts/expense_split.py` | 46 |
| `scripts/medication_runout.py` | 76 |
| `scripts/insurance_claim_review.py` | 64 |

Run everything with `python3 -m unittest discover -s tests`.

Still to write: the packaging above, the remaining toolkit scripts, and the six
skills. `LOOP-PROMPT.md` holds the current order and the reasoning behind it.
**Packaging comes first** — scripts nobody can install do not demo.

## Scope decisions — deliberately not built

### Third-party commerce skills (GrabMall, GrabFood, etc.)

**Not in scope for the 9 August submission.** Recorded here so the reasoning
isn't relitigated, and because it belongs in the prepared answers for Demo Day.

There is one legitimate shape: `medication-watch` forecasts a run-out, and the
agent **prepares a pharmacy delivery cart the senior reviews and pays for
herself**. That completes an existing skill, meets a real need for a homebound
senior, and stays inside the thesis — the cart is prepared, the human is still
the actuator, exactly as with a letter.

The shape that breaks the product is the agent completing the purchase. An AI
with standing ability to spend an elderly person's money is the precise harm
vector this product is positioned against. Elder financial exploitation is not
hypothetical in Singapore, and a judge will make that connection immediately.

Reasons for deferring even the legitimate shape:

- **Unverifiable.** Whether a third-party commerce skill can halt before
  checkout is an empirical question answerable only inside WorkBuddy. Building
  on a skill whose behaviour can't be tested after 3 August is an unhedgeable
  bet.
- **Trigger collisions.** A food-ordering skill with broad trigger phrases is
  the most likely thing in the marketplace to fire on letter content or a
  medication refill phrase. Trigger collision is already on the risk register.
- **Demo budget.** Three minutes. A delivery beat costs the scheme-radar beat —
  the moment an EASE grant surfaces that nobody asked about — which is the
  strongest moment in the demo, because it is the one where the agent notices
  something a human missed.

**Prepared answer for "how does this productionise":** the medication forecast
already knows what runs out and when; a delivery integration would be a prepared
cart, never an autonomous purchase; and it was deliberately not shipped because
an agent that can spend a senior's money needs a consent model that doesn't
exist yet. Not shipping it under time pressure is the point, not the excuse.

### Also out of scope, permanently

Anything requiring Singpass, portal login, credential storage, or submission on
someone's behalf. See the hard constraints above. These are design boundaries,
not unfinished work.

## Code conventions

- **Python 3, standard library only.** No pandas, no openpyxl, no Pillow. Emit
  CSV for spreadsheets; Excel opens it fine. This keeps `pip` out of the picture
  and keeps the install-time security scanner quiet.
- **`Decimal` for all money.** Never `float`.
- **Explicit `encoding='utf-8'` on every file open**, read and write. The target
  machine is Windows; a bare `open()` will raise `UnicodeEncodeError` the first
  time a Chinese or Tamil artifact renders.
- **`pathlib`** for paths, never string concatenation.
- **Validate and early-exit at the top of every script.** Raise on bad input
  rather than producing a plausible wrong number.
- **No network calls from any skill script, ever.** External data is fetched
  offline into dated snapshots under `references/` by `tools/fetch_references.py`,
  which a human runs and no skill invokes. See `docs/DATA-SOURCES.md` for why.
- **Every script must be runnable and testable from the command line**, with no
  WorkBuddy present and with no network available.
- Structured logging to stderr; JSON result to stdout. Never mix them.
