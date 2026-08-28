"""Harvest the TRA public case register and extract the fields needed to join a
TRA case to the measures that appear in the operative tariff.

The join key is the commodity code list each case publishes under
"Commodities affected".
"""
import html, json, os, re, sys, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "tra_cases.jsonl")
BASE = "https://public-file.trade-remedies.service.gov.uk"
UA = {"User-Agent": "curl/8.7.1"}
_lock = threading.Lock()

def get(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
    return None

def text_of(h):
    t = re.sub(r"<script.*?</script>", " ", h, flags=re.S)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())

def field(txt, label, nxt):
    """Pull the value between a label and the next known label."""
    m = re.search(re.escape(label) + r"\s+(.*?)\s+(?:" + "|".join(re.escape(n) for n in nxt) + ")", txt)
    return m.group(1).strip() if m else None

LABELS = ["Applicant", "Country", "Last Updated", "Initiation date",
          "Commodities affected", "Public file", "Contents", "Case details",
          "Measure type", "Decision", "Email"]

def parse_case(ref, h):
    txt = text_of(h)
    title = None
    m = re.search(re.escape(ref.upper()) + r"\s*-\s*(.*?)\s+" + re.escape(ref.upper()), txt)
    if m:
        title = m.group(1).strip()
    comm = field(txt, "Commodities affected", LABELS)
    codes = re.findall(r"\b\d{8,10}\b", comm) if comm else []
    status = None
    ms = re.search(r"\b(Active|Completed|Closed|Terminated|Suspended)\b\s+([A-Z][a-z]+(?: [A-Za-z]+){0,3})", txt)
    if ms:
        status, kind = ms.group(1), ms.group(2)
    else:
        kind = None
    return {
        "case_ref": ref.upper(),
        "title": title,
        "status": status,
        "case_kind": kind,
        "applicant": field(txt, "Applicant", LABELS),
        "country": field(txt, "Country", LABELS),
        "initiation_date": field(txt, "Initiation date", LABELS),
        "last_updated": field(txt, "Last Updated", LABELS),
        "commodity_codes": sorted(set(codes)),
        "url": f"{BASE}/case/{ref.lower()}/",
    }

def discover():
    refs = set()
    for path in ["/", "/?tab=active", "/?tab=completed"]:
        h = get(BASE + path)
        if h:
            refs |= {m.upper() for m in re.findall(r"/case/([a-z]{2}\d{4})/", h)}
            refs |= set(re.findall(r"\b([A-Z]{2}\d{4})\b", h))
    return sorted(refs)

def main():
    os.makedirs(CACHE, exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip():
                done.add(json.loads(l)["case_ref"])
    refs = discover()
    todo = [r for r in refs if r not in done]
    print(f"TRA cases discovered: {len(refs)}, to fetch: {len(todo)}", flush=True)

    def one(ref):
        h = get(f"{BASE}/case/{ref.lower()}/")
        if not h:
            return
        rec = parse_case(ref, h)
        with _lock:
            with open(OUT, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, todo))
    n = sum(1 for _ in open(OUT))
    print(f"TRA CASE HARVEST COMPLETE: {n} cases", flush=True)

if __name__ == "__main__":
    main()
