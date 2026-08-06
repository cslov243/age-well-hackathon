# Care Navigator

A WorkBuddy expert for a family looking after an elderly relative in Singapore.

A letter arrives — from CPF, a polyclinic, a hospital, an insurer. Today it goes
to whoever in the family reads English fastest, and the senior finds out
afterwards what was decided about her. Care Navigator reverses that order. It
reads the letter with her, in the language she reads, and only then hands the
family a list of what has to happen and by when.

It prepares. A person acts. That line is the product, not a caveat on it.

## What is installed

An expert plus two skills, in a single plugin:

- `.codebuddy-plugin/plugin.json` — marketplace and display metadata.
- `agents/care-navigator.md` — the expert: who it is for, how it talks, and the
  rules it does not break.
- `skills/care-coordinator-toolkit/SKILL.md` — when and how to invoke each
  script, and what the toolkit refuses to do.
- `skills/care-coordinator-toolkit/scripts/` — six deterministic scripts.
- `skills/care-coordinator-toolkit/references/` — dated data snapshots,
  refreshed by a person and read from disk.
- `skills/medication-watch/SKILL.md` — the daily supply check and the pharmacy
  cart draft. Runs on a schedule and on request; ships no scripts of its own.

There is nothing to install beyond copying the plugin in. The scripts are
Python 3, standard library only: no `pip` step, no third-party package, no
network fetch at import time.

## The split of labour — why this is the point

The model does exactly two things: it **extracts facts from documents**, and it
**writes prose for people**.

Every number comes from a script. Days of supply left, a submission deadline, an
amount outstanding, one sibling's share of a bill — each is computed by Python
that can be run again, on the same input, by anyone who doubts the answer.

This is not a style preference, and it is not an optimisation. It is the only
reason "this agent cannot invent a deadline" is a true statement rather than a
hope. A model that is allowed to do the arithmetic when the arithmetic looks
easy is a model that will one day produce a plausible wrong date on a letter
about someone's medication, and nobody downstream will be able to tell.

So the rule reads, in the expert and in the skill and here: **never compute a
number in prose.** If a number is needed and no script produced it, the expert
says so and stops.

Two consequences worth naming. Every run carries a `tool_run_id`, an `issued_at`
stamped `+08:00`, and an `audit_hash` over the resolved inputs and the computed
output — so a figure in a family artifact can be traced to the run behind it and
reproduced months later. And the scheduled work costs almost nothing in tokens,
because it is arithmetic over structured records rather than a model re-reading
documents.

## The six scripts

| Script | What it computes |
|---|---|
| `medication_runout.py` | Days of supply left, the last covered day, and the date to order by. |
| `insurance_claim_review.py` | Submission and appeal windows, amounts outstanding or refundable, documents still to gather. |
| `expense_split.py` | A shared care cost divided between family members, by weight or by ratio, with the residual cent accounted for. |
| `clinic_finder.py` | The nearest clinics to a point in a dated snapshot, by straight-line distance rounded to 10 m. |
| `purchase_terms.py` | How each medicine is obtained, copied from the household file so no model ever infers it. |
| `pharmacy_cart.py` | A cart draft from a run-out forecast: what to buy, how much of it, and a total only when every line has a price. |

All six take the same form:

```
python3 scripts/medication_runout.py --input <input.json> [--output <output.json>]
python3 scripts/insurance_claim_review.py --input <input.json> [--output <output.json>]
python3 scripts/expense_split.py --input <input.json> [--output <output.json>]
python3 scripts/clinic_finder.py --input <input.json> [--output <output.json>]
python3 scripts/purchase_terms.py --input <input.json> [--output <output.json>]
python3 scripts/pharmacy_cart.py --input <input.json> [--output <output.json>]
```

Everything in angle brackets is a placeholder for an **absolute** path — the
working directory at invocation time is not something the platform guarantees.
A real one:

```
python3 scripts/medication_runout.py --input /care/household/medication.json --output /care/out/family/medication_forecast.json
```

- `--input` omitted → the script reads JSON from stdin.
- `--output` omitted → it writes JSON to stdout.
- Structured logs go to stderr. The result goes to stdout. They are never mixed.
- Exit 0 means success. Bad input raises: the scripts refuse rather than emit a
  plausible wrong number, so there is no half-valid result to salvage.

Money is `Decimal` throughout and amounts are passed as strings. Divisions that
could land on a rounding boundary are done on exact fractions. Supply is floored,
never rounded up.

Distances are straight-line, rounded to the nearest 10 m, and never a walking
route — nothing in this repo computes one.

The pharmacy cart is a draft and nothing else. It carries
`requires_human_checkout: true`, no code path can set it false, and nothing in
the repo calls a shop. A medicine enters it only if the household recorded that
it can be bought without a prescription; an unrecorded supply channel is
*unknown*, and unknown stays out of the cart.

## Running the tests

No WorkBuddy, no packages, no fixtures to download, and **no network** — that
last one is a property of the suite, not of the scripts, which may now fetch.
From the repo root:

```
python3 -m unittest discover -s tests
```

That runs 534 tests in about seven seconds, with one skip — the avatar file
below, which turns green by itself once a human supplies it.

Everything is runnable from a command line on any machine with Python 3. That is
deliberate: access to the WorkBuddy box lapsed on 3 August 2026, and code that
can only be exercised inside the product is code nobody can verify before
submission.

## The hard constraints

These are carried in the expert body and in the skill — the two places a runtime
reads. The expert body is the normative copy and a test fails if an edit drops a
rule from it. Where a rule can be enforced in code rather than in prose, it is:
the scripts refuse bad input rather than emit a plausible wrong number.

- **Prepare and hand off — never submit.** No form is filed, no portal is
  touched, no message is sent on anyone's behalf.
- **No Singpass, no login, no credential.** Not a password, not an OTP, not one
  a user volunteers. Automating a vulnerable person's digital identity is the
  shape of the scams this sits against, and there is no benign version of it.
- **No irreversible action without explicit human confirmation** — including
  spending. The furthest this ever goes is a prepared cart she reviews and pays
  for herself.
- **No clinical advice.** No dose, no diagnosis, no reading of a result, no view
  on whether something is serious. Medication work is arithmetic about supply and
  nothing else.
- **Never assert eligibility.** Exactly three phrasings are permitted:
  `likely eligible`, `worth checking`, `insufficient information`.
  Never "you qualify". Every scheme claim carries
  `criteria as of YYYY-MM-DD — verify at <URL>`.
- **Evidence or nothing.** Every deadline, amount and issuer needs a **verbatim**
  snippet of the document. No snippet, and the field is `null` and the record is
  flagged `REQUIRES_HUMAN_CONFIRMATION`. Absent (the letter never said it) and
  present-but-unquotable (unknown) are different, and conflating them once
  produced a draft claiming SGD 4,320.00 was owed when the figure was SGD
  1,220.00.
- **Two artifacts, every run.** One in `out/family/` for the people organising,
  one in `out/senior/` written to her, in her language, large print, every
  acronym expanded. One without the other is an unfinished run.
- **Every disclosure is logged.** A line appends to `out/senior/shared_log.jsonl`
  recording what was shared about her, with whom, and when. Append-only. She is
  entitled to know what has been said about her.
- **Every external fact carries its source.** Scripts may reach the network.
  Anything fetched renders the URL and the time it was retrieved, the same way a
  dated snapshot renders its date, and a source that cannot be reached falls back
  to the snapshot marked stale rather than to a guess. Reaching a public source is
  not logging in as her — the credential rules above are untouched by this. The
  test suite still runs with no network at all.

## Deliberately not built

Not omissions, and not a roadmap.

- **Anything requiring Singpass, a portal login, credential storage, or
  submission on someone's behalf.** There is no submission API for HealthHub or
  CHAS, and building one by automating a national digital identity for elderly
  users is the exact pattern this product is positioned against.
- **Buying anything.** The pharmacy cart stops at a draft, and that is the whole
  of what ships: `pharmacy_cart.py` prepares lines the senior reviews and pays
  for herself. No shop is called, no payment is held, and no code path can set
  `requires_human_checkout` false. An agent with standing ability to spend an
  elderly person's money needs a consent model that does not exist yet, so the
  half that would need one is not built. Stopping at the draft under time
  pressure is the point, not the excuse.
- **Clinical interpretation, and anything touching a Lasting Power of Attorney.**
  Those go to a qualified professional, and the expert says so.

## Not built yet

Named plainly, because a README that lists intentions as features is the same
defect as a skill citing a script that was never written.

- **Five of the six skills** — `letter-triage`, `daily-brief`, `scheme-radar`,
  `deadline-watch`, `family-dispatch` — are **not written**. What exists today is
  the expert, the toolkit skill, `medication-watch`, and the six scripts above.
  The toolkit is extended as each script lands, never ahead of it.
- **`avatars/expert.png`** — a 1024×1024 PNG. The manifest already points at the
  path; the file is a human to-do and the test for it skips until it appears. It
  is left as a visible skip on purpose: a generated placeholder would pass
  silently and be forgotten.
- **`skills/care-coordinator-toolkit/templates/`** does not exist. Nothing needs
  it yet. The references directory now holds the CHAS clinic snapshot that
  `clinic_finder.py` reads; the dated *scheme criteria* snapshots are still to
  come, which is why no scheme matching ships today.
- Several toolkit scripts are still to write — deadline windows, the escalation
  cooldown, profile merge, a shared evidence validator, letter deduplication.
  Their intended behaviour, and the bugs the earlier versions had, are recorded
  in `docs/AUDIT-FINDINGS.md`.

## Where the rest is written down

- `CLAUDE.md` — the design rules.
- `docs/DECISIONS.md` — the scope calls that are settled, and why. Read it before
  reopening one.
- `docs/WORKBUDDY-PLATFORM.md` — the platform formats, each tagged verified,
  documented or unknown.
- `docs/CONTRACTS.md` — the record types and script I/O.
- `docs/AUDIT-FINDINGS.md` — confirmed defects and their reproductions.
- `docs/DATA-SOURCES.md` — where external data comes from, and why no script
  fetches it.
- `evals/CASES.md` — the behavioural evaluation: caregiver prompts, fixtures and
  ground truth, graded by hand at the end of a cycle. It is the only check that
  reads English, so it catches what the test suite structurally cannot. It does
  not ship in the plugin and is not part of the test command above.
