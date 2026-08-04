# Audit findings — existing scripts

Audited 3 August 2026 against the installed plugin. Every finding below was
**reproduced by execution**, not inferred by reading. Fix in the order given.

The scripts were previously reported as "smoke-tested". They were tested only on
happy-path inputs, which is why all of this survived.

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
