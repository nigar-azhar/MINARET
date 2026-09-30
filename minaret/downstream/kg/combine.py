"""Merge the schema (TBox) plus every per-series instance .ttl into one combined graph."""
from __future__ import annotations

from pathlib import Path

from rdflib import Graph
from rdflib.namespace import SKOS

from minaret.downstream.kg.common import HADITH, MIN, QUR, TAFSIR

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.ttl"


def combine(instances_dir: Path, out_path: Path, schema_path: Path = SCHEMA_PATH) -> Graph:
    g = Graph()
    g.bind("minaret", MIN)
    g.bind("hadith", HADITH)
    g.bind("qur", QUR)
    g.bind("tafsir", TAFSIR)
    g.bind("skos", SKOS)
    g.parse(schema_path, format="turtle")
    series_files = sorted(Path(instances_dir).glob("*.ttl"))
    for f in series_files:
        g.parse(f, format="turtle")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(out_path), format="turtle")
    print(f"wrote {out_path} -- {len(g)} triples from schema + {len(series_files)} series file(s)")
    return g
