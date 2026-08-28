"""Reconstruct the full locator for every legal act whose published URL is
truncated at the 200 character cap.

Method: the truncated string still contains the full gov.uk collection path and
a prefix of the document slug. Fetch the collection page, list the documents it
links, and keep the one whose URL starts with the truncated string. A repair is
only accepted when exactly one candidate matches and it returns HTTP 200.
"""
import json, os, re, sys, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(ROOT, "repairs", "legal_act_url_repairs.json")
UA = {"User-Agent": "curl/8.7.1"}
CAP = 200

def fetch(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read(400000).decode("utf-8", "replace"), r.url
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception:
        return None, "", url

def main():
    R = [json.loads(l) for l in open(os.path.join(CACHE, "resolutions.jsonl")) if l.strip()]
    recs = [json.loads(l) for l in open(os.path.join(CACHE, "commodities.jsonl")) if l.strip()]

    cites = {}
    for rec in recs:
        for m in rec["measures"]:
            for a in m.get("legal_acts") or []:
                cites[a] = cites.get(a, 0) + 1

    truncated = [r for r in R if len(r.get("regulation_url") or "") == CAP]
    print(f"legal acts at the {CAP} character cap: {len(truncated)}", flush=True)

    repairs = []
    for r in truncated:
        trunc = r["regulation_url"]
        collection = trunc.rsplit("/", 1)[0]
        status, html, _ = fetch(collection)
        cands = []
        if status == 200:
            for href in set(re.findall(r'href="(/government/publications/[^"#?]+)"', html)):
                full = "https://www.gov.uk" + href
                if full.startswith(trunc):
                    cands.append(full)
        rec = {"legal_act_id": r["legal_act_id"],
               "regulation_code": r["regulation_code"],
               "published_url": trunc,
               "published_url_length": len(trunc),
               "published_url_status": (r.get("resolution") or {}).get("http_status"),
               "collection_url": collection,
               "collection_status": status,
               "candidates": sorted(cands),
               "citations": cites.get(r["legal_act_id"], 0)}
        if len(cands) == 1:
            st, _, final = fetch(cands[0])
            rec["repaired_url"] = cands[0]
            rec["repaired_status"] = st
            rec["accepted"] = (st == 200)
        else:
            rec["repaired_url"] = None
            rec["accepted"] = False
        repairs.append(rec)
        print(f"  {r['legal_act_id']:10} cands={len(cands)} accepted={rec['accepted']}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(repairs, open(OUT, "w"), indent=2)
    ok = sum(1 for x in repairs if x["accepted"])
    aff = sum(x["citations"] for x in repairs if x["accepted"])
    print(f"\nrepaired {ok} of {len(repairs)}; those cover {aff} measure-to-act citations")
    print(f"written to {OUT}")

if __name__ == "__main__":
    main()
