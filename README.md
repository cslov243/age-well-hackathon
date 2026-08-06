# Care Navigator

A WorkBuddy expert for a family looking after an elderly relative in Singapore.

A letter arrives — from CPF, a polyclinic, a hospital, an insurer. Today it goes
to whoever in the family reads English fastest, and the senior finds out
afterwards what was decided about her. Care Navigator reverses that order. It
reads the letter with her, in the language she reads, and only then hands the
family a list of what has to happen and by when.

It prepares. A person acts. That line is the product, not a caveat on it.

## The skills

| Skill | Runs | What it does |
|---|---|---|
| `skills/letter-triage/SKILL.md` | a document arrives | Hashes the pages, reads them **once**, files one record per letter. The only skill where the model itself is the instrument, and the only one gated on quoting what it claims to have read. Insurer letters route through `insurance_claim_review.py` from here. |
| `skills/medication-watch/SKILL.md` | daily, and on request | Days of supply left, and a pharmacy cart **draft** she reviews and pays for herself. Ships no scripts of its own. |
| `skills/daily-brief/SKILL.md` | 8am, and on request | The morning briefing. The one skill where **she is written to first** and the family copy is secondary. Reads structured records only — no re-read of any document, so a daily run is nearly free. |
| `skills/deadline-watch/SKILL.md` | daily, and on request | What falls due inside a window, written out as a calendar file the family imports. Any write into a real calendar is confirmed one event at a time. |
| `skills/care-coordinator-toolkit/SKILL.md` | invoked by the others | The scripts: when to run each, what it refuses, and what to do when one refuses you. |

Every skill also runs when a caregiver simply asks. Whether an unattended
scheduled run clears WorkBuddy's permission dialog is not established, so
nothing depends on it.

Beside them sit `agents/care-navigator.md` — the expert definition, and the
normative copy of the rules — and `.codebuddy-plugin/plugin.json` for
marketplace metadata.

## The split of labour

The model does exactly two things: it **extracts facts from documents**, and it
**writes prose for people**. Every number comes from a script.

This is not a style preference. It is the only reason "this agent cannot invent
a deadline" is a true statement rather than a hope. So the rule reads, in the
expert and in every skill: **never compute a number in prose.** If a number is
needed and no script produced it, the expert says so and stops.

Each run carries a `tool_run_id`, an `issued_at` stamped `+08:00`, and an
`audit_hash` over the resolved inputs and computed output — so any figure in an
artifact traces back to the run behind it and reproduces months later.

## The nine scripts

In `skills/care-coordinator-toolkit/scripts/`:

| Script | What it computes |
|---|---|
| `letter_record.py` | A letter's identity from the bytes of its pages, and the evidence gate over the fields read off it. |
| `medication_runout.py` | Days of supply left, the last covered day, and the date to order by. |
| `insurance_claim_review.py` | Submission and appeal windows, amounts outstanding or refundable, documents still to gather. |
| `expense_split.py` | A shared care cost divided between family members, with the residual cent accounted for. |
| `clinic_finder.py` | The nearest clinics to a point in a dated snapshot, straight-line, rounded to 10 m. |
| `purchase_terms.py` | How each medicine is obtained, copied from the household file so no model infers it. |
| `pharmacy_cart.py` | A cart draft: what to buy, how much, and a total only when every line has a price. |
| `deadline_calendar.py` | Dates the scripts above already computed, turned into calendar events and an `.ics`. It copies dates and computes none. |
| `confirmations.py` | Whether a run needs a person, merged across every result it produced. |

Beside them, `_evidence.py` — not a script and no command line. It holds the one
check that a snippet actually contains the value quoted for it, shared by
`letter_record.py` and `insurance_claim_review.py` so the rule cannot be
implemented to two different strengths.

Dated data snapshots live in `skills/care-coordinator-toolkit/references/`,
refreshed by a person and read from disk.

## Running a script

```
python3 scripts/letter_record.py --input <input.json> --records <extracted/> [--output <output.json>]
python3 scripts/medication_runout.py --input <input.json> [--output <output.json>]
python3 scripts/insurance_claim_review.py --input <input.json> [--output <output.json>]
python3 scripts/expense_split.py --input <input.json> [--output <output.json>]
python3 scripts/clinic_finder.py --input <input.json> [--output <output.json>]
python3 scripts/purchase_terms.py --input <input.json> [--output <output.json>]
python3 scripts/pharmacy_cart.py --input <input.json> [--output <output.json>]
python3 scripts/deadline_calendar.py --input <input.json> --ics <calendar.ics> [--output <output.json>]
python3 scripts/confirmations.py --input <input.json> [--output <output.json>]
```

Angle brackets are placeholders for **absolute** paths — the working directory
at invocation is not guaranteed. A real one:

```
python3 scripts/medication_runout.py --input /care/household/medication.json --output /care/out/family/medication_forecast.json
```

- `--input` omitted → reads JSON from stdin. `--output` omitted → writes to stdout.
- Structured logs go to stderr, the result to stdout. They are never mixed.
- Exit 0 is success. Bad input raises: a script refuses rather than emit a
  plausible wrong number, so there is no half-valid result to salvage.

Money is `Decimal` and amounts are passed as strings. Divisions that could land
on a rounding boundary use exact fractions. Supply is floored, never rounded up.
Distances are straight-line, never a walking route.

There is nothing to install beyond copying the plugin in. Python 3, standard
library only: no `pip` step, no third-party package, no network at import time.

## The rules it does not break

Carried in the expert body, which is the normative copy and the one a test
guards. Where a rule can be enforced in code rather than prose, it is.

- **Prepare and hand off — never submit.** No form filed, no portal touched, no
  message sent on anyone's behalf.
- **No Singpass, no login, no credential** — not a password, not an OTP, not one
  a user volunteers.
- **No irreversible action without explicit human confirmation**, including
  spending. The furthest this goes is a cart she reviews and pays for herself;
  no code path can set `requires_human_checkout` false.
- **No clinical advice.** No dose, no diagnosis, no reading of a result.
- **Never assert eligibility.** Exactly three phrasings — `likely eligible`,
  `worth checking`, `insufficient information` — each scheme claim carrying
  `criteria as of YYYY-MM-DD — verify at <URL>`.
- **Evidence or nothing.** Every deadline, amount and issuer needs a verbatim
  snippet. No snippet and the field is `null`, flagged for a person. *Absent*
  (the letter never said it) and *present-but-unquotable* (unknown) are
  different things.
- **Two artifacts, every run.** One in `out/family/`, one in `out/senior/`
  written to her, in her language, large print, every acronym expanded. One
  without the other is an unfinished run.
- **Every disclosure is logged**, append-only, to `out/senior/shared_log.jsonl`.
  She is entitled to know what has been said about her.
- **Every external fact carries its source.** A script may fetch; anything
  fetched renders its URL and retrieval time, and an unreachable source falls
  back to a dated snapshot marked stale, never to a guess.

## Not built yet

Named plainly, because a README that lists intentions as features is the same
defect as a skill citing a script nobody wrote.

- **Two of the six skills are not written** — `scheme-radar` and
  `family-dispatch`. What ships today is the expert, the toolkit, and
  `letter-triage`, `medication-watch`, `daily-brief` and `deadline-watch`.
- **`avatars/expert.png`** — a 1024×1024 PNG. The manifest points at it already;
  the file is a human to-do and its test skips until it appears. Left as a
  visible skip on purpose: a generated placeholder would pass silently.
- **`skills/care-coordinator-toolkit/templates/`** does not exist; nothing needs
  it yet.
- **No scheme criteria snapshots ship**, which is why no scheme matching does.
  The references directory holds the CHAS clinic snapshot and nothing else.

Deliberately not built, and not a roadmap: anything requiring a portal login or
submission on someone's behalf; buying anything; clinical interpretation; and
anything touching a Lasting Power of Attorney.

## Running the tests

No WorkBuddy, no packages, nothing to download, and **no network** — that last
one is a property of the suite, not of the scripts. From the repo root:

```
python3 -m unittest discover -s tests
```

879 tests in about twelve seconds, with one skip: the avatar above, which turns
green by itself once a human supplies the file.

Everything runs from a command line on any machine with Python 3. That is
deliberate — access to the WorkBuddy box lapsed on 3 August 2026, and code that
can only be exercised inside the product is code nobody can verify.

## Where the rest is written down

- `CLAUDE.md` — the design rules.
- `docs/DECISIONS.md` — settled scope calls, and why. Read before reopening one.
- `docs/WORKBUDDY-PLATFORM.md` — platform formats, each tagged verified,
  documented or unknown.
- `docs/CONTRACTS.md` — record types and script I/O.
- `docs/AUDIT-FINDINGS.md` — confirmed defects and their reproductions.
- `docs/DATA-SOURCES.md` — where external data comes from.
- `evals/CASES.md` — the behavioural evaluation, graded by hand. It is the only
  check that reads English, so it catches what a unit test structurally cannot.
  It does not ship in the plugin.
