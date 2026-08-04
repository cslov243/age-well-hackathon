# External data sources

## Policy: snapshot at build time, never call at runtime

**No script in this project makes a network call.** Datasets are fetched
offline, written into `references/` with the fetch date, and read from disk by
scripts that have no networking code at all.

Three reasons, in order of importance:

1. WorkBuddy security-scans plugins on install for risky behaviour. A Python
   script issuing outbound HTTP is exactly the shape that scanner looks for.
   Do not gamble the submission on a scanner's judgment.
2. The demo cannot depend on an API being up, a rate limit not firing, or the
   venue's network working.
3. It makes the provenance line literally true. `criteria as of 2026-08-03 —
   verify at <URL>` is honest about a dated snapshot in a way that a live query
   never is.

Say this on stage as a design choice, not an apology: *we snapshot government
data with a date rather than querying live, because a caregiving tool should
never tell you something it can't show you the source of.*

Fetching happens in a separate `tools/fetch_references.py`, run by a human,
never invoked by a skill.

---

## Verification status

**None of the endpoints below have been executed.** They were gathered from
documentation and secondary sources on 3 August 2026. Dataset IDs and parameter
names are leads to verify, not confirmed working calls. Verify each one before
building on it, and record the result here.

---

## OneMap (Singapore Land Authority)

The national map. Free, no cloud billing account, no per-query cost. More
accurate for Singapore addresses than commercial alternatives.

### Barrier-Free Access (BFA) routing — highest value here

BFA provides wheelchair-friendly routes, built for wheelchair users, people with
strollers, and **seniors**, routing via ramps, lifts and covered walkways. It
began as 1,000 km of accessible paths across nine areas including Bukit Merah,
Ang Mo Kio and Orchard, and has expanded by a further 5,000 km island-wide.

This is what makes `HouseholdProfile.senior.mobility_aids` load-bearing rather
than decorative. The senior-facing artifact should read:

> Thursday, 9:40am — Toa Payoh Polyclinic.
> Step-free route: covered walkway, lift at the overhead bridge. 14 minutes.
> Bring your blue CHAS card.

not "you have an appointment."

Routing supports `routeType` of `walk`, `drive`, `cycle`, or `pt` (public
transport). `pt` unlocks `maxWalkDistance` and `mode` (TRANSIT / BUS / RAIL).

**Routing requires a registered API token.** Some endpoints, such as geocoding
search, historically did not. Register early — this account is independent of
WorkBuddy and survives any access lapse.

**Runtime exception:** routing is the one thing that genuinely varies per
request, since the start point changes. For the 9 August submission,
**precompute** routes for the demo household's actual block and cache them into
`references/`. Do not add a live call to a skill.

### Other OneMap surfaces worth checking

- Geocoding / address search — postal code or building name → lat/long.
- Reverse geocoding — WGS84 or SVY21.
- Themes: 100+ thematic layers covering locations and amenities. Platform data
  layers have long included **eldercare services**. Worth an hour of browsing
  for anything care-adjacent.
- Nearby transport — MRT/LRT stations and bus stops near a point.
- Static map images, useful for the large-print senior card.

---

## data.gov.sg

All APIs are public and usable without a key for testing; a free key is
recommended for production and raises rate limits. Rate limiting has been
progressively enforced from late 2025 — register a key.

### CHAS Clinics (MOH) — snapshot this

```
dataset_id: d_548c33ea2d99e29ec63a7cc9edcccedc
poll-download: https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download
```

The poll-download endpoint returns `{code, data:{url}, errMsg}`; fetch
`data.url` for the actual GeoJSON. `code != 0` means failure — check it.

Format is GeoJSON FeatureCollection, CRS84. **Free forever for personal or
commercial use under the Open Data Licence.** Attribution: Ministry of Health,
CHAS Clinics, data.gov.sg.

Enables scheme-radar to say "there are three CHAS clinics within 600m of your
block, here they are" — concrete, verifiable, and asserting nothing about
eligibility.

### Health Facilities — primary care, dental clinics, pharmacies (MOH)

```
dataset_id: d_e4663ad3f088a46dabd3972dc166402d
https://data.gov.sg/api/action/datastore_search?resource_id={dataset_id}
```

### Real-time weather (NEA via data.gov.sg)

data.gov.sg exposes specific real-time APIs for weather and traffic. Small win,
maybe twenty lines: heat and rain genuinely matter for an elderly person walking
to a 9:40am appointment. Include it in the daily brief only if it changes
advice — do not add noise.

### Other datasets to scan

- Clinics onboard the Health Appointment System (OGP),
  `d_3cd840069e95b6a521aa5301a084b25a`
- Health Facilities and Beds in Inpatient Facilities (collection 521)
- Public holidays — affects deadline arithmetic and clinic opening

---

## What does not exist, and must not be attempted

- **No submission API for HealthHub or CHAS.** There is no way to file on
  someone's behalf. This is not a gap to work around; it is why the product
  prepares and hands off.
- **No Singpass automation.** Ever. National digital identity, MFA, and
  credential handling aimed at vulnerable users is precisely the scam pattern
  the product exists to protect against. Anything requiring Singpass login is
  out of scope by design, not by limitation.
- Do not scrape any government portal that requires authentication.

---

## Why not more autonomy

The absence of live tool-calling magic is the thesis, not a shortfall. The agent
prepares and hands off; the human is the actuator; the arithmetic cannot
hallucinate. Adding autonomy weakens all three claims.

What these data sources add is **specificity in the senior-facing artifact** —
which is where the product actually lives — not agent independence. Judge every
proposed integration against that: does it make what she reads more concrete, or
does it just make the agent do more without her?
