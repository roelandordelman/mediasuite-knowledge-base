#!/usr/bin/env python3
"""
Phase 4: Load Media Suite entity graph into Apache Jena Fuseki.

Reads the four Turtle vocabulary files, validates them with rdflib, then loads
them into a single named graph via the SPARQL Graph Store Protocol. Idempotent —
re-running replaces the graph with the current file contents.

Usage:
    python pipelines/graph/build_graph.py
    python pipelines/graph/build_graph.py --dry-run   # validate TTL only, no upload
"""

import argparse
import sys
import time
from pathlib import Path

import requests
import yaml
from rdflib import Dataset, Graph


ROOT = Path(__file__).resolve().parents[2]


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def validate_turtle(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


def wait_for_fuseki(base_url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/$/ping", timeout=3)
            if r.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)
    return False


def ensure_dataset(base_url: str, dataset: str, user: str, password: str) -> None:
    auth = (user, password)
    r = requests.get(f"{base_url}/$/datasets/{dataset}", auth=auth, timeout=10)
    if r.status_code == 200:
        print(f"  dataset /{dataset} already exists")
        return
    r = requests.post(
        f"{base_url}/$/datasets",
        auth=auth,
        data={"dbType": "tdb2", "dbName": dataset},
        timeout=10,
    )
    r.raise_for_status()
    print(f"  created dataset /{dataset} (TDB2)")


def upload_graph(
    base_url: str,
    dataset: str,
    named_graph: str,
    turtle_files: list[Path],
    user: str,
    password: str,
) -> int:
    auth = (user, password)
    gsp_url = f"{base_url}/{dataset}/data"
    params = {"graph": named_graph}

    merged = Dataset()
    for path in turtle_files:
        merged.parse(path, format="turtle")

    serialised = merged.serialize(format="turtle")

    r = requests.put(
        gsp_url,
        auth=auth,
        params=params,
        data=serialised.encode("utf-8"),
        headers={"Content-Type": "text/turtle; charset=utf-8"},
        timeout=60,
    )
    r.raise_for_status()
    return len(merged)


def triple_count(base_url: str, dataset: str, named_graph: str, user: str, password: str) -> int:
    query = f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{named_graph}> {{ ?s ?p ?o }} }}"
    r = requests.get(
        f"{base_url}/{dataset}/sparql",
        auth=(user, password),
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=15,
    )
    r.raise_for_status()
    return int(r.json()["results"]["bindings"][0]["n"]["value"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Media Suite vocabulary into Fuseki")
    parser.add_argument("--dry-run", action="store_true", help="Validate TTL only, no upload")
    args = parser.parse_args()

    cfg = load_config()
    gcfg = cfg["graph"]
    base_url = gcfg["fuseki_url"].rstrip("/")
    dataset = gcfg["dataset"]
    named_graph = gcfg["named_graph"]
    user = gcfg["admin_user"]
    password = gcfg["admin_password"]
    turtle_files = [ROOT / p for p in gcfg["turtle_files"]]

    print("Validating Turtle files…")
    total_triples = 0
    for path in turtle_files:
        try:
            g = validate_turtle(path)
            print(f"  {path.name}: {len(g)} triples — OK")
            total_triples += len(g)
        except Exception as e:
            print(f"  {path.name}: PARSE ERROR — {e}", file=sys.stderr)
            sys.exit(1)
    print(f"  total: {total_triples} triples across {len(turtle_files)} files")

    if args.dry_run:
        print("Dry run — skipping upload.")
        return

    print(f"\nConnecting to Fuseki at {base_url}…")
    if not wait_for_fuseki(base_url):
        print(
            "ERROR: Fuseki not reachable. Start it with:\n"
            "  docker run -d --name fuseki -p 3030:3030 \\\n"
            f"    -v $(pwd)/stores/fuseki_data:/fuseki/databases \\\n"
            "    -e ADMIN_PASSWORD=admin stain/jena-fuseki",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Ensuring dataset /{dataset}…")
    ensure_dataset(base_url, dataset, user, password)

    print(f"Uploading to <{named_graph}>…")
    upload_graph(base_url, dataset, named_graph, turtle_files, user, password)

    count = triple_count(base_url, dataset, named_graph, user, password)
    print(f"  {count} triples now in graph")
    print(f"\nSPARQL endpoint: {base_url}/{dataset}/sparql")
    print(f"Named graph:     {named_graph}")
    print(f"Web UI:          {base_url}")


if __name__ == "__main__":
    main()
