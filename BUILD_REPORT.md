# Build report

Built 28 August 2026. Every figure in this file is produced twice, set-based in Python
and again by SPARQL over the built graph, by `pipeline/governance_report.py`, which exits
non-zero if the two paths disagree. They agree on all fifteen metrics.

## What was fetched

| Source | Access | Result |
|---|---|---|
| UK Trade Tariff API | open, keyless | 21,008 commodity codes visited, complete census |
| legislation.gov.uk | open | 119 legal act locators dereferenced |
| gov.uk publications | open | 13 collection pages read to rebuild truncated locators |
| GLEIF v1 API | open, keyless | 985 exporter names looked up |
| WTO Timeseries API | **blocked** | HTTP 401, requires a subscription key. Not used. |
| trade.gov ADCVD | **not found** | HTTP 404 at the documented path. Not used. |

The census is complete rather than sampled. No figure here rests on a partial cursor.

## Scale

- 405 of 21,008 commodity codes carry a trade remedy measure
- 9,385 distinct measures
- 49 legal instruments cited by those measures, out of 119 present on the same commodities
- 990 additional codes, of which 982 name an exporter and 8 are residual rates

## Findings

**F1. The tariff truncates the legal instrument locator at 200 characters, and every
truncated locator is dead.** Thirteen of the 49 cited instruments publish a locator of
exactly 200 characters, each cut mid word. All thirteen return HTTP 404. Every locator
shorter than 200 characters returns HTTP 200. The length histogram has no value above
200. 1,477 of the 9,385 measures, 15.7 percent, cite an instrument whose published
locator is dead. The affected instruments are overwhelmingly trade remedies notices,
whose gov.uk paths are the longest in the set.

**F2. All thirteen are repairable, and have been repaired.** For each, the collection
page named in the surviving prefix was fetched and its document links filtered to those
beginning with the truncated string. Every one of the thirteen yielded exactly one
candidate, and every candidate returned HTTP 200. The repairs are in
`repairs/legal_act_url_repairs.csv` with the original and rebuilt locator side by side.

**F3. Legal citation format is ungoverned.** 87 citation records match neither declared
citation scheme. One class of instrument is cited as `Trade remedies notice 2025/20`,
`Trade Remedies Notice: 2024/11`, `Trade Remedies Notice 2026/20`, `Taxation Notice:
2023/014`, `Taxation notice 2022/10`, `2026/23`, `2025 No.7`, `2025 NO.13` and, in one
record, `15`. The most cited instrument of all, at 6,738 citations, is recorded as
`Statutory Instruments  2019 No. 450`, with a double space.

**F5. The TRA case register strips leading zeros from chapter 3 commodity codes.**
Cases ER0080 (Active) and TS0002 (Completed) each publish six nine-digit values. Nine is
not a UK commodity granularity. All twelve return HTTP 404 against the tariff; all twelve
resolve with HTTP 200 once the leading zero is restored, and each resolves to a trout
product consistent with the case. Repaired in `repairs/tra_case_code_repairs.json`,
accepted only where the published value fails and the restored value resolves.

**F6. The case to measure join holds.** 79 of 92 cases join to at least one commodity
carrying a measure. 8 of 405 measured commodities are named by no case. Of 2,204
published codes, 1,393 carry a measure and 811 do not, the latter concentrated in
completed cases. 21 cases mix 8 and 10 digit granularity inside a single list.

**F4. The exporter name field is not a name field.** Of 982 named exporters, 955 do not
resolve to exactly one entity under a GLEIF legal-name lookup. 595, which is 60.6
percent, mix the company name with address fragments, so `Cargill Inc., Wayzata` and
`BIOX Corporation, Oakville, Ontario, Canada` are single field values. 65 carry raw HTML
markup or double encoded entities, including a `<br>` tag inside a company name. 55 pack
more than one legal entity into one value. Fourteen state a scope rule rather than name
anyone, for example `Sustainable Aviation Fuel is excluded from the measure`.

## Claims that were tested and dropped

**Dropped: "a live trade remedy measure cites a revoked sanctions regulation."** Legal
act `X2209980` records its code as `2022 No.998` while its locator points at
`uksi/2022/689`, which resolves to a Russia sanctions instrument marked revoked. This is
a genuine internal contradiction in the tariff and it is the only one in the set. It is
**not** cited by any trade remedy measure. It is co-present on commodities that also
carry remedy measures. Presenting it as a trade remedies defect would have been wrong,
and an earlier draft of our outreach did exactly that before the check was run. Two
further revoked instruments, `S.I. 2019/134` and `S.I. 2019/136`, are likewise present
but not cited by a remedy measure.

**Dropped: "87 additional codes are malformed."** Our own scheme registry declared the
additional code pattern as `^[A-Z][0-9]{3}$`. The UK uses further families, including
`8`-prefixed codes such as `8A43` and `8C00`, and reserved values such as `VATZ`. The
pattern was wrong, not the data. Corrected to `^[A-Z0-9]{4}$`, after which the defect
count is zero.

**Dropped: "exporter descriptions are truncated."** An apparent mid-word cut was an
artifact of our own console slicing. The description field has no cap; the longest is
3,101 characters.

**Corrected mid-build: the measure to legal act link.** The first extractor read a
relationship key `legal_act` that does not exist; the API key is `legal_acts`, a list.
The bug produced zero measure-to-instrument links and was caught only because a check
asked whether the revoked instruments were actually cited. The 405 affected commodities
were re-fetched with the corrected key. The buggy first pass is retained at
`cache/commodities_v1_buggy.jsonl`.

## Verification

Three independent paths, as required before anything ships.

1. **Our own engine**, `open-ontologies` v1.2.0. `validate` reports 99,095 triples,
   agreeing exactly with rdflib. `lint` reports zero issues on both ontology files.
   `vocab-check` closed-world reports `conforms: true`, zero undeclared terms, across 43
   ontology terms, 25 predicates and 7 types.
2. **pyshacl 0.40.1**, 26.1s over the full graph.
3. **Dual computation**, `governance_report.py`, fifteen metrics, both paths agreeing.

### A defect in our own engine, to be filed

`open-ontologies shacl` reported `"conforms": null` and named `sh:minInclusive` and
`sh:maxInclusive` as not implemented. They were collected by neither the property-shape
query nor the known-predicate filter, so a shape carrying a numeric bound could neither
pass nor fail.

**Corrected on re-test:** an earlier draft of this report also said the engine did not
evaluate `sh:sparql` shapes. That was wrong. It does, and once the shapes were rewritten
as `sh:sparql` it returned exactly pyshacl's 1,136. The only real gap was the range
constraints.

**Fixed in open-ontologies commit a44f668**, with three regression tests pinned against
pyshacl 0.40.1 on a shared fixture. After the fix the engine reports `conforms: false`,
`skipped_constraints: none`, and 2,091 violations: the same 1,136 as pyshacl, plus 955
from a native range formulation of the same rule, which independently reproduces the
SPARQL figure of 955.

### A shape bug the two engines exposed

The first version of shapes D3, D5, D6 and D8 used `sh:hasValue`, which treats a missing
property as a violation. That inflated D3 from 1 to 70 and D5 from 3 to 28. All four
were rewritten as `sh:sparql` so that absence is not a violation. The corrected counts
match the set-based figures exactly.

## Sources that needed a route around a gate

- **WTO Timeseries API returns HTTP 401** and needs a subscription key. Routed around it:
  the WTO publishes the same measure counts as open PDFs at wto.org, which need no key
  and extract cleanly with `pdftotext -layout`. 61 members parsed for anti-dumping by
  reporting member, 100 by exporting country, 27 for countervailing. See
  `pipeline/harvest_wto.py`.
- **The TRA public file has no JSON API**; `/api/cases`, `/api/v1/cases` and `/cases` all
  return 404. Routed around it: the case pages are server-rendered and publish the fields
  needed for the join, including the commodity code list. 92 cases harvested. See
  `pipeline/harvest_tra_cases.py`.
- **EU TRON** was reachable and is not harvested in this version, so no UK to EU
  comparison of transitioned measures is made. The WTO notification counts stand in as
  the cross-jurisdiction reference instead.
