# Distressed Before It Sells

**Live:** https://distressed-before-sale.vercel.app

Minneapolis houses piling up nuisance, housing and code-enforcement cases while the owner lives
somewhere else, ranked for the investors who buy them before they list. The step taken over:
finding the off-market deal, which today is driving blocks, reading the city's case portal one
address at a time, and buying skip-trace lists.

The join: the City of Minneapolis code-enforcement case feed (open data, live) to Hennepin
County's parcel, taxpayer and sale records. A house is on the list when it is a one-to-three-unit
house, not homesteaded, with two or more nuisance / housing-complaint / code-enforcement /
vacant-building cases in the last 12 months, or any vacant-building registration or
condemnation. Rental-licence and fire inspections are left out as routine.

## Free and paid

| | what | why |
|---|---|---|
| free | the last 30 days in numbers (new cases by kind, new vacant registrations, houses that joined the list, how many of these houses sold in 12 months and at what median), every house as a dot on the map, and the top 5 with block-level address, case count, owner type, assessor value | proves the pipe is flowing and the ranking is real before anyone pays |
| **$500** | all rows with the exact address, taxpayer name and mailing address (the county's public record), every case with status, milestone and the inspector's violation text, the last recorded sale, the spreadsheet, and a fresh list every week | the part they act on is *which* door and *where to send the letter* |

## Price

$500 once. **A hypothesis**, set 2026-10-19 by the rule (about a tenth of what one use is worth):
one use is one off-market deal found. What one handed-over off-market deal is worth to an
investor is what a wholesaler charges for exactly that, the assignment fee: $2,000 to $7,000
commonly in Minnesota (Hammer Group, Aug 2026) and $8,000 to $18,000 in Minneapolis (Deal Run,
Mar 2026). Call one deal $5,000, the top of the statewide range and the bottom of the
Minneapolis one. A tenth is $500. Revise on checkout-vs-payment evidence; msp-house-index at
$100 drew 10 checkouts and 0 payments, so the price is the thing under test.

## The paywall

Ported from `~/Desktop/mpls-new-rentals` (`product-paywall` skill). `site/` ships only the free
slice; `scripts/publish.py` writes the full list to `private/bundle/full.json.gz` (gitignored) and
`scripts/deploy.py` uploads it as `api/_full/`, which only `/api/data` reads. The webhook is
registered with the shared router (`~/Desktop/stripe-router`), never a per-product endpoint.

| route | does |
|---|---|
| `POST /api/checkout` | Stripe embedded Checkout, $500, mints the password into session metadata + invoice |
| `POST /api/stripe-webhook` | emails the buyer the password (Mailgun), once |
| `GET /api/session-status` | the return page's check; sends the password if the webhook has not |
| `GET /api/data` | password in `x-password`: HMAC check, then a paid session in Stripe |
| `/for/<token>/` | the same page opened on one recipient's own record (`site/f/<token>.json`) |

Comp password: `python3 scripts/issue_password.py "comp:<label>"`. A lost password:
`python3 scripts/fulfil.py <session_id>`. Vercel env: `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `ACCESS_SECRET`, `MAILGUN_*`, `SITE_URL`.

## Run it

    python3 pipeline/pull.py                      # the city feed since 2025-09-01 (~50k rows, ~1 min) -> cache/
    ~/Desktop/bricks/.venv/bin/python pipeline/build.py   # join + rank -> private/rows.json (reads bricks closed_system.duckdb read-only)
    cd scripts && python3 publish.py && VERCEL_TOKEN=... python3 deploy.py
    python3 -m pytest tests -q | tee tests/last_run.txt   # 19 tests

Weekly refresh is the same four commands. `DATA_MODEL.md` has the ideal model and what could not
be filled. `outreach/` (gitignored) holds the round-1 ledger and drafts.

## Distribution

Round 1: 50+ named recipients in three segments (flippers already in the outreach ledger,
company buyers with a Minneapolis holding on a listed block, and we-buy-houses operators with a
published email), each with a `/for/<token>/` page that opens on their own record. One A/B
variable, shared with the six sibling products so results pool: **A** states the price in the
email, **B** leaves the price to the page. Hypothesis: stating the price in the email lowers
clicks but raises paid-per-click. Readout at day 3 by variant, product and pooled: `/for/`
visits, `checkout_open`, `paid`, replies (Vercel events carry `variant`; it never appears in the URL).

Sources, all public: City of Minneapolis CaseViolations and CaseInspections (ArcGIS open data),
Hennepin County parcels and taxpayer records (MetroGIS), recorded sales. Minneapolis only.

Private repo: the paid rows have been in `private/` only, never in git.
