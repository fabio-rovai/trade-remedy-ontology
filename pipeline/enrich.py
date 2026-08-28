"""Enrich the harvested tariff slice with two external checks.

1. Dereference every legal citation locator and record HTTP status, title and
   revocation state as a ResolutionObservation.
2. Resolve every named exporter against GLEIF and record how many distinct
   entities the published name matches.

Both are resumable from JSONL caches. Neither circumvents any access control.
"""
import json, os, re, sys, threading, time
import urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
COMMODITIES = os.path.join(CACHE, "commodities.jsonl")
RES_JSONL = os.path.join(CACHE, "resolutions.jsonl")
GLEIF_JSONL = os.path.join(CACHE, "gleif.jsonl")

_lock = threading.Lock()
UA = {"User-Agent": "curl/8.7.1"}  # honest UA; never spoof a browser

def append(path, obj):
    with _lock:
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            f.flush()

def load_keys(path, key):
    out = set()
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                out.add(json.loads(line)[key])
            except Exception:
                pass
    return out

def load_records():
    return [json.loads(l) for l in open(COMMODITIES) if l.strip()]

# ---- citation code parsing -------------------------------------------------

def parse_code(code):
    """Return (year, number) from a UK legal citation code, or None.

    Handles every variant observed in the operative tariff:
      'S.I. 2020/1430', '2022 No. 748', '2022 No.998',
      'Statutory Instruments  2019 No. 450'
    """
    if not code:
        return None
    c = " ".join(code.split())
    m = re.search(r"(?:S\.I\.|Statutory Instruments?)\s*(\d{4})[/ ]+(?:No\.?\s*)?(\d+)", c, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b(\d{4})\s*No\.?\s*(\d+)", c, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b(\d{4})/(\d+)\b", c)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None

def parse_locator(url):
    """Return (year, number) from a legislation.gov.uk uksi locator, or None."""
    if not url:
        return None
    m = re.search(r"/uksi/(\d{4})/(\d+)", url)
    return (int(m.group(1)), int(m.group(2))) if m else None

# ---- resolution ------------------------------------------------------------

def resolve(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            html = r.read(200000).decode("utf-8", "replace")
            status, final = r.status, r.url
    except urllib.error.HTTPError as e:
        return {"http_status": e.code, "title": None, "revoked": None, "final_url": url}
    except Exception as e:
        return {"http_status": None, "title": None, "revoked": None,
                "final_url": url, "error": type(e).__name__}
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = " ".join(m.group(1).split()) if m else None
    revoked = None
    if title:
        revoked = bool(re.search(r"\((revoked|repealed)\)", title, re.I))
    return {"http_status": status, "title": title, "revoked": revoked, "final_url": final}

def run_resolutions():
    recs = load_records()
    acts = {}
    for r in recs:
        for aid, a in r["legal_acts"].items():
            acts[aid] = a
    done = load_keys(RES_JSONL, "legal_act_id")
    todo = [(k, v) for k, v in acts.items() if k not in done]
    print(f"legal acts: {len(acts)} distinct, {len(todo)} to resolve", flush=True)

    def one(item):
        aid, a = item
        url = a.get("regulation_url")
        code = a.get("regulation_code")
        rec = {"legal_act_id": aid, "regulation_code": code, "regulation_url": url,
               "code_parsed": parse_code(code), "locator_parsed": parse_locator(url)}
        rec["resolution"] = resolve(url) if url else None
        cp, lp = rec["code_parsed"], rec["locator_parsed"]
        rec["code_locator_agreement"] = (cp == lp) if (cp and lp) else None
        append(RES_JSONL, rec)

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(one, todo))

# ---- GLEIF -----------------------------------------------------------------

def gleif_count(name):
    """Exact legal-name match count and the LEIs it returns. Keyless API."""
    q = urllib.parse.quote(name)
    url = (f"https://api.gleif.org/api/v1/lei-records"
           f"?filter%5Bentity.legalName%5D={q}&page%5Bsize%5D=5")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.loads(r.read().decode())
            total = d.get("meta", {}).get("pagination", {}).get("total", 0)
            leis = [x["id"] for x in d.get("data", [])]
            return {"total": total, "leis": leis}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            return {"total": None, "leis": [], "error": f"HTTP {e.code}"}
        except Exception as e:
            time.sleep(2 * (attempt + 1))
    return {"total": None, "leis": [], "error": "retries exhausted"}

def clean_name(raw):
    """Undo the publication layer's own damage before querying an entity register."""
    s = raw or ""
    s = re.sub(r"<[^>]+>", " ", s)                       # raw markup
    s = (s.replace("&amp;", "&").replace("&lt;", "<")
           .replace("&gt;", ">").replace("&quot;", '"'))  # double encoding
    s = s.replace("’", "'").replace("‘", "'")   # typographic apostrophes
    return " ".join(s.split())

def run_gleif():
    recs = load_records()
    names = {}
    for r in recs:
        for code, a in r["additional_codes"].items():
            d = a.get("description") or ""
            if d:
                names.setdefault(clean_name(d), set()).add(a.get("code") or code)
    done = load_keys(GLEIF_JSONL, "name")
    todo = [n for n in names if n not in done]
    print(f"exporter names: {len(names)} distinct, {len(todo)} to resolve", flush=True)

    def one(n):
        res = gleif_count(n)
        append(GLEIF_JSONL, {"name": n, "codes": sorted(names[n]), **res})

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(one, todo))

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "resolutions"):
        run_resolutions()
    if which in ("all", "gleif"):
        run_gleif()
    print("ENRICH COMPLETE", flush=True)
