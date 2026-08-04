# Decisions

Scope calls that are **settled**, with the reasoning that settled them. Recorded
here so they are not relitigated, and because most of them are prepared Demo Day
answers.

This file is not a backlog. Open work lives in `LOOP-PROMPT.md`.

---

## Singpass, portal logins and submission — permanently out of scope

**Decided:** never build. Not deferred; not a limitation.

There is no submission API for HealthHub or CHAS, so any "submit on her behalf"
feature would mean driving a portal with her national digital identity.
Automating Singpass for vulnerable users is precisely the scam pattern this
product is positioned against, and there is no benign version of it.

The product prepares and hands off. That is the thesis, not a workaround for a
missing API.

**Demo Day answer:** *we never touch Singpass, and the reason is that an agent
which can log in as an elderly person is the exact thing her family is trying to
protect her from.*

---

## Third-party commerce — Grab, and the shape that is permitted

**Decided:** build the **prepared cart**. Never the purchase.

Two shapes exist and only one is acceptable:

| Shape | Verdict |
|---|---|
| `medication-watch` forecasts a run-out, the agent **prepares a pharmacy order the senior reviews and pays for herself** | Permitted. Completes an existing skill, meets a real need for a homebound senior, human stays the actuator. |
| The agent completes the purchase | Never. An AI with standing ability to spend an elderly person's money is the precise harm vector this product is positioned against. |

Elder financial exploitation is not hypothetical in Singapore, and a judge will
make that connection immediately.

**How it is built, given WorkBuddy access lapsed 3 August:** a script emits a
cart draft — line items, quantities, pharmacy, deep link, and an explicit
`requires_human_checkout` flag. It makes **no Grab API call**. Whether a
marketplace commerce skill can be made to halt before checkout is answerable only
inside WorkBuddy, so nothing is built on top of that question. The cart is an
artifact we generate and test standalone.

Two rules the cart inherits:

- **No invented prices.** A price appears only if it came from a snapshot or the
  caregiver. Absent price → `null`, and the total is suppressed entirely. A cart
  with a confident wrong total is worse than one with no total.
- **Prescription-only items never enter the cart.** They route to the polyclinic
  refill path with a plain sentence saying why.

**Demo Day answer:** *the medication forecast already knows what runs out and
when. The delivery integration is a prepared cart, never an autonomous purchase,
because an agent that can spend a senior's money needs a consent model that
doesn't exist yet.*

---

## External data — snapshot at build time, never call at runtime

**Decided:** dated snapshots, fetched offline by `tools/fetch_references.py`,
which a human runs and no skill invokes.

Three reasons, in order:

1. WorkBuddy security-scans plugins on install. A script issuing outbound HTTP is
   exactly the shape that scanner looks for. Do not gamble the submission on it.
2. The demo cannot depend on an API being up, a rate limit not firing, or the
   venue's wifi working.
3. It makes the provenance line literally true. `criteria as of 2026-08-03 —
   verify at <URL>` is honest about a dated snapshot in a way a live query never
   is.

This applies to the clinic connector too: nearest-clinic ranking runs locally
over a dated CHAS-clinic snapshot, and step-free routes are precomputed into
`references/` rather than fetched per request.

**Demo Day answer, said as a design choice and not an apology:** *we snapshot
government data with a date rather than querying live, because a caregiving tool
should never tell you something it can't show you the source of.*

Full endpoint detail is in `docs/DATA-SOURCES.md`.

---

## Behavioural evaluations — decided, not built

**Decided:** not built before submission. This is `docs/AUDIT-FINDINGS.md` #8,
answered rather than left open.

Every test in this repo is **structural**: it checks that prose tells the truth
about what is on disk — that every script named exists, that invocation lines
match the contract, that the worked example reproduces when executed. None of
them check the question that matters at runtime: given `SKILL.md` and a
caregiver's message, does a model reach for the right script, and does it refuse
when it should?

Why it is not built:

- The **real** evaluation needs WorkBuddy — does the expert select the skill and
  invoke the script — and access lapsed 3 August. That half is unclosable.
- The standalone half needs a live model, which makes the suite
  non-deterministic and non-offline. `python3 -m unittest discover -s tests` is
  printed in `README.md` and executed by a test; it stays offline and
  dependency-free.

What would be built first, in order, one per failure mode already seen:

1. A letter with an unquotable amount — must null the field and flag, not fill.
2. "How many days of tablets are left" — must invoke `medication_runout.py`,
   never answer directly.
3. A request to submit or log in — must refuse and hand off.

**Demo Day answer:** *we have no behavioural evals, and here is exactly why, and
here is what we'd build first. What we do have is 300-odd structural tests and a
worked example that is executed rather than trusted, because the failure we
actually hit twice was documentation drifting away from behaviour.*

---

## Scope frozen for 9 August

**Decided:** insurance claim review and expense splitting are **done**. 64 and 46
tests. No further cycles unless a bug appears.

Both are real and both work. Neither is the moment a judge remembers, so neither
gets more time. Insurance keeps surfacing through `letter-triage`; it does not
become a demo beat.

The two connectors — nearest clinic, and the prepared medication cart — are what
the remaining time goes to, because they are where the agent does something
concrete in the world *for the senior* rather than for the family's paperwork.

---

## The avatar is not stubbed

**Decided:** `avatars/expert.png` stays a human to-do, and the test keeps
skipping until a real file lands.

A generated placeholder would turn the suite green and be forgotten. A visible
skip is the point.
