#!/usr/bin/env python3
"""
Phase 4: Backfill entity_uri metadata on existing ChromaDB chunks.

Assigns a knowledge-graph entity URI to each chunk based on (in priority order):
  1. URL substring match (url_entity_map in config) — highest confidence
  2. Single tool in tools_mentioned with no collections → that tool's entity_uri
  3. Single collection in collections_mentioned with no tools → that collection's entity_uri
  4. No match → entity_uri left as "" (chunk is not primarily about one entity)

Idempotent: re-running re-evaluates and overwrites entity_uri on all chunks.
Also updates build_index.py so new chunks get entity_uri automatically on indexing.

Usage:
    python pipelines/graph/enrich_entity_uri.py
    python pipelines/graph/enrich_entity_uri.py --dry-run   # report without writing
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb
import yaml

ROOT = Path(__file__).resolve().parents[2]
BATCH_SIZE = 200


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def assign_entity_uri(
    url: str,
    tools_mentioned: list[str],
    collections_mentioned: list[str],
    url_entity_map: dict[str, str],
    tool_entities: dict[str, dict],
    collection_entities: dict[str, str],
) -> str:
    # Priority 1: URL substring match (ordered; first match wins)
    for substring, uri in url_entity_map.items():
        if substring in url:
            return uri

    # Priority 2: exactly one tool mentioned, no collections
    if len(tools_mentioned) == 1 and len(collections_mentioned) == 0:
        tool = tools_mentioned[0]
        if tool in tool_entities:
            return tool_entities[tool]["entity_uri"]

    # Priority 3: exactly one collection mentioned, no tools
    if len(collections_mentioned) == 1 and len(tools_mentioned) == 0:
        coll = collections_mentioned[0]
        if coll in collection_entities:
            return collection_entities[coll]

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill entity_uri on ChromaDB chunks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report assignments without writing to ChromaDB")
    args = parser.parse_args()

    cfg = load_config()
    vs = cfg["vector_store"]
    gcfg = cfg["graph"]
    url_entity_map = gcfg.get("url_entity_map", {})
    tool_entities = cfg.get("tool_entities", {})
    collection_entities = gcfg.get("collection_entities", {})

    client = chromadb.HttpClient(host=vs["chroma_host"], port=vs["chroma_port"])
    collection = client.get_collection(vs["collection_name"])

    print(f"Fetching all chunks from ChromaDB '{vs['collection_name']}'…")
    result = collection.get(include=["metadatas"])
    ids = result["ids"]
    metadatas = result["metadatas"]
    print(f"  {len(ids):,} chunks fetched")

    # Tally assignments by method for reporting
    counts = {"url_map": 0, "single_tool": 0, "single_collection": 0, "none": 0}
    updated_ids: list[str] = []
    updated_metadatas: list[dict] = []

    for chunk_id, meta in zip(ids, metadatas):
        tools = json.loads(meta.get("tools_mentioned", "[]"))
        colls = json.loads(meta.get("collections_mentioned", "[]"))
        url = meta.get("url", "")

        uri = assign_entity_uri(url, tools, colls, url_entity_map, tool_entities, collection_entities)

        # Track method for stats
        if uri:
            for substring in url_entity_map:
                if substring in url:
                    counts["url_map"] += 1
                    break
            else:
                if len(tools) == 1 and len(colls) == 0:
                    counts["single_tool"] += 1
                else:
                    counts["single_collection"] += 1
        else:
            counts["none"] += 1

        updated_ids.append(chunk_id)
        updated_metadatas.append({**meta, "entity_uri": uri})

    assigned = len(ids) - counts["none"]
    print(f"\nAssignment summary:")
    print(f"  URL map match:        {counts['url_map']:4d}")
    print(f"  Single tool:          {counts['single_tool']:4d}")
    print(f"  Single collection:    {counts['single_collection']:4d}")
    print(f"  No match (empty):     {counts['none']:4d}")
    print(f"  Total assigned:       {assigned:4d} / {len(ids)} ({100*assigned//len(ids)}%)")

    if args.dry_run:
        print("\nDry run — no changes written.")
        # Show a sample of assigned URIs
        sample = [(i, m["entity_uri"], m.get("url", ""))
                  for i, m in zip(updated_ids, updated_metadatas)
                  if m["entity_uri"]][:10]
        print("\nSample assignments:")
        for chunk_id, uri, url in sample:
            short_uri = uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]
            print(f"  {short_uri:<30} {url}")
        return

    print(f"\nWriting entity_uri to ChromaDB in batches of {BATCH_SIZE}…")
    for i in range(0, len(updated_ids), BATCH_SIZE):
        batch_ids = updated_ids[i : i + BATCH_SIZE]
        batch_meta = updated_metadatas[i : i + BATCH_SIZE]
        collection.update(ids=batch_ids, metadatas=batch_meta)
        print(f"  Updated batch {i // BATCH_SIZE + 1} / {-(-len(updated_ids) // BATCH_SIZE)}")

    print(f"\nDone. entity_uri written to {len(updated_ids):,} chunks.")


if __name__ == "__main__":
    main()
