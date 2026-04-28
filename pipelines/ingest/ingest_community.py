"""
Ingest the Media Suite Community site (roelandordelman/media-suite-community).

Ingests configured root pages (e.g. sane.md) and Jekyll collection items
(e.g. _sane-collections/*.md). URL for root pages is derived from the
'permalink' frontmatter field; collection items use the url_prefix in config.

Usage:
    python pipelines/ingest/ingest_community.py
    python pipelines/ingest/ingest_community.py --repo /tmp/media-suite-community
    python pipelines/ingest/ingest_community.py --config /path/to/config.yaml

Output: community.json

Requirements:
    pip install python-frontmatter pyyaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import frontmatter
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def clean_markdown(text: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def split_into_sections(body: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)
    sections = []
    last_end = 0
    current_heading = ""

    for match in pattern.finditer(body):
        chunk_text = body[last_end:match.start()].strip()
        if chunk_text:
            sections.append((current_heading, chunk_text))
        current_heading = match.group(2).strip()
        last_end = match.end()

    remaining = body[last_end:].strip()
    if remaining:
        sections.append((current_heading, remaining))

    return sections


def chunk_text(text: str, target: int, overlap: int) -> list[str]:
    if len(text) <= target:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + target, len(text))
        if end < len(text):
            para_break = text.rfind('\n\n', start, end)
            if para_break > start + target // 2:
                end = para_break
            else:
                sent_break = max(
                    text.rfind('. ', start, end),
                    text.rfind('.\n', start, end),
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
        if re.search(r'\b' + re.escape(item) + r'\b', haystack, re.IGNORECASE)
    ]


def ingest_file(
    filepath: Path,
    collection_id: str,
    url: str,
    content_type: str,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
    title_override: str | None = None,
) -> list[dict]:
    try:
        post = frontmatter.load(filepath)
    except Exception as e:
        print(f"  ERROR parsing {filepath}: {e}", file=sys.stderr)
        return []

    title = title_override or str(post.get("title", filepath.stem))
    description = str(post.get("description", ""))
    slug = filepath.stem

    body = post.content or ""
    if description and description not in body:
        body = description + "\n\n" + body

    body_clean = clean_markdown(body)
    if not body_clean.strip():
        return []

    sections = split_into_sections(body_clean) or [("", body_clean)]

    records = []
    chunk_idx = 0

    for section_heading, section_text in sections:
        context_prefix = title
        if section_heading:
            context_prefix += f" — {section_heading}"

        for text_item in chunk_text(section_text, chunk_target, chunk_overlap):
            full_text = f"[{context_prefix}]\n{text_item}"
            records.append({
                "id": f"community/{collection_id}/{slug}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": "community",
                "content_type": content_type,
                "url": url,
                "tags": [],
                "author": "",
                "categories": [],
                "tools_mentioned": extract_mentioned(full_text, known_tools),
                "collections_mentioned": extract_mentioned(full_text, known_collections),
                "modified_date": "",
                "source_commit": "",
                "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
                "text": full_text,
                "char_count": len(full_text),
            })
            chunk_idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(description="Ingest Media Suite Community site into the knowledge base")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--repo", type=Path, help="Path to cloned media-suite-community repo (overrides config)")
    parser.add_argument("--output", type=Path, help="Output JSON (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    comm_cfg = cfg.get("community_site", {})

    if not comm_cfg:
        print("No community_site section in config.yaml.", file=sys.stderr)
        sys.exit(1)

    repo_path = args.repo or Path(comm_cfg["repo_path"])
    output_path = args.output or (args.config.parent / comm_cfg.get("output", "community.json"))
    base_url = comm_cfg["base_url"].rstrip("/")
    title_overrides = comm_cfg.get("title_overrides", {})
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]

    if not repo_path.exists():
        print(f"ERROR: repo not found at {repo_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Ingesting from: {repo_path.resolve()}")
    print("-" * 60)

    all_chunks: list[dict] = []

    # Root pages — URL derived from 'permalink' frontmatter field
    for page_cfg in comm_cfg.get("pages", []):
        filepath = repo_path / page_cfg["file"]
        if not filepath.exists():
            print(f"  WARNING: {page_cfg['file']} not found — skipping", file=sys.stderr)
            continue

        try:
            post = frontmatter.load(filepath)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue

        permalink = str(post.get("permalink", f"/{filepath.stem}/")).strip("/")
        url = f"{base_url}/{permalink}/"
        content_type = page_cfg.get("content_type", "Community Documentation")
        title_override = title_overrides.get(filepath.stem)

        chunks = ingest_file(
            filepath, "pages", url, content_type,
            chunk_target, chunk_overlap, known_tools, known_collections,
            title_override=title_override,
        )
        print(f"  {page_cfg['file']}: {len(chunks)} chunks  →  {url}")
        all_chunks.extend(chunks)

    # Jekyll collections — URL constructed from collection url_prefix + slug
    for coll_dir_name, coll_conf in comm_cfg.get("collections", {}).items():
        coll_dir = repo_path / coll_dir_name
        if not coll_dir.exists():
            print(f"  WARNING: {coll_dir_name} not found — skipping", file=sys.stderr)
            continue

        url_prefix = coll_conf["url_prefix"].rstrip("/")
        content_type = coll_conf.get("content_type", "Community Documentation")

        for filepath in sorted(coll_dir.glob("*.md")):
            slug = filepath.stem
            url = f"{url_prefix}/{slug}/"
            chunks = ingest_file(
                filepath, coll_dir_name, url, content_type,
                chunk_target, chunk_overlap, known_tools, known_collections,
            )
            print(f"  {coll_dir_name}/{filepath.name}: {len(chunks)} chunks  →  {url}")
            all_chunks.extend(chunks)

    print("-" * 60)
    print(f"Total: {len(all_chunks)} chunks")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Written to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
