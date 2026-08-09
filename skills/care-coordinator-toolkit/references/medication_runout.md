## `medication_runout.py` — days of supply left

**Use when** a refill, a collection date, a pharmacy trip or "how much is left"
comes up, and on every scheduled medication check.

**Requires, no defaults:**

- `medications` — required even when `[]`. A misspelled key would otherwise exit
  0 having silently forecast nothing.
- `default_lead_time_days`.
- `count_basis` on every medication — whether the count day's doses were already
  taken. A bare tablet count cannot say this, and getting it wrong shifts every
  date by a day. **Ask the caregiver rather than assuming.**

**Source of truth:** `household/medication.json`. Counts come from a person
looking at the box, never from a previous forecast.

**Never** forecast an as-needed (`prn`) medicine — they appear in `not_forecast`
with a quantity and no dates. That would be a clinical judgement wearing
arithmetic clothing.

Supply is floored, never rounded up. Quote the script's `summary` sentence with
any run-out date: "7 days left" is ambiguous about whether today counts, and the
summary says which convention was used.

### Worked example

<!-- worked-example: medication_runout.py -->
```json
{
  "as_of": "2026-08-03",
  "default_lead_time_days": 7,
  "medications": [
    {
      "id": "metformin-500",
      "name": "Metformin 500mg",
      "form": "tablet",
      "quantity_on_hand": "15",
      "count_basis": "doses_on_count_day_pending",
      "schedule": {
        "mode": "fixed_daily",
        "units_per_dose": "1",
        "doses_per_day": 2
      }
    }
  ]
}
```

produces, in `forecast[0].summary`:

<!-- worked-example-output: medication_runout.py -->
```text
Metformin 500mg: 15 tablets counted on 3 Aug 2026, on the basis that that day's doses had not yet been taken. At 2 tablets a day, that is 7 days of doses in full: the last full day is 9 Aug 2026, and 10 Aug 2026 is the first day not covered. 1 tablet left over beyond the last full day. Order by 3 Aug 2026, allowing 7 days lead time.
```

Seven days, not eight. Quote the sentence, not a rounded retelling.
