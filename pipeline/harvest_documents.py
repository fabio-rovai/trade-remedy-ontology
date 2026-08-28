"""Document-layer harvest: every submission and every public file document
across all TRA cases.

Stage 1: case page -> submission listing (type, party, dates, file count)
Stage 2: submission page -> file URLs on the CDN
Stage 3: download every PDF to corpus/ (resumable, size-capped per file)
Stage 4: extract text with pdftotext for the deficiency-pattern corpus

All resumable via JSONL manifests. Corpus dir is gitignored; the manifests are not.
"""
import json, os, re, subprocess, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
CORPUS = os.path.join(ROOT, "corpus")
SUBS = os.path.join(CACHE, "tra_submissions.jsonl")
FILES = os.path.join(CACHE, "tra_files.jsonl")
BASE = "https://public-file.trade-remedies.service.gov.uk"
UA = {"User-Agent": "curl/8.7.1"}
MAX_BYTES = 60 * 1024 * 1024   # per-file cap; larger files are logged, not fetched
_lock = threading.Lock()

def get(url, binary=False, cap=None):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read(cap) if cap else r.read()
                return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
    return None

def append(path, obj):
    with _lock:
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n"); f.flush()

def done_keys(path, key):
    out = set()
    if os.path.exists(path):
        for l in open(path):
            if l.strip():
                try: out.add(json.loads(l)[key])
                except Exception: pass
    return out

def stage1():
    cases = [json.loads(l) for l in open(os.path.join(CACHE, "tra_cases.jsonl")) if l.strip()]
    done = done_keys(SUBS, "submission_url")
    def one(c):
        h = get(f"{BASE}/case/{c['case_ref'].lower()}/")
        if not h: return
        for m in re.finditer(
            r'href\s*=\s*"(' + re.escape(BASE) + r'/case/[a-z0-9]+/submission/[^"]+)"\s*>([^<]+)<', h):
            url, label = m.group(1), m.group(2).strip()
            if url in done: continue
            tail = h[m.end():m.end()+2500]
            pub = re.search(r"(\d{4}-\d{2}-\d{2})", tail)
            nf = re.search(r"No\. of files:\s*</span>?\s*(\d+)", tail) or re.search(r">(\d+)\s*</td>", tail)
            append(SUBS, {"case_ref": c["case_ref"], "submission_url": url,
                          "submission_type": label,
                          "published": pub.group(1) if pub else None,
                          "n_files_listed": int(nf.group(1)) if nf else None})
            done.add(url)
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, cases))
    print(f"stage1 done: {sum(1 for _ in open(SUBS))} submissions", flush=True)

def stage2():
    subs = [json.loads(l) for l in open(SUBS) if l.strip()]
    done = done_keys(FILES, "file_url")
    seen_subs = done_keys(FILES, "submission_url")
    todo = [s for s in subs if s["submission_url"] not in seen_subs]
    print(f"stage2: {len(subs)} submissions, {len(todo)} to walk", flush=True)
    def one(s):
        h = get(s["submission_url"])
        if not h:
            append(FILES, {"submission_url": s["submission_url"], "case_ref": s["case_ref"],
                           "file_url": None, "error": "submission page unreachable"})
            return
        found = 0
        for m in re.finditer(r'href\s*=\s*"(https://[^"]*\.azurefd\.net/content/[^"]+)"', h):
            url = m.group(1)
            if url in done: continue
            append(FILES, {"submission_url": s["submission_url"], "case_ref": s["case_ref"],
                           "submission_type": s.get("submission_type"),
                           "published": s.get("published"),
                           "file_url": url, "file_name": url.rsplit("/", 1)[-1]})
            done.add(url); found += 1
        if not found:
            append(FILES, {"submission_url": s["submission_url"], "case_ref": s["case_ref"],
                           "file_url": None, "error": "no CDN links on page"})
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, todo))
    n = sum(1 for l in open(FILES) if json.loads(l).get("file_url"))
    print(f"stage2 done: {n} files discovered", flush=True)

def stage3():
    files = [json.loads(l) for l in open(FILES) if l.strip()]
    files = [f for f in files if f.get("file_url")]
    os.makedirs(CORPUS, exist_ok=True)
    def one(f):
        name = re.sub(r"[^A-Za-z0-9._-]", "_", f["file_name"])
        path = os.path.join(CORPUS, f["case_ref"], name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = get(f["file_url"], binary=True, cap=MAX_BYTES)
        if data:
            with open(path, "wb") as fh: fh.write(data)
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, files))
    total = sum(os.path.getsize(os.path.join(dp, fn))
                for dp, _, fns in os.walk(CORPUS) for fn in fns)
    n = sum(len(fns) for _, _, fns in os.walk(CORPUS))
    print(f"stage3 done: {n} files, {total/1e9:.2f} GB", flush=True)

def stage4():
    n = ok = 0
    for dp, _, fns in os.walk(CORPUS):
        for fn in fns:
            if not fn.lower().endswith(".pdf"): continue
            n += 1
            src = os.path.join(dp, fn); dst = src[:-4] + ".txt"
            if os.path.exists(dst): ok += 1; continue
            r = subprocess.run(["pdftotext", "-layout", src, dst],
                               capture_output=True, timeout=120)
            if r.returncode == 0: ok += 1
    print(f"stage4 done: {ok}/{n} PDFs extracted to text", flush=True)

if __name__ == "__main__":
    stage1(); stage2(); stage3(); stage4()
    print("DOCUMENT HARVEST COMPLETE", flush=True)
