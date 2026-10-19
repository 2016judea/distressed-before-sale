"""Shared by every product page: render site/index.html from template.html, write the free slice
into the page, and gzip the full rows for /api/data (private/bundle/, uploaded by scripts/deploy.py).

The free slice is the sample rows (paid fields stripped), every row's dot on the map (rounded to
~100 m), and the counts. Nothing else of the full list ever lands in site/.
"""
import gzip, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SITE, BUNDLE = ROOT / "site" / "public", ROOT / "private" / "bundle"  # only site/public/ is served statically
dump = lambda o: json.dumps(o, separators=(",", ":"))


def analytics(site):
    ph = subprocess.run(["python3", str(Path.home() / ".claude/skills/site-analytics/posthog_inject.py"), "--site", site, "--print"],
                        capture_output=True, text=True, check=True).stdout
    reader = (Path(__file__).resolve().parent / "reader_events.js").read_text().strip()
    return ph + "<script>" + reader + "</script>"


def render(*, rows, sample, paid_fields, chip_key, chip_order, cfg_js, subs, site, dot_color=lambda r: 0):
    for r in sample:
        assert r in rows
    free_rows = [{k: v for k, v in r.items() if k not in paid_fields} for r in sample]
    counts = {g: sum(r[chip_key] == g for r in rows) for g in chip_order}
    dots = [[round(r["lat"], 3), round(r["lon"], 3), chip_order.index(r[chip_key]), dot_color(r)] for r in rows if r.get("lat")]
    free = {"rows": free_rows, "counts": counts, "total": len(rows), "dots": dots}
    h = (Path(__file__).resolve().parent / "template.html").read_text()
    for k, v in subs.items():
        h = h.replace(k, v)
    h = h.replace("__ANALYTICS__", analytics(site)).replace("__CFG__", cfg_js).replace("__FREE__", dump(free))
    assert "__" not in h.split("<script src=\"/paywall.js\">")[0].replace("__SV", "").replace("__proto__", ""), "unfilled token"
    (SITE / "index.html").write_text(h)
    BUNDLE.mkdir(parents=True, exist_ok=True)
    (BUNDLE / "full.json.gz").write_bytes(gzip.compress(dump({"rows": rows}).encode(), 9))
    leak = [f for f in paid_fields if any(r.get(f) for r in free_rows)]
    assert not leak, leak
    return counts
