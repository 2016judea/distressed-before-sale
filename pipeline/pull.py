#!/usr/bin/env python3
"""Pull the City of Minneapolis CaseViolations feed (ArcGIS, open data) into cache/.

    python3 pipeline/pull.py            # every violation row processed since SINCE
    python3 pipeline/pull.py --probe    # just the count and the group descriptions

One row per violation code per case. Fields that matter: APN (Hennepin PIN), Display (address),
Violation_Case_Number, Case_Group / Case_Group_Desc, Status_Violation_Case (Closed, Enforce,
Pending, Cancelled, Stop Work), Milestone_Violation_Case (Intent to Assess, Condemnation,
Citation Tier N...), Violation_Code_Description, Processed_Date (the city last worked the row),
Resolved_Date.

Pages of 2000: ArcGIS reads cap at 2000 silently whatever maxRecordCount says
(bricks memory, reference_arcgis_reads_cap_at_2000). The pull verifies the page total
against returnCountOnly before it writes.

This is NOT the layer cached in bricks closed_system as `mpls_caseviolations`: that one has the
CaseInspections schema (375,264 rows, Start_Date mostly null). Found 2026-10-18.
"""
import gzip, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CaseViolations/FeatureServer/0/query"
SINCE = "2025-09-01"
OUT = ROOT / "cache" / "violations.json.gz"
PAGE = 2000


def q(**params):
    params.setdefault("f", "json")
    data = urllib.parse.urlencode(params).encode()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, data=data), timeout=120) as r:
                j = json.loads(r.read())
            if "error" in j:
                raise RuntimeError(j["error"])
            return j
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def main():
    where = f"Processed_Date >= TIMESTAMP '{SINCE} 00:00:00'"
    total = q(where=where, returnCountOnly="true")["count"]
    groups = q(where=where, groupByFieldsForStatistics="Case_Group,Case_Group_Desc",
               outStatistics=json.dumps([{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}]))
    desc = {f["attributes"]["Case_Group"]: (f["attributes"]["Case_Group_Desc"], f["attributes"]["n"]) for f in groups["features"]}
    print(f"{total} rows since {SINCE}")
    for g, (d, n) in sorted(desc.items(), key=lambda x: -x[1][1]):
        print(f"  {n:6d}  {g!r:12}  {d}")
    if "--probe" in sys.argv:
        return
    rows, offset = [], 0
    while True:
        j = q(where=where, outFields="*", orderByFields="OBJECTID", resultOffset=offset, resultRecordCount=PAGE)
        feats = [f["attributes"] for f in j["features"]]
        rows.extend(feats)
        offset += len(feats)
        print(f"  page -> {offset}", end="\r", flush=True)
        if len(feats) < PAGE or not j.get("exceededTransferLimit", True) and len(feats) < PAGE:
            break
        if len(feats) < PAGE:
            break
    print()
    assert len(rows) == total, f"paged {len(rows)} but the count says {total}"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(gzip.compress(json.dumps({"pulled": time.strftime("%Y-%m-%d"), "since": SINCE, "url": URL, "groups": desc, "rows": rows}).encode(), 9))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
