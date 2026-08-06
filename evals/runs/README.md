# Eval runs — what the agent actually wrote

One directory per graded run of `evals/CASES.md`, newest cycle last. These are
**outputs, not fixtures.** Nothing here is an input to anything, and nothing
here should ever be copied into `evals/fixtures/` — a fixture is what a run
starts from, and mixing the two is how a run ends up grading its own output.

Every defect in case G for five cycles was invisible in the JSON and plain in
the prose, which is why these are kept. `evals/RESULTS.md` says what was graded
and why; this is the evidence behind it.

All three runs are the same case, the same letter, and a cold Haiku agent given
only the preamble in `evals/CASES.md`. The letter itself is
`evals/fixtures/care/inbox/ge-claim-2026-07-28.txt`.

| Run | Cycle | Tool | Answer | Instructions | What it showed |
|---|---|---|---|---|---|
| `2026-08-06-cycle-N` | N | pass | pass | fail | Invented `by 25 August 2026`, a date no script produced (#20) |
| `2026-08-06-cycle-O` | O | fail | pass | fail | `confirmations.py` landed: the flag reached both artifacts (#22, #16). Lost the `check` call (#25) |
| `2026-08-06-cycle-P` | P | fail | pass | — | `check` ran first and `record` carried its hash. Then deleted a filed record, and never ran `confirmations.py` |

## Layout

```
<run>/workspace/   what the run left in the household folder
        extracted/   the filed record
        out/family/  the family artifact
        out/senior/  her copy, and shared_log.jsonl
        processed/   the letter, moved after filing
<run>/inputs/      the JSON payloads the agent built for each script
```

`household/` is omitted from each copy — it is fixture input, unchanged by every
run, and duplicating it three times would invite someone to edit the wrong one.

## What replays and what does not

The `audit_hash` values quoted in these artifacts were verified at grading time
by re-running the script on the payload the agent left behind. **They will not
replay from this directory**, because `source_files` inside each payload points
at the scratch workspace the run used, and the hash covers the resolved input
paths. That is not a defect in the archive; it is
[finding #23](../../docs/AUDIT-FINDINGS.md) — the run quoted a hash that nothing
in the workspace could reproduce, because the inputs were written to `/tmp` and
the outputs were never filed with `--output`.

Cycle O's claim-review payload is **missing** for the same reason: the cycle P
agent wrote to `/tmp/claims_input.json` and overwrote it. What survives is that
run's *output*, `inputs/claims_output.json`, which carries the same hash the
artifact quotes. A run whose inputs live in a shared temp directory is a run
that can be silently destroyed by the next one, which is the argument for fixing
#23 rather than a footnote to it.
