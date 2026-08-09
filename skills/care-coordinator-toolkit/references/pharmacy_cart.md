

## `pharmacy_cart.py` — a cart draft a person pays for

**Use when** a forecast says something runs out.

**Requires:** `forecast` — a `medication_runout.py` result passed **verbatim**;
its `audit_hash` is recomputed and a mismatch refused — plus `cover_days` and
`purchase` (even when `{}`).

**Never recompute the forecast** — copy its dates and rates. **Never check
out**, and never offer to: `requires_human_checkout` is always true.

`purchase[id].supply_channel` is `general_sale`, `pharmacist_only` or
`prescription_only`. **An id you leave out is unknown, and unknown is excluded** —
never called buyable. Prescription items go to the refill path.

**No invented price.** A price needs a `currency` and `source`. One unpriced
line suppresses the whole `total` — report none rather than a partial one.

### Worked example

<!-- worked-example: pharmacy_cart.py -->
```json
{
  "cover_days": 30,
  "forecast": {
    "medications": [
      {
        "id": "metformin-500",
        "name": "Metformin 500mg",
        "days_left": 7,
        "order_by_date": "2026-08-09",
        "runs_out_on": "2026-08-16"
      },
      {
        "id": "vitamin-d-1000",
        "name": "Vitamin D 1000IU",
        "days_left": 12,
        "order_by_date": "2026-08-14",
        "runs_out_on": "2026-08-21"
      }
    ],
    "audit_hash": "f4a9c2e1b8d3a0..."
  },
  "purchase": {
    "metformin-500": {
      "supply_channel": "prescription_only",
      "pack_size": 90
    }
  }
}
```

produces, in `forecast[0].summary`:

<!-- worked-example-output: medication_runout.py -->
```text
Metformin 500mg — prescription_only, refill needed by 9 Aug 2026, covering 30 days. requires_human_checkout: true.

Vitamin D 1000IU — excluded, reason: supply_channel_unknown. Ask the caregiver to record where this is purchased before it can be added to a cart.
```
