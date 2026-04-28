"""
Ingest local PDF documents into the knowledge base.

Handles internal or non-DOI documents that are configured explicitly in
config.yaml. Unlike the publications pipeline there is no Zotero/OpenAlex
lookup or summary generation — sections are extracted and chunked directly.

Usage:
    python pipelines/ingest/ingest_local_docs.py
    python pipelines/ingest/ingest_local_docs.py --config /path/to/config.yaml
    python pipelines/ingest/ingest_local_docs.py --output /path/to/local_docs.json

Output: local_docs.json (path configurable in config.yaml)

Requirements:
    pip install pdfplumber pyyaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"

HEADING_RE = re.compile(
    r"^(?:\d+\.?\s*)?"
    r"(abstract|introduction|background|related work|"
    r"research method(?:ology)?|method(?:ology)?|data and method|"
    r"approach|materials? and method|"
    r"results?|findings?|analysis|discussion|"
    r"conclusion|summary|acknowledgment|references?)s?\.?$",
    re.IGNORECASE,
)

ALL_CAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z\s&/()\-]{2,44}$")

# Matches numbered section headings in Dutch institutional documents
# e.g. "1. Wat is de Media Suite?", "3.1 Grip op AI", "3.2 Hoogwaardige Databronnen"
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)?\.?\s+\S.{2,40}$")

NEVER_KEEP = {"references", "acknowledgment", "acknowledgments", "bibliography"}


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def extract_text_sections(pdf_path: Path) -> dict[str, str]:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as e:
        print(f"    PDF PARSE FAILED: {e}", file=sys.stderr)
        return {}

    full_text = "\n".join(pages_text)
    if len(full_text.strip()) < 200:
        return {}

    all_stripped = [l.strip() for p in pages_text for l in p.split("\n") if l.strip()]
    freq = Counter(all_stripped)
    n_pages = len(pages_text)
    boilerplate = {line for line, count in freq.items() if count >= max(3, n_pages * 0.3)}

    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []

    for line in full_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in boilerplate:
            continue
        is_url_footnote = bool(re.match(r"^\d+\s+https?://", stripped))
        if not is_url_footnote and len(stripped) < 60 and (
            HEADING_RE.match(stripped)
            or ALL_CAPS_HEADING_RE.match(stripped)
            or NUMBERED_HEADING_RE.match(stripped)
        ):
            current = stripped.lower()
            if current not in sections:
                sections[current] = []
        else:
            sections[current].append(stripped)

    return {k: " ".join(v) for k, v in sections.items() if v}


def chunk_text(text: str, target: int, overlap: int) -> list[str]:
    if len(text) <= target:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + target, len(text))
        if end < len(text):
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + target // 2:
                end = para_break
            else:
                sent_break = max(
                    text.rfind(". ", start, end),
                    text.rfind(".\n", start, end),
                )
                if sent_break > start + target // 2:
                    end = sent_break + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def extract_mentioned(haystack: str, known: list[str]) -> list[str]:
    return [
        item for item in known
        if re.search(r"\b" + re.escape(item) + r"\b", haystack, re.IGNORECASE)
    ]


def make_chunks(
    doc_cfg: dict,
    sections: dict[str, str],
    known_tools: list[str],
    known_collections: list[str],
    chunk_target: int,
    chunk_overlap: int,
) -> list[dict]:
    id_slug = doc_cfg["id_slug"]
    title = doc_cfg["title"]
    url = doc_cfg.get("url", "")
    content_type = doc_cfg.get("content_type", "Planning Document")
    year = str(doc_cfg.get("year", ""))
    author = doc_cfg.get("author", "")

    records = []
    chunk_idx = 0

    for section_name, text in sections.items():
        if any(k in section_name for k in NEVER_KEEP):
            continue

        context_prefix = title
        if section_name and section_name != "preamble":
            context_prefix += f" — {section_name.title()}"

        for sub_text in chunk_text(text, chunk_target, chunk_overlap):
            full_text = f"[{context_prefix}]\n{sub_text.strip()}"
            records.append({
                "id": f"local_docs/{id_slug}/{chunk_idx}",
                "title": title,
                "section": "" if section_name == "preamble" else section_name,
                "collection": "local_docs",
                "content_type": content_type,
                "url": url,
                "tags": [],
                "author": author,
                "categories": [],
                "tools_mentioned": extract_mentioned(full_text, known_tools),
                "collections_mentioned": extract_mentioned(full_text, known_collections),
                "modified_date": year,
                "source_commit": "",
                "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
                "text": full_text,
                "char_count": len(full_text),
            })
            chunk_idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(description="Ingest local PDF documents into the knowledge base")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, help="Output JSON (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    local_cfg = cfg.get("local_docs", {})

    if not local_cfg:
        print("No local_docs section in config.yaml — nothing to do.", file=sys.stderr)
        sys.exit(0)

    output_path = args.output or (args.config.parent / local_cfg.get("output", "local_docs.json"))
    documents = local_cfg.get("documents", [])
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]

    all_chunks: list[dict] = []

    for doc_cfg in documents:
        pdf_path = Path(doc_cfg["path"])
        print(f"\n{doc_cfg['title']}")
        print(f"  {pdf_path}")

        if not pdf_path.exists():
            print(f"  WARNING: file not found — skipping", file=sys.stderr)
            continue

        sections = extract_text_sections(pdf_path)
        if not sections:
            print(f"  No sections extracted — skipping")
            continue

        print(f"  Extracted {len(sections)} sections: {list(sections.keys())[:8]}")
        chunks = make_chunks(
            doc_cfg, sections, known_tools, known_collections, chunk_target, chunk_overlap
        )
        all_chunks.extend(chunks)
        print(f"  → {len(chunks)} chunks")

    print(f"\nTotal: {len(all_chunks)} chunks from {len(documents)} documents")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Written to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
