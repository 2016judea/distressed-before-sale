# Data model: Distressed Before It Sells

Written from the need alone (BUSINESS.md rule 5) on 2026-10-18, before the data was opened.
Then checked against reality, field by field, below.

**The need.** An investor who buys Minneapolis houses before they list wants the parcels that
are piling up nuisance and code-enforcement cases while the owner lives somewhere else, ranked
so the top of the list is the owner most likely to take an offer this month. The step taken
over: finding the off-market deal, which today is driving blocks, reading city case portals one
address at a time, and buying skip-trace lists.

## Ideal model

**Parcel** (one per Minneapolis tax parcel with at least one case in the last 12 months)

| field | answers |
|---|---|
| address, lat/lon, neighborhood | where it is; is it on my block |
| property type, year built, finished sq ft, units | is it the kind of house I buy |
| assessor value (land + building), tax | what the county thinks it is worth; the ceiling on an offer |
| last sale date and price | how long the owner has held it; what they paid |
| **case count, last 12 months** | how much trouble the house is in now |
| **case count, last 3 months** | is it getting worse |
| case groups (nuisance, housing, vacant building, fire, zoning) | what kind of trouble |
| most recent case date and type | how fresh |
| open vs closed cases | is the city still on them |
| vacant-building registration (yes/no, date) | is it empty, the strongest sell signal |
| **owner type**: out-of-state, in-state absentee, local non-homestead, homestead | does the owner live there; are they far away |
| taxpayer name | who to write to |
| taxpayer mailing address (public assessor record) | where to send the letter |
| rank score | the order to work the list |

**Case** (one per city case, joins to parcel on PIN)

| field | answers |
|---|---|
| case number, group, type | what the city opened |
| opened / completed date | when |
| last inspection result | resolved or still failing |

**Sale** (one per recorded sale, joins to parcel)

| field | answers |
|---|---|
| date, price | holding period and basis |
| buyer (from the next assessor snapshot's owner) | who bought the last distressed one on this block (the own-record opener for distribution) |

**Monthly pulse** (one per month, for the free slice)

| field | answers |
|---|---|
| new cases this month, by group | is the pipe flowing |
| parcels crossing 3+ cases this month | how many new candidates |
| new vacant-building registrations this month | the hard-core of the list |
| distressed parcels that sold this month, median price | proof that these houses trade |

## Reality, field by field (checked 2026-10-18, `~/Desktop/bricks/data/closed_system.duckdb`)

| field | source | filled? |
|---|---|---|
| address, lat/lon, PIN | `mpls_caseviolations` attrs (Display, Latitude, Longitude, APN), joined to `parcel` | yes |
| neighborhood | not in the case feed; `parcel`/`parcel_snapshot` carry no neighborhood | **no**: zip shown instead |
| property type, year built, sq ft, units | `parcel_snapshot` (Hennepin, Minneapolis only) `useclass1`, `year_built`, `fin_sq_ft`, `num_units` | yes |
| assessor value, tax | `parcel_snapshot.emv_total`, `total_tax`, latest `mkt_year` | yes |
| last sale date and price | `sale` + `parcel_snapshot.sale_date/sale_value` | yes; Hennepin `sale_date_grain='day'` rows are really month grain |
| case counts, groups, dates | `mpls_caseviolations`: `Start_Date` is null on 372,043 of 375,264 rows, so **`Completed_Date` is the event**; `Case_Group` carries nuisance/housing/vacant etc. | yes, with the event redefined as the inspection's completion |
| open vs closed | `Inspection_Result` is per inspection, not a case status; the feed has no case-closed field | **partial**: "last inspection result" shown; "open" is not knowable |
| vacant-building registration | `Case_Group` VBR-type cases in the same feed | yes, as a case group, not a register (the `mpls_vacant_boarded` layer stops in 2013) |
| owner type | `taxpayer_mail_hennepin` attrs (`HMSTD_CD1`, mailing lines) vs the parcel's own city/state | yes: homestead code + mailing state/city gives four classes |
| taxpayer name and mailing address | `taxpayer_mail_hennepin` TAXPAYER_NM..NM_3, public assessor record | yes |
| buyer of a sold distressed parcel | `parcel_snapshot.owner_name` in the vintage after the sale | yes for parcels with a later snapshot; the name, never an email |
| monthly pulse | computed from the above | yes |

Verdict: build. Two fields fall short. Neighborhood is replaced by zip (a cosmetic loss). "Case
still open" cannot be read from the city feed, so the list ranks on recency and count instead of
open status; the page says "last inspection result", never "open". Neither changes what the
investor does with the list.

## Reality, revised 2026-10-19 (after building)

- **Neighborhood: filled.** `parcel_snapshot.attrs->>'NEIGHBORHOOD'` carries it for Minneapolis; the "zip instead" note above is superseded.
- **Open vs closed: filled.** The city's inspection feed (CaseInspections) carries a case status (Enforce, Pending, Stop Work = open), so "still open" is the city's own word, not inferred.
- **Owner type, tightened.** No homestead is not enough: 238 of 1,078 first-build rows mailed the tax bill to the house itself, so the owner may live there. Those are left out (house number + street match); the list is 839 houses on 2026-10-19.
- **Still unfilled: the buyer of a sold distressed house** as a named contact. The next snapshot's owner name is there; an email is not, which is why distribution needs a separate email hunt.
