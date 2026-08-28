# Trade Remedy Ontology

An open ontology and validation suite for UK trade remedy measures, tested end to end
against the TRA case register, the full UK Trade Tariff, legislation.gov.uk, the WTO
measure notifications and the Global LEI System.

Every anti-dumping and countervailing duty the UK charges runs a chain: an investigating
authority opens a case, the case names commodity codes, a legal instrument gives the
resulting measure force, and the measure assigns a duty rate to a named exporter. This
repository models that chain and then checks whether it holds together.

It breaks in twenty-five places. All twenty-five are repaired here.

## What was measured

| | |
|---|---|
| Commodity codes visited | 21,008, the complete UK tariff |
| Commodities carrying a remedy measure | 405 |
| Distinct measures | 9,385 |
| Legal instruments cited by those measures | 49 of 119 present |
| Additional codes assigning duty to a named exporter | 990 |
| TRA cases harvested | 92, of which 91 publish commodity codes |
| Triples | 103,780 |

## Finding 1: the tariff truncates the legal instrument link at 200 characters

- 13 of the 49 cited instruments publish a locator of **exactly 200 characters**, cut mid word
- **all 13 return HTTP 404**
- **every locator shorter than 200 characters returns HTTP 200**
- no locator in the set exceeds 200 characters

That is a field length limit rather than a content error. It falls almost entirely on
trade remedies notices, whose gov.uk paths are the longest in the set.

**1,477 of the 9,385 live measures, 15.7 percent, publish a broken link to the instrument
that gives them legal force.**

All thirteen are repaired in
[`repairs/legal_act_url_repairs.csv`](repairs/legal_act_url_repairs.csv). For each we
fetched the gov.uk collection page named in the surviving prefix and filtered its links
to those beginning with the truncated string. Every one yielded exactly one candidate,
and every candidate returned HTTP 200. A repair is recorded only where it is a strict
continuation of what was published, never a substitution.

## Finding 2: the case register drops leading zeros from commodity codes

A UK commodity code is 6, 8 or 10 digits. Two TRA cases, **ER0080 (Active)** and
**TS0002 (Completed)**, each publish six **nine-digit** codes. Every one returns HTTP 404
against the tariff. Restore the leading zero and every one returns HTTP 200 and resolves
to a trout product, which is what both cases are about.

```
301919011  ->  404        0301919011  ->  200  Weighing 1.2 kg or less each
304429010  ->  404        0304429010  ->  200  Of the species Oncorhynchus mykiss
```

That is a numeric cast stripping a leading zero on chapter 3 goods. All twelve are
repaired in [`repairs/tra_case_code_repairs.json`](repairs/tra_case_code_repairs.json).
A repair is accepted only where the published value fails to resolve **and** the restored
value resolves.

## Finding 3: legal citation format is ungoverned

87 citation records match neither declared citation scheme. One class of instrument is
cited as `Trade remedies notice 2025/20`, `Trade Remedies Notice: 2024/11`, `Trade
Remedies Notice 2026/20`, `Taxation Notice: 2023/014`, `Taxation notice 2022/10`,
`2026/23`, `2025 No.7`, `2025 NO.13` and, in one record, simply `15`. The most cited
instrument of all, at 6,738 citations, is recorded as `Statutory Instruments  2019 No.
450`, with a double space.

## Finding 4: the exporter name field is not a name field

Of 982 named exporters, 955 do not resolve to exactly one entity under a GLEIF legal name
lookup. 60.6 percent mix the company name with address fragments, so `Cargill Inc.,
Wayzata` and `BIOX Corporation, Oakville, Ontario, Canada` are single field values. 65
carry raw HTML markup or double encoded entities, including a `<br>` tag inside a company
name. 55 pack more than one legal entity into one value. Fourteen state a scope rule
rather than naming anyone, for example `Sustainable Aviation Fuel is excluded from the
measure`.

## The case to measure join

79 of the 92 TRA cases join to at least one commodity carrying a measure. 8 of the 405
commodities carrying measures are named by no TRA case. Of 2,204 commodity codes
published across the case register, 1,393 carry a measure and 811 do not, the latter
concentrated in completed cases whose measures have since expired.

For independent context the WTO's own notification data is harvested from the open PDFs
at wto.org, which need no subscription key and extract cleanly with `pdftotext -layout`.
The WTO records the United Kingdom as having notified **7** anti-dumping measures and
**3** countervailing measures in total since 1995, against 46 measures in force per the
TRA's 2025-26 annual report. The UK's in-force book is therefore overwhelmingly inherited
rather than UK-originated, which is the correct frame for reading everything above.

## Design

Identity and legal citation are modelled as **dated assertions by a named source**, never
as properties of a thing, so that disagreement between registers is representable rather
than lost.

- `IdentifierAssertion` records who published which identifier for whom, with
  `schemeConformant`, `nonConformanceReason` and `resolutionCardinality`
- `LegalCitationAssertion` records the citation code and the locator **separately**,
  because they can disagree, with `codeLocatorAgreement`
- `ResolutionObservation` records what a locator returned on a given date, including
  whether the instrument it reached is marked revoked
- `RemedyCase` records commodity codes **exactly as published**, before any repair, so
  that granularity defects survive into the graph instead of being normalised away

Each identifier and citation scheme declares its **own conformance rules as data** in
[`ontology/schemes.ttl`](ontology/schemes.ttl), so adding a jurisdiction means adding a
concept rather than editing code.

SHACL carries one shape per defect class, so the validation report is the findings table.

## Reproduce it

```bash
pip install rdflib pyshacl pytest      # pdftotext for the WTO step

python3 pipeline/reharvest_tr.py       # tariff slice, about 10 minutes
python3 pipeline/harvest_tra_cases.py  # TRA case register
python3 pipeline/harvest_wto.py        # WTO notification counts
python3 pipeline/enrich.py             # dereference locators, resolve names
python3 pipeline/build_graph.py        # emit and parse-verify the graph
python3 pipeline/governance_report.py  # every figure twice, non-zero on disagreement
python3 pipeline/repair_urls.py        # rebuild the truncated locators
python3 pipeline/repair_case_codes.py  # restore the stripped leading zeros
pytest tests/ -v
```

`governance_report.py` computes all twenty headline figures set-based in Python **and**
again by SPARQL over the graph, and exits non-zero if the two disagree. Nothing here is
asserted from a single computation path.

## Validation

Three independent engines, all agreeing.

| | |
|---|---|
| `open-ontologies` v1.2.0 | 103,780 triples, agreeing exactly with rdflib. `lint` zero issues. Closed-world `vocab-check` conforms, zero undeclared terms. |
| pyshacl 0.40.1 | 1,136 violations across six defect classes |
| `open-ontologies shacl` | the same 1,136, plus 955 from an independent range formulation of the same rule |

Validating this vertical exposed a gap in our own engine: `sh:minInclusive` and
`sh:maxInclusive` were collected by neither the shape query nor the known-predicate
filter, so a shape carrying either was reported as skipped and suppressed the verdict to
null. Fixed in
[open-ontologies a44f668](https://github.com/fabio-rovai/open-ontologies/commit/a44f668),
with regression tests pinned against pyshacl on a shared fixture.

[`BUILD_REPORT.md`](BUILD_REPORT.md) records exactly what was fetched, every claim that
was tested and dropped, and the bugs caught mid-build.

## Licence

Code MIT. Ontology, shapes and documentation CC BY 4.0. Source data from the UK Trade
Tariff, the TRA public file and legislation.gov.uk is Crown copyright under the Open
Government Licence v3.0; GLEIF data is CC0; WTO notification tables are published open on
wto.org.

## What else this repository carries

**A measure expiry tracker**, in [`tracker/`](tracker/). Which UK measures expire when,
by commodity and exporter, regenerated from the live tariff by
[`pipeline/expiry_tracker.py`](pipeline/expiry_tracker.py). 2,792 dated measures across
22 expiry dates; 3 measures expire on 30 August 2026, and the largest single cliff is
900 measures on 6 April 2027. Every per-date count is computed twice, set-based and by
SPARQL through the [open-ontologies engine](https://github.com/fabio-rovai/open-ontologies),
and the build fails on disagreement.

**The start of a cross-jurisdiction divergence map.** The EU parent regulations the UK
book still cites are checked for in-force status against the Publications Office record
in [`cache/eu_parent_regs.jsonl`](cache/eu_parent_regs.jsonl); both are no longer in
force in the EU. The Canadian register is parsed in
[`cache/ca_measures.json`](cache/ca_measures.json), 189 measures and 4,681 codes with
zero malformed tokens, and US Federal Register order counts are in
[`cache/us_fedreg.json`](cache/us_fedreg.json). The full map, every transitioned UK
measure against its EU counterpart rate by rate and scope by scope, is the natural next
step; if it would be useful to you, email us.

## Contact

Built by [The Tesseract Academy](https://gov.tesseract.academy/).

If you run a register and want the same census run against it, or you want these repairs
as a patch against your own pipeline, email **fabio@thetesseractacademy.com**.
