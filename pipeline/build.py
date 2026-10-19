#!/usr/bin/env python3
"""Join the city's violation feed to the county's parcel, owner and sale records and rank.

    python3 pipeline/build.py        # -> private/rows.json (the ranked list + the monthly pulse + sold)

Reads cache/violations.json.gz (pipeline/pull.py) and, read-only, bricks closed_system.duckdb:
  parcel_snapshot 'minneapolis_assessor_2025'  neighborhood, building use, year built, beds, sq ft, class
  parcel_snapshot 'metrogis_current'           assessor value, tax, homestead, owner, taxpayer mailing address
  record 'taxpayer_mail_hennepin'              homestead code + mailing lines (fallback)
  record 'mpls_caseviolations'                 really the CaseInspections feed: first inspection date per case
  sale                                         recorded sales (Hennepin: month grain)

Every number on the page is computed here. See DATA_MODEL.md for what each field answers.
"""
import gzip, json, re, datetime as dt
from collections import defaultdict
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = Path.home() / "Desktop/bricks/data/closed_system.duckdb"
SRC = ROOT / "cache/violations.json.gz"
OUT = ROOT / "private/rows.json"

SIGNAL = {"Nuisance": "Nuisance", "HISINSP": "Housing complaint", "VBR": "Vacant building", "CVBR": "Vacant building",
          "PVE1": "Code enforcement", "PVE2": "Code enforcement", "PVE3": "Code enforcement", "PVE4": "Code enforcement"}
OPEN = {"Enforce", "Pending", "Stop Work", "In Process", "Hold"}
HEAVY = {"Condemnation", "Intent to Assess", "Pending Assessment", "Assessment Hearing", "Assessment Appeal",
         "Citation Tier 2 Issuance", "Citation Tier 3 Issuance", "Citation Tier 4 Issuance"}
ENTITY = re.compile(r"\b(LLC|L L C|INC|CORP|CO|COMPANY|PROPERT\w*|HOMES|HOLDINGS|INVEST\w*|CAPITAL|REALTY|ENTERPRISE\w*|GROUP|PARTNERS|VENTURES|FUND|TRUST|TR|LP|LLP|ASSOC\w*|BANK|HOUSING|DEVELOPMENT|DEVEL|DEV)\b")
RES = ("RESIDENTIAL 1 UNIT", "RESIDENTIAL 2 UNITS", "RESIDENTIAL 3 UNITS", "RESIDENTIAL 1 UNIT - TOWNHOUSE",
       "RESIDENTIAL 1 UNIT - ZERO LOT LINE", "RESIDENTIAL MISC STRUCTURE")


def ms(v):
    return dt.datetime.utcfromtimestamp(v / 1000).date() if v else None


def title(s):
    s = re.sub(r"\s+", " ", (s or "").strip()).title()
    s = re.sub(r"\b(Ne|Nw|Se|Sw|N|S|E|W|Llc|Inc|Ii|Iii|Iv|Mn|Po)\b", lambda m: m.group(0).upper(), s)
    return re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s)


def house_key(line):
    w = re.sub(r"[^A-Z0-9 ]", " ", (line or "").upper()).split()
    return (w[0], w[1]) if len(w) >= 2 and w[0].isdigit() else None


def block_of(display):
    """'2427 ILION AVE N' -> '24xx Ilion Ave N'; a 3-digit house number -> '4xx'."""
    m = re.match(r"(\d+)\s+(.*)", display or "")
    if not m:
        return title(display)
    n, street = m.groups()
    return (n[:-2] + "xx" if len(n) > 2 else "x" * len(n)) + " " + title(street)


def main():
    pulled = json.loads(gzip.decompress(SRC.read_bytes()))
    today = dt.date.fromisoformat(pulled["pulled"])
    y1, d30, d90 = today - dt.timedelta(days=365), today - dt.timedelta(days=30), today - dt.timedelta(days=90)

    # one record per case: status, milestone, dates, descriptions
    cases = {}
    for r in pulled["rows"]:
        g = (r.get("Case_Group") or "").strip()
        if g not in SIGNAL or not r.get("APN"):
            continue
        cn = r["Violation_Case_Number"]
        c = cases.setdefault(cn, {"cn": cn, "pin": r["APN"], "display": r["Display"], "lat": r["Latitude"], "lon": r["Longitude"],
                                  "group": g, "kind": SIGNAL[g], "status": None, "milestone": None, "touched": None, "resolved": None, "what": set()})
        p, res = ms(r.get("Processed_Date")), ms(r.get("Resolved_Date"))
        c["touched"] = max(c["touched"], p) if c["touched"] and p else (c["touched"] or p)
        c["resolved"] = max(c["resolved"], res) if c["resolved"] and res else (c["resolved"] or res)
        if r.get("Status_Violation_Case"):
            c["status"] = r["Status_Violation_Case"]
        if r.get("Milestone_Violation_Case"):
            c["milestone"] = r["Milestone_Violation_Case"]
        if r.get("Violation_Code_Description"):
            c["what"].add(r["Violation_Code_Description"].strip())

    con = duckdb.connect(str(DB), read_only=True)
    cns = list(cases)
    con.execute("create temp table cn as select unnest(?) cn", [cns])
    opened = dict(con.execute("""select (attrs->>'Violation_Case_Number') cn, min(coalesce(dates['Completed_Date'], dates['Scheduled_Date']))::date
        from record where layer='mpls_caseviolations' and (attrs->>'Violation_Case_Number') in (select cn from cn) group by 1""").fetchall())
    for c in cases.values():
        c["opened"] = opened.get(c["cn"]) or c["touched"]
        c["open"] = c["status"] in OPEN
        c["what"] = sorted(c["what"])[:6]

    by_pin = defaultdict(list)
    for c in cases.values():
        by_pin[c["pin"]].append(c)
    pins = list(by_pin)
    con.execute("create temp table pins as select unnest(?) pin", [pins])

    assessor = {r[0]: r for r in con.execute("""select pin, useclass1, year_built, attrs->>'NEIGHBORHOOD', attrs->>'COMMUNITY', attrs->>'BUILDINGUSE',
        (attrs->>'TOTALBEDROOMS')::int, (attrs->>'ABOVEGROUNDAREA')::int, lat, lon from parcel_snapshot
        where vintage='minneapolis_assessor_2025' and pin in (select pin from pins)""").fetchall()}
    county = {r[0]: r for r in con.execute("""select pin, emv_total, total_tax, homestead, owner_name, tax_name, attrs->>'TAX_ADD_L1', attrs->>'TAX_ADD_L2',
        attrs->>'TAX_ADD_L3', sale_date, sale_value, anumber, street, zip from parcel_snapshot
        where vintage='metrogis_current' and county='hennepin' and pin in (select pin from pins)""").fetchall()}
    taxmail = {r[0]: r for r in con.execute("""select (attrs->>'PID'), attrs->>'HMSTD_CD1', trim(attrs->>'TAXPAYER_NM'), trim(attrs->>'TAXPAYER_NM_1'),
        trim(attrs->>'TAXPAYER_NM_2'), trim(attrs->>'TAXPAYER_NM_3') from record where layer='taxpayer_mail_hennepin' and (attrs->>'PID') in (select pin from pins)""").fetchall()}
    sales = defaultdict(list)
    for pin, d, v in con.execute("""select split_part(parcel_key,':',2), sale_date, sale_value from sale
        where parcel_key like 'hennepin:%' and split_part(parcel_key,':',2) in (select pin from pins) order by sale_date""").fetchall():
        sales[pin].append([d.isoformat(), v])

    rows = []
    for pin, cs in by_pin.items():
        a, k, t = assessor.get(pin), county.get(pin), taxmail.get(pin)
        if not a or not k or a[1] not in RES:
            continue
        hs = (k[3] or "").lower().startswith("y") if k[3] else (t and t[1] == "H")
        if hs:
            continue
        live = [c for c in cs if c["touched"] and c["touched"] >= y1]
        if not live:
            continue
        n, n_open = len(live), sum(c["open"] for c in live)
        vbr = sum(c["kind"] == "Vacant building" for c in live)
        heavy = sum((c["milestone"] in HEAVY) for c in live)
        condemned = any(c["milestone"] == "Condemnation" for c in live)
        if not (n >= 2 or vbr or condemned):
            continue
        # owner and where the tax bill goes
        mail = [x for x in (k[6], k[7], k[8]) if x] or ([x for x in (t[3], t[4], t[5]) if x] if t else [])
        # No homestead filed but the bill goes to the house itself: the owner may live there, so the
        # house is not "owner lives somewhere else" (238 of 1,078 rows on 2026-10-19). Left out.
        # Matched on house number + first street word, so "Avenue"/"Ave", a unit or a missing suffix still match.
        if mail and house_key(mail[0]) and house_key(mail[0]) == house_key(cs[0]["display"]):
            continue
        last = mail[-1] if mail else ""
        m = re.search(r"\b([A-Z]{2})\s+(\d{5})", last)
        state = m.group(1) if m else ""
        mcity = re.sub(r"\s+[A-Z]{2}\s+\d{5}.*$", "", last).strip() if m else ""
        owner = title(k[5] or k[4] or (t[2] if t else ""))
        if state and state != "MN":
            otype = "Out of state"
        elif mcity and mcity != "MINNEAPOLIS":
            otype = "Minnesota, outside Minneapolis"
        else:
            otype = "Minneapolis, lives elsewhere"
        entity = bool(ENTITY.search((k[5] or k[4] or "").upper()))
        latest = max(c["touched"] for c in live)
        score = 2 * n_open + (n - n_open) + 4 * vbr + 3 * heavy + (3 if condemned else 0) \
            + (2 if latest >= d30 else 1 if latest >= d90 else 0) \
            + {"Out of state": 3, "Minnesota, outside Minneapolis": 2, "Minneapolis, lives elsewhere": 1}[otype]
        sl = sales.get(pin) or ([[k[9].isoformat(), k[10]]] if k[9] else [])
        rows.append({
            "pin": pin, "addr": title(cs[0]["display"]), "block": block_of(cs[0]["display"]), "zip": k[13],
            "hood": title(a[3]), "community": title(a[4]), "use": title(a[5] or a[1]), "built": a[2], "beds": a[6], "sqft": a[7],
            "lat": a[8] or cs[0]["lat"], "lon": a[9] or cs[0]["lon"],
            "emv": k[1], "tax": k[2], "owner": owner, "entity": entity, "otype": otype, "mail": ", ".join(title(x) for x in mail),
            "n": n, "n_open": n_open, "vbr": vbr, "heavy": heavy, "condemned": condemned, "latest": latest.isoformat(),
            "kinds": sorted({c["kind"] for c in live}, key=lambda x: ["Vacant building", "Housing complaint", "Code enforcement", "Nuisance"].index(x)),
            "lead": "Vacant building" if vbr else ("Housing complaint" if any(c["kind"] == "Housing complaint" for c in live) else
                                                   ("Code enforcement" if any(c["kind"] == "Code enforcement" for c in live) else "Nuisance")),
            "cases": sorted([{"cn": c["cn"], "kind": c["kind"], "status": c["status"], "milestone": c["milestone"],
                              "opened": c["opened"].isoformat() if c["opened"] else None, "touched": c["touched"].isoformat(), "what": c["what"]}
                             for c in live], key=lambda c: c["touched"], reverse=True),
            "sales": sl, "last_sale": sl[-1][0] if sl else None, "last_price": sl[-1][1] if sl else None,
            "score": score,
        })
    rows.sort(key=lambda r: (-r["score"], -r["n_open"], r["latest"]), reverse=False)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # the monthly pulse, over every signal case (not just the ranked parcels)
    allc = list(cases.values())
    new30 = [c for c in allc if c["opened"] and c["opened"] >= d30]
    pulse = {
        "asof": today.isoformat(), "since": d30.isoformat(),
        "new_cases_30d": len(new30),
        "new_by_kind_30d": {k: sum(c["kind"] == k for c in new30) for k in ("Nuisance", "Housing complaint", "Code enforcement", "Vacant building")},
        "new_vbr_30d": sum(c["kind"] == "Vacant building" for c in new30),
        "touched_30d": sum(1 for c in allc if c["touched"] and c["touched"] >= d30),
        "parcels_ranked": len(rows), "parcels_open": sum(r["n_open"] > 0 for r in rows),
        "parcels_new_30d": sum(1 for r in rows if any(c["opened"] and c["opened"] >= d30.isoformat() for c in r["cases"])),
        "by_otype": {o: sum(r["otype"] == o for r in rows) for o in ("Out of state", "Minnesota, outside Minneapolis", "Minneapolis, lives elsewhere")},
        "by_lead": {o: sum(r["lead"] == o for r in rows) for o in ("Vacant building", "Housing complaint", "Code enforcement", "Nuisance")},
        "entity": sum(r["entity"] for r in rows),
        "median_emv": sorted(r["emv"] for r in rows if r["emv"])[len([r for r in rows if r["emv"]]) // 2],
    }

    # sold: parcels that had 2+ signal cases in the 24 months before a recorded sale since 2024-09 (buyer = taxpayer now)
    sold = []
    cv = con.execute("""select split_part(parcel_key,':',2) pin, (attrs->>'Violation_Case_Number') cn, min(dates['Completed_Date'])::date d
        from record where layer='mpls_caseviolations' and parcel_key like 'hennepin:%' and (attrs->>'Case_Group') in ('Nuisance','HISINSP','VBR','CVBR','PVE1','PVE2','PVE3','PVE4')
        and dates['Completed_Date'] >= timestamp '2022-06-01' group by 1,2""").fetchall()
    hist = defaultdict(list)
    for pin, cn, d in cv:
        hist[pin].append(d)
    sold_rows = con.execute("""select split_part(s.parcel_key,':',2) pin, s.sale_date, s.sale_value, a.useclass1, a.attrs->>'NEIGHBORHOOD', m.tax_name, m.owner_name, m.homestead, a.anumber||' '||a.street
        from sale s join parcel_snapshot a on a.parcel_key=s.parcel_key and a.vintage='minneapolis_assessor_2025'
        join parcel_snapshot m on m.parcel_key=s.parcel_key and m.vintage='metrogis_current'
        where s.sale_date >= date '2024-09-01' and s.sale_value >= 20000 and s.parcel_key like 'hennepin:%'""").fetchall()
    for pin, d, v, use, hood, tax, own, hs, addr in sold_rows:
        if use not in RES:
            continue
        pre = [x for x in hist.get(pin, []) if d - dt.timedelta(days=730) <= x <= d + dt.timedelta(days=31)]
        if len(pre) < 2:
            continue
        sold.append({"pin": pin, "addr": title(addr), "hood": title(hood), "sold": d.isoformat(), "price": v, "cases_before": len(pre),
                     "buyer": title(tax or own), "entity": bool(ENTITY.search((tax or own or "").upper())), "homestead_now": (hs or "").lower().startswith("y")})
    sold.sort(key=lambda s: s["sold"], reverse=True)
    pulse["sold_24mo"] = len(sold)
    pulse["sold_median"] = sorted(s["price"] for s in sold)[len(sold) // 2] if sold else None
    pulse["sold_12mo"] = sum(1 for s in sold if s["sold"] >= y1.isoformat())

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"pulled": pulled["pulled"], "rows": rows, "pulse": pulse, "sold": sold}, default=str))
    print(json.dumps(pulse, indent=1))
    print(f"{len(rows)} ranked parcels, {len(sold)} sold-after-distress parcels -> {OUT}")
    for r in rows[:5]:
        print(r["rank"], r["score"], r["block"], r["hood"], r["otype"], r["n"], r["n_open"], r["lead"], r["emv"], r["owner"])


if __name__ == "__main__":
    main()
