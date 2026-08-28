"""Census the UK Trade Tariff for trade-remedy measures.

Resumable: every commodity's extracted slice is appended to a JSONL cache keyed
by commodity id. Re-running skips ids already present. Only the trade-remedy
slice is retained; the full ~550KB payloads are discarded after extraction.
"""
import json, os, sys, time, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.trade-tariff.service.gov.uk/api/v2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
HEADINGS_JSONL = os.path.join(CACHE, "headings.jsonl")
COMMODITY_JSONL = os.path.join(CACHE, "commodities.jsonl")

# Trade remedy measure type ids, verified from /api/v2/measure_types 28 Aug 2026
TR_TYPES = {"551","552","553","554","555","561","562","564","565","566","570","690","696"}

_lock = threading.Lock()

def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None

def load_done(path, key="id"):
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)[key])
                except Exception:
                    pass  # tolerate a torn final line from an interrupted run
    return done

def append(path, obj):
    with _lock:
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            f.flush()

def harvest_headings():
    """Walk sections -> chapters -> headings to enumerate every commodity id."""
    done = load_done(HEADINGS_JSONL, "heading")
    secs = get(f"{BASE}/sections")
    heading_codes = []
    for s in secs["data"]:
        sid = s["id"]
        sec = get(f"{BASE}/sections/{sid}")
        for ch in [x for x in sec.get("included", []) if x["type"] == "chapter"]:
            cid = ch["attributes"]["goods_nomenclature_item_id"][:2]
            chap = get(f"{BASE}/chapters/{cid}")
            if not chap:
                continue
            for h in [x for x in chap.get("included", []) if x["type"] == "heading"]:
                heading_codes.append(h["attributes"]["goods_nomenclature_item_id"][:4])
    heading_codes = sorted(set(heading_codes))
    todo = [h for h in heading_codes if h not in done]
    print(f"headings: {len(heading_codes)} total, {len(todo)} to fetch", flush=True)

    def one(h):
        d = get(f"{BASE}/headings/{h}")
        if not d:
            return
        coms = [x["attributes"]["goods_nomenclature_item_id"]
                for x in d.get("included", []) if x["type"] == "commodity"]
        append(HEADINGS_JSONL, {"heading": h, "commodities": sorted(set(coms))})

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    return HEADINGS_JSONL

def all_commodities():
    coms = set()
    with open(HEADINGS_JSONL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                coms.update(json.loads(line)["commodities"])
            except Exception:
                pass
    return sorted(coms)

def extract(cid, d):
    """Keep only what the vertical needs: TR measures and the records they cite."""
    inc = d.get("included", [])
    by = {}
    for x in inc:
        by.setdefault(x["type"], {})[x["id"]] = x

    tr_measures = []
    for m in by.get("measure", {}).values():
        rel = m.get("relationships", {})
        mt = (rel.get("measure_type", {}).get("data") or {}).get("id")
        if mt not in TR_TYPES:
            continue
        def rid(k):
            dd = rel.get(k, {}).get("data")
            if isinstance(dd, list):
                return [y["id"] for y in dd]
            return dd["id"] if dd else None
        tr_measures.append({
            "measure_id": m["id"],
            "measure_type": mt,
            "attributes": m.get("attributes", {}),
            "geographical_area": rid("geographical_area"),
            "additional_code": rid("additional_code"),
            "legal_acts": rid("legal_acts") or [],
            "components": rid("measure_components") or [],
            "order_number": rid("order_number"),
            "excluded_countries": rid("excluded_countries") or [],
            "footnotes": rid("footnotes") or [],
        })
    if not tr_measures:
        return None
    return {
        "id": cid,
        "description": (by.get("commodity", {}).get(d["data"]["id"], {})
                        .get("attributes", {}).get("description"))
                       or d["data"]["attributes"].get("description"),
        "measures": tr_measures,
        "additional_codes": {k: v["attributes"] for k, v in by.get("additional_code", {}).items()},
        "geographical_areas": {k: v["attributes"] for k, v in by.get("geographical_area", {}).items()},
        "legal_acts": {k: v["attributes"] for k, v in by.get("legal_act", {}).items()},
        "measure_components": {k: v["attributes"] for k, v in by.get("measure_component", {}).items()},
        "duty_expressions": {k: v["attributes"] for k, v in by.get("duty_expression", {}).items()},
    }

def harvest_commodities():
    done = load_done(COMMODITY_JSONL, "id")
    seen_path = os.path.join(CACHE, "commodities_seen.txt")
    seen = set()
    if os.path.exists(seen_path):
        seen = set(open(seen_path).read().split())
    coms = all_commodities()
    todo = [c for c in coms if c not in seen]
    print(f"commodities: {len(coms)} total, {len(done)} with TR measures cached, "
          f"{len(todo)} still to visit", flush=True)
    n = [0]

    def one(c):
        d = get(f"{BASE}/commodities/{c}")
        with _lock:
            with open(seen_path, "a") as f:
                f.write(c + "\n")
            n[0] += 1
            if n[0] % 500 == 0:
                print(f"  visited {n[0]}/{len(todo)}", flush=True)
        if not d:
            return
        rec = extract(c, d)
        if rec:
            append(COMMODITY_JSONL, rec)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))

if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    if "commodities" not in sys.argv:
        harvest_headings()
    harvest_commodities()
    print("HARVEST COMPLETE", flush=True)
