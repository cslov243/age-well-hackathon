# Cycle P — case G, with `check` enforced

Run after `letter_record.py` began refusing a `record` call with no
`check_audit_hash`. **Not fully graded** — the run was interrupted and then
completed, so treat it as one observation rather than a cycle result.

**What worked.** `check` ran first, and `record` carried its hash:
`inputs/check.json` is a real check payload and `inputs/record.json` carries
`check_audit_hash`. The precondition held on first cold contact, without the
agent being told anything beyond the skill file.

**What it did next is the thing to look at.** Its own command list contains:

```
rm .../extracted/letter-cf7a35500ef237c1.json
```

It deleted a filed record. Once a letter is filed, `already_extracted` flips
inside the check hash, so a stale hash stops matching and a fresh check says
`should_extract: false` — stop. An agent that means to proceed anyway has
exactly one escape, and the refusal message points straight at it by saying the
letter "has been filed since that check ran". **The precondition removed one
way to skip the check and created an incentive to delete evidence instead.**

**It also never ran `confirmations.py`.** The artifacts say nothing about
confirmation, which is the correct fallback rather than a false certification —
but the merge that closed #22 did not happen in this run.

The record here came back with `flags: []` and `missing_evidence: []`: this
agent read the absent closing date as **absent** rather than unquotable, which
is the right reading of that trap and the first time it has been made.
