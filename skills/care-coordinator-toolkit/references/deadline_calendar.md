

## `deadline_calendar.py` — dates a person imports into a calendar

**Use when** a deadline needs to leave this repo and land somewhere she or the
family will actually see it.

**Requires:** `forecast` and `claims` — whole results passed **verbatim**, each
`audit_hash` recomputed and a mismatch refused — plus `horizon_days` and
`detail_level`. **Write `null` for a source you do not have**; the key itself is
required, because an absent key and a misspelled one are the same thing from
inside the script, and one of them scheduled nothing.

`--ics` is required and is the deliverable: the file goes in `out/family/` and a
person imports it. Nothing here writes to anyone's calendar.

**It copies dates and computes none.** They come from `order_by` and
`runs_out_on` in the forecast and `deadlines[].due_on` in the claims review.

**`detail_level` is a disclosure decision, not a formatting one.** A calendar is
read by everyone it is shared with.

| | |
|---|---|
| `minimal` | "Medication refill due" — no medicine, condition, insurer or amount. Two reminders on nearby days look identical **on purpose**; the family artifact says which is which |
| `named` | names the medicine or the insurer, **and is a disclosure** — `disclosure.required` comes back true and step 5 of the checklist below applies to it |

Ask which. Never pick `named` because it reads better.

**Nothing is dropped quietly.** Every date lands in `events` or in `omitted`
with a reason: `no_date`, `beyond_horizon`, or `already_passed`. Report the
`already_passed` ones to the caregiver in prose — a back-dated entry notifies
nobody, and that deadline needs a person today.
