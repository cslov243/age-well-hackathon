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

## External data — reversed 6 August 2026: fetching is allowed

**Now decided:** a script may reach the network. Every fetched fact renders its
source URL and retrieval time; an unreachable source degrades to the dated
snapshot marked stale, never to a guess; and the test suite stays offline.

**Why the reversal:** the no-network rule was bounding the product, not just the
implementation. Live scheme criteria, real geocoding and step-free routing are
the difference between a filing assistant and something that answers "where do I
take her and can she get in". Three of the four reasons below survive as
*preferences* — snapshot what is slow-moving, keep the demo independent of the
venue's wifi — but they were being enforced as a prohibition, and the cost of
that showed up as scope.

**What did not change, and must not be confused with this:** no Singpass, no
portal login, no credential, no submission. Reaching a public source is not
acting as her. That rule is untouched.

**Risk knowingly accepted:** WorkBuddy security-scans plugins on install, and
whether outbound HTTP from a script trips it is **[UNKNOWN]** and untestable
since access lapsed on 3 August. If an install is refused at submission, the
network calls are the first thing to strip — which is why snapshots stay the
default for anything the demo depends on.

---

**Superseded — the original decision, kept because the reasoning is still the
right default:** dated snapshots, fetched offline by `tools/fetch_references.py`,
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

## A spoken-only language does not stop the run — decided 6 August 2026

`senior.language` may be `hokkien`, `teochew` or `cantonese`. These are spoken,
not written, and no production text-to-speech ships for them. The first version
of `daily-brief` treated that as unresolvable and stopped the whole run, which
is the honest reading of *dual output on every skill*: one artifact without the
other is unfinished.

Measured the same day, eval case D: the agent read the profile, named the gap,
asked which language to use instead, and wrote nothing. Correct by the rule, and
a caregiver who asked for a brief got no figures at all — every day, forever,
because nobody in this project can add Hokkien TTS.

**Decided: produce the run.** Her copy becomes a **read-aloud script for whoever
is with her** — short spoken sentences, second person, in a language the
household reads — labelled as that at the top. The gap is stated once in the
family copy and not raised again daily.

What did **not** change: no near-enough substitution. Mandarin because the
profile says `hokkien` is still the failure this product exists to prevent, and
it is still fluent, confident, and not her language. The difference is that the
answer is now a person reading to her rather than a run that produces nothing.

`skills/daily-brief/SKILL.md` and `skills/deadline-watch/SKILL.md` both carry
it. `evals/RESULTS.md` records the open question this closes.

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

---

## MCP is a layer, never a dependency — decided 6 August 2026

**Decided:** the `.ics` file is the shipped calendar path. An MCP calendar write
is optional, and `mcpServers` does **not** go into `.codebuddy-plugin/plugin.json`
before 9 August. `.mcp.json` was removed from the repo the same day.

Three surfaces got confused with each other, so they are separated here.

| Surface | Setup for us | Setup for a user |
|---|---|---|
| `.ics` in `out/family/` | none | none — it imports into any calendar |
| A claude.ai connector | none | connect Google once, in claude.ai |
| Our own MCP server, in the plugin | Cloud project, two APIs, OAuth client, **Google verification** | consent flow, plus an "unverified app" warning until that verification lands |

**The URL was never the problem.** `https://calendarmcp.googleapis.com/mcp/v1`
is exactly what Google documents. What the documentation adds is everything
around it: a Cloud project, both `calendar-json.googleapis.com` and
`calendarmcp.googleapis.com` enabled, a consent screen, and our own OAuth client
ID and secret. Google's own instruction for Claude is a custom connector
configured in settings — not a `.mcp.json`, which has nowhere to put a client
secret. The repo's `.mcp.json` had the right address in a form that could never
authenticate, and it was deleted rather than completed.

**Two reasons it is not completed.**

**It wants a credential in the repo.** `.mcp.json` is a tracked file. This is the
product whose entire posture is that it never touches a credential, and
WorkBuddy security-scans plugins on install. Even where a client secret is
low-value, this repo is the wrong place for one.

**Calendar is a sensitive scope, so the cost is not ours to pay once.** An
unverified OAuth app is capped at 100 test users and shows Google's warning
screen. Shipping to real users means Google's verification review — weeks, not
days. "Users configure it themselves" understates it: before a user can click
allow, the app has to exist and be approved.

**The product reason outranks both.** The users are caregivers looking after
elderly parents, and the senior is the primary user. A calendar feature that
opens with an OAuth consent flow has already lost the person it is for. The
`.ics` needs no account, no permission dialog, no network and no configuration
by anybody. It is the deliverable, not the fallback — which is also why a judge
running a fresh install on 9 August sees a working file rather than an auth
error.

**What still works, and is the demo path.** The claude.ai Google Calendar
connector is live in Claude Code and account-scoped, so the optional confirmed
write is demonstrable today with no setup at all. That is the layer working as
intended: MCP earns its place on the **handoff** side, where the model is
legitimately the actor, and never for anything that produces a number — an MCP
tool carries no `tool_run_id` and no `audit_hash`.

**Reopen this after Demo Day**, if the plugin ever ships to users outside the
hackathon. Adding `mcpServers` is still one line; the verification is the work.
