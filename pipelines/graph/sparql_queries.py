#!/usr/bin/env python3
"""
Phase 4: SPARQL query library for structural retrieval over the Media Suite knowledge graph.

Provides named query templates for the four core structural retrieval patterns.
Used by the chatbot's hybrid retrieval router to answer questions that vector
search handles poorly: "what tools exist for X?", "which collections are open?",
"what workflows use this tool?", etc.

All queries operate on the named graph <https://mediasuite.clariah.nl/graph>.
The SPARQL endpoint is configured in config.yaml under graph.fuseki_url / graph.dataset.

Usage (standalone test):
    python pipelines/graph/sparql_queries.py
    python pipelines/graph/sparql_queries.py --query tools_by_activity --activity searching
    python pipelines/graph/sparql_queries.py --query chunks_for_tool --tool SearchTool
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
GRAPH = "https://mediasuite.clariah.nl/graph"

PREFIXES = """
PREFIX ms:      <https://mediasuite.clariah.nl/vocab#>
PREFIX clariah: <https://roelandordelman.github.io/mediasuite-knowledge-base/vocab#>
PREFIX tadirah: <https://vocabs.dariah.eu/tadirah/>
PREFIX schema:  <https://schema.org/>
PREFIX dcat:    <http://www.w3.org/ns/dcat#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX euright: <http://publications.europa.eu/resource/authority/access-right/>
"""

# ── Query templates ────────────────────────────────────────────────────────────
# Each query returns enough to answer a structural researcher question without
# needing to hit ChromaDB. The chatbot uses these results to filter ChromaDB
# by entity_uri for follow-up chunk retrieval.

QUERIES: dict[str, str] = {}

# Q1: Which tools support a given research activity?
# Answers: "What can I use for annotation?", "Which tools support searching?"
QUERIES["tools_by_activity"] = PREFIXES + """
SELECT ?uri ?label ?description ?status
WHERE {{
  GRAPH <{graph}> {{
    ?uri a clariah:ComponentTool ;
         rdfs:label ?label ;
         clariah:researchActivity <{activity_uri}> .
    OPTIONAL {{ ?uri schema:description ?description }}
    OPTIONAL {{ ?uri schema:releaseNotes ?status }}
  }}
}}
ORDER BY ?label
"""

# Q2: All component tools with their full activity list
# Answers: "What tools does the Media Suite have?", "List all tools"
QUERIES["all_tools"] = PREFIXES + """
SELECT ?uri ?label ?description ?activity
WHERE {{
  GRAPH <{graph}> {{
    ?uri a clariah:ComponentTool ;
         rdfs:label ?label ;
         clariah:researchActivity ?activity .
    OPTIONAL {{ ?uri schema:description ?description }}
  }}
}}
ORDER BY ?label ?activity
"""

# Q3: Infrastructure services and the tools that expose them
# Answers: "What powers the Similarity Tool?", "What backend services exist?"
QUERIES["services_by_tool"] = PREFIXES + """
SELECT ?toolLabel ?serviceUri ?serviceLabel ?serviceDesc
WHERE {{
  GRAPH <{graph}> {{
    ?tool a clariah:ComponentTool ;
          rdfs:label ?toolLabel ;
          clariah:deploysService ?serviceUri .
    ?serviceUri rdfs:label ?serviceLabel .
    OPTIONAL {{ ?serviceUri schema:description ?serviceDesc }}
  }}
}}
ORDER BY ?toolLabel
"""

# Q4: Datasets accessible via the Media Suite, with access rights
# Answers: "Which collections are open?", "What can I access without login?"
QUERIES["collections_by_access"] = PREFIXES + """
SELECT ?uri ?label ?accessRights ?license ?conditions
WHERE {{
  GRAPH <{graph}> {{
    ?uri a dcat:Dataset ;
         rdfs:label ?label ;
         clariah:partOf ms:MediaSuite .
    OPTIONAL {{ ?uri dcterms:accessRights ?accessRights }}
    OPTIONAL {{ ?uri dcterms:license ?license }}
    OPTIONAL {{ ?uri schema:conditionsOfAccess ?conditions }}
  }}
}}
ORDER BY ?accessRights ?label
"""

# Q5: Open-access datasets only (PUBLIC)
# Answers: "What collections can I access without logging in?"
QUERIES["open_collections"] = PREFIXES + """
SELECT ?uri ?label ?license
WHERE {{
  GRAPH <{graph}> {{
    ?uri a dcat:Dataset ;
         rdfs:label ?label ;
         dcterms:accessRights euright:PUBLIC .
    OPTIONAL {{ ?uri dcterms:license ?license }}
  }}
}}
ORDER BY ?label
"""

# Q6: Workflows that use a given tool as an instrument
# Answers: "What research workflows involve the Search Tool?"
QUERIES["workflows_by_tool"] = PREFIXES + """
SELECT DISTINCT ?wfUri ?wfName ?status ?stepName
WHERE {{
  GRAPH <{graph}> {{
    ?wfUri schema:name ?wfName ;
           schema:step ?step .
    ?step schema:instrument <{tool_uri}> .
    OPTIONAL {{ ?step schema:name ?stepName }}
    OPTIONAL {{ ?wfUri clariah:workflowStatus ?status }}
  }}
}}
ORDER BY ?wfName
"""

# Q7: All workflows with their status
# Answers: "What research workflows does the Media Suite support?"
QUERIES["all_workflows"] = PREFIXES + """
SELECT ?uri ?name ?status ?description
WHERE {{
  GRAPH <{graph}> {{
    ?uri a clariah:Workflow ;
         schema:name ?name .
    OPTIONAL {{ ?uri clariah:workflowStatus ?status }}
    OPTIONAL {{ ?uri schema:description ?description }}
  }}
}}
ORDER BY ?status ?name
"""

# Q8: All steps in a specific workflow (ordered)
# Answers: "Walk me through the SANE workflow"
QUERIES["workflow_steps"] = PREFIXES + """
SELECT ?stepName ?position ?instrument ?activity ?result ?optional
WHERE {{
  GRAPH <{graph}> {{
    <{workflow_uri}> schema:step ?step .
    ?step schema:name ?stepName ;
          schema:position ?position .
    OPTIONAL {{ ?step schema:instrument ?instrument }}
    OPTIONAL {{ ?step clariah:researchActivity ?activity }}
    OPTIONAL {{ ?step schema:result ?result }}
    OPTIONAL {{ ?step clariah:optional ?optional }}
  }}
}}
ORDER BY ?position
"""

# Q9: Entity description — full details for one tool or collection
# Used for "tell me about the Search Tool" structural lookups before chunk retrieval
QUERIES["entity_description"] = PREFIXES + """
SELECT ?label ?description ?url ?activity ?status
WHERE {{
  GRAPH <{graph}> {{
    <{entity_uri}> rdfs:label ?label .
    OPTIONAL {{ <{entity_uri}> schema:description ?description }}
    OPTIONAL {{ <{entity_uri}> schema:url ?url }}
    OPTIONAL {{ <{entity_uri}> clariah:researchActivity ?activity }}
    OPTIONAL {{ <{entity_uri}> schema:releaseNotes ?status }}
  }}
}}
"""

# Q10: Which tadirah activities does a given tool support?
# Complement to Q1 — given a tool, what can it do?
QUERIES["activities_by_tool"] = PREFIXES + """
SELECT ?activity ?prefLabel
WHERE {{
  GRAPH <{graph}> {{
    <{tool_uri}> clariah:researchActivity ?activity .
    OPTIONAL {{
      ?activity skos:prefLabel ?prefLabel
      FILTER(lang(?prefLabel) = 'en')
    }}
  }}
}}
ORDER BY ?activity
"""


# ── Execution helpers ──────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def sparql_endpoint(cfg: dict) -> str:
    gcfg = cfg["graph"]
    return f"{gcfg['fuseki_url'].rstrip('/')}/{gcfg['dataset']}/sparql"


def run_query(endpoint: str, query: str, auth: tuple | None = None) -> list[dict[str, Any]]:
    r = requests.get(
        endpoint,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        auth=auth,
        timeout=15,
    )
    r.raise_for_status()
    bindings = r.json()["results"]["bindings"]
    return [
        {k: v["value"] for k, v in row.items()}
        for row in bindings
    ]


def tool_uri(local_name: str) -> str:
    return f"https://mediasuite.clariah.nl/vocab#{local_name}"


def tadirah_uri(local_name: str) -> str:
    return f"https://vocabs.dariah.eu/tadirah/{local_name}"


# ── CLI for testing all queries ────────────────────────────────────────────────

def _print_results(rows: list[dict], max_rows: int = 20) -> None:
    if not rows:
        print("  (no results)")
        return
    for i, row in enumerate(rows[:max_rows]):
        parts = []
        for k, v in row.items():
            short_v = v.split("#")[-1] if "#" in v else v.split("/")[-1] if "/" in v else v
            if len(short_v) > 60:
                short_v = short_v[:57] + "…"
            parts.append(f"{k}={short_v}")
        print(f"  {i+1:2d}. {' | '.join(parts)}")
    if len(rows) > max_rows:
        print(f"  … and {len(rows) - max_rows} more")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SPARQL queries against the Media Suite graph")
    parser.add_argument("--query", choices=list(QUERIES.keys()), help="Run a specific query")
    parser.add_argument("--activity", default="searching", help="tadirah activity local name for tools_by_activity")
    parser.add_argument("--tool", default="SearchTool", help="Tool local name for workflow/activity queries")
    parser.add_argument("--workflow", default="GenderWorkflow", help="Workflow local name for workflow_steps")
    parser.add_argument("--entity", default="SearchTool", help="Entity local name for entity_description")
    args = parser.parse_args()

    cfg = load_config()
    endpoint = sparql_endpoint(cfg)
    gcfg = cfg["graph"]
    auth = (gcfg["admin_user"], gcfg["admin_password"])

    def run(name: str, **kwargs) -> None:
        template = QUERIES[name]
        query = template.format(graph=GRAPH, **kwargs)
        print(f"\n{'─'*60}")
        print(f"Query: {name}")
        if kwargs:
            print(f"Params: {kwargs}")
        rows = run_query(endpoint, query, auth=auth)
        print(f"Results: {len(rows)} rows")
        _print_results(rows)

    if args.query:
        # Run just the requested query
        params: dict[str, str] = {}
        if "{activity_uri}" in QUERIES[args.query]:
            params["activity_uri"] = tadirah_uri(args.activity)
        if "{tool_uri}" in QUERIES[args.query]:
            params["tool_uri"] = tool_uri(args.tool)
        if "{workflow_uri}" in QUERIES[args.query]:
            params["workflow_uri"] = tool_uri(args.workflow)
        if "{entity_uri}" in QUERIES[args.query]:
            params["entity_uri"] = tool_uri(args.entity)
        run(args.query, **params)
    else:
        # Run all queries with default parameters
        run("all_tools")
        run("tools_by_activity", activity_uri=tadirah_uri("searching"))
        run("tools_by_activity", activity_uri=tadirah_uri("annotating"))
        run("services_by_tool")
        run("open_collections")
        run("collections_by_access")
        run("workflows_by_tool", tool_uri=tool_uri("SearchTool"))
        run("all_workflows")
        run("workflow_steps", workflow_uri=tool_uri("GenderWorkflow"))
        run("entity_description", entity_uri=tool_uri("SearchTool"))
        run("activities_by_tool", tool_uri=tool_uri("AnnotationTool"))


if __name__ == "__main__":
    main()
