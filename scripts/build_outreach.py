#!/usr/bin/env python3
"""Round-1 distribution: ledger, drafts and /for/<token>/ pages. DRAFTS ONLY, nothing is sent.

Inputs (outreach/round1/, gitignored): seg*_source.json, one recipient per row with org, name, email,
email_source, email_source_date, record_quoted (their own public record, quoted on line one),
hold_names (how the county spells their entities) and optionally anchor_addrs (Minneapolis addresses
from their own record). Their own row on our list is the listed house nearest one of their own
Minneapolis addresses (their record, or a parcel the county shows them owning), within 1.0 km.
No Minneapolis address, or none near a listed house -> status=hold, never sent the example.

Writes outreach/round1/ledger.csv + drafts/<token>.txt, and site/public/f/<token>.json (block-level,
no email, no owner, no PIN: the same fields the free slice already shows).
Deduped against ~/Desktop/outreach-ledger/outreach.duckdb `contacted` (a prior send = touch 2).
"""
import csv, datetime as dt, hashlib, json, math, re, sys
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent.parent
R1 = ROOT / "outreach" / "round1"
FDIR = ROOT / "site" / "public" / "f"
SITE = json.loads((ROOT / "site/offer.json").read_text())["site"]
PRICE = json.loads((ROOT / "site/offer.json").read_text())["price_usd"]
DB = Path.home() / "Desktop/bricks/data/closed_system.duckdb"
LEDGER_DB = Path.home() / "Desktop/outreach-ledger/outreach.duckdb"
SUBSTACK = "https://randomaidan.substack.com/p/business-prototypes"
TODAY = dt.date.today().isoformat()
MAX_KM = 1.0
COLS = ["token", "variant", "segment", "company", "name", "email", "email_source", "email_source_date", "own_record",
        "own_row_block", "own_row_rank", "own_row_km", "anchor", "touch", "status", "hold_reason", "drafted_on", "sent_on",
        "reply_kind", "reply_on", "page_url"]

D = json.load(open(ROOT / "private" / "rows.json"))
ROWS, P = D["rows"], D["pulse"]


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def anchors_for(con, rec):
    """Their own Minneapolis addresses with lat/lon: from their record, then parcels the county shows them owning."""
    out = []
    for a in rec.get("anchor_addrs", []):
        m = re.match(r"(\d+)\s+(.+)", a.strip())
        if not m:
            continue
        num, street = m.group(1), m.group(2).upper()
        first = street.split()[0]
        r = con.execute("""select anumber||' '||street, lat, lon, pin from parcel_snapshot where vintage='metrogis_current'
            and city='MINNEAPOLIS' and anumber=? and street like ? and lat is not null limit 1""", [num, first + "%"]).fetchone()
        if r:
            out.append(("their record", r[0], r[1], r[2], r[3]))
    names = [norm(n) for n in rec.get("hold_names", []) if n]
    if names:
        q = """select anumber||' '||street, lat, lon, pin, coalesce(sale_date, date '1900-01-01') sd from parcel_snapshot where vintage='metrogis_current'
            and city='MINNEAPOLIS' and lat is not null and (regexp_replace(upper(coalesce(owner_name,'')),'[^A-Z0-9]','','g') in ({0})
            or regexp_replace(upper(coalesce(tax_name,'')),'[^A-Z0-9]','','g') in ({0})) order by sd desc""".format(",".join("?" * len(names)))
        for r in con.execute(q, names + names).fetchall():
            out.append(("a parcel the county shows them owning", r[0], r[1], r[2], r[3]))
    return out


def own_row(anchors):
    best = None
    mine = {a[4] for a in anchors}  # a listed house they own is not a lead for them
    for why, addr, la, lo, _ in anchors:
        for r in ROWS:
            if not r.get("lat") or r["pin"] in mine:
                continue
            d = km((la, lo), (r["lat"], r["lon"]))
            # the strongest listed house near them, not merely the closest weak one
            # (rank 6+ first: the top 5 are already open on the free page, so their own row shows something new)
            key = lambda rr, dd: (rr["rank"] <= 5, rr["rank"], dd)
            if d <= MAX_KM and (best is None or key(r, d) < key(best[1], best[0])):
                best = (d, r, addr, why)
    return best


def blocks(d_km):
    b = max(1, round(d_km / 0.1))  # a Minneapolis block is ~100 m on the short side
    return f"{b} block{'s' if b != 1 else ''}"


def token(seg, email):
    return hashlib.sha256(f"distressed-before-sale:{seg}:{email.lower()}".encode()).hexdigest()[:10]


def title(s):
    s = re.sub(r"\s+", " ", (s or "").strip()).title()
    s = re.sub(r"\b(Ne|Nw|Se|Sw|N|S|E|W)\b", lambda m: m.group(0).upper(), s)
    return re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s)


MONTHS = "January February March April May June July August September October November December".split()


def deed_sentence(q):
    m = re.match(r"county deed: bought (.+?), ([A-Za-z .]+) (\d{4})-(\d{2}) for (\$[\d,]+); listed now (\$[\d,]+)", q)
    if not m:
        return None
    addr, city, y, mo, paid, ask = m.groups()
    when = MONTHS[int(mo) - 1] + ("" if y == "2026" else f" {y}")
    return f"The county shows you bought {addr} in {city} in {when} for {paid}, and it is listed now at {ask}."


def fmt_date(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month - 1][:3]} {d.day}"


def body(rec, row, d_km, anchor, variant):
    who = rec.get("name", "").split()[0] if rec.get("name") else ""
    line1 = rec.get("opener") or deed_sentence(rec["record_quoted"])
    if not line1:
        raise SystemExit(f"no second-person opener for {rec['org']}: add 'opener' to its source row")
    fact = (f"{blocks(d_km)} from your {title(anchor)}, {row['block']} has {row['n']} city cases in the last 12 months, "
            f"{row['n_open']} still open, and the tax bill goes to {row['otype'].lower().replace('minneapolis, lives elsewhere', 'a different Minneapolis address').replace('minnesota, outside minneapolis', 'an address outside Minneapolis').replace('out of state', 'an address out of state')}. "
            f"It is one of {len(ROWS):,} Minneapolis houses like that this week; {P['parcels_new_30d']} joined in the last 30 days.")
    link = f"{SITE}/for/{token(rec['segment'], rec['email'])}/"
    price = f" The full list, with each exact address, the owner's mailing address and every case, refreshed weekly, is ${PRICE}, once." if variant == "A" else ""
    poke = f"5 are open to poke at, no login: {link}{price}"
    hi = f"{who},\n\n" if who else ""
    return (f"To: {rec['email']}\nSubject: bricks / {rec['company_short']}\n\n{hi}{line1}\n\n{fact}\n\n{poke}\n\n"
            f"How this gets built: {SUBSTACK}\n\nAidan\nBrick & Mortar\n")


def main():
    con = duckdb.connect(str(DB), read_only=True)
    led = duckdb.connect(str(LEDGER_DB), read_only=True)
    recs = []
    for f in sorted(R1.glob("seg[0-9]_source.json")):
        for rec in json.load(open(f)):
            recs.append(rec)
    seen, out = set(), []
    alt = {}
    (R1 / "drafts").mkdir(exist_ok=True)
    FDIR.mkdir(parents=True, exist_ok=True)
    for old in FDIR.glob("*.json"):
        old.unlink()
    for rec in recs:
        rec.setdefault("company_short", rec["org"].split(" / ")[0].split(" (")[0].strip())
        e = rec["email"].strip().lower()
        if e in seen:
            continue
        seen.add(e)
        c = led.execute("select sends, replies from contacted where recipient_key=?", [e]).fetchone()
        touch = 2 if (c and c[0]) else 1
        row = {"token": token(rec["segment"], e), "segment": rec["segment"], "company": rec["org"], "name": rec.get("name", ""),
               "email": e, "email_source": rec["email_source"], "email_source_date": rec.get("email_source_date", ""),
               "own_record": rec["record_quoted"], "touch": touch, "drafted_on": TODAY, "sent_on": "", "reply_kind": "", "reply_on": ""}
        if c and c[1]:
            row.update(status="hold", hold_reason="replied to an earlier touch: answer that thread by hand")
            out.append(row); continue
        if rec.get("force_hold"):
            row.update(status="hold", hold_reason=rec["force_hold"])
            out.append(row); continue
        best = own_row(anchors_for(con, rec))
        if not best:
            row.update(status="hold", hold_reason="no Minneapolis address of their own within 1.0 km of a listed house (the list is Minneapolis only)")
            out.append(row); continue
        d_km, r, anchor, why = best
        n = alt.get(rec["segment"], 0); alt[rec["segment"]] = n + 1
        variant = "AB"[n % 2]
        row.update(variant=variant, status="drafted", hold_reason="", own_row_block=r["block"], own_row_rank=r["rank"],
                   own_row_km=round(d_km, 2), anchor=f"{title(anchor)} ({why})", page_url=f"{SITE}/for/{row['token']}/")
        (R1 / "drafts" / f"{row['token']}.txt").write_text(body(rec, r, d_km, anchor, variant))
        free = {k: r[k] for k in ("block", "hood", "n", "n_open", "lead", "otype", "use", "built", "emv", "latest", "rank")}
        (FDIR / f"{row['token']}.json").write_text(json.dumps({
            "variant": variant, "label": f"Near {title(anchor)}",
            "html": (f"{blocks(d_km)} from your {title(anchor)}: <b>{r['block']}</b>, rank {r['rank']} of {len(ROWS):,}. "
                     f"{r['n']} city cases in 12 months, <b>{r['n_open']} still open</b>. {r['otype']}. "
                     f"Assessed ${round((r['emv'] or 0) / 1000)}k. City last acted {fmt_date(r['latest'])}."),
            "row": free}, separators=(",", ":")))
        out.append(row)
    with open(R1 / "ledger.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for row in out:
            w.writerow({k: row.get(k, "") for k in COLS})
    from collections import Counter
    print("recipients", len(out), dict(Counter((r["segment"], r["status"]) for r in out)))
    print("variants", dict(Counter((r["segment"], r.get("variant")) for r in out if r["status"] == "drafted")))
    print("touch 2 drafted", sum(1 for r in out if r["status"] == "drafted" and r["touch"] == 2))


if __name__ == "__main__":
    sys.exit(main())
