# Cycle Q — case G, 6 August 2026

One cold Haiku agent, the preamble in `evals/CASES.md` verbatim, a scratch copy
of `evals/fixtures/care/`. The cycle fixed audit finding #26.

| Axis | | |
|---|---|---|
| Correct tool | **pass** | All four scripts, in order, for the first time |
| Correct answer | **fail** | The JSON is right. Her copy says the clinic billed *two thousand two hundred and twenty dollars* for SGD 1,220.00 |
| Followed instructions | **fail** | The page was never moved to `processed/`; her copy composed a status instead of quoting one |

**#26 did not recur** — nothing was deleted, and the run never reached the
already-filed path, so that is an absence rather than a measurement.

**#25 is now structural.** The record on disk cannot exist without a `check`
call having produced the hash that licensed it, so this is no longer a thing the
eval has to catch.

## What is here

```
workspace/extracted/   the filed record, and the claim review the agent
                       wrongly wrote here too — finding #28
workspace/out/family/  the family artifact
workspace/out/senior/  her copy, and shared_log.jsonl
```

`inputs/` is **missing entirely**. Every payload went through `/dev/stdin` from
a heredoc, so nothing survived the run and no input is recoverable — the same
defect as cycle O's clobbered payload, one step worse. That is
[finding #23](../../../docs/AUDIT-FINDINGS.md), not an archive defect. The
`audit_hash` values in the artifacts were verified against the outputs that were
written, and the appeal date and day count were confirmed to come from
`insurance_claim_review.py` rather than from prose.

These are **outputs, never fixtures.** Nothing here belongs in
`evals/fixtures/`.
