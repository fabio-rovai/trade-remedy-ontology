import sys, time, collections, rdflib, pyshacl
g = rdflib.Graph(); g.parse("graph/traderemedy.ttl", format="turtle")
core = rdflib.Graph(); core.parse("ontology/traderemedy.ttl", format="turtle")
core.parse("ontology/schemes.ttl", format="turtle")
g += core
s = rdflib.Graph(); s.parse("shacl/layer2_conformance.ttl", format="turtle")
t0 = time.time()
conforms, results_graph, _ = pyshacl.validate(
    g, shacl_graph=s, advanced=True, inference="none", abort_on_first=False)
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
msgs = collections.Counter()
for r in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
    m = str(next(results_graph.objects(r, SH.resultMessage), ""))
    msgs[m.split(" ")[0]] += 1
print(f"pyshacl conforms={conforms} in {time.time()-t0:.1f}s")
print("violations by defect class:")
for k, v in sorted(msgs.items()):
    print(f"  {k:6} {v:6}")
print(f"  TOTAL  {sum(msgs.values()):6}")
