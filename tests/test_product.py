"""The suite: the model loader, the paywall split, the API 401 path, the page build.

    python3 -m pytest tests -q 2>&1 | tee tests/last_run.txt

Runs against private/rows.json and site/index.html as built (pipeline/build.py, scripts/publish.py).
"""
import gzip, json, os, re, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
ROWS = json.load(open(ROOT / "private/rows.json"))
PAGE = (ROOT / "site/public/index.html").read_text()
OFFER = json.load(open(ROOT / "site/offer.json"))
FREE = json.loads(re.search(r"const FREE=(\{.*?\});\nconst \$=", PAGE, re.S).group(1))
PAID = ["pin", "addr", "owner", "mail", "cases", "sales", "last_sale", "last_price", "entity", "zip"]
RES = ("Residential",)


# ---- the model loader (pipeline/build.py output) ----
def test_rows_are_ranked_and_distinct():
    rows = ROWS["rows"]
    assert len(rows) > 500
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert len({r["pin"] for r in rows}) == len(rows)
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_every_row_meets_the_definition():
    for r in ROWS["rows"]:
        assert r["n"] >= 2 or r["vbr"] or r["condemned"], r["pin"]
        assert r["otype"] in ("Out of state", "Minnesota, outside Minneapolis", "Minneapolis, lives elsewhere")
        assert r["n_open"] <= r["n"] == len(r["cases"])
        assert r["lead"] in ("Vacant building", "Housing complaint", "Code enforcement", "Nuisance")
        assert re.match(r"^\d{13}$", r["pin"])
        assert r["lat"] and r["lon"] and 44.8 < r["lat"] < 45.1 and -93.4 < r["lon"] < -93.15


def test_block_hides_the_house_number():
    for r in ROWS["rows"]:
        assert r["block"] != r["addr"]
        assert "xx" in r["block"] or r["block"].startswith("x"), r["block"]
        assert r["addr"].split(" ", 1)[1].lower() == r["block"].split(" ", 1)[1].lower()


def test_case_kinds_exclude_routine_inspections():
    kinds = {c["kind"] for r in ROWS["rows"] for c in r["cases"]}
    assert kinds <= {"Vacant building", "Housing complaint", "Code enforcement", "Nuisance"}


def test_pulse_numbers_are_internally_consistent():
    P = ROWS["pulse"]
    assert P["parcels_ranked"] == len(ROWS["rows"])
    assert P["parcels_open"] == sum(r["n_open"] > 0 for r in ROWS["rows"])
    assert sum(P["by_otype"].values()) == len(ROWS["rows"])
    assert sum(P["by_lead"].values()) == len(ROWS["rows"])
    assert P["new_vbr_30d"] == P["new_by_kind_30d"]["Vacant building"] <= P["new_cases_30d"]
    assert P["sold_12mo"] <= P["sold_24mo"] == len(ROWS["sold"])


def test_sold_rows_had_distress_before_the_sale():
    for s in ROWS["sold"]:
        assert s["cases_before"] >= 2 and s["price"] >= 20000 and s["sold"] >= "2024-09-01"


# ---- the paywall split ----
def test_free_slice_is_the_sample_only():
    assert len(FREE["rows"]) == 5
    assert FREE["total"] == len(ROWS["rows"])
    assert [r["rank"] for r in FREE["rows"]] == [1, 2, 3, 4, 5]


def test_free_rows_carry_no_paid_field():
    for r in FREE["rows"]:
        for f in PAID:
            assert f not in r, f


def test_page_leaks_no_exact_address_owner_or_mailing_address():
    low = PAGE.lower()
    for r in ROWS["rows"]:
        assert r["addr"].lower() not in low, r["addr"]
        # public bodies own a few of these; their names are words the page uses legitimately
        if r["owner"] and len(r["owner"]) > 6 and not re.search(r"minneapolis|hennepin|minnesota|housing|authority", r["owner"], re.I):
            assert r["owner"].lower() not in low, r["owner"]
        assert r["pin"] not in PAGE


def test_dots_are_rounded_and_cover_every_row():
    assert len(FREE["dots"]) == len(ROWS["rows"])
    for d in FREE["dots"]:
        assert round(d[0], 3) == d[0] and round(d[1], 3) == d[1] and d[3] in (0, 1)


def test_full_bundle_has_everything():
    full = json.loads(gzip.decompress((ROOT / "private/bundle/full.json.gz").read_bytes()))
    assert len(full["rows"]) == len(ROWS["rows"])
    assert all(f in full["rows"][0] for f in PAID)


def test_offer_is_one_plain_price():
    assert OFFER["price_usd"] == 500 and OFFER["product"] == "distressed-before-sale"
    assert "$500, once" in OFFER["line"] and f"{len(ROWS['rows']):,}" in OFFER["line"]
    assert not re.search(r"discount|save|bundle|%|limited", OFFER["line"], re.I)


# ---- the API 401 path (site/api/data.js driven with a fake req/res) ----
NODE = r"""
process.env.ACCESS_SECRET = "test-secret"; process.env.STRIPE_SECRET_KEY = "sk_test_x";
const h = require(process.argv[1]);
const res = { code: 0, headers: {}, body: null, status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; }, setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; return this; } };
const pw = process.argv[2] || "";
h({ headers: pw ? { "x-password": pw } : {}, query: {} }, res).then(() => { console.log(JSON.stringify({ code: res.code, body: typeof res.body === "string" ? res.body.slice(0, 40) : res.body })); });
"""


def drive(pw=""):
    out = subprocess.run(["node", "-e", NODE, str(ROOT / "site/api/data.js"), pw], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_api_data_is_401_without_a_password():
    r = drive()
    assert r["code"] == 401 and "password" in r["body"]["error"].lower()


def test_api_data_is_401_for_a_made_up_password():
    r = drive("ABCD-EFGH-JKLM")
    assert r["code"] == 401


def test_api_data_opens_for_a_comp_password(tmp_path):
    # a comp password is an HMAC in the "comp:" domain under ACCESS_SECRET (same as scripts/issue_password.py)
    import hashlib, hmac
    ALPHA = "23456789BCDFGHJKMNPQRSTVWXYZ"
    nonce = "QQQQQ"
    mac = hmac.new(b"test-secret", ("comp:" + nonce).encode(), hashlib.sha256).digest()
    pw = nonce + "".join(ALPHA[b % len(ALPHA)] for b in mac[:7])
    # point the handler at the bundle, via FULL_DIR
    node = NODE.replace('process.env.ACCESS_SECRET = "test-secret";', f'process.env.ACCESS_SECRET = "test-secret"; process.env.FULL_DIR = {json.dumps(str(ROOT / "private/bundle"))};')
    out = subprocess.run(["node", "-e", node, str(ROOT / "site/api/data.js"), pw], capture_output=True, text=True, timeout=30)
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["code"] == 200, out.stderr


# ---- the page build ----
def test_page_has_no_unfilled_token_and_both_analytics_tags():
    head = PAGE.split("<script src=\"/paywall.js\">")[0]
    assert not re.search(r"__[A-Z]+__", head)
    assert "/_vercel/insights/script.js" in PAGE
    assert "bm-posthog:begin" in PAGE
    assert 'window.va("event"' in (ROOT / "site/public/paywall.js").read_text() or "va('event'" in PAGE


def test_page_numbers_come_from_the_data():
    P = ROWS["pulse"]
    assert f"{len(ROWS['rows']):,} Minneapolis houses" in PAGE
    assert f"{P['new_cases_30d']:,}" in PAGE and str(P["new_vbr_30d"]) in PAGE and str(P["parcels_new_30d"]) in PAGE
    assert f"{P['parcels_open']:,} still have a case open" in PAGE


def test_for_pages_rewrite_to_the_index():
    v = json.load(open(ROOT / "site/vercel.json"))
    srcs = [r["source"] for r in v["rewrites"]]
    assert "/for/:token" in srcs and "/for/:token/" in srcs


def test_for_json_files_never_carry_an_email_or_a_paid_row():
    for p in (ROOT / "site/public/f").glob("*.json") if (ROOT / "site/public/f").exists() else []:
        j = json.load(open(p))
        assert j["variant"] in ("A", "B")
        assert "@" not in json.dumps(j)
        for f in ("owner", "mail", "pin"):
            assert f not in j


def test_only_site_public_is_served_statically():
    # outputDirectory "." served api/_full/ (the paid bundle) at /api/%5Ffull/full.json.gz — proven live 2026-10-19
    v = json.load(open(ROOT / "site/vercel.json"))
    assert v["outputDirectory"] == "public"
    assert '"outputDirectory": "public"' in (ROOT / "scripts/deploy.py").read_text()
    assert not any("_full" in str(p) or p.name == "full.json.gz" for p in (ROOT / "site/public").rglob("*"))
