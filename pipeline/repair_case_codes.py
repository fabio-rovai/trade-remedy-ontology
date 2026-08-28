"""Repair commodity codes in the TRA case register that lost a leading zero.

A UK commodity code is 6, 8 or 10 digits. Nine-digit values in the published case
register are ten-digit codes whose leading zero was dropped by a numeric cast. A
repair is accepted only when the published value fails to resolve against the
tariff AND the zero-restored value resolves.
"""
import json, os, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "repairs", "tra_case_code_repairs.json")
API = "https://www.trade-tariff.service.gov.uk/api/v2/commodities/"
UA = {"User-Agent": "curl/8.7.1"}

def probe(code):
    try:
        req = urllib.request.Request(API + code, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode())
            return 200, d["data"]["attributes"].get("description")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None

def main():
    cases = [json.loads(l) for l in
             open(os.path.join(ROOT, "cache", "tra_cases.jsonl")) if l.strip()]
    repairs = []
    for c in cases:
        for code in c["commodity_codes"]:
            if len(code) != 9:
                continue
            st_pub, _ = probe(code)
            cand = "0" + code
            st_rep, desc = probe(cand)
            repairs.append({
                "case_ref": c["case_ref"], "case_status": c["status"],
                "case_url": c["url"],
                "published_code": code, "published_code_status": st_pub,
                "repaired_code": cand, "repaired_code_status": st_rep,
                "repaired_description": desc,
                "accepted": st_pub == 404 and st_rep == 200,
            })
            print(f"  {c['case_ref']} {code} ({st_pub}) -> {cand} ({st_rep}) "
                  f"{(desc or '')[:44]}", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(repairs, open(OUT, "w"), indent=2)
    ok = sum(1 for r in repairs if r["accepted"])
    print(f"\n{ok} of {len(repairs)} accepted; written to {OUT}")

if __name__ == "__main__":
    main()
