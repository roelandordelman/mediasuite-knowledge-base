"""
Ingest publications from publications.beeldengeluid.nl via OAI-PMH.

Uses the Sickle library for harvesting. First run fetches all records (no `from`
date). Subsequent runs pass `from=<last_harvest>` for incremental updates.
State is persisted in stores/beng_publications_state.json (gitignored).

Relevance filtering (applied before indexing):
  1. Keyword pre-filter — record must mention Media Suite, NISV collections, or
     specific MS tool/collection names in title + abstract + dc:subject.
  2. LLM verify — Mistral (via Ollama) scores each keyword-matched record as
     RELEVANT or NOT_RELEVANT based on title + abstract. Result cached in
     stores/beng_publications_llm_cache.json so re-runs don't repeat LLM calls.
  3. DOI dedup — records whose DOI already appears in publications.json are
     skipped (Zotero version is richer; prefer it).

Flags:
  --no-filter   skip relevance filtering, index all records
  --no-llm      keyword pre-filter only, skip LLM verification step
  --full        ignore last_harvest state, re-harvest all records
  --limit N     stop after N records from the OAI-PMH feed (for testing;
                does not update state)

Failure behaviour:
  - Endpoint unavailable: logs error, exits non-zero (no silent stale data).
  - Individual record parse error: logs warning, skips record, continues.
  - Ollama unavailable: logs warning, falls back to keyword-only decision.

Requirements:
    pip install sickle pyyaml ollama
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"

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

# Signals that on their own reliably indicate relevance — used to include
# records without an abstract (can't LLM-verify those).
MS_DIRECT_SIGNALS = {
    "media suite", "mediasuite", "clariah media", "clariah wp5", "clariah wp 5",
}

LLM_PROMPT = """\
You are filtering publications for a knowledge base about the CLARIAH Media Suite — \
a Dutch research infrastructure for working with audiovisual archive collections \
(Sound & Vision, Radio/Television Archive, KB Newspaper Collection, EYE Film Collection, etc.).

A publication is RELEVANT if it meets at least one of these criteria:
1. It describes research conducted using Media Suite tools or the NISV data collections.
2. It analyses or discusses NISV (Netherlands Institute for Sound and Vision) audiovisual \
data in a way useful to researchers accessing these collections through the Media Suite.

A publication is NOT_RELEVANT if it:
- Only mentions Sound & Vision or NISV institutionally (as partner, funder, or employer) \
without engaging with the data or collections.
- Covers general AV preservation workflows, metadata standards, or institutional policy \
without reference to the collections themselves.
- Is about unrelated topics that happen to mention Beeld en Geluid.

Title: {title}

Abstract: {abstract}

Reply with exactly one word: RELEVANT or NOT_RELEVANT"""

DOI_RE = re.compile(r"\b(10\.\d{4,}/\S+)", re.IGNORECASE)


# ── Config / state helpers ────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def load_llm_cache(cache_path: Path) -> dict:
    return json.loads(cache_path.read_text()) if cache_path.exists() else {}


def save_llm_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2))


# ── DOI helpers ───────────────────────────────────────────────────────────────

def _norm_doi(raw: str) -> str:
    doi = raw.lower().strip().rstrip(".,;)")
    for prefix in ("doi:", "https://doi.org/", "http://doi.org/", "http://dx.doi.org/"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def extract_doi(identifiers: list[str]) -> str:
    for ident in identifiers:
        if ident.startswith("doi:"):
            return _norm_doi(ident)
        m = DOI_RE.search(ident)
        if m:
            return _norm_doi(m.group(1))
    return ""


def load_existing_dois(publications_json: Path) -> set[str]:
    if not publications_json.exists():
        return set()
    chunks = json.loads(publications_json.read_text())
    dois: set[str] = set()
    for chunk in chunks:
        for field in ("url", "id", "text"):
            m = DOI_RE.search(chunk.get(field, "")[:500])
            if m:
                dois.add(_norm_doi(m.group(1)))
                break
    return dois


# ── OAI / chunk helpers ───────────────────────────────────────────────────────

def clean_type(raw: str) -> str:
    if raw in EU_TYPE_MAP:
        return EU_TYPE_MAP[raw]
    return raw.rsplit("/", 1)[-1].replace("-", " ").title() if "/" in raw else raw


def extract_https_url(identifiers: list[str]) -> str:
    for ident in identifiers:
        if ident.startswith("https://"):
            return ident
    return next((i for i in identifiers if i.startswith("http://")), "")


def oai_id_to_local_id(oai_id: str) -> str:
    return f"publications_beeldengeluid/{oai_id.rsplit(':', 1)[-1]}"


def first(lst: list, default: str = "") -> str:
    return lst[0] if lst else default


def build_chunk_text(title, description, creators, date, pub_type, keywords) -> str:
    parts = [f"[{title}]"]
    if description:
        parts.append(description)
    meta = []
    if creators:
        meta.append(f"Authors: {'; '.join(creators)}")
    if date:
        meta.append(f"Date: {date}")
    if pub_type:
        meta.append(f"Type: {pub_type}")
    if keywords:
        meta.append(f"Keywords: {', '.join(keywords)}")
    if meta:
        parts.append("\n".join(meta))
    return "\n\n".join(parts)


def extract_mentioned(text: str, candidates: list[str]) -> list[str]:
    tl = text.lower()
    return [c for c in candidates if c.lower() in tl]


# ── Relevance filter ──────────────────────────────────────────────────────────

def build_keyword_signals(cfg: dict) -> list[str]:
    known_tools = [t.lower() for t in cfg.get("known_tools", [])]
    known_collections = [c.lower() for c in cfg.get("known_collections", [])]
    return sorted(
        MS_DIRECT_SIGNALS
        | {
            "sound and vision", "beeld en geluid", "beeldengeluid", "nisv",
            "data.beeldengeluid.nl", "lod.sound-and-vision",
        }
        | set(known_tools)
        | set(known_collections),
        key=len, reverse=True,  # longest first to avoid substring shadowing
    )


def keyword_match(title: str, description: str, subjects: list[str],
                  signals: list[str]) -> str | None:
    """Return first matching signal, or None."""
    haystack = " ".join([title, description] + subjects).lower()
    return next((s for s in signals if s in haystack), None)


def llm_is_relevant(title: str, description: str, model: str,
                    cache: dict, oai_id: str) -> bool:
    """
    Ask Mistral whether the record is relevant. Checks cache first.
    Falls back to True (include) if Ollama is unavailable.
    """
    if oai_id in cache:
        return cache[oai_id] == "relevant"

    try:
        import ollama as _ollama
        prompt = LLM_PROMPT.format(title=title, abstract=description[:2000])
        resp = _ollama.generate(model=model, prompt=prompt, options={"temperature": 0})
        answer = resp["response"].strip().upper()
        decision = "relevant" if "NOT_RELEVANT" not in answer and "RELEVANT" in answer else "not_relevant"
    except Exception as e:
        logging.warning(f"LLM unavailable for {oai_id}: {e} — defaulting to include")
        decision = "relevant"

    cache[oai_id] = decision
    return decision == "relevant"


# ── Record conversion ─────────────────────────────────────────────────────────

def record_to_chunk(record, content_type: str, source_collection: str,
                    known_tools: list[str], known_collections: list[str]) -> dict | None:
    if record.header.deleted:
        return None

    md = record.metadata
    oai_id = record.header.identifier
    title = first(md.get("title", []))
    if not title:
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
    doi = extract_doi(identifiers)

    url = extract_https_url(identifiers)

    pub_type = next((EU_TYPE_MAP[t] for t in raw_types if t in EU_TYPE_MAP), "")
    if not pub_type and raw_types:
        pub_type = clean_type(raw_types[0])

    text = build_chunk_text(title, description, creators, date, pub_type, keywords)

    return {
        "id": oai_id_to_local_id(oai_id),
        "oai_id": oai_id,
        "doi": doi,
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
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "creators": creators,
        "description": description,
        "date": date,
        "language": language,
        "type": pub_type,
        "rights": rights,
        "keywords": keywords,
        "publisher": publisher,
        "source": source_collection,
    }


# ── Harvest ───────────────────────────────────────────────────────────────────

def harvest(cfg: dict, full: bool, limit: int | None,
            apply_filter: bool, use_llm: bool) -> tuple[list[dict], list[str]]:
    try:
        from sickle import Sickle
        from sickle.oaiexceptions import OAIError
    except ImportError:
        logging.error("sickle not installed. Run: pip install sickle")
        sys.exit(1)

    source_cfg = cfg["beng_publications"]
    endpoint = source_cfg["oai_endpoint"]
    metadata_prefix = source_cfg.get("metadata_prefix", "oai_dc")
    content_type = source_cfg.get("content_type", "B&G Publication")
    source_collection = source_cfg.get("source_collection", "publications_beeldengeluid")
    gen_model = cfg.get("tech_stack", {}).get("generation_model", "mistral")
    state_path = Path(source_cfg["state_file"])
    cache_path = state_path.parent / "beng_publications_llm_cache.json"

    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])
    signals = build_keyword_signals(cfg)

    # Load existing Zotero DOIs for deduplication
    pub_json = Path(cfg.get("output", {}).get("knowledge_base_json", "knowledge_base.json")).parent / "publications.json"
    existing_dois = load_existing_dois(pub_json) if apply_filter else set()
    if existing_dois:
        logging.info(f"Loaded {len(existing_dois)} existing DOIs from publications.json for dedup")

    llm_cache = load_llm_cache(cache_path) if use_llm else {}

    state = load_state(state_path)
    from_date = None if (full or "last_harvest" not in state) else state["last_harvest"]
    logging.info(
        f"{'Full' if not from_date else f'Incremental from {from_date}'} harvest"
        + (f" | filter={'keyword+llm' if use_llm else 'keyword-only' if apply_filter else 'none'}")
    )

    sickle = Sickle(endpoint)
    kwargs: dict = {"metadataPrefix": metadata_prefix}
    if from_date:
        kwargs["from"] = from_date

    try:
        records_iter = sickle.ListRecords(**kwargs)
    except OAIError as e:
        logging.error(f"OAI-PMH error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to connect to {endpoint}: {e}")
        sys.exit(1)

    chunks: list[dict] = []
    deleted_ids: list[str] = []
    n_doi_dup = n_no_keyword = n_llm_reject = n_no_abstract = 0

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
                continue

            if apply_filter:
                # 1. DOI dedup
                if chunk["doi"] and chunk["doi"] in existing_dois:
                    n_doi_dup += 1
                    continue

                # 2. Keyword pre-filter
                sig = keyword_match(
                    chunk["title"], chunk["description"], chunk["keywords"], signals
                )
                if not sig:
                    n_no_keyword += 1
                    continue

                # 3. LLM verify (requires abstract; use direct signal as fallback)
                if use_llm:
                    if not chunk["description"]:
                        # No abstract — include only on direct MS signal in title
                        if not keyword_match(chunk["title"], "", [], list(MS_DIRECT_SIGNALS)):
                            n_no_abstract += 1
                            continue
                    else:
                        if not llm_is_relevant(
                            chunk["title"], chunk["description"],
                            gen_model, llm_cache, chunk["oai_id"]
                        ):
                            n_llm_reject += 1
                            logging.debug(f"LLM rejected: {chunk['title'][:60]}")
                            continue

            chunks.append(chunk)

        except Exception as e:
            oai_id = getattr(getattr(record, "header", None), "identifier", "?")
            logging.warning(f"Skipping {oai_id}: {e}")

    if use_llm:
        save_llm_cache(cache_path, llm_cache)
        logging.info(f"LLM cache saved ({len(llm_cache)} decisions)")

    logging.info(
        f"Harvested {len(chunks)} relevant chunks"
        + (f" | {n_doi_dup} DOI dups" if n_doi_dup else "")
        + (f" | {n_no_keyword} no keyword" if n_no_keyword else "")
        + (f" | {n_no_abstract} no abstract (weak signal)" if n_no_abstract else "")
        + (f" | {n_llm_reject} LLM rejected" if n_llm_reject else "")
        + (f" | {len(deleted_ids)} deleted" if deleted_ids else "")
    )
    return chunks, deleted_ids


def load_existing_chunks(output_path: Path) -> dict[str, dict]:
    if not output_path.exists():
        return {}
    return {c["id"]: c for c in json.loads(output_path.read_text())}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Ingest B&G publications via OAI-PMH")
    parser.add_argument("--full", action="store_true",
                        help="Force full re-harvest (ignore last_harvest state)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after N OAI records (for testing; state not updated)")
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip relevance filtering — index all records")
    parser.add_argument("--no-llm", action="store_true",
                        help="Keyword pre-filter only, skip LLM verification")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    parser.add_argument("--config", default=None, help="Config YAML file path")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else CONFIG_PATH
    cfg = load_config(config_path)

    source_cfg = cfg["beng_publications"]
    output_path = Path(args.output) if args.output else Path(source_cfg["output"])
    state_path = Path(source_cfg["state_file"])

    apply_filter = not args.no_filter
    use_llm = apply_filter and not args.no_llm

    new_chunks, deleted_ids = harvest(cfg, args.full, args.limit, apply_filter, use_llm)

    existing = {} if args.full else load_existing_chunks(output_path)
    for chunk in new_chunks:
        existing[chunk["id"]] = chunk
    for dead_id in deleted_ids:
        existing.pop(dead_id, None)

    all_chunks = list(existing.values())
    output_path.write_text(json.dumps(all_chunks, indent=2, ensure_ascii=False))
    logging.info(f"Wrote {len(all_chunks)} chunks to {output_path}")

    if args.limit is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = load_state(state_path)
        state["last_harvest"] = now
        state["record_count"] = len(all_chunks)
        save_state(state_path, state)
        logging.info(f"State updated: last_harvest={now}, record_count={len(all_chunks)}")
    else:
        logging.info("--limit active: state not updated")


if __name__ == "__main__":
    main()
