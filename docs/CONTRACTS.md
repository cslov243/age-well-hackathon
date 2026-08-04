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
| `doc_type` | enum | `chas` \| `appointment` \| `hdb` \| `medication` \| `bill` \| `insurance` \| `other` |
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

## InsuranceClaimRecord

Consumed by `scripts/insurance_claim_review.py`. A `LetterRecord` with
`doc_type: "insurance"` is the source; this is the structured claim extracted
from it. Added 4 August 2026.

| Field | Type | Evidence-gated |
|-------|------|----------------|
| `id` | string | — |
| `insurer` | string \| null | **yes** (it is the issuer) |
| `policy_reference` | string \| null | no — an identifier, not a claim about the world |
| `incident_date` | date \| null | **yes** |
| `submission_window_days` | int ≥ 0 \| null | **yes** |
| `insurer_decision` | enum | — closed set, read off the document |
| `decision_date` | date \| null | **yes** |
| `appeal_window_days` | int ≥ 0 \| null | **yes** |
| `amounts.billed` / `.insurer_paid` / `.household_paid` | Decimal ≥ 0 \| null | **yes**, each |
| `documents_required` / `documents_held` | list[string] | — |
| `evidence` | dict[field path → snippet] | — |

`insurer_decision` is exactly `paid`, `partially_paid`, `rejected`, `pending`,
`not_stated`. An unrecognised value is **refused**, never mapped to the nearest
one. Deadline status is `ok`, `due_today`, `overdue`, `unknown`.

### This never decides coverage

Whether a claim will be paid is the insurer's decision. The script reports the
outcome the letter states and does the arithmetic around it. There is no code
path that emits "you are covered", and none that submits or appeals anything —
`prepare and hand off; never submit` applies here exactly as it does to CHAS.

The three-string eligibility vocabulary does **not** apply: it is for matching a
profile against scheme criteria, which is a different question from reporting an
insurer's stated decision. Do not reuse it here.

### Evidence rule, applied to money

- Value present **with** a usable snippet → used.
- Value present with **no** snippet (or an all-whitespace one) → nulled, listed
  in `missing_evidence`, claim flagged `REQUIRES_HUMAN_CONFIRMATION`.
- Value **absent** → null, no flag. "Not found in the document" is honest.

**Any unevidenced amount suppresses `outstanding` and `refund_due` entirely.**
An absent amount is genuinely zero; an unquotable one is *unknown*, and
subtracting zero for it would overstate what the household still owes. A missing
total and a wrong total are not equally bad.

`outstanding = billed − insurer_paid − household_paid`, floored at zero; any
excess is reported as `refund_due` rather than a negative outstanding.

---

## MedicationRecord

Lives at `household/medication.json`. Consumed by `scripts/medication_runout.py`
and by `medication-watch`. Added 4 August 2026 — this file previously referenced
`household/medication.json` without specifying it.

| Field | Type | Notes |
|-------|------|-------|
| `as_of` | date \| absent | Optional. Absent → SG today, resolved **once**. |
| `default_lead_time_days` | int ≥ 0 | **Required.** No hardcoded default anywhere. |
| `medications` | list[object] | May be empty. |

Each medication:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Unique within the file. |
| `name` | string | As the senior would recognise it. |
| `form` | string | Unit noun — `tablet`, `capsule`, `ml`. |
| `form_plural` | string \| absent | Optional; defaults to `form` + `s`. |
| `quantity_on_hand` | Decimal ≥ 0 | In units of `form`. Never a binary float. |
| `schedule` | object | `{"mode": "fixed_daily", "units_per_dose", "doses_per_day"}` or `{"mode": "prn"}` |
| `counted_on` | date \| absent | `fixed_daily` only. Defaults to `as_of`; must be ≤ `as_of`. |
| `count_basis` | enum | `fixed_daily` only. **Required, no default** — see below. |
| `lead_time_days` | int ≥ 0 \| absent | `fixed_daily` only. Overrides the file default. |

`counted_on`, `count_basis` and `lead_time_days` are **rejected** on a `prn`
medication rather than ignored, as are `units_per_dose` and `doses_per_day`. A
caregiver who supplies a lead time expects an order-by date and would otherwise
silently not get one.

### Dose-boundary convention

`count_basis` is required and has no default, because whether the count day's
doses were already taken shifts every run-out date by exactly one day:

- `doses_on_count_day_taken` — counted after that day's doses. Coverage starts
  the day **after** `counted_on`.
- `doses_on_count_day_pending` — counted before. Coverage starts **on**
  `counted_on`.

Output must state the convention in words, never as a bare day count.

### Forecast rules

- `days_of_supply = floor(quantity_on_hand / units_per_day)`, on exact
  `Fraction`s. **Supply is never rounded up.** `leftover_units` is what remains
  beyond the last full day and buys no further full day.
- `runs_out_on` is the first day not fully covered; `last_full_dose_day` is the
  day before it.
- `order_by = runs_out_on − lead_time_days`.
- A `counted_on` earlier than `as_of` consumes supply — a stale count shortens
  the forecast rather than extending it.
- Status vocabulary is closed: `ok`, `order_now`, `order_overdue`, `no_supply`.
  All four derive from the single resolved `as_of`, never the wall clock.

PRN medications are excluded from `forecast` and listed in `not_forecast` with
`reason: "prn_no_fixed_rate"`, their quantity, and **no dates**. Forecasting one
is clinical judgement, not arithmetic.

---

## ClinicSnapshot

Written by `tools/fetch_references.py` into
`skills/care-coordinator-toolkit/references/`, consumed by `clinic_finder.py`.
Added 4 August 2026. **Additive** — no existing consumer changes.

One dated pair per fetch: `chas-clinics-YYYY-MM-DD.json` and its
`.manifest.json`.

| Field | Type | Notes |
|-------|------|-------|
| `record_type` | `"ClinicSnapshot"` | |
| `as_of` | date | The snapshot's date; the freshness rule reads this. |
| `fetched_at` | ISO 8601 `+08:00` | Excluded from `content_hash`. |
| `source_url` / `dataset_id` | string | Provenance for the citation line. |
| `source_kind` | `dataset_download` \| `local_file` | Which it actually was. A `--from-file` snapshot carries a `dataset_id` for the dataset it is *meant* to be, but nothing verified that — so it does not inherit the dataset's provenance. |
| `attribution` | string | Required by the Open Data Licence. |
| `record_count` | int ≥ 1 | Never 0 — see below. |
| `clinics_without_mapped_name` | int ≥ 0 | How many names could not be mapped. |
| `content_hash` | sha256 | Over `clinics` only. |
| `clinics` | list[object] | Sorted by `id`. |

Each clinic:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | `clinic-<12 hex>`, derived from **content, not position**. |
| `longitude` / `latitude` | **string** | The source's exact decimal text. |
| `name` / `address` | string \| null | Null when no recognised key matched. |
| `properties` | object | The source properties, carried through verbatim. |

### The schema below `properties` is unverified

`docs/DATA-SOURCES.md` records that no endpoint has been executed. So the
fetcher validates **geometry**, which is schema-independent, and maps `name` and
`address` only from keys it recognises. An unrecognised key leaves the field
`null`, counted in `clinics_without_mapped_name`, with the value still present in
`properties`. Inventing a clinic name from an unconfirmed schema is the same
class of mistake as inventing a deadline.

### Two refusals, not warnings

- **Coordinates outside Singapore** (longitude 103.55–104.15, latitude
  1.10–1.52) are refused. GeoJSON is `[longitude, latitude]`; reversed, every
  clinic lands in the Indian Ocean and haversine returns a confident distance to
  it.
- **An empty `features` list** is refused. A snapshot with no clinics makes every
  later run say "there are no clinics near you" — a wrong answer dressed as a
  fact. `features` is required even though `[]` is legal JSON.

Coordinates are strings for the same reason money is `Decimal`: nothing
downstream should inherit binary floating-point error it did not ask for.
`clinic_finder.py` converts to float at the trig and nowhere else.

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
