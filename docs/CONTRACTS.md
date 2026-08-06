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

### How one is produced — `scripts/letter_record.py`

Added 6 August 2026. The table above is unchanged; this says who fills it in.

```
python3 scripts/letter_record.py --input <input.json> --records <extracted/>
```

`--records` is the `extracted/` directory: read in both modes, written in one.

| Input field | Notes |
|---|---|
| `mode` | required, no default: `check` \| `record` |
| `source_files` | required, non-empty, **in page order** — the identity is the bytes |
| `doc_type`, `fields`, `evidence` | required in `record`, **refused** in `check` |

`check` runs **before** the vision model and answers `should_extract`. `record`
runs after it. A `content_hash` already present in `--records` is a no-op:
nothing is written and the existing record stands.

Every key of `fields` is required even when the value is `null` —
`issuer`, `issue_date`, `deadline`, `amounts`, `required_action`. `evidence`
is keyed by field path, with amounts at `amounts[0]`, `amounts[1]`, …

**The gate keeps a value only when its snippet exists, is not blank, and
contains the value itself** — a date by day, month and year; an amount by
numeric equality after grouping separators are stripped; an issuer by every
meaningful word of its name. Anything else is nulled, listed in
`missing_evidence` with a reason in `evidence_problems`, and flagged
`REQUIRES_HUMAN_CONFIRMATION`. One unquotable amount nulls the whole `amounts`
list: a list with the bad entry dropped reads as a complete set of figures.

A record where nothing at all could be quoted is flagged too, reason
`nothing_evidenced`. That is what an unreadable scan looks like, and it must
not pass as a letter that happened to say nothing.

**What the check cannot do.** There is no document text here to diff a snippet
against, only an image the model already looked at. It catches a value quoted
against text stating a different value; it does not catch a snippet invented
whole, and nothing available offline would.

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

**Strengthened 6 August 2026** — audit finding #14. The third bullet below is
new; the field table above is unchanged, and no output key was added or
removed. What changed is which inputs survive the gate, so a claim whose
snippets never contained their values now flags where it previously passed.

- Value present **with** a usable snippet that **contains it** → used.
- Value present with **no** snippet, an all-whitespace one, **or one that does
  not contain the value** → nulled, listed in `missing_evidence`, claim flagged
  `REQUIRES_HUMAN_CONFIRMATION`.
- Value **absent** → null, no flag. "Not found in the document" is honest.

Containment is the same test `LetterRecord` applies, from the same module —
`scripts/_evidence.py`. A date by day, month and year; an amount by numeric
equality after grouping separators are stripped; a window in days by the number
itself; an issuer by every meaningful word of its name. One rule, one
implementation, because two implementations were two answers that disagreed:
a balance computed by subtraction and quoted against *"The balance is payable
by the policyholder"* was refused by `letter_record.py` and accepted here, in
the same run.

The same limit applies as it does to `LetterRecord`: this catches a value
quoted against text stating a different value. It does not catch a snippet
invented whole, and nothing available offline would.

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
| `supply_channel` | enum \| absent | `general_sale` \| `pharmacist_only` \| `prescription_only`. Added 5 August 2026 — see below. |
| `purchase` | object \| absent | Optional pack size and price. Added 5 August 2026 — see below. |

### `supply_channel` — added for `pharmacy_cart.py`, additive

**Absent is not a default, it is `unknown`.** `medication_runout.py` neither
reads nor echoes this field, so its output and its audit hash are unchanged and
no existing consumer moves. The only consumer is `pharmacy_cart.py`, which
excludes anything whose channel it was not told, and never assumes general sale.

That asymmetry is the whole point. Getting `general_sale` wrong puts a
prescription medicine in a shopping cart; getting `unknown` wrong costs one
question to the caregiver. The two mistakes are not the same size, so the
default goes to the cheap one.

### `purchase` — added for `purchase_terms.py`, additive

Optional, one per medication. `medication_runout.py` neither reads nor hashes
it, so the forecast and its `audit_hash` are unchanged and no existing consumer
moves — the same additive shape `supply_channel` took.

| Field | Type | Notes |
|-------|------|-------|
| `pack_size` | int ≥ 1 \| absent | Units per pack. |
| `pack_price` | Decimal string \| absent | Requires `pack_size`. |
| `unit_price` | Decimal string \| absent | Mutually exclusive with `pack_price`. |
| `currency` | string | **Required with a price.** |
| `source` | string | **Required with a price.** Where the figure came from. |

An unrecognised key inside the block is **refused**, unlike an unrecognised key
at the top of the file. The asymmetry is deliberate: the top level is shared
with `medication_runout.py` and must tolerate fields it gains, while a typo
inside `purchase` silently drops a price and the cart then suppresses its total
for a reason nobody can trace back to a misspelling.

A `purchase` block recorded against a medication with no `supply_channel` is
refused. Without a channel it can never enter a cart, so the price would be
accepted and never used — and the caregiver who typed it would never learn it
did nothing.


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
| `record_count` | int ≥ 1 | Clinics kept. Never 0 — see below. |
| `features_in_source` | int | What arrived, before rejects. |
| `rejected_count` | int ≥ 0 | Dropped bad rows. |
| `rejected` | list[{where, reason}] | Why each was dropped. Never silent. |
| `clinics_without_mapped_name` | int ≥ 0 | How many names could not be mapped. |
| `content_hash` | sha256 | Over `clinics` only. |
| `clinics` | list[object] | Sorted by `id`. |

Each clinic:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | `clinic-<12 hex>`, derived from **content, not position**. |
| `longitude` / `latitude` | **string** | The source's exact decimal text. |
| `name` | string \| null | From `HCI_NAME`. Null if only a placeholder was found. |
| `address` | string \| null | Composed from labelled parts; null if none. |
| `postal_code` / `phone` | string \| null | From `POSTAL_CD` / `HCI_TEL`. |
| `programmes` | list[string] | From `CLINIC_PROGRAMME_CODE`. A dataset fact. |
| `attributes` | object | The `Description` table, unwrapped. Values verbatim. |
| `properties` | object | Any source properties not in that table. |

### `Name` in this dataset is not a name

Verified 4 August 2026. GeoJSON `properties` carries only `{Name, Description}`.
`Name` is a **KML export artifact** — `kml_367` — and every real field lives in
an HTML attribute table inside `Description`.

The first version accepted `Name`, reported `clinics_without_mapped_name: 0` for
all 1,192 clinics, and would have told a senior to walk to "kml_367". A guard
that reports success while the answer is wrong is worse than no guard. Values
matching `kml_<n>` are now refused as names, and the field goes null rather than
plausible.

`attributes` holds the unwrapped table with values carried verbatim — nothing is
renamed or interpreted. `address` is **composed mechanically** from
`BLK_HSE_NO`, `STREET_NAME`, `BUILDING_NAME`, `FLOOR_NO`/`UNIT_NO` and
`POSTAL_CD`; every component survives in `attributes`, so the composition is
never the only copy of anything.

`programmes` is a fact about the dataset and **says nothing about eligibility**.
The three-string vocabulary does not apply to it.

### Reading it — `clinic_finder.py`

The only consumer. It recomputes `content_hash` over `clinics` and **refuses a
snapshot that does not match**: a hand-edited one is the single failure the
fetcher's guarantees do not survive, and it would produce a confident distance
to a coordinate nobody checked.

Distance is haversine on a sphere of radius 6371008.8 m — the mean radius of the
WGS 84 ellipsoid — **rounded to the nearest 10 m**. Ranking runs on the
unrounded value and ties by clinic id, so the display rounding can never reorder
the list. Coordinates stay decimal strings until the trigonometry.

It is a **straight line, not a walking distance**. No route is computed, nothing
is said about stairs or step-free access, and every record repeats that in its
`summary` so a record quoted on its own keeps the caveat.

A snapshot more than 30 days older than `as_of` is flagged `stale` and still
used. One dated *after* `as_of` is refused — one of the two dates is wrong and
the script cannot tell which.

### Nothing credential-shaped is ever written

The data.gov.sg download URL is presigned and carries `AWSAccessKeyId`, a
`Signature` and an `x-amz-security-token`. `source_url` is stripped to scheme,
host and path, and `write_snapshot` refuses outright if the snapshot still
matches a credential shape. No secrets in the plugin payload is a hard
constraint, and this directory ships inside it.

### A bad row and a misread file are different problems

Confirmed against the live extract on 4 August 2026: it contains a point 16 km
south of Singapore's southernmost island. Refusing the whole file for that meant
one upstream geocoding error blocked the connector permanently.

| Case | Behaviour |
|---|---|
| A point outside Singapore (longitude 103.55–104.15, latitude 1.10–1.52) | **Row dropped**, reason recorded in `rejected`, count in the manifest |
| A point valid **only** if longitude and latitude are exchanged | **Whole file refused.** One is enough — a correctly ordered file contains no row that only makes sense reversed, so the plausible-looking rows are no more trustworthy |
| More than 2% of features rejected | **Whole file refused.** Not a dirty dataset; a parsing mistake wearing one's clothes |
| An empty `features` list | **Refused.** "There are no clinics near you" is a wrong answer dressed as a fact. `features` is required even though `[]` is legal JSON |

A dropped row is never silent: it appears in `rejected` with its index and
reason, and `record_count` plus `rejected_count` must add up to
`features_in_source`.

Coordinates are strings for the same reason money is `Decimal`: nothing
downstream should inherit binary floating-point error it did not ask for.
`clinic_finder.py` converts to float at the trig and nowhere else.

---

## PurchaseTermsMap

Written by `scripts/purchase_terms.py`. Added 5 August 2026. Input is a
`MedicationRecord` document — the same `household/medication.json` the forecaster
reads, unchanged.

| Field | Type | Notes |
|-------|------|-------|
| `purchase` | object | Keyed by medication id. Feeds `pharmacy_cart.py` verbatim. |
| `omitted[]` | list | `{id, name, reason, summary}`. Reason is always `no_supply_channel_recorded`. |
| `counts` | object | `with_terms + omitted == medications`. |

Each row carries `supply_channel` and, only where recorded, `form_plural`,
`pack_size` and a price. Nothing is defaulted and nothing is computed — there is
no arithmetic in the script at all, because quantities and totals are
`pharmacy_cart.py`'s work and a second copy would be a second answer.

### Why this is a script

`pharmacy_cart.py` refuses to guess a supply channel, but something has to hand
it the map. If that something is a model transcribing a field by hand, the guard
is worth exactly what the transcription is worth: a hallucinated `general_sale`
puts a prescription medicine in a cart, and nothing downstream can notice,
because the cart cannot tell a copied value from an invented one.

A medicine with no `supply_channel` is **left out of the map**, never given one.
An unrecognised channel raises rather than being mapped to the nearest legal
value — `otc` is not `general_sale`.

---

## PharmacyCartDraft

Written by `scripts/pharmacy_cart.py`. Added 5 August 2026. **Additive** — its
only input beyond `MedicationRecord.supply_channel` is supplied per run.

Input: a `medication_runout.py` result passed **verbatim** as `forecast`, plus
`cover_days`, a `purchase` map keyed by medication id, and an optional
`pharmacy`. The forecast's `audit_hash` is recomputed with
`medication_runout.audit_hash_of` — the same function that wrote it, imported
rather than reimplemented — and a mismatch is refused. A forecast dated after
`as_of` is refused; one more than 7 days older is flagged `stale` and still used.

| Field | Type | Notes |
|-------|------|-------|
| `requires_human_checkout` | `true` | A constant. No input can make it false. |
| `cover_days` | int ≥ 1 | **Required, no default.** How much to buy is not this script's call. |
| `cart.items[]` | list | Only `general_sale` medicines that the forecast says are due. |
| `cart.currency` | string \| null | One currency per cart. Two are refused, never summed. |
| `cart.total` | Decimal string \| null | **Null unless every line is priced.** |
| `cart.total_suppressed_because` | string \| null | Which ids lack a price, in words. |
| `excluded[]` | list | `{id, name, reason, route, summary}`. |
| `counts` | object | `cart_items + excluded == medications_in_forecast`. |

Each item carries `units_needed` (`cover_days` × the forecast's daily rate,
**rounded up** — the opposite of the forecast's floor, because half a tablet
cannot be bought), `pack_size`, `packs`, `units_ordered`, `price` and
`line_total`. `price` requires a `currency` **and** a `source`: this script looks
nothing up, so an unsourced price is one somebody remembered.

Exclusion reasons, in the order the summary reads them:
`prescription_only`, `pharmacist_only`, `supply_channel_unknown`,
`no_forecast_quantity` (prn — no daily rate, so no quantity), `not_due_yet`.
Channel is tested before timing: saying "not due yet" about a prescription
medicine implies it will be buyable later, and it never will.

### It prepares. It does not buy.

No purchase API, no payment, no stored card, no standing authority. A
`deep_link` is a string the caller supplies and a person clicks; it is validated
(`https://` only, no userinfo, nothing credential-shaped) and copied, never
opened. `docs/DECISIONS.md` records why the purchase itself is never built.

---

## DeadlineCalendar

Written by `scripts/deadline_calendar.py`. Added 6 August 2026. **Additive** —
it introduces no field on any existing record; every date it emits was already
computed by `medication_runout.py` or `insurance_claim_review.py`.

Input: `forecast` and `claims`, each a whole result passed **verbatim** or an
explicit `null`. **Both keys are required even when null**, because an absent
key and a misspelled one are indistinguishable inside the script and one of them
means a set of deadlines was silently scheduled into nothing. Each `audit_hash`
is recomputed with the function that wrote it — imported, not reimplemented —
and a mismatch is refused. A source dated after `as_of` is refused.

| Field | Type | Notes |
|-------|------|-------|
| `horizon_days` | int ≥ 1 | **Required, no default.** How far ahead to look is a person's call. |
| `detail_level` | `minimal` \| `named` | **Required, no default.** A disclosure decision, not a formatting one. |
| `events[]` | list | `{uid, kind, starts_on, days_away, title, body, source_tool, source_id, source_tool_run_id, source_audit_hash, discloses}`. |
| `omitted[]` | list | `{kind, source_id, starts_on, reason, detail}`. |
| `counts` | object | `events + omitted == dates_considered`. |
| `disclosure` | object | `{required, discloses, note}`. `required` is true whenever any event names something. |

Dates are **copied**: `order_by` and `runs_out_on` from the forecast,
`deadlines[].due_on` from the claims review. The only arithmetic is
`(date - as_of).days`, and it decides one thing — whether a date falls inside
`horizon_days`. Comparing a reminder window against itself is the defect
recorded as audit finding #3, which reported a deadline 58 days away as due this
week, every day. Proximity is measured against `as_of` and nothing else.

Omission reasons: `no_date` (the source never had one to copy),
`beyond_horizon`, `already_passed`. An already-passed deadline is **not**
back-dated into the calendar — an entry in the past notifies nobody, so it is
reported in prose to a person instead.

`kind` is `medication_order_by`, `medication_runs_out`, `claim_submission` or
`claim_appeal`. `uid` is derived from the source `audit_hash`, the kind, the
source id and the date, so an unchanged re-run reproduces it and a second import
updates rather than duplicates.

### A calendar is a shared surface

At `minimal` no event names a medicine, condition, insurer or amount — the
title says something is due and the family artifact says what. `named` is a
disclosure: `disclosure.required` comes back true and a line belongs in
`out/senior/shared_log.jsonl`. The choice is never made on her behalf.

The `.ics` written to `--ics` is the deliverable and requires no integration to
work. Nothing in this script writes to a calendar; a write beyond the file is a
separate action confirmed one event at a time.

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
