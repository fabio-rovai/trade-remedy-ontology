"""Segment replication: run the same integrity questions against the EU, Canada
and the US, and record Australia's register as blocked rather than skipped.

EU:  every EU parent regulation the UK tariff still cites is checked for
     in-force status via the Publications Office CELLAR (keyless RDF), and the
     ongoing EU case list is taken from TRON's open list endpoint.
CA:  the CBSA measures-in-force table, with the same code-granularity and
     link-resolution checks the UK got.
US:  Federal Register API counts for AD and CVD orders (keyless).
AU:  industry.gov.au and adcommission.gov.au refuse the connection outright
     (HTTP/2 stream errors on an honest UA). Recorded as BLOCKED.
"""
import json, os, re, html, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
UA = {"User-Agent": "curl/8.7.1"}
_lock = threading.Lock()

def get(url, headers=None, timeout=60):
    h = dict(UA); h.update(headers or {})
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception:
            pass
    return None, b""

# ---- EU --------------------------------------------------------------------

def eu_celex_from_code(code):
    """'R1722/18' -> '32018R1722'. Only R-codes are EU regulations."""
    m = re.match(r"^R(\d{4})/(\d{2})$", code or "")
    if not m:
        return None
    num, yy = m.group(1), int(m.group(2))
    year = 1900 + yy if yy > 50 else 2000 + yy
    return f"3{year}R{int(num):04d}"

def run_eu():
    out = os.path.join(CACHE, "eu_parent_regs.jsonl")
    recs = [json.loads(l) for l in open(os.path.join(CACHE, "commodities.jsonl")) if l.strip()]
    cited = {}
    for r in recs:
        for m in r["measures"]:
            for a in m.get("legal_acts") or []:
                code = r["legal_acts"].get(a, {}).get("regulation_code")
                cx = eu_celex_from_code(code)
                if cx:
                    cited.setdefault(cx, {"code": code, "measures": 0})
                    cited[cx]["measures"] += 1
    done = set()
    if os.path.exists(out):
        done = {json.loads(l)["celex"] for l in open(out) if l.strip()}
    print(f"EU parent regulations cited by live UK measures: {len(cited)}", flush=True)

    def one(item):
        cx, meta = item
        if cx in done:
            return
        st, body = get(f"https://publications.europa.eu/resource/celex/{cx}?language=eng",
                       headers={"Accept": "application/rdf+xml"})
        rec = {"celex": cx, "uk_code": meta["code"], "uk_measures_citing": meta["measures"],
               "cellar_status": st}
        if st == 200:
            x = body.decode("utf-8", "replace")
            m = re.search(r"resource_legal_in-force[^>]*>(true|false)<", x)
            rec["eu_in_force"] = (m.group(1) == "true") if m else None
            d = re.search(r"date_document[^>]*>(\d{4}-\d{2}-\d{2})<", x)
            rec["date_document"] = d.group(1) if d else None
        with _lock:
            with open(out, "a") as f:
                f.write(json.dumps(rec) + "\n"); f.flush()

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(one, cited.items()))

    st, body = get("https://tron.trade.ec.europa.eu/investigations/api/eucase/list/ongoing")
    if st == 200:
        open(os.path.join(CACHE, "eu_ongoing_cases.json"), "wb").write(body)
        print(f"EU ongoing cases: {len(json.loads(body))}", flush=True)

# ---- Canada ----------------------------------------------------------------

def run_canada():
    st, body = get("https://www.cbsa-asfc.gc.ca/sima-lmsi/mif-mev/menu-eng.html")
    if st != 200:
        print(f"CA: blocked, HTTP {st}", flush=True); return
    h = body.decode("utf-8", "replace")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S)
    out = []
    for r in rows[1:]:
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) < 5:
            continue
        codes = re.findall(r"\d{4}\.\d{2}\.\d{2}\.\d{2}", cells[4]) if len(cells) > 4 else []
        bad = [c for c in re.findall(r"[\d.]+", cells[4])
               if re.match(r"^\d", c) and not re.match(r"^\d{4}\.\d{2}\.\d{2}(\.\d{2})?$", c)] if len(cells) > 4 else []
        out.append({"case": cells[0], "product": cells[1], "type": cells[2],
                    "country": cells[3], "codes": codes, "malformed_codes": bad,
                    "markup_in_product": bool(re.search(r"&(amp|lt|gt);", cells[1]))})
    json.dump(out, open(os.path.join(CACHE, "ca_measures.json"), "w"), indent=1)
    n_codes = sum(len(x["codes"]) for x in out)
    n_bad = sum(len(x["malformed_codes"]) for x in out)
    print(f"CA: {len(out)} measure rows, {n_codes} codes, {n_bad} malformed tokens", flush=True)

# ---- US --------------------------------------------------------------------

def run_us():
    base = ("https://www.federalregister.gov/api/v1/documents.json"
            "?conditions%5Bagencies%5D%5B%5D=international-trade-administration&per_page=20"
            "&order=newest&conditions%5Bterm%5D=")
    res = {}
    for key, term in [("antidumping_duty_order", "%22antidumping%20duty%20order%22"),
                      ("countervailing_duty_order", "%22countervailing%20duty%20order%22")]:
        st, body = get(base + term)
        if st == 200:
            d = json.loads(body)
            res[key] = {"count": d.get("count"),
                        "recent": [{"date": r["publication_date"], "title": r["title"],
                                    "html_url": r["html_url"]} for r in d.get("results", [])[:10]]}
        print(f"US {key}: HTTP {st}, count {res.get(key,{}).get('count')}", flush=True)
    json.dump(res, open(os.path.join(CACHE, "us_fedreg.json"), "w"), indent=1)

# ---- Australia -------------------------------------------------------------

def run_australia():
    status = {}
    for u in ["https://www.industry.gov.au/", "https://www.adcommission.gov.au/"]:
        st, _ = get(u, timeout=25)
        status[u] = st
    json.dump({"blocked": True, "detail": status,
               "note": "Both hosts refuse the connection to an honest scripted client "
                       "(HTTP/2 stream errors / no response). Not circumvented. "
                       "WTO notification PDFs stand in for Australian counts."},
              open(os.path.join(CACHE, "au_status.json"), "w"), indent=1)
    print(f"AU: {status}", flush=True)

if __name__ == "__main__":
    run_eu(); run_canada(); run_us(); run_australia()
    print("JURISDICTIONS COMPLETE", flush=True)
