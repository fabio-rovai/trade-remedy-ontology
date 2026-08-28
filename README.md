# Trade Remedy Ontology

An open ontology and validation suite for UK trade remedy measures, tested against the
full UK Trade Tariff, legislation.gov.uk and the Global LEI System.

Every anti-dumping and countervailing duty the UK charges is attached to a commodity
code, an origin, a named exporter and a legal instrument. This repository models that
chain, then checks whether it holds together. It does not hold together in thirteen
places, and this repository also contains the fix.

## The headline finding

**The UK Trade Tariff truncates the legal instrument link at 200 characters, and every
truncated link is dead.**

We visited all 21,008 commodity codes in the tariff. 405 carry a trade remedy measure,
giving 9,385 distinct measures that cite 49 legal instruments between them.

- 13 of those 49 instruments publish a locator of **exactly 200 characters**, cut mid word
- **all 13 return HTTP 404**
- **every locator shorter than 200 characters returns HTTP 200**
- no locator in the set exceeds 200 characters

That is a field length limit rather than a content error. It falls almost entirely on
trade remedies notices, whose gov.uk paths are the longest in the set.

**1,477 of the 9,385 live measures, 15.7 percent, publish a broken link to the instrument
that gives them legal force.**

## The fix

All thirteen are repaired in [`repairs/legal_act_url_repairs.csv`](repairs/legal_act_url_repairs.csv).

For each one we fetched the gov.uk collection page named in the surviving prefix, listed
the documents it links, and kept those beginning with the truncated string. Every one of
the thirteen yielded exactly one candidate, and every candidate returned HTTP 200. A
repair is only recorded where it is a strict continuation of what was published, never a
substitution.

| Instrument | Citations | Published locator | Repaired |
|---|---|---|---|
| Taxation Notice: 2023/014 | 630 | 200 chars, 404 | 200 OK |
| Taxation Notice: 2023/015 | 630 | 200 chars, 404 | 200 OK |
| Taxation Notice: 2023/16 | 204 | 200 chars, 404 | 200 OK |
| Trade remedies notice 2025/20 | 180 | 200 chars, 404 | 200 OK |

The full thirteen, with both locators side by side, are in the CSV.

## The other findings

**Legal citation format is ungoverned.** 87 citation records match neither declared
citation scheme. One class of instrument is cited as `Trade remedies notice 2025/20`,
`Trade Remedies Notice: 2024/11`, `Taxation Notice: 2023/014`, `Taxation notice 2022/10`,
`2026/23`, `2025 No.7`, and in one record simply `15`. The most cited instrument of all,
at 6,738 citations, is recorded as `Statutory Instruments  2019 No. 450`, with a double
space.

**The exporter name field is not a name field.** Duty rates are assigned to individually
named exporters through additional codes. Of 982 named exporters, 955 do not resolve to
exactly one entity under a GLEIF legal name lookup. 60.6 percent mix the company name
with address fragments, so `Cargill Inc., Wayzata` is a single field value. 65 carry raw
HTML markup or double encoded entities, including a `<br>` tag inside a company name. 55
pack more than one legal entity into one value.

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

Each identifier and citation scheme declares its **own conformance rules as data** in
[`ontology/schemes.ttl`](ontology/schemes.ttl), so adding a jurisdiction means adding a
concept rather than editing code.

SHACL carries one shape per defect class, so the validation report is the findings table.

## Reproduce it

```bash
pip install rdflib pyshacl pytest

python3 pipeline/reharvest_tr.py       # rebuild the tariff slice, about 10 minutes
python3 pipeline/enrich.py             # dereference locators, resolve names
python3 pipeline/build_graph.py        # emit and parse-verify the graph
python3 pipeline/governance_report.py  # every figure computed twice, non-zero on disagreement
python3 pipeline/repair_urls.py        # rebuild the truncated locators
pytest tests/ -v
```

`governance_report.py` computes all fifteen headline figures set-based in Python **and**
again by SPARQL over the graph, and exits non-zero if the two disagree. Nothing in this
README is asserted from a single computation path.

## Honesty

[`BUILD_REPORT.md`](BUILD_REPORT.md) records what was fetched, what could not be
obtained, three claims that were tested and dropped, a bug in our own extractor that was
caught mid-build, a bug in our own SHACL shapes that two engines exposed, and a defect in
our own validation engine. Findings that died are recorded alongside findings that lived.

The WTO Timeseries API requires a subscription key and was not used. The TRA case
register is not yet joined to the measures, so nothing here claims anything about TRA
recommendations, only about measures as published.

## Licence

Code MIT. Ontology, shapes and documentation CC BY 4.0. Source data from the UK Trade
Tariff and legislation.gov.uk is Crown copyright under the Open Government Licence v3.0;
GLEIF data is CC0.

## Contact

Built by [The Tesseract Academy](https://gov.tesseract.academy/).

If you run a register and want the same census run against it, or you want the thirteen
repairs as a patch against your own pipeline, email **fabio@thetesseractacademy.com**.
