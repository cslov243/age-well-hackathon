

## `expense_split.py` — dividing a care cost

**Use when** siblings settle up, a bill needs apportioning, or a family artifact
reports who owes what.

**Requires:** `members`, `expenses`, `split_rule` — one of `even`, `weighted`
(weights sum to 1) or `ratio` (normalised for you).

**Source of truth:** `household/profile.json` for the roster. A `paid_by` that
matches no member raises, rather than letting money vanish from the totals.

Shares sum exactly to the total. The stray cent goes one each, largest applied
weight first, ties by member id — quote `residual_rule` so nobody reverse-engineers
who absorbed it. Money is `Decimal`: pass amounts as **strings** (`"123.70"`),
never floats.
