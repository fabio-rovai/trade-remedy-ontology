"""Harvest WTO anti-dumping and countervailing measure counts by reporting member.

The WTO Timeseries API requires a subscription key. These PDFs do not: they are
published open on wto.org and extract cleanly with pdftotext -layout. They give
an independent, third-party count of measures each member has notified, which is
the cross-check for anything we compute from a single national tariff.
"""
import json, os, re, subprocess, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "wto_measures.json")
UA = {"User-Agent": "curl/8.7.1"}
SOURCES = {
    "anti_dumping_by_reporting_member":
        "https://www.wto.org/english/tratop_e/adp_e/AD_MeasuresByRepMem.pdf",
    "anti_dumping_by_exporting_country":
        "https://www.wto.org/english/tratop_e/adp_e/AD_MeasuresByExpCty.pdf",
    "countervailing_by_reporting_member":
        "https://www.wto.org/english/tratop_e/scm_e/CV_MeasuresByRepMem.pdf",
}

def fetch(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        open(path, "wb").write(r.read())

def parse(txt):
    """Rows are 'Name  y1 y2 ... Total'. Footnote markers and provisional
    asterisks are preserved on the name so nothing is silently normalised."""
    out, title, years = {}, None, []
    for line in txt.split("\n"):
        if not line.strip():
            continue
        if title is None:
            title = line.strip()
            continue
        if line.strip().startswith("Reporting Member") or line.strip().startswith("Exporting"):
            years = re.findall(r"\b(19|20)\d{2}\b", line)
            years = re.findall(r"\b((?:19|20)\d{2})\b", line)
            continue
        m = re.match(r"^\s*(.+?)\s{2,}(\d[\d\s\*]*)$", line)
        if not m:
            continue
        name = m.group(1).strip()
        nums = m.group(2).split()
        total = None
        for tok in reversed(nums):
            if tok.isdigit():
                total = int(tok)
                break
        out[name] = {"total": total, "cells": nums}
    return {"title": title, "years": years, "members": out}

def main():
    os.makedirs(CACHE, exist_ok=True)
    result = {}
    for key, url in SOURCES.items():
        pdf = os.path.join(CACHE, key + ".pdf")
        if not os.path.exists(pdf):
            fetch(url, pdf)
        txt = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                             capture_output=True, text=True, check=True).stdout
        result[key] = {"source_url": url, **parse(txt)}
        n = len(result[key]["members"])
        uk = result[key]["members"].get("United Kingdom", {}).get("total")
        print(f"{key}: {n} members parsed, United Kingdom total = {uk}", flush=True)
    json.dump(result, open(OUT, "w"), indent=2)
    print(f"written to {OUT}")

if __name__ == "__main__":
    main()
