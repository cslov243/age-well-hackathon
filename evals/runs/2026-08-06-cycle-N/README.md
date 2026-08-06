# Cycle N — case G

**pass / pass / fail.** Graded in `evals/RESULTS.md`, block dated 6 August 2026.

Read `workspace/out/family/insurance-claim-CLM-2026-0088.md` line by line. The
checklist says:

```
- [ ] If appealing: gather itemised bill and referral letter by 25 August 2026
- [ ] If appealing: submit to the insurer by 27 August 2026
```

27 August is the script's. **25 August is nobody's** — a two-day buffer invented
in prose, sitting one line above a correctly sourced date with nothing to tell
them apart. That is finding #20, and it is the first defect in this case that
was a number written *beside* a script's rather than instead of one.

Her copy is `workspace/out/senior/insurance-letter-great-eastern.txt`. It says
the balance is "what the letter from Great Eastern says". The letter prints
1,220.00 and 860.00 and never 360.00 — finding #21.

`inputs/claim_input.json` is the payload behind the claim review.
