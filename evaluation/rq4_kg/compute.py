#!/usr/bin/env python3
"""RQ4 -- knowledge-graph correctness: ontology/KG statistics (paper Table "Statistics of the
MINARET Ontology and Knowledge Graph") and the 16 competency questions in cqs/*.rq, executed
against the combined graph.

    python evaluation/rq4_kg/compute.py [--artifacts runs/] [--tafsir-kg SemanticTafsirKG.ttl]

CQ16 is federated: step 1 runs on MINARET's graph; step 2 needs the external SemanticTafsir KG
and only runs when --tafsir-kg is given.
"""
import sys
from collections import Counter
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SKOS

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common.artifacts import REPO_ROOT, arg_parser, write_results  # noqa: E402

HERE = Path(__file__).resolve().parent
MIN = "http://minaret-eval.org/ontology#"
HADITH = "http://www.semantichadith.com/ontology/"
QUR = "http://quranontology.com/Resource/"
TAFSIR = "http://www.semantictafsir.com/ontology/"
SCHEMA = REPO_ROOT / "minaret" / "downstream" / "kg" / "schema.ttl"


def local(u):
    return str(u).split("#")[-1].split("/")[-1]


def statistics(g: Graph, schema: Graph) -> dict:
    classes = {c for c in schema.subjects(RDF.type, OWL.Class) if str(c).startswith(MIN)}
    obj_props = {p for p in schema.subjects(RDF.type, OWL.ObjectProperty) if str(p).startswith(MIN)}
    data_props = {p for p in schema.subjects(RDF.type, OWL.DatatypeProperty) if str(p).startswith(MIN)}
    inverse_pairs = sum(1 for _ in schema.triples((None, OWL.inverseOf, None)))
    subclass_edges = [(s, o) for s, o in schema.subject_objects(RDFS.subClassOf)
                      if str(s).startswith(MIN) and isinstance(o, URIRef) and str(o).startswith(MIN)]

    instance_counts = Counter()
    individuals = set()
    for s, c in g.subject_objects(RDF.type):
        if c in classes:
            instance_counts[local(c)] += 1
            individuals.add(s)

    def count_pred(pred, obj_class=None):
        n = 0
        for s, o in g.subject_objects(pred):
            if obj_class is None or (o, RDF.type, URIRef(MIN + obj_class)) in g:
                n += 1
        return n

    def ext_links(pred, subj_class, prefix):
        return sum(1 for s, o in g.subject_objects(pred)
                   if (s, RDF.type, URIRef(MIN + subj_class)) in g and str(o).startswith(prefix))

    usage = Counter(local(o) for o in g.objects(None, URIRef(MIN + "hasUsageType")))
    extent = Counter(local(o) for o in g.objects(None, URIRef(MIN + "hasExtentType")))

    # Topics shared across >= 2 series: Topic <- discussesTopic - SegmentGroup - containsSegment ->
    # Segment <- hasSegment - Transcript <- hasTranscript - Recording <- hasRecording - AudioSeries
    q = f"""
    PREFIX minaret: <{MIN}>
    SELECT ?name (GROUP_CONCAT(DISTINCT ?code; separator=", ") AS ?series) (COUNT(DISTINCT ?code) AS ?n) WHERE {{
      ?sg minaret:discussesTopic ?t . ?t minaret:nameEn ?name .
      ?sg minaret:containsSegment ?seg . ?tr minaret:hasSegment ?seg . ?rec minaret:hasTranscript ?tr .
      ?s minaret:hasRecording ?rec . ?s minaret:seriesCode ?code .
    }} GROUP BY ?name HAVING (COUNT(DISTINCT ?code) >= 2) ORDER BY ?name"""
    shared = [{"topic": str(r.name), "series": str(r.series)} for r in g.query(q)]

    hadith_total = instance_counts.get("Hadith", 0)
    hadith_resolved = ext_links(SKOS.exactMatch, "Hadith", HADITH)
    return {
        "structure": {
            "ontology_classes": len(classes),
            "object_properties": len(obj_props),
            "owl_inverseOf_axioms": inverse_pairs,
            "datatype_properties": len(data_props),
            "class_hierarchy_depth": 0 if not subclass_edges else "non-flat",
            "schema_triples": len(schema),
        },
        "knowledge_graph": {
            "total_triples": len(g),
            "total_individuals": len(individuals),
            "classes_populated": f"{sum(1 for c in classes if instance_counts.get(local(c)))} / {len(classes)}",
            "instances_per_class": dict(instance_counts.most_common()),
        },
        "internal_links": {
            "containsSegment": count_pred(URIRef(MIN + "containsSegment")),
            "hasSegment": count_pred(URIRef(MIN + "hasSegment")),
            "precedesSegment": count_pred(URIRef(MIN + "precedesSegment")),
            "hasUsageType": dict(usage), "hasExtentType": dict(extent),
            "discussesTopic": count_pred(URIRef(MIN + "discussesTopic")),
            "occursIn": count_pred(URIRef(MIN + "occursIn")),
            "refersTo_QuranVerse": count_pred(URIRef(MIN + "refersTo"), "QuranVerse"),
            "refersTo_Hadith": count_pred(URIRef(MIN + "refersTo"), "Hadith"),
            "refersTo_Dua": count_pred(URIRef(MIN + "refersTo"), "Dua"),
            "hasHeading": count_pred(URIRef(MIN + "hasHeading")),
            "hasRecording": count_pred(URIRef(MIN + "hasRecording")),
            "skos_related_topic": sum(1 for s, o in g.subject_objects(SKOS.related)
                                      if (s, RDF.type, URIRef(MIN + "Topic")) in g),  # directed triples, as in the paper
            "skos_altLabel": sum(1 for _ in g.triples((None, SKOS.altLabel, None))),
        },
        "external_links": {
            "hadith_exactMatch_SemanticHadith": hadith_resolved,
            "topic_closeMatch_or_exactMatch_hadith_concepts":
                ext_links(SKOS.closeMatch, "Topic", HADITH) + ext_links(SKOS.exactMatch, "Topic", HADITH),
            "hadith_resolution_rate": f"{hadith_resolved} / {hadith_total}",
            "verse_exactMatch_QuranOntology": ext_links(SKOS.exactMatch, "QuranVerse", QUR),
            "verse_exactMatch_SemanticTafsir": ext_links(SKOS.exactMatch, "QuranVerse", TAFSIR),
        },
        "cross_series_topics": shared,
    }


def run_cqs(g: Graph, tafsir_kg: Path | None) -> dict:
    results = {}
    for rq in sorted((HERE / "cqs").glob("CQ*.rq")):
        if "step2" in rq.stem:
            continue
        rows = [[str(v) if v is not None else None for v in row] for row in g.query(rq.read_text(encoding="utf-8"))]
        results[rq.stem] = {"row_count": len(rows), "rows": rows[:20]}
        if rq.stem == "CQ09":  # per-collection tally, as reported in the paper
            results[rq.stem]["by_collection"] = dict(Counter(r[0].split("_")[0] for r in rows).most_common())
    if tafsir_kg:
        tg = Graph().parse(tafsir_kg)
        rq = HERE / "cqs" / "CQ16_step2_semantictafsir.rq"
        rows = [[str(v) for v in row] for row in tg.query(rq.read_text(encoding="utf-8"))]
        results["CQ16_step2"] = {"row_count": len(rows), "rows": rows}
    return results


def main():
    p = arg_parser(__doc__)
    p.add_argument("--tafsir-kg", type=Path, default=None)
    args = p.parse_args()
    out = args.out or HERE / "results"
    g = Graph().parse(Path(args.artifacts) / "kg" / "minaret_combined.ttl")
    schema = Graph().parse(SCHEMA)
    stats = statistics(g, schema)
    cqs = run_cqs(g, args.tafsir_kg)

    kg, st, links = stats["knowledge_graph"], stats["structure"], stats["internal_links"]
    md = ["# RQ4 -- ontology / KG statistics and competency questions", "",
          "| Variable | Value |", "|---|---:|"]
    md += [f"| {k} | {v} |" for k, v in st.items()]
    md += [f"| total_triples | {kg['total_triples']} |", f"| total_individuals | {kg['total_individuals']} |",
           f"| classes_populated | {kg['classes_populated']} |"]
    md += [f"| {c} | {n} |" for c, n in kg["instances_per_class"].items()]
    md += [f"| {k} | {v} |" for k, v in links.items()]
    md += [f"| {k} | {v} |" for k, v in stats["external_links"].items()]
    md += ["", "Topics shared across >= 2 series:", ""] + [f"- {t['topic']}: {t['series']}" for t in stats["cross_series_topics"]]
    md += ["", "## Competency questions", "", "| CQ | Rows |", "|---|---:|"]
    md += [f"| {k} | {v['row_count']} |" for k, v in cqs.items()]
    write_results(out, "rq4_kg", {"statistics": stats, "competency_questions": cqs}, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
