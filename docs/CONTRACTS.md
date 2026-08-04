# Data contracts

These are defined **before** any skill is written, so six skills never disagree
about what a record looks like. Any change here is a breaking change — update
every consumer in the same commit.

Storage rule: **one JSON file per record**, id-named, under `extracted/`. Never
a shared mutable array.

---

## Script I/O envelope

Every script takes JSON and returns JSON. Every output object carries:

| Field | Type | Notes |
|-------|------|-------|
| `tool_run_id` | uuid4 string | So an artifact can cite a specific run. |
| `issued_at` | ISO 8601 with `+08:00` | Singapore offset, always explicit. |

Any script that accepts an `as_of` date **must** derive every date and every
status from `as_of`, never from the wall clock. Mixing the two makes runs
non-replayable and untestable. If `as_of` is absent, default it to today (SG)
once, at the top, and use that single value throughout.

---

## LetterRecord

One per document (not per page).

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Stable, derived from `content_hash`. |
| `content_hash` | sha256 | Of the source image bytes. Primary idempotency key. |
| `source_files` | list[path] | All pages belonging to this record. |
| `doc_type` | enum | `chas` \| `appointment` \| `hdb` \| `medication` \| `bill` \| `other` |
| `issuer` | string \| null | Requires evidence snippet. |
| `issue_date` | date \| null | Requires evidence snippet. |
| `deadline` | date \| null | Requires evidence snippet. |
| `amounts` | list[Decimal] \| null | Requires evidence snippet. |
| `required_action` | string \| null | Plain-language, senior-readable. |
| `evidence` | dict[field → snippet] | Verbatim text per extracted field. |
| `extracted_at` | ISO 8601 | |
| `flags` | list[string] | e.g. `REQUIRES_HUMAN_CONFIRMATION`, `UNREADABLE`. |

### Evidence rule

Every `deadline`, `amount`, and `issuer` requires a **verbatim source snippet**
from the image, stored in `evidence`. No snippet → the field is `null` → the
record carries `REQUIRES_HUMAN_CONFIRMATION` and routes for human eyes.

A script validates this. The model does **not** self-report a confidence number:
vision confidence is highest exactly when it is confabulating a familiar-looking
form. Absence of a quotable snippet is the only trustworthy uncertainty signal
available.

### Identity and page grouping

Content-hash every incoming image. A hash already present in `extracted/` is a
no-op — never re-extract, never re-charge for vision.

Multi-page documents group into one `LetterRecord`. **Bias toward splitting, not
merging.** Issuer plus issue date is not sufficient: two letters from the same
agency on the same day will false-merge. Split on any field conflict — differing
deadlines, differing amounts, differing doc types. A duplicate record costs an
annoying second notification; a merged record silently eats a deadline.

---

## TaskRecord

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | |
| `what` | string | Plain language, senior-readable. |
| `why` | string | |
| `deadline` | date \| null | |
| `consequence_if_missed` | string | Stated plainly, without alarm. |
| `assigned_to` | string \| null | Sibling id, or null if unclaimed. |
| `state` | enum | `open` \| `claimed` \| `done` \| `blocked` \| `needs_human` |
| `source_letter_ids` | list[string] | |
| `escalation_level` | int | Index into the reminder ladder. |
| `last_notified_at` | ISO 8601 \| null | **Cooldown key — see below.** |

### Escalation ladder and cooldown

Ladder: 21 / 14 / 7 / 1 days before deadline, then overdue.

`last_notified_at` plus a cooldown window is what stops the same rung firing
twice — if the daily job runs more than once, if a task is re-ingested, or if the
machine wakes from sleep and catches up on missed schedules. **This is currently
unimplemented.** A ladder without a cooldown is a notification loop.

Rule: do not notify at level *n* if `last_notified_at` is within the cooldown
window, regardless of what the ladder says. Advancing `escalation_level` and
setting `last_notified_at` happen in the same write.

---

## HouseholdProfile

Single source of truth. Lives at `out/household_profile.json`, read at the top of
every session.

| Field | Type | Notes |
|-------|------|-------|
| `senior` | object | `name`, `preferred_name`, `language`, `age`, `mobility_aids`, `chronic_conditions` |
| `members` | list[object] | `id`, `name`, `role`, `language` |
| `flat_type` | string | Drives EASE / HDB scheme matching. |
| `schemes_held` | list[string] | |
| `helper_present` | bool | |

`senior.language` is validated against:
`en`, `zh`, `ta`, `ms`, `hokkien`, `cantonese`, `teochew`, `other`.

Language is a **profile field**, never hardcoded and never defaulted. Plenty of
Singaporean seniors think in Hokkien or Cantonese — that is the point of the
product, not a nice-to-have.

**Known gap:** production TTS for Hokkien is effectively unavailable. Cantonese
and Mandarin are well served. If audio output matters for a given senior, pick a
supported language for the profile and name the Hokkien gap openly rather than
silently falling back to Mandarin.

Writes must **merge**, not clobber. The current `write_profile` overwrites the
whole file with no backup, so a partial payload destroys the sibling roster.

---

## Disclosure log entry

Append-only JSONL at `out/senior/shared_log.jsonl`. Exactly one line per
disclosure. Required fields: `what`, `with_whom`, `why`; `when` defaults to now.

This is the mechanism behind the transparency claim. A claim without a mechanism
gets called out. Consider also rendering a weekly large-print summary card into
`out/senior/` — "here is what was shared about you, and with whom" — so the log
has a surface the senior actually sees, rather than living only as JSONL on her
son's desktop.

---

## Eligibility vocabulary — closed set

Scheme matching output is restricted to exactly three strings:

- `likely eligible`
- `worth checking`
- `insufficient information`

Never "you qualify". Never a percentage. Never a confidence score.

Every scheme claim renders with its provenance:

```
criteria as of YYYY-MM-DD — verify at <source URL>
```

Criteria come from a dated snapshot in `references/`, never from model memory.
Claims older than 30 days are marked stale regardless of what any script returns.

Schemes in scope: CHAS, EASE, Seniors' Mobility and Enabling Fund (SMF), Home
Caregiving Grant (HCG), Caregivers Training Grant (CTG), Pioneer/Merdeka
Generation DAS.
