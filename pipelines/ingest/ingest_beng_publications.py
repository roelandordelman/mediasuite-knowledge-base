"""
Ingest publications from publications.beeldengeluid.nl via OAI-PMH.

Uses the Sickle library for harvesting. First run fetches all records (no `from`
date). Subsequent runs pass `from=<last_harvest>` for incremental updates.
State is persisted in stores/beng_publications_state.json (gitignored).

Each publication becomes one chunk: title + abstract + metadata as plain text.
No splitting — abstracts are 100–400 words, well within embedding context limits.

Usage:
    python pipelines/ingest/ingest_beng_publications.py
    python pipelines/ingest/ingest_beng_publications.py --full     # ignore state, re-harvest all
    python pipelines/ingest/ingest_beng_publications.py --limit 20 # test on first 20 records
    python pipelines/ingest/ingest_beng_publications.py --output beng_publications.json

Failure behaviour:
    - Endpoint unavailable: logs error, exits non-zero (no silent stale data).
    - Individual record parse error: logs warning, skips record, continues.

Requirements:
    pip install sickle pyyaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"

# Map EU repository semantic type URIs to human-readable labels
EU_TYPE_MAP = {
    "info:eu-repo/semantics/article": "Article",
    "info:eu-repo/semantics/report": "Report",
    "info:eu-repo/semantics/bookPart": "Book Chapter",
    "info:eu-repo/semantics/book": "Book",
    "info:eu-repo/semantics/conferencePaper": "Conference Paper",
    "info:eu-repo/semantics/conferencePoster": "Conference Poster",
    "info:eu-repo/semantics/doctoralThesis": "Doctoral Thesis",
    "info:eu-repo/semantics/masterThesis": "Master's Thesis",
    "info:eu-repo/semantics/preprint": "Preprint",
    "info:eu-repo/semantics/workingPaper": "Working Paper",
    "info:eu-repo/semantics/other": "Other",
}


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def clean_type(raw_type: str) -> str:
    if raw_type in EU_TYPE_MAP:
        return EU_TYPE_MAP[raw_type]
    # Fallback: use the last path segment of the URI
    if "/" in raw_type:
        return raw_type.rsplit("/", 1)[-1].replace("-", " ").title()
    return raw_type


def extract_https_url(identifiers: list[str]) -> str:
    for ident in identifiers:
        if ident.startswith("https://"):
            return ident
    for ident in identifiers:
        if ident.startswith("http://"):
            return ident
    return ""


def oai_id_to_local_id(oai_id: str) -> str:
    # "oai:publications.beeldengeluid.nl:2571" → "publications_beeldengeluid/2571"
    return f"publications_beeldengeluid/{oai_id.rsplit(':', 1)[-1]}"


def first(lst: list, default: str = "") -> str:
    return lst[0] if lst else default


def build_chunk_text(
    title: str,
    description: str,
    creators: list[str],
    date: str,
    pub_type: str,
    keywords: list[str],
) -> str:
    parts = [f"[{title}]"]
    if description:
        parts.append(description)
    meta_lines = []
    if creators:
        meta_lines.append(f"Authors: {'; '.join(creators)}")
    if date:
        meta_lines.append(f"Date: {date}")
    if pub_type:
        meta_lines.append(f"Type: {pub_type}")
    if keywords:
        meta_lines.append(f"Keywords: {', '.join(keywords)}")
    if meta_lines:
        parts.append("\n".join(meta_lines))
    return "\n\n".join(parts)


def extract_mentioned(text: str, candidates: list[str]) -> list[str]:
    text_lower = text.lower()
    return [c for c in candidates if c.lower() in text_lower]


def record_to_chunk(
    record,
    content_type: str,
    source_collection: str,
    known_tools: list[str],
    known_collections: list[str],
) -> dict | None:
    """Convert a Sickle OAI record to a knowledge base chunk dict. Returns None to skip."""
    if record.header.deleted:
        return None

    md = record.metadata
    oai_id = record.header.identifier

    title = first(md.get("title", []))
    if not title:
        logging.warning(f"Skipping {oai_id}: no title")
        return None

    creators = md.get("creator", [])
    description = first(md.get("description", []))
    date = first(md.get("date", []))
    language = first(md.get("language", []))
    raw_types = md.get("type", [])
    rights = first(md.get("rights", []))
    identifiers = md.get("identifier", [])
    keywords = md.get("subject", [])
    publisher = first(md.get("publisher", []))

    url = extract_https_url(identifiers)

    # Pick the best human-readable type (prefer EU semantic URI, fall back to first entry)
    pub_type = ""
    for t in raw_types:
        mapped = clean_type(t)
        # A successful EU URI mapping is short and title-cased
        if t in EU_TYPE_MAP:
            pub_type = mapped
            break
    if not pub_type and raw_types:
        pub_type = clean_type(raw_types[0])

    text = build_chunk_text(title, description, creators, date, pub_type, keywords)
    content_hash = hashlib.sha256(text.encode()).hexdigest()

    return {
        "id": oai_id_to_local_id(oai_id),
        "oai_id": oai_id,
        "title": title,
        "section": "",
        "collection": source_collection,
        "content_type": content_type,
        "url": url,
        "tags": keywords,
        "author": "; ".join(creators),
        "categories": [],
        "tools_mentioned": extract_mentioned(text, known_tools),
        "collections_mentioned": extract_mentioned(text, known_collections),
        "text": text,
        "char_count": len(text),
        "content_hash": content_hash,
        # Fields specific to this source (passed through to ChromaDB metadata)
        "creators": creators,
        "description": description,
        "date": date,
        "language": language,
        "type": pub_type,
        "rights": rights,
        "keywords": keywords,
        "publisher": publisher,
        "source": source_collection,  # enables ChromaDB where filter: source == "publications_beeldengeluid"
    }


def load_existing(output_path: Path) -> dict[str, dict]:
    """Load existing output file as a dict keyed by chunk ID."""
    if not output_path.exists():
        return {}
    with open(output_path) as f:
        existing = json.load(f)
    return {chunk["id"]: chunk for chunk in existing}


def harvest(cfg: dict, full: bool, limit: int | None) -> tuple[list[dict], int]:
    """
    Harvest records from the OAI-PMH endpoint.

    Returns (new_or_updated_chunks, deleted_count).
    On incremental run, only records modified since last_harvest are returned.
    On full run, all records are returned.
    """
    try:
        from sickle import Sickle
        from sickle.oaiexceptions import OAIError
    except ImportError:
        logging.error("sickle is not installed. Run: pip install sickle")
        sys.exit(1)

    source_cfg = cfg["beng_publications"]
    endpoint = source_cfg["oai_endpoint"]
    metadata_prefix = source_cfg.get("metadata_prefix", "oai_dc")
    content_type = source_cfg.get("content_type", "B&G Publication")
    source_collection = source_cfg.get("source_collection", "publications_beeldengeluid")
    state_path = Path(source_cfg["state_file"])

    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    state = load_state(state_path)
    from_date = None if (full or "last_harvest" not in state) else state["last_harvest"]

    if from_date:
        logging.info(f"Incremental harvest from {from_date}")
    else:
        logging.info("Full harvest (no from date — fetching all records)")

    sickle = Sickle(endpoint)
    kwargs: dict = {"metadataPrefix": metadata_prefix}
    if from_date:
        kwargs["from"] = from_date

    try:
        records_iter = sickle.ListRecords(**kwargs)
    except OAIError as e:
        logging.error(f"OAI-PMH error on ListRecords: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to connect to OAI-PMH endpoint {endpoint}: {e}")
        sys.exit(1)

    chunks: list[dict] = []
    deleted_ids: list[str] = []
    skipped = 0

    for i, record in enumerate(records_iter):
        if limit is not None and i >= limit:
            break
        try:
            if record.header.deleted:
                deleted_ids.append(oai_id_to_local_id(record.header.identifier))
                continue
            chunk = record_to_chunk(
                record, content_type, source_collection, known_tools, known_collections
            )
            if chunk is None:
                skipped += 1
            else:
                chunks.append(chunk)
        except Exception as e:
            oai_id = getattr(getattr(record, "header", None), "identifier", "?")
            logging.warning(f"Skipping {oai_id}: {e}")
            skipped += 1

    logging.info(
        f"Harvested {len(chunks)} records"
        + (f", {len(deleted_ids)} deleted" if deleted_ids else "")
        + (f", {skipped} skipped" if skipped else "")
    )
    return chunks, deleted_ids, state_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Ingest B&G publications via OAI-PMH",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force full re-harvest (ignore last_harvest state)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Limit to first N records (for testing)",
    )
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--config", type=str, default=None, help="Config YAML file path")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else CONFIG_PATH
    cfg = load_config(config_path)

    source_cfg = cfg["beng_publications"]
    output_path = Path(args.output) if args.output else Path(source_cfg["output"])
    state_path = Path(source_cfg["state_file"])

    # Harvest new/updated records
    new_chunks, deleted_ids, _ = harvest(cfg, args.full, args.limit)

    # Merge with existing output (upsert by chunk ID, remove deleted)
    existing = {} if args.full else load_existing(output_path)
    for chunk in new_chunks:
        existing[chunk["id"]] = chunk
    for dead_id in deleted_ids:
        existing.pop(dead_id, None)
        logging.info(f"Removed deleted record: {dead_id}")

    all_chunks = list(existing.values())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)

    logging.info(f"Wrote {len(all_chunks)} total chunks to {output_path}")

    # Update state only when not using --limit (partial run shouldn't advance the cursor)
    if args.limit is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_state = load_state(state_path)
        old_state["last_harvest"] = now
        old_state["record_count"] = len(all_chunks)
        save_state(state_path, old_state)
        logging.info(f"State updated: last_harvest={now}, record_count={len(all_chunks)}")
    else:
        logging.info("--limit active: state not updated")


if __name__ == "__main__":
    main()
