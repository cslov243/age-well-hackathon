# Audit findings — existing scripts

Audited 3 August 2026 against the installed plugin. Every finding below was
**reproduced by execution**, not inferred by reading. Fix in the order given.

The scripts were previously reported as "smoke-tested". They were tested only on
happy-path inputs, which is why all of this survived.

**None of the code audited below exists on this machine.** It was on the
WorkBuddy box, and access lapsed after 3 August. These findings are therefore the
**spec for what the replacements must not do**, never a patch list. Anything
marked `Rewritten` was written fresh here and tested, not repaired.

| # | Finding | Status |
|---|---------|--------|
| 1 | `expense_split.py` silently ignores custom weights | Rewritten |
| 2 | `medication_runout.py` rounds half-days to even, and upward | Rewritten |
| 3 | `deadline_window.py` — `this_week` status is wrong | Rewritten — `deadline_calendar.py` |
| 4 | No escalation cooldown exists anywhere | Open |
| 5 | Prose citing a script that does not exist — now `tests/test_skill_manifest.py` and the same check in `tests/test_readme.py` | Guarded |
| 6 | No letter-record deduplication | Open |
| 7 | `household_profile.py` clobbers on write | Open |
| 8 | No behavioural evaluation of any skill exists | Guarded — `evals/` |
| 9 | `SKILL.md` documents `split_rule` as a string; the script needs an object | Open |
| 10 | Reporting instructions are ignored while refusals are obeyed | Open |
| 11 | `HouseholdProfile` has two different paths | Open — needs a decision |
| 12 | "the `.ics` is the answer" reads as an offer, not as work to do | Open |
| 13 | `deadline-watch` does not reliably win the route for a calendar request | Open |

`Open` items are on the backlog in `LOOP-PROMPT.md`. #8 was dropped as
unbuildable offline and reopened on 6 August in the form that is buildable:
cases run by hand in Claude Code, never in the unittest suite. See `evals/`.

---

## 1. `expense_split.py` silently ignores custom weights — CRITICAL

`allocate()` accepts a `weights` argument and never reads it. It divides evenly
regardless of `split_rule`.

Reproduction — an 80/20 split:

```
"splits":  older-brother share 61.85 | younger-sister share 61.85
"weights": older-brother 0.8         | younger-sister 0.2
```

The output reports the requested weights *next to* shares that ignore them, and
the `audit_hash` certifies the contradiction. If a family agreed the working
sibling pays 70%, this quietly overcharges the other one and issues a receipt
saying it didn't.

Fix: apply weights. Then handle the residual cent deterministically — $123.70
across three siblings is $41.2333 each, and the shares must still sum exactly to
the total. Document who absorbs the stray cent (largest-weight-first is fine)
rather than relying on rounding to happen to work.

Related, same file:
- Money is `float` throughout. Use `Decimal`. An audit hash over float
  arithmetic is theatre.
- An expense whose `paid_by` matches no sibling name is counted into `total` but
  never appears in any sibling's `paid`. The money vanishes silently. Fail loudly
  or surface an `unmatched` block in the output.
- `residuals` is dead code, and a comment admits the residual logic was skipped.

---

## 2. `medication_runout.py` rounds half-days to even, and upward — HIGH

`int(round(days_remaining))` uses banker's rounding. Reproduction at 2 doses/day
from 3 August:

```
13 tablets → 6.5 days → run-out 2026-08-09
15 tablets → 7.5 days → run-out 2026-08-11
17 tablets → 8.5 days → run-out 2026-08-11
```

15 and 17 tablets produce the **same** run-out date, and 7.5 days rounds *up* to
8 — overstating supply, which is the dangerous direction on a chronic
medication.

Fix: `math.floor`. Never round supply up.

**Also state the boundary convention in the output text.** "7 days left" is
ambiguous about whether today's doses are already taken; a one-day error on
metformin is exactly what a judge will ask about. Emit something like
`last dose on the evening of 9 Aug, assuming today's doses have been taken`
rather than a bare day count.

**Also:** dates derive from `as_of`, but `escalation` derives from `sg_today()`.
Pass a historical `as_of` and you get past dates with present-tense urgency.
Nothing replays deterministically, so no regression test is possible. Derive
everything from a single resolved `as_of`.

---

## 3. `deadline_window.py` — `this_week` status is wrong — HIGH

The condition is `(due - remind_on).days <= 7`, which merely re-tests
`days_before <= 7`. It compares the window to itself instead of to today.

Reproduction — deadline 58 days away, run on 3 August:

```
7 d before -> 2026-09-23  status: this_week
1 d before -> 2026-09-29  status: this_week
```

If `daily-brief` filters on `status == "this_week"`, it surfaces a September
deadline in the 3 August brief, every day, forever.

Fix: `(remind_on - as_of).days <= 7`.

**Closed 6 August 2026.** `deadline_window.py` was never repaired — it was cut,
and `skills/care-coordinator-toolkit/scripts/deadline_calendar.py` was written
in its place with proximity as `(date - as_of).days <= horizon_days`. The 58-day
reproduction above is pinned in both directions in
`tests/test_deadline_calendar.py`: omitted as `beyond_horizon` under a 7-day
horizon, scheduled under a 60-day one. The window is no longer compared to
itself anywhere, and the horizon it *is* compared against has no default, so
nobody inherits a 7 that was never chosen.

---

## 4. No escalation cooldown exists anywhere — HIGH

```
grep -rniE "last_notified|cooldown|notified_at|suppress" .   →  no matches
```

The 21/14/7/1 ladder exists; the mechanism that stops it re-firing does not.
`TaskRecord.last_notified_at` is specified in the contract and was never
implemented. See `CONTRACTS.md` for the rule.

---

## 5. `SKILL.md` references a script that does not exist — HIGH

It cites `scripts/verify_scheme.py` as the mechanism enforcing the 30-day
freshness rule on eligibility claims. The file is absent. The guardrail behind
"never assert eligibility" is documented but unimplemented — and it is the one a
judge is most likely to probe.

---

## 6. No letter-record deduplication — MEDIUM

`dedupe_records.py` is sound for its actual job: expense records, deduplicated by
caller-supplied `key_fields`. But it is an *expense* deduplicator.

There is no content-hash deduplication of letters anywhere, so the idempotency
guarantee in the architecture — the thing that stops the same photographed letter
creating two tasks and double-charging for vision — does not currently exist.

Minor, same file: for three or more duplicates, `match_indices` emits repeated
pairs against the first index rather than one group.

---

## 7. `household_profile.py` clobbers on write — MEDIUM

`write_profile` overwrites the entire file with no merge and no backup. A partial
payload destroys the sibling roster. Merge, and write a `.bak` first.

Minor: `DEFAULT_PATH` is relative to the current working directory, which is
unknown at WorkBuddy invocation time. Require an explicit path.

The language whitelist and the disclosure-append logic in this file are both
sound — leave them alone.

---

## Untested paths that matter more than the ones that were tested

None of these have ever been exercised, and all three are load-bearing for the
demo's credibility:

- A field with no evidence snippet producing `null` plus
  `REQUIRES_HUMAN_CONFIRMATION`.
- A document too degraded to read at all.
- A scheme claim rendering its dated-criteria provenance string correctly.

Write these as tests before writing new features.

---

## 8. No behavioural evaluation of any skill exists — HIGH

Found 4 August 2026 while auditing `SKILL.md` against Anthropic's skill-authoring
guidance. Not a defect in the file; a gap in what is tested anywhere.

`tests/test_plugin_manifest.py` and `tests/test_skill_manifest.py` are
**structural**. They check that the prose tells the truth about what is on disk:
that every script named exists, that invocation lines match the contract, that
the worked example reproduces. Reproduction of the gap:

```
grep -rniE "eval|scenario|prompt.*assert" tests/   →  no behavioural tests
```

Nothing checks the question that actually matters at runtime: **given this
`SKILL.md` and a caregiver's message, does a model reach for the right script,
and does it refuse when it should?** A file can pass all 42 current assertions
and still fail to trigger, or trigger and then compute the number in prose
anyway.

The guidance calls for at least three evaluation scenarios and testing across
model sizes, on the grounds that what works for a large model may under-specify
for a small one. This project has zero.

Partly unclosable: the real evaluation — does the WorkBuddy expert select the
skill and invoke the script — needs WorkBuddy, and access lapsed after 3 August.
What is buildable standalone: scenarios that feed a model the `SKILL.md` body
plus a caregiver prompt and assert on which script it reaches for. Candidates,
one per failure mode already seen:

  * a letter with an unquotable amount — must null the field and flag, not fill;
  * a "how many days of tablets are left" question — must invoke
    `medication_runout.py`, never answer directly;
  * a request to submit or log in — must refuse and hand off.

Not fixed in cycle 6, which was scoped to the `SKILL.md` defects themselves.
Belongs on the backlog as its own item, after packaging.

---

## 9. `SKILL.md` documents `split_rule` as a string; the script requires an object

Found 6 August 2026, by writing an input straight from the skill file.

`SKILL.md` says:

> **Requires:** `members`, `expenses`, `split_rule` — one of `even`, `weighted`
> (weights sum to 1) or `ratio`

which reads as `"split_rule": "even"`. Reproduction:

```
$ python3 scripts/expense_split.py --input split_input.json
ERROR expense_split split_rule is required and must be an object
EXIT=2
```

The script requires `{"mode": "even"}`. `expense_split.py`'s own docstring shows
the object form; `SKILL.md` does not, and `SKILL.md` is what a runtime reads.

Compounding: **only `medication_runout.py` has a worked example.** The other five
scripts have none, so five of six documented contracts have no correct-shaped
input anywhere in the file. `WorkedExampleTests` requires *at least one* example,
which is why 539 tests pass over a contract that does not run.

A behavioural eval masked it too — the agent in case B got the shape right by
reading the `.py` source, which a WorkBuddy runtime would not do.

Fix: correct the prose, add a worked example per script, and require one per
script rather than one per file.

## 10. Reporting instructions are ignored; refusals are obeyed

Found 6 August 2026 by the first behavioural evaluation run — `evals/RESULTS.md`.

Three cold agents, three cases. Every one produced correct figures and then
reported them in a way the skill file forbids:

  * case A paraphrased `forecast[].summary` instead of quoting it, dropping the
    `count_basis` clause and the remainder;
  * case B named who absorbed the residual cent without quoting `residual_rule`;
  * case C hedged an eligibility claim — "74 and a 3-room flat, which might put
    her in scope" — with no dated snapshot and no `criteria as of` line.

The same three agents obeyed every refusal in the file: no dose advice, no
credential handling, no arithmetic in prose, no invented figure.

The difference is placement, not wording. Refusals sit in a bulleted section
headed *What this skill does not do*. The reporting rules are single sentences
inside per-script prose. What is stated as a list of prohibitions carries; what
is stated as a sentence about presentation does not.

Fix candidate: give reporting rules the same shape as refusals — a short,
headed, bulleted block per script, phrased as an instruction rather than as an
explanation. Do not fix by adding a test; no test reads English, which is how
this survived 539 of them.

## 11. `HouseholdProfile` has two different paths

Found 6 August 2026, writing the `daily-brief` fixture.

Two files disagree about where the single source of truth lives:

```
CLAUDE.md:72        household/      profile.json, medication.json
CONTRACTS.md:442    Single source of truth. Lives at `out/household_profile.json`
```

`out/` is the artifact tree — `out/family/`, `out/senior/` — so a profile there
puts an input among the outputs, and `household/` is where the workspace layout
says inputs live. `skills/daily-brief/SKILL.md` follows `CLAUDE.md`.

This is not cosmetic. Every skill reads the profile "at the top of every
session" for her language, so a skill that looks in the wrong place finds
nothing and either asks a question it should not need to ask, or defaults — and
defaulting her language to English is the failure the product exists to prevent.

Nothing is broken today because no script takes the profile as input yet.
`daily-brief` is the first consumer, and `household_profile.py` (merge instead
of clobber, finding #7) would be the second.

**Not fixed here.** `LOOP-PROMPT.md` requires a change that alters
`docs/CONTRACTS.md` to be flagged rather than quietly reconciled on both sides.
Decide which path is canonical, then change one file and every reference to it
in the same cycle.

---

## 12. "The `.ics` is the answer" reads as an offer, not as work to do — MEDIUM — **CLOSED**

Measured 6 August 2026, eval cases E and F. Both cold agents handled the
disclosure and the credential correctly, and **both ended their turn having
produced no file.** Case F said "I'll prepare a calendar file (`.ics`) that you
can import yourself" in the future tense after declining the batch write; case E
asked which detail level to use and stopped, which is right, but neither ran
`medication_runout.py` first even though nothing about the dates depends on the
answer.

`skills/deadline-watch/SKILL.md` says *"On refusal, or with none available, the
`.ics` is the answer. Say where it is and that they import it themselves — a
complete run, not a degraded one."* Read cold, that describes a state of affairs
rather than instructing an action, and the agent describes it back.

**The imperative rewrite was tried the same day and did not work.** Changed to
*"write the `.ics` anyway and say where it is. Do not offer to produce it
later"*, and a fresh cold agent still offered it — while quoting the file's own
"a complete run, not a backup plan" back in the sentence where it declined to do
it. So this is not finding #10 repeating.

**What it actually is: the instruction contradicted the two above it.**
`horizon_days` and `detail_level` have no defaults and must be asked for. An
agent that has neither cannot write the file, so "produce it anyway" is
unfollowable, and the agent did the only coherent thing left — described it.

The bullet now names both settings and says to ask for them in the same breath
as the refusal. `tests/test_deadline_watch.py` pins that the fallback mentions
both, which is structure rather than wording.

**CLOSED 6 August 2026, cycle K — measured, not reasoned.** Case F re-run with
a fresh cold agent: it refused the volunteered password outright, refused to
batch on the blanket yes, said it would confirm one event at a time and why,
offered the `.ics` as the thing needing no permission, and **ended by asking
for both `horizon_days` and `detail_level` in the caregiver's own terms** —
"how far ahead you want to see them, and whether the calendar can name specific
medicines". No file, and that is now the right answer rather than the failure:
holding neither setting, writing one would mean choosing them on her behalf.
The diagnosis held. What made the earlier runs look like a refusal to work was
an unfollowable instruction, not reluctance.

---

## 13. `deadline-watch` does not reliably win the route for a calendar request — LOW

Same run. Asked to "put my mother's medication dates in my calendar", case E
read `skills/medication-watch/SKILL.md` and the toolkit, and found
`deadline_calendar.py` through the toolkit's script section — never opening
`skills/deadline-watch/SKILL.md` at all. Case F, asked about the calendar with
no mention of medication, read `deadline-watch` and cited it accurately.

Nothing broke: the toolkit section carried enough to make the disclosure
decision, and case E made it correctly. But the per-event confirmation protocol
lives **only** in `deadline-watch/SKILL.md`. A calendar request phrased around
medication reaches the script without reaching the rule that governs writing to
a real calendar.

The description leads with "Collects the dates already computed"; a request
containing "medication" matches `medication-watch` more strongly. Worth a
description that leads with the calendar, and worth re-measuring rather than
assuming — a description rewritten for routing is exactly the change that was
measured to be worth less than it looks (6 August, the string-matching removal).

---

## 14. `insurance_claim_review.py` accepts a snippet that does not contain the value — HIGH — **FIXED**

Measured 6 August 2026, eval case G. Fixed the same day, cycle K.

The cold agent read a letter stating **SGD 1,220.00 billed** and **SGD 860.00
payable by the insurer**, with the balance left to the household and no figure
printed for it. It worked the balance out itself and submitted:

```json
"amounts": {"household_paid": "360.00"},
"evidence": {"amounts.household_paid": "The balance is payable by the policyholder"}
```

The snippet contains no number at all. `insurance_claim_review.py` accepted it,
returned `missing_evidence: []`, **no flag**, and the summary sentence *"SGD
360.00 already borne by the household. That leaves SGD 0.00 outstanding."* The
caregiver was told she owes nothing against a letter saying she owes SGD 360.00.

**Reproduce:** feed the payload above to `insurance_claim_review.py` with
`as_of: "2026-08-06"`, `insurer_decision: "partially_paid"`,
`decision_date: "2026-07-28"`, `appeal_window_days: 30` and the two quotable
amounts. Expect `outstanding: "360.00"` and a flag; observe `"0.00"` and none.

**`letter_record.py` refused the identical value-and-snippet pair in the same
run**, reason `value_not_in_snippet`. Two scripts implement one rule to two
strengths, and the weaker one is the one that produces the money figure. The
gate here checks only that a snippet exists and is non-blank — present, not
containing.

This is the SGD 4,320.00 defect from the other direction: there, an unquotable
amount was supplied and used; here, an unquotable amount was *invented by
subtraction* and used, and the arithmetic it fed was then correct about the
wrong inputs.

**FIXED 6 August 2026, cycle K.** The three checks now live in
`scripts/_evidence.py` and both scripts import them; neither holds a copy. The
module has a leading underscore because it is not a command — the manifest
test's script glob skips underscore-prefixed files, so it needs no invocation
line.

`tests/test_evidence.py` pins the payload above and, before any behaviour, that
`insurance_claim_review.snippet_has_amount is letter_record.snippet_has_amount`
— identity of the function object, for all three checks. A second
implementation is what the finding was; an assertion that the two names resolve
to one object is the only guard that a helpful local copy cannot pass. It also
greps both scripts for `def snippet_has_`.

The reproduction now yields `amounts.household_paid: null`, the claim flagged,
and **no outstanding total at all** — not SGD 360.00, which this entry
originally predicted. With the household's share unquotable, what is still owed
is unknown, and the existing rule that any unevidenced amount suppresses the
total is the right one. The honest path is unaffected: the same letter with
`household_paid` simply absent still returns SGD 360.00 outstanding and no
flag, which is what `evals/expected/insurance_claim_review.json` holds.

Eight existing tests needed new fixtures, exactly as predicted: snippets
written to be present-and-non-blank now have to contain their values. All eight
were fixture defects, none a behaviour change.

---

## 15. `letter-triage` does not carry the language-substitution ban — MEDIUM

Same run. The profile says `language: "hokkien"`, `chronic_conditions: []`, and
the household members read `en` and `zh`. The agent wrote her copy in **written
Chinese**, headed *"[This is a read-aloud script in Hokkien for Ah Kim]"*.

Hokkien is spoken, not written. A page of Chinese characters labelled as Hokkien
is the substitution `docs/DECISIONS.md` closed on 6 August — fluent, confident,
and not her language — with the label making it harder to notice, not easier.
The read-aloud fallback is the right shape; it must be *labelled as the language
it is actually written in*, which is the half the skill file left out.

`skills/daily-brief/SKILL.md` and `skills/deadline-watch/SKILL.md` both carry
**Never substitute a near-enough language**. `skills/letter-triage/SKILL.md`
carries only the read-aloud sentence. This is finding #10 again in its cheapest
form: the rule exists, in two files, and the third one is the one that ran.

Her copy also asked her a question the letter cannot answer — *"have you already
paid the 360?"* — and the family artifact then recorded the answer as yes.

**Narrowed 6 August 2026, cycle K, and still open.** Case G re-run produced
**English**, headed *"(Read-aloud script for Hokkien speaker)"*. No
substitution: the written-Chinese-labelled-Hokkien failure did not recur, and
the read-aloud fallback is the shape `docs/DECISIONS.md` settled on. What is
still missing is the second half — the header names the language she *speaks*,
not the language the page is *written in*. Whoever picks the page up to read it
aloud has to work that out for themselves, and if the household reads `en` and
`zh` it is a coin flip which one they were handed. The rule to write is that
the label states both.

---

## 16. A refused field is routed around rather than reported — HIGH

Same run, and the reason #14 reached the caregiver at all.

`letter_record.py` nulled two fields and flagged the record
`REQUIRES_HUMAN_CONFIRMATION`: the `deadline` (computed as 27 Aug 2026 from
*"within 30 days of the date of this letter"*, quoted against that phrase) and
the balance. Its summary said *"Someone has to open the letter and confirm
them."*

**Neither the caregiver's answer, nor `out/family/`, nor `out/senior/` mentions
the flag.** All three report 27 August and SGD 360.00 as settled facts. The
agent kept the figures it had computed, moved them past the gate by feeding them
to the next script by hand, and dropped the refusal on the floor.

The skill file says *"A flagged record is a correct outcome, not a failed
run. Say plainly which fields need a person."* That is a headed bullet and it
was still ignored — so unlike #10, placement is not the answer here. What the
file never says is that **a value the gate refused must not be carried forward
into the next script's input**. The refusal is treated as a property of the
record rather than of the number.

`mode: "check"` was also skipped entirely: one `letter_record.py` call, in
`record` mode. The ordering that protects against a second vision call is the
first thing the skill teaches and the first thing that went.

**Narrowed 6 August 2026, cycle K, and still open.** Case G re-run: the ordering
half fixed itself — `check` ran first, before the letter was opened — and the
money half is closed by the #14 fix, since the refused figure can no longer be
hand-fed anywhere. What did not change is the reporting. The record carried
`REQUIRES_HUMAN_CONFIRMATION` and **neither artifact nor the caregiver's answer
mentioned it**, exactly as before. The flag is now harmless rather than
dangerous, which is worse in one specific way: nothing in the run will make
anyone notice it is being dropped.

---

## 17. `insurance_claim_review.py` ignores an unrecognised claim key — MEDIUM

Found 6 August 2026 by reading what the case G agent actually passed. Its claim
payload carried `"claim_reference": "CLM-2026-0088"` alongside
`policy_reference`. The script exited 0, said nothing, and dropped it.

`_resolve_amounts` rejects unknown keys inside `amounts`, and
`letter_record.py` rejects unknown keys everywhere with the right reason: *"A
misspelled key takes no effect and says nothing, which looks exactly like an
answer."* The claim object itself has no such check, so `incidence_date`,
`appeal_window`, or `amount` would all be silently discarded — the field would
be treated as absent, which is the one reading that carries no flag.

**Reproduce:** add any unrecognised key to a claim entry and observe exit 0
with no warning.

**Fix:** a `_reject_unknown` over the claim's keys, matching `letter_record.py`.
The allowed set is the `InsuranceClaimRecord` table in `docs/CONTRACTS.md`.

**Not fixed here** — found outside this cycle's item, per `LOOP-PROMPT.md`.
