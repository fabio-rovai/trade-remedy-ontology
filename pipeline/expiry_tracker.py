"""Measure expiry tracker: which UK trade remedy measures expire when, by
commodity and exporter.

Dual-computed, as everything here is: once set-based over the JSONL cache, and
once by SPARQL executed by the open-ontologies engine over the built graph.
The script exits non-zero if the two disagree on any bucket.
"""
import json, os, subprocess, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
GRAPH = os.path.join(ROOT, "graph", "traderemedy.ttl")
OUT_DIR = os.path.join(ROOT, "tracker")
ENGINE = os.path.expanduser("~/projects/open-ontologies/target/release/open-ontologies")
T = "https://gov.tesseract.academy/def/traderemedy#"

def set_based():
    recs = [json.loads(l) for l in open(os.path.join(CACHE, "commodities.jsonl")) if l.strip()]
    rows = {}
    for r in recs:
        for m in r["measures"]:
            vt = (m["attributes"].get("effective_end_date") or "")[:10]
            if not vt:
                continue
            ac = m.get("additional_code")
            exporter = None
            if ac and ac in r["additional_codes"]:
                exporter = (r["additional_codes"][ac].get("description") or "")[:120]
            rows[m["measure_id"]] = {
                "measure_id": m["measure_id"],
                "expires": vt,
                "commodity": r["id"],
                "commodity_description": (r.get("description") or "")[:120],
                "measure_type": m["measure_type"],
                "geographical_area": m.get("geographical_area"),
                "additional_code": ac,
                "exporter": exporter,
            }
    return rows

def engine_counts():
    """Ask our own engine: how many distinct dated measures expire per date."""
    q = f"""SELECT ?d (COUNT(DISTINCT ?m) AS ?n) WHERE {{
             ?m a <{T}TradeRemedyMeasure> ; <{T}validTo> ?d .
           }} GROUP BY ?d ORDER BY ?d"""
    env = dict(os.environ, OPEN_ONTOLOGIES_STORAGE_MODE="persistent")
    subprocess.run([ENGINE, "clear"], capture_output=True, env=env)
    r = subprocess.run([ENGINE, "load", GRAPH], capture_output=True, text=True, env=env)
    assert '"ok":true' in r.stdout, r.stdout[:300]
    r = subprocess.run([ENGINE, "query", q], capture_output=True, text=True, env=env)
    d = json.loads(r.stdout)
    rows = d.get("results", d.get("bindings", d))
    out = {}
    if isinstance(rows, dict) and "results" in rows:
        rows = rows["results"].get("bindings", [])
    for b in rows:
        def val(x):
            v = b.get(x)
            if isinstance(v, dict):
                v = v.get("value")
            return str(v)
        date = val("d").strip('"').split("^^")[0].strip('"')[:10]
        n = int(float(val("n").strip('"').split("^^")[0].strip('"')))
        out[date] = n
    return out

def main():
    rows = set_based()
    by_date = collections.Counter(r["expires"] for r in rows.values())
    eng = engine_counts()
    bad = 0
    for d, n in sorted(by_date.items()):
        if eng.get(d) != n:
            print(f"DISAGREE {d}: set-based {n}, engine {eng.get(d)}", file=sys.stderr)
            bad += 1
    extra = set(eng) - set(by_date)
    if extra:
        print(f"engine has dates set-based lacks: {sorted(extra)[:5]}", file=sys.stderr)
        bad += 1
    if bad:
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["expires"], r["commodity"]))
    with open(os.path.join(OUT_DIR, "expiry_tracker.json"), "w") as f:
        json.dump(ordered, f, indent=1)
    import csv
    with open(os.path.join(OUT_DIR, "expiry_tracker.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ordered[0].keys()))
        w.writeheader(); w.writerows(ordered)

    lines = ["# UK trade remedy measure expiry tracker", "",
             "Regenerated from the live UK Trade Tariff by `pipeline/expiry_tracker.py`.",
             "Every per-date count is computed twice, set-based in Python and by SPARQL",
             "through the open-ontologies engine, and the build fails on disagreement.", "",
             f"Measures carrying an expiry date: {len(rows)}", "",
             "| Expiry date | Measures |", "|---|---|"]
    for d, n in sorted(by_date.items()):
        lines.append(f"| {d} | {n} |")
    open(os.path.join(OUT_DIR, "README.md"), "w").write("\n".join(lines) + "\n")
    print(f"tracker written: {len(rows)} dated measures across {len(by_date)} expiry dates; "
          f"engine agrees on all {len(by_date)} buckets")
    return 0

if __name__ == "__main__":
    sys.exit(main())
