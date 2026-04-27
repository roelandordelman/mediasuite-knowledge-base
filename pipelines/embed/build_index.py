"""
Build ChromaDB vector index from knowledge_base.json.

Connects to a running ChromaDB HTTP server (start with: chroma run --path ./stores/chroma_db).
Embeddings are generated locally via Ollama (nomic-embed-text).

Usage:
    python pipelines/embed/build_index.py
    python pipelines/embed/build_index.py --input /path/to/knowledge_base.json
    python pipelines/embed/build_index.py --config /path/to/config.yaml

Requirements:
    pip install chromadb ollama pyyaml
    ollama pull nomic-embed-text
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ollama
import chromadb
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _list_to_json(value: list) -> str:
    """Encode a list as a JSON string for ChromaDB metadata (which requires scalar values)."""
    return json.dumps(value, ensure_ascii=False)


def build_index(input_path: Path, cfg: dict) -> None:
    vs = cfg["vector_store"]
    embed_cfg = cfg["embedding"]

    print(f"Loading chunks from {input_path} …")
    chunks = json.loads(input_path.read_text())
    print(f"  {len(chunks):,} chunks loaded")

    client = chromadb.HttpClient(host=vs["chroma_host"], port=vs["chroma_port"])
    collection = client.get_or_create_collection(vs["collection_name"])

    existing_ids = set(collection.get(include=[])["ids"])
    new_chunks = [c for c in chunks if c["id"] not in existing_ids]
    print(f"  {len(new_chunks):,} new chunks to embed "
          f"(skipping {len(existing_ids):,} already indexed)")

    if not new_chunks:
        print("Nothing to do.")
        return

    batch_size = embed_cfg["batch_size"]
    total_batches = -(-len(new_chunks) // batch_size)  # ceiling division

    for i in range(0, len(new_chunks), batch_size):
        batch = new_chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]

        response = ollama.embed(model=embed_cfg["model"], input=texts)
        embeddings = response["embeddings"]

        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "title": c.get("title", ""),
                    "section": c.get("section", ""),
                    "collection": c.get("collection", ""),
                    "content_type": c.get("content_type", ""),
                    "url": c.get("url", ""),
                    "author": c.get("author", ""),
                    "tags": _list_to_json(c.get("tags", [])),
                    "categories": _list_to_json(c.get("categories", [])),
                    "tools_mentioned": _list_to_json(c.get("tools_mentioned", [])),
                    "collections_mentioned": _list_to_json(c.get("collections_mentioned", [])),
                    "modified_date": c.get("modified_date", ""),
                    "source_commit": c.get("source_commit", ""),
                    "content_hash": c.get("content_hash", ""),
                    "char_count": c.get("char_count", 0),
                }
                for c in batch
            ],
        )
        print(f"  Indexed batch {i // batch_size + 1} / {total_batches}")

    print(f"\nDone. {len(new_chunks):,} chunks indexed into "
          f"'{vs['collection_name']}' on {vs['chroma_host']}:{vs['chroma_port']}")


def main():
    parser = argparse.ArgumentParser(description="Embed knowledge_base.json into ChromaDB")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="Path to config.yaml")
    parser.add_argument("--input", type=Path,
                        help="Input JSON file (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    input_path = args.input or (args.config.parent / cfg["output"]["knowledge_base_json"])

    if not input_path.exists():
        print(f"ERROR: knowledge base not found at {input_path}")
        print("Run pipelines/ingest/ingest_mediasuite.py first.")
        raise SystemExit(1)

    build_index(input_path, cfg)


if __name__ == "__main__":
    main()
