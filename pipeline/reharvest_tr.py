"""Re-fetch only the commodities known to carry remedy measures, with the
corrected legal_acts relationship key."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_tariff as H
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ids = [l.strip() for l in open(os.path.join(ROOT, "cache", "tr_ids.txt")) if l.strip()]
done = H.load_done(H.COMMODITY_JSONL, "id")
todo = [i for i in ids if i not in done]
print(f"re-harvest: {len(ids)} TR commodities, {len(todo)} to fetch", flush=True)

def one(c):
    d = H.get(f"{H.BASE}/commodities/{c}")
    if not d:
        return
    rec = H.extract(c, d)
    if rec:
        H.append(H.COMMODITY_JSONL, rec)

with ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(one, todo))
print("REHARVEST COMPLETE", flush=True)
