"""Emit the trade remedy graph as Turtle text, then parse-verify it.

Direct text emission rather than rdflib construction, because rdflib is a fine
parser and a slow builder at this scale (see the BRO build report).
"""
import json, os, re, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(ROOT, "graph", "traderemedy.ttl")
TODAY = date.today().isoformat()

TRADE = "https://gov.tesseract.academy/def/traderemedy#"
SCHEME = "https://gov.tesseract.academy/def/traderemedy/scheme#"
BASE = "https://gov.tesseract.academy/id/traderemedy/"

sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from enrich import clean_name

def esc(s):
    if s is None:
        return ""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", ""))

def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-")

def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]

def main():
    commodities = jl(os.path.join(CACHE, "commodities.jsonl"))
    resolutions = {r["legal_act_id"]: r for r in jl(os.path.join(CACHE, "resolutions.jsonl"))}
    gleif = {g["name"]: g for g in jl(os.path.join(CACHE, "gleif.jsonl"))}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    L = []
    w = L.append
    w(f"@prefix trade: <{TRADE}> .")
    w(f"@prefix scheme: <{SCHEME}> .")
    w(f"@prefix id: <{BASE}> .")
    w("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
    w("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
    w("")

    exporters = {}   # code -> raw label
    acts_seen = set()
    n_measures = 0

    for rec in commodities:
        cid = rec["id"]
        w(f'id:commodity-{cid} a trade:Commodity ; rdfs:label "{esc(rec.get("description"))}" .')
        for m in rec["measures"]:
            n_measures += 1
            mid = f"id:measure-{m['measure_id']}"
            w(f"{mid} a trade:TradeRemedyMeasure ;")
            w(f"    trade:appliesToCommodity id:commodity-{cid} ;")
            w(f"    trade:hasMeasureType id:measuretype-{m['measure_type']} ;")
            ga = m.get("geographical_area")
            if ga:
                w(f"    trade:appliesToArea id:area-{slug(ga)} ;")
            ac = m.get("additional_code")
            if ac:
                w(f"    trade:namesExporter id:exporter-{slug(ac)} ;")
            for la in (m.get("legal_acts") or []):
                w(f"    trade:citesInstrument id:instrument-{slug(la)} ;")
            a = m.get("attributes", {})
            vf, vt = a.get("effective_start_date"), a.get("effective_end_date")
            if vf:
                w(f'    trade:validFrom "{vf[:10]}"^^xsd:date ;')
            if vt:
                w(f'    trade:validTo "{vt[:10]}"^^xsd:date ;')
            w(f'    rdfs:label "measure {m["measure_id"]}" .')

            if ac and ac in rec["additional_codes"]:
                exporters[ac] = rec["additional_codes"][ac]
            for la in (m.get("legal_acts") or []):
                if la in rec["legal_acts"]:
                    acts_seen.add(la)

        for code, attrs in rec["additional_codes"].items():
            exporters.setdefault(code, attrs)
        for aid in rec["legal_acts"]:
            acts_seen.add(aid)

    # Exporters, and the identifier assertions about them.
    for code, attrs in exporters.items():
        raw = attrs.get("description") or ""
        cleaned = clean_name(raw)
        eid = f"id:exporter-{slug(code)}"
        residual = bool(re.search(r"all other|residual", cleaned, re.I))
        w(f"{eid} a trade:Exporter ;")
        w(f'    trade:exporterLabel "{esc(raw)}" ;')
        w(f'    trade:isResidualRate {"true" if residual else "false"} ;')
        w(f'    rdfs:label "{esc(cleaned)}" .')

        # The additional code itself is an identifier assertion by HMRC.
        aid_n = f"id:idassert-addcode-{slug(code)}-{TODAY}"
        w(f"{aid_n} a trade:IdentifierAssertion ;")
        w(f"    trade:assertionSubject {eid} ;")
        w(f'    trade:assertedBy "His Majesty\'s Revenue and Customs" ;')
        w(f'    trade:assertedOn "{TODAY}"^^xsd:date ;')
        w(f"    trade:identifierScheme scheme:UKAdditionalCode ;")
        w(f'    trade:identifierValue "{esc(attrs.get("code") or code)}" .')

        # What GLEIF says about the published name.
        g = gleif.get(cleaned)
        if g is not None and not residual:
            total = g.get("total")
            leis = g.get("leis") or []
            lid = f"id:idassert-lei-{slug(code)}-{TODAY}"
            if total:
                w(f"{lid} a trade:IdentifierAssertion ;")
                w(f"    trade:assertionSubject {eid} ;")
                w(f'    trade:assertedBy "GLEIF" ;')
                w(f'    trade:assertedOn "{TODAY}"^^xsd:date ;')
                w(f"    trade:identifierScheme scheme:LEI ;")
                w(f"    trade:resolutionCardinality {int(total)} ;")
                w(f'    trade:schemeConformant true ;')
                w(f'    trade:identifierValue "{esc(leis[0]) if leis else ""}" .')
            else:
                w(f"{lid} a trade:IdentifierAssertion ;")
                w(f"    trade:assertionSubject {eid} ;")
                w(f'    trade:assertedBy "GLEIF" ;')
                w(f'    trade:assertedOn "{TODAY}"^^xsd:date ;')
                w(f"    trade:identifierScheme scheme:LEI ;")
                w(f"    trade:resolutionCardinality 0 ;")
                w(f'    trade:nonConformanceReason "published name does not match any GLEIF legal name" ;')
                w(f'    trade:identifierValue "" .')

    # Legal instruments, citation assertions, resolution observations.
    all_acts = {}
    for rec in commodities:
        all_acts.update(rec["legal_acts"])
    for aid, attrs in all_acts.items():
        iid = f"id:instrument-{slug(aid)}"
        code = attrs.get("regulation_code")
        url = attrs.get("regulation_url")
        w(f"{iid} a trade:LegalInstrument ;")
        w(f'    rdfs:label "{esc(code)}" .')

        cid_n = f"id:citation-{slug(aid)}-{TODAY}"
        w(f"{cid_n} a trade:LegalCitationAssertion ;")
        w(f"    trade:assertionSubject {iid} ;")
        w(f'    trade:assertedBy "UK Trade Tariff" ;')
        w(f'    trade:assertedOn "{TODAY}"^^xsd:date ;')
        if code:
            w(f'    trade:citationCode "{esc(code)}" ;')
        if url:
            w(f'    trade:citationLocator "{esc(url)}"^^xsd:anyURI ;')
        r = resolutions.get(aid)
        agree = r.get("code_locator_agreement") if r else None
        if agree is not None:
            w(f'    trade:codeLocatorAgreement {"true" if agree else "false"} ;')
        w(f'    rdfs:label "citation of {esc(code)}" .')

        if r and r.get("resolution"):
            res = r["resolution"]
            rid = f"id:resolution-{slug(aid)}-{TODAY}"
            w(f"{rid} a trade:ResolutionObservation ;")
            w(f"    trade:assertionSubject {iid} ;")
            w(f'    trade:assertedBy "legislation.gov.uk" ;')
            w(f'    trade:assertedOn "{TODAY}"^^xsd:date ;')
            if res.get("http_status") is not None:
                w(f'    trade:httpStatus {int(res["http_status"])} ;')
            if res.get("title"):
                w(f'    trade:resolvedTitle "{esc(res["title"])}" ;')
            if res.get("revoked") is not None:
                w(f'    trade:resolvedRevoked {"true" if res["revoked"] else "false"} ;')
            w(f'    rdfs:label "resolution of {esc(code)}" .')

    with open(OUT, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"emitted {OUT}: {len(L)} lines, {n_measures} measures, "
          f"{len(exporters)} exporters, {len(all_acts)} legal acts", flush=True)

    # TRA case register, and the join to commodities carrying measures.
    cases = jl(os.path.join(CACHE, "tra_cases.jsonl"))
    tariff = {rec["id"] for rec in commodities}
    L2 = []
    for c in cases:
        cid = f"id:case-{slug(c['case_ref'])}"
        L2.append(f"{cid} a trade:RemedyCase ;")
        L2.append(f'    trade:caseReference "{esc(c["case_ref"])}" ;')
        if c.get("status"):
            L2.append(f'    trade:caseStatus "{esc(c["status"])}" ;')
        if c.get("applicant"):
            L2.append(f'    trade:caseApplicant "{esc(c["applicant"])}" ;')
        if c.get("initiation_date"):
            L2.append(f'    trade:initiationDate "{esc(c["initiation_date"])}" ;')
        for code in c.get("commodity_codes") or []:
            L2.append(f'    trade:namesCommodityCode "{esc(code)}" ;')
            if code in tariff:
                L2.append(f"    trade:caseCoversCommodity id:commodity-{code} ;")
            else:
                for t in tariff:
                    if len(code) < 10 and t.startswith(code):
                        L2.append(f"    trade:caseCoversCommodity id:commodity-{t} ;")
        L2.append(f'    rdfs:label "{esc(c["case_ref"])} {esc((c.get("title") or "")[:70])}" .')
        # granularity is a property of the published code, asserted per case
        for code in c.get("commodity_codes") or []:
            valid = len(code) in (6, 8, 10)
            L2.append(f'{cid} trade:codeGranularityValid {"true" if valid else "false"} .' if not valid else "")
    with open(OUT, "a") as f:
        f.write("\n".join(x for x in L2 if x) + "\n")
    print(f"appended {len(cases)} TRA cases", flush=True)

    import rdflib
    g = rdflib.Graph()
    g.parse(OUT, format="turtle")
    print(f"parse-verified: {len(g)} triples", flush=True)

if __name__ == "__main__":
    main()
