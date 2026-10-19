#!/usr/bin/env python3
"""Write site/index.html (free slice), site/offer.json (price line with the live count) and
private/bundle/full.json.gz (the paid list) from private/rows.json (pipeline/build.py).
Every number on the page is computed here or in build.py; none is typed."""
import json, datetime as dt
from pathlib import Path
from sitekit import render
ROOT = Path(__file__).resolve().parent.parent
D = json.load(open(ROOT / "private" / "rows.json"))
rows, P = D["rows"], D["pulse"]
ORDER = ["Vacant building", "Housing complaint", "Code enforcement", "Nuisance"]
OTYPES = ["Out of state", "Minnesota, outside Minneapolis", "Minneapolis, lives elsewhere"]
PAID = ["pin", "addr", "owner", "mail", "cases", "sales", "last_sale", "last_price", "entity", "zip"]
SAMPLE_N = 5
asof = dt.date.fromisoformat(P["asof"]).strftime("%b %-d, %Y")
since = dt.date.fromisoformat(P["since"]).strftime("%b %-d")
sample = rows[:SAMPLE_N]
RIVER = [[45.052,-93.2885],[45.03,-93.2805],[45.012,-93.2745],[44.998,-93.2685],[44.988,-93.2625],[44.9815,-93.2575],[44.977,-93.2475],[44.972,-93.2385],[44.967,-93.2295],[44.962,-93.2225],[44.953,-93.2065],[44.946,-93.2005],[44.935,-93.2005],[44.917,-93.2035],[44.905,-93.1995],[44.889,-93.1935]]
COLS = [("rank","Rank"),("addr","Address"),("hood","Neighborhood"),("zip","ZIP"),("use","Property type"),("built","Year built"),("beds","Bedrooms"),("sqft","Finished sq ft"),
        ("emv","Assessor value"),("tax","Property tax"),("n","Cases, last 12 months"),("n_open","Cases still open"),("lead","Main kind of case"),
        ("vbr","Vacant-building cases"),("condemned","Condemnation on file"),("latest","City last acted"),("otype","Where the owner gets mail"),("owner","Taxpayer"),("mail","Taxpayer mailing address"),
        ("entity","Owned by a company"),("last_sale","Last sale"),("last_price","Last sale price"),("score","Rank score")]

offer = {
  "product": "distressed-before-sale", "site": "https://distressed-before-sale.vercel.app", "price_usd": 500, "launch": 1792800000,
  "name": "Distressed Before It Sells: the full ranked list", "short": "Distressed Before It Sells", "thing": "full list",
  "description": f"{len(rows)} Minneapolis houses piling up city cases while the owner lives somewhere else, ranked, with the owner's mailing address, every case and the last sale. Refreshed weekly.",
  "line": f"The full list of {len(rows):,} houses, with each address, the owner's mailing address, every case, the last sale, the spreadsheet, and a fresh list every week, is $500, once."}
for _o in (ROOT / "site" / "offer.json", ROOT / "site" / "public" / "offer.json"):  # functions read the first, the page the second
    _o.write_text(json.dumps(offer, indent=2) + "\n")

cfg = """{chipKey:"lead",chipOrder:%(order)s,river:%(river)s,csv:"distressed-before-sale-minneapolis.csv",cols:%(cols)s,
 pulseLabel:"The last 30 days, %(since)s to %(asof)s",
 stats:[["%(new)s","new cases the city opened",""],["%(vbr)s","new vacant-building registrations","hot"],["%(joined)s","houses joined this list",""],["%(sold)s","of these houses sold in 12 months, median %(soldmed)s",""]],
 legend:[["var(--hot)","Has a case still open"],["var(--done)","Every case closed"],["var(--ink)","(ring) one of the %(sn)d open to look at"]],
 dotColor:["var(--done)","var(--hot)"],
 color:r=>r.n_open>0?"var(--hot)":"var(--done)",
 title:r=>FULL?r.addr:r.block,
 what:r=>`${r.n} ${r.n===1?"case":"cases"} in 12 months${r.n_open?`, <b>${r.n_open} still open</b>`:", <i>all closed</i>"}${r.condemned?", <b>condemned</b>":""}${r.vbr?", registered vacant":""}`,
 tag:r=>`<span class="tag ${r.lead==="Vacant building"||r.condemned?"hot":""}">${esc(r.lead)}</span>`,
 meta:r=>[r.hood,r.otype,r.emv?"Assessed "+usdk(r.emv):"",r.use+(r.built?", built "+r.built:""),"City last acted "+fmt(r.latest)],
 paid:r=>[`Taxpayer: ${esc(r.owner)}${r.entity?" (company)":""}`,r.mail?`Mail goes to ${esc(r.mail)}`:"",r.last_sale?`Last sale ${mon(r.last_sale)} for ${usd(r.last_price)}`:"No recorded sale",
   `<details><summary>${r.cases.length} ${r.cases.length===1?"case":"cases"}</summary><ul>${r.cases.map(c=>`<li>${esc(c.kind)} ${esc(c.cn)}: ${esc(c.status||"")}${c.milestone?", "+esc(c.milestone):""}; opened ${fmt(c.opened)}, last acted ${fmt(c.touched)}${c.what.length?" — "+esc(c.what.join("; ")):""}</li>`).join("")}</ul></details>`].filter(Boolean).map(x=>x.startsWith("<details")?x:`<div>${x}</div>`).join(""),
 sorts:[["rank","Rank (most trouble, farthest owner)",false],["open","Most open cases first",false],["recent","City acted most recently",false],["away","Out-of-state owners first",false],["value","Lowest assessed value first",false],["hood","By neighborhood",false]],
 sortFn:{rank:r=>r.sort((a,b)=>a.rank-b.rank),open:r=>r.sort((a,b)=>b.n_open-a.n_open||a.rank-b.rank),recent:r=>r.sort((a,b)=>b.latest.localeCompare(a.latest)),
   away:r=>r.sort((a,b)=>%(otypes)s.indexOf(a.otype)-%(otypes)s.indexOf(b.otype)||a.rank-b.rank),value:r=>r.sort((a,b)=>(a.emv||9e9)-(b.emv||9e9)),hood:r=>r.sort((a,b)=>a.hood.localeCompare(b.hood)||a.rank-b.rank)},
 lockText:n=>`${n} more houses, with the exact address, the owner's mailing address and every case`}""" % dict(
    order=json.dumps(ORDER), river=json.dumps(RIVER), cols=json.dumps([[c[0], c[1]] for c in COLS]), since=since, asof=asof,
    new=f"{P['new_cases_30d']:,}", vbr=P["new_vbr_30d"], joined=P["parcels_new_30d"], sold=P["sold_12mo"],
    soldmed="$" + f"{round(P['sold_median']/1000)}k", sn=len(sample), otypes=json.dumps(OTYPES))

LIGHT = '--bg:#f6f3ee;--panel:#ece7df;--ink:#211a14;--ink2:#41372e;--muted:#6f655b;--rule:#d9d1c5;--accent:#3d5a73;--onaccent:#f6f3ee;--hot:#b0412a;--done:#8d8378;--ghost:#cbc3b7;--water:#8fb0bf;--tagbg:#e6e0d6;--tagfg:#4d443b;--hotbg:#f3d9d0;--hotfg:#8a2f1b;--display:"Fraunces",Georgia,serif;--body:"Public Sans",system-ui,sans-serif;--h1w:600;'
DARK = '--bg:#16130f;--panel:#1f1a15;--ink:#eee7de;--ink2:#cbc1b5;--muted:#958a7e;--rule:#342c24;--accent:#8fb2cc;--onaccent:#16130f;--hot:#ef8a6c;--done:#7a7066;--ghost:#3a322a;--water:#3e6475;--tagbg:#2a231d;--tagfg:#bcb1a4;--hotbg:#4a2217;--hotfg:#f6b5a0;'
by = P["by_otype"]
counts = render(rows=rows, sample=sample, paid_fields=PAID, chip_key="lead", chip_order=ORDER, cfg_js=cfg, site="distressed-before-sale",
  dot_color=lambda r: 1 if r["n_open"] > 0 else 0, subs={
 "__TITLE__": "Distressed Before It Sells",
 "__DESC__": f"{len(rows)} Minneapolis houses piling up city nuisance and code cases while the owner lives somewhere else, ranked for investors who buy before the listing.",
 "__FONTS__": "family=Fraunces:opsz,wght@9..144,600&family=Public+Sans:wght@400;500;600",
 "__LIGHT__": LIGHT, "__DARK__": DARK,
 "__EYEBROW__": f"For investors who buy before the listing · Minneapolis public records · city feed read {asof}",
 "__H1__": f"{len(rows):,} Minneapolis houses in trouble with the city, and the owner lives somewhere else",
 "__LEDE__": f"Each one has at least two open-or-recent nuisance, housing or code cases in the last 12 months, or is registered vacant, and the tax bill goes to an address that is not the house. <b>{P['parcels_open']:,} still have a case open</b>; {by['Out of state']} owners get their mail out of state. Ranked so the top is the most trouble and the farthest owner.",
 "__MAPLABEL__": "Map of Minneapolis with each house as a dot",
 "__NOTE__": f"<p>Sources, all public: the City of Minneapolis code-enforcement case feed (CaseViolations, open data, read {asof}), the city's inspection feed for when each case opened, Hennepin County parcel and taxpayer records for the assessor value, homestead status and where the tax bill is mailed, and recorded sales. Owner names and mailing addresses are the county's public taxpayer record, shown as the county publishes them.</p><p>How a house gets on the list: a one-to-three-unit house (not a condo) that is not homesteaded, with two or more cases of these kinds in the last 12 months (nuisance, housing complaint, code enforcement, vacant-building registration), or any vacant-building or condemnation case. \"Open\" is the city's own case status (Enforce, Pending, Stop Work). Rental-license and fire inspections are left out: they are routine. The rank adds up open cases, closed cases, vacant and condemnation flags, how recently the city acted, and how far away the owner's mail goes.</p><p>What this list is not: it does not say the owner wants to sell. It says the house is costing them time and money with the city and they are not living in it. Minneapolis only. Refreshed weekly.</p><p>From Aidan Jude at Brick &amp; Mortar (aidan@brickandmortar.dev).</p>"})
print("rows", len(rows), "open", P["parcels_open"], counts, "sample", len(sample), "otype", by, "price", offer["price_usd"])
