"""
Collect knowledge base metrics and generate data/stats.json.

Queries ChromaDB and Fuseki for live counts, reads the latest eval results,
and writes data/stats.json.  Also regenerates
content/system/knowledge-base-coverage.md from those stats.

Run after all ingest + build_index steps are complete:
    python pipelines/stats/build_stats.py

Requirements: chromadb, requests, pyyaml
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).parents[2]
CONFIG_PATH = ROOT / "config.yaml"
STATS_PATH = ROOT / "data" / "stats.json"
COVERAGE_PATH = ROOT / "content" / "system" / "knowledge-base-coverage.md"
EVAL_RESULTS_PATH = ROOT / "evaluate" / "results" / "latest.json"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# ChromaDB stats
# ---------------------------------------------------------------------------

def collect_chroma_stats(cfg: dict) -> dict | None:
    try:
        import chromadb
    except ImportError:
        print("WARNING: chromadb not installed — skipping chunk stats", file=sys.stderr)
        return None

    vs = cfg["vector_store"]
    try:
        client = chromadb.HttpClient(host=vs["chroma_host"], port=vs["chroma_port"])
        collection = client.get_or_create_collection(vs["collection_name"])
    except Exception as exc:
        print(f"WARNING: cannot connect to ChromaDB ({exc}) — chunk stats set to null",
              file=sys.stderr)
        return None

    total = collection.count()
    if total == 0:
        return {
            "total": 0,
            "by_content_type": {},
            "by_collection": {},
            "with_entity_uri": 0,
            "by_tier": {},
        }

    # Fetch all metadata in one call.  ChromaDB returns a flat list.
    result = collection.get(include=["metadatas"])
    metadatas = result["metadatas"]

    by_content_type: Counter = Counter()
    by_collection: Counter = Counter()
    with_entity_uri = 0
    by_tier: Counter = Counter()

    for m in metadatas:
        by_content_type[m.get("content_type", "")] += 1
        by_collection[m.get("collection", "")] += 1
        if m.get("entity_uri", ""):
            with_entity_uri += 1
        tier = m.get("tier", 0)
        by_tier[str(tier)] += 1

    return {
        "total": total,
        "by_content_type": dict(
            sorted(by_content_type.items(), key=lambda kv: -kv[1])
        ),
        "by_collection": dict(
            sorted(by_collection.items(), key=lambda kv: -kv[1])
        ),
        "with_entity_uri": with_entity_uri,
        "by_tier": dict(sorted(by_tier.items())),
    }


# ---------------------------------------------------------------------------
# Fuseki stats
# ---------------------------------------------------------------------------

def sparql_select(endpoint: str, query: str, timeout: int = 10) -> list[dict]:
    """Run a SPARQL SELECT and return bindings as a list of dicts."""
    resp = requests.get(
        endpoint,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["results"]["bindings"]


def collect_fuseki_stats(cfg: dict) -> dict | None:
    gcfg = cfg.get("graph", {})
    fuseki_url = gcfg.get("fuseki_url", "")
    dataset = gcfg.get("dataset", "")
    named_graph = gcfg.get("named_graph", "")

    if not fuseki_url or not dataset:
        print("WARNING: graph.fuseki_url or graph.dataset not set — graph stats set to null",
              file=sys.stderr)
        return None

    sparql_endpoint = f"{fuseki_url.rstrip('/')}/{dataset}/sparql"

    try:
        # Count triples in both the default graph and all named graphs.
        bindings = sparql_select(
            sparql_endpoint,
            "SELECT (COUNT(*) AS ?n) WHERE { { ?s ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } } }",
        )
        total_triples = int(bindings[0]["n"]["value"]) if bindings else 0

        type_bindings = sparql_select(
            sparql_endpoint,
            f"SELECT ?type (COUNT(?s) AS ?n) WHERE {{ "
            f"GRAPH <{named_graph}> {{ ?s a ?type }} }} GROUP BY ?type",
        )
        by_entity_type = {
            b["type"]["value"]: int(b["n"]["value"])
            for b in type_bindings
        }

    except requests.RequestException as exc:
        print(f"WARNING: Fuseki unreachable ({exc}) — graph stats set to null",
              file=sys.stderr)
        return None

    return {
        "total_triples": total_triples,
        "by_entity_type": dict(
            sorted(by_entity_type.items(), key=lambda kv: -kv[1])
        ),
    }


# ---------------------------------------------------------------------------
# Eval stats
# ---------------------------------------------------------------------------

def collect_eval_stats(path: Path) -> dict:
    null_eval = {
        "hit_at_10": None,
        "mrr": None,
        "structural_routing": None,
        "eval_date": None,
    }
    if not path.exists():
        return null_eval
    try:
        data = json.loads(path.read_text())
        return {
            "hit_at_10": data.get("hit_at_10"),
            "mrr": data.get("mrr"),
            "structural_routing": data.get("structural_routing"),
            "eval_date": data.get("eval_date"),
        }
    except Exception as exc:
        print(f"WARNING: could not read eval results ({exc})", file=sys.stderr)
        return null_eval


# ---------------------------------------------------------------------------
# Coverage document
# ---------------------------------------------------------------------------

def _fmt_score(value) -> str:
    if value is None:
        return "not yet measured"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def generate_coverage_doc(stats: dict, output_path: Path) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    ts = stats["build_timestamp"][:10]

    chunks = stats.get("chunks")
    graph = stats.get("graph")
    eval_ = stats.get("eval", {})

    # --- chunk coverage section ---
    if chunks:
        total = chunks["total"]
        by_ct = chunks.get("by_content_type", {})
        n_types = len(by_ct)
        coverage_intro = (
            f"The knowledge base contains {total:,} chunks across "
            f"{n_types} content type{'s' if n_types != 1 else ''}."
        )
        table_rows = "\n".join(
            f"| {ct} | {n:,} |" for ct, n in list(by_ct.items())
        )
        coverage_table = (
            "| Content type | Chunks |\n"
            "|---|---|\n"
            + table_rows
        )
    else:
        coverage_intro = "Chunk statistics are not available (ChromaDB was unreachable at build time)."
        coverage_table = ""

    # --- graph section ---
    if graph and graph.get("total_triples") is not None:
        graph_sentence = f"The knowledge graph contains {graph['total_triples']:,} RDF triples."
    else:
        graph_sentence = "The knowledge graph has not yet been built or was unreachable at build time."

    # --- eval section ---
    hit = _fmt_score(eval_.get("hit_at_10"))
    routing = _fmt_score(eval_.get("structural_routing"))
    eval_date_raw = eval_.get("eval_date")
    eval_date_phrase = f"on {eval_date_raw}" if eval_date_raw else "(no evaluation run yet)"

    front_matter = f"""\
---
title: "Knowledge base coverage"
content_type: "System Documentation"
url_stub: "system/knowledge-base-coverage"
tags: [knowledge base, coverage, statistics, sources, chatbot development]
author: "generated"
status: active
created: "{today}"
last_reviewed: "{today}"
tier: 1
---"""

    body = f"""\
## What is this?

This document describes the current state of the Ask Media Suite knowledge base: how many sources it covers, what types of content it contains, and how well retrieval is performing. It is regenerated automatically each time the knowledge base is rebuilt.

## Knowledge base build

The knowledge base was last built on {ts}.

## Content coverage

{coverage_intro}

{coverage_table}

## Retrieval evaluation

Retrieval quality is measured on a fixed test question set. Scores below are from the evaluation run {eval_date_phrase}.

| Metric | Score |
|---|---|
| Hit@10 | {hit} |
| Structural routing | {routing} |

*Hit@10 = fraction of test questions where at least one expected source appears in the top 10 results. Higher is better; 1.0 = perfect.*

## Knowledge graph

{graph_sentence}

## Coverage updates

Coverage is updated each time the knowledge base is rebuilt by running `pipelines/stats/build_stats.py`."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(front_matter + "\n\n" + body + "\n", encoding="utf-8")
    print(f"Coverage doc written to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config(CONFIG_PATH)

    embed_model = cfg.get("embedding", {}).get("model", "")
    generate_model = cfg.get("publications", {}).get("generation_model", "")

    print("Collecting ChromaDB stats …")
    chroma_stats = collect_chroma_stats(cfg)

    print("Collecting Fuseki stats …")
    fuseki_stats = collect_fuseki_stats(cfg)

    print(f"Reading eval results from {EVAL_RESULTS_PATH} …")
    eval_stats = collect_eval_stats(EVAL_RESULTS_PATH)

    stats = {
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "embed_model": embed_model,
        "generate_model": generate_model,
        "chunks": chroma_stats,
        "graph": fuseki_stats,
        "eval": eval_stats,
    }

    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Stats written to {STATS_PATH}")

    print("Generating coverage document …")
    generate_coverage_doc(stats, COVERAGE_PATH)


if __name__ == "__main__":
    main()
