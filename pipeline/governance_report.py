"""Compute every headline figure twice and exit non-zero on disagreement.

Path A is set-based Python over the JSONL caches.
Path B is SPARQL over the built graph.
A number only one path can produce is not a finding, it is a bug.
"""
import json, os, re, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
GRAPH = os.path.join(ROOT, "graph", "traderemedy.ttl")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from enrich import clean_name
T = "https://gov.tesseract.academy/def/traderemedy#"
S = "https://gov.tesseract.academy/def/traderemedy/scheme#"
CAP = 200

def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []

def main():
    recs = jl(os.path.join(CACHE, "commodities.jsonl"))
    R = {r["legal_act_id"]: r for r in jl(os.path.join(CACHE, "resolutions.jsonl"))}

    A = {}
    A["commodities_with_remedies"] = len(recs)
    A["distinct_measures"] = len({m["measure_id"] for r in recs for m in r["measures"]})

    ac = {}
    for r in recs:
        ac.update(r["additional_codes"])
    A["exporter_codes"] = len(ac)
    named = {k: clean_name(a.get("description") or "") for k, a in ac.items()}
    resid = {k for k, v in named.items() if re.search(r"all other|residual", v, re.I)}
    A["residual_codes"] = len(resid)
    A["named_exporters"] = len(ac) - len(resid)
    A["names_with_markup"] = sum(
        1 for a in ac.values()
        if re.search(r"<[a-zA-Z/][^>]*>", a.get("description") or "")
        or re.search(r"&(amp|lt|gt|quot|#[0-9]+);", a.get("description") or ""))

    acts = {}
    for r in recs:
        acts.update(r["legal_acts"])
    A["legal_acts_present"] = len(acts)
    cited = collections.Counter()
    meas_by_act = collections.defaultdict(set)
    for r in recs:
        for m in r["measures"]:
            for a in m.get("legal_acts") or []:
                cited[a] += 1
                meas_by_act[a].add(m["measure_id"])
    A["legal_acts_cited_by_measures"] = len(cited)
    A["locators_at_200_cap"] = sum(
        1 for a in acts.values() if len(a.get("regulation_url") or "") == CAP)
    trunc404 = [k for k, v in acts.items()
                if len(v.get("regulation_url") or "") == CAP
                and (R.get(k, {}).get("resolution") or {}).get("http_status") == 404]
    A["truncated_locators_returning_404"] = len(trunc404)
    A["measures_resting_on_a_dead_locator"] = len(set().union(*[meas_by_act[a] for a in trunc404])) if trunc404 else 0
    A["locator_revoked"] = sum(
        1 for k in acts if (R.get(k, {}).get("resolution") or {}).get("revoked") is True)
    A["citation_code_locator_disagreement"] = sum(
        1 for k in acts if R.get(k, {}).get("code_locator_agreement") is False)
    A["citation_scheme_nonconformant"] = sum(
        1 for v in acts.values()
        if v.get("regulation_code")
        and not re.match(r"^S\.I\. \d{4}/\d+$", v["regulation_code"])
        and not re.match(r"^Taxation Notice: \d{4}/\d{3}$", v["regulation_code"]))

    G = {g["name"]: g for g in jl(os.path.join(CACHE, "gleif.jsonl"))}
    A["names_not_resolving_to_one_entity"] = sum(
        1 for k, v in named.items()
        if k not in resid and (G.get(v, {}).get("total") if G.get(v) else None) != 1)

    cases = jl(os.path.join(CACHE, "tra_cases.jsonl"))
    A["tra_cases"] = len(cases)
    A["tra_cases_publishing_codes"] = sum(1 for c in cases if c["commodity_codes"])
    A["tra_published_codes"] = sum(len(c["commodity_codes"]) for c in cases)
    A["tra_codes_with_invalid_granularity"] = sum(
        1 for c in cases for x in c["commodity_codes"] if len(x) not in (6, 8, 10))
    tariff = {r["id"] for r in recs}
    A["tra_cases_joined_to_a_measured_commodity"] = sum(
        1 for c in cases
        if any(x in tariff or (len(x) < 10 and any(t.startswith(x) for t in tariff))
               for x in c["commodity_codes"]))

    import rdflib
    g = rdflib.Graph(); g.parse(GRAPH, format="turtle")
    def one(q): return int(list(g.query(q))[0][0].toPython())

    B = {}
    B["commodities_with_remedies"] = one(f"SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{ ?c a <{T}Commodity> }}")
    B["distinct_measures"] = one(f"SELECT (COUNT(DISTINCT ?m) AS ?n) WHERE {{ ?m a <{T}TradeRemedyMeasure> }}")
    B["exporter_codes"] = one(f"SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE {{ ?e a <{T}Exporter> }}")
    B["residual_codes"] = one(f"SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE {{ ?e a <{T}Exporter> ; <{T}isResidualRate> true }}")
    B["named_exporters"] = one(f"SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE {{ ?e a <{T}Exporter> ; <{T}isResidualRate> false }}")
    B["names_with_markup"] = one(f"""SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE {{
        ?e a <{T}Exporter> ; <{T}exporterLabel> ?l .
        FILTER (REGEX(?l,"<[a-zA-Z/][^>]*>") || REGEX(?l,"&(amp|lt|gt|quot|#[0-9]+);")) }}""")
    B["legal_acts_present"] = one(f"SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE {{ ?i a <{T}LegalInstrument> }}")
    B["legal_acts_cited_by_measures"] = one(f"SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE {{ ?m <{T}citesInstrument> ?i }}")
    B["locators_at_200_cap"] = one(f"""SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{
        ?c a <{T}LegalCitationAssertion> ; <{T}citationLocator> ?u .
        FILTER (STRLEN(STR(?u)) = {CAP}) }}""")
    B["truncated_locators_returning_404"] = one(f"""SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE {{
        ?c a <{T}LegalCitationAssertion> ; <{T}assertionSubject> ?i ; <{T}citationLocator> ?u .
        FILTER (STRLEN(STR(?u)) = {CAP})
        ?r a <{T}ResolutionObservation> ; <{T}assertionSubject> ?i ; <{T}httpStatus> 404 . }}""")
    B["measures_resting_on_a_dead_locator"] = one(f"""SELECT (COUNT(DISTINCT ?m) AS ?n) WHERE {{
        ?m <{T}citesInstrument> ?i .
        ?c a <{T}LegalCitationAssertion> ; <{T}assertionSubject> ?i ; <{T}citationLocator> ?u .
        FILTER (STRLEN(STR(?u)) = {CAP})
        ?r a <{T}ResolutionObservation> ; <{T}assertionSubject> ?i ; <{T}httpStatus> 404 . }}""")
    B["locator_revoked"] = one(f"SELECT (COUNT(DISTINCT ?r) AS ?n) WHERE {{ ?r a <{T}ResolutionObservation> ; <{T}resolvedRevoked> true }}")
    B["citation_code_locator_disagreement"] = one(f"SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{ ?c a <{T}LegalCitationAssertion> ; <{T}codeLocatorAgreement> false }}")
    B["citation_scheme_nonconformant"] = one(f"""SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{
        ?c a <{T}LegalCitationAssertion> ; <{T}citationCode> ?code .
        FILTER (!REGEX(?code,"^S\\\\.I\\\\. [0-9]{{4}}/[0-9]+$"))
        FILTER (!REGEX(?code,"^Taxation Notice: [0-9]{{4}}/[0-9]{{3}}$")) }}""")
    B["names_not_resolving_to_one_entity"] = one(f"""SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE {{
        ?a <{T}assertionSubject> ?e ; <{T}identifierScheme> <{S}LEI> ; <{T}resolutionCardinality> ?c .
        ?e <{T}isResidualRate> false .
        FILTER (?c != 1) }}""")

    B["tra_cases"] = one(f"SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{ ?c a <{T}RemedyCase> }}")
    B["tra_cases_publishing_codes"] = one(f"""SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{
        ?c a <{T}RemedyCase> ; <{T}namesCommodityCode> ?x }}""")
    B["tra_published_codes"] = one(f"""SELECT (COUNT(*) AS ?n) WHERE {{
        ?c a <{T}RemedyCase> ; <{T}namesCommodityCode> ?x }}""")
    B["tra_codes_with_invalid_granularity"] = one(f"""SELECT (COUNT(*) AS ?n) WHERE {{
        ?c a <{T}RemedyCase> ; <{T}namesCommodityCode> ?x .
        FILTER (STRLEN(?x) != 6 && STRLEN(?x) != 8 && STRLEN(?x) != 10) }}""")
    B["tra_cases_joined_to_a_measured_commodity"] = one(f"""SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{
        ?c a <{T}RemedyCase> ; <{T}caseCoversCommodity> ?x }}""")

    bad = 0
    print(f"{'metric':44}{'set-based':>11}{'SPARQL':>10}   agree")
    for k in A:
        b = B.get(k); ok = (b == A[k]); bad += (not ok)
        print(f"{k:44}{A[k]:>11}{str(b):>10}   {'yes' if ok else 'NO'}")
    os.makedirs(os.path.join(ROOT, "graph"), exist_ok=True)
    json.dump({"set_based": A, "sparql": B},
              open(os.path.join(ROOT, "graph", "headline_figures.json"), "w"), indent=2)
    if bad:
        print(f"\nDISAGREEMENT on {bad} metric(s)", file=sys.stderr); return 1
    print("\nall metrics agree across both computation paths")
    return 0

if __name__ == "__main__":
    sys.exit(main())
