"""
Ingest Media Suite Data Stories from beeldengeluid/data-stories (Gatsby site).

Content lives in content/blog/<slug>/index.en.md (preferred) or index.md.
Dutch-only stories (no index.en.md and Dutch index.md) are skipped via
skip_slugs in config.yaml.

Usage:
    python pipelines/ingest/ingest_datastories.py
    python pipelines/ingest/ingest_datastories.py --repo /tmp/data-stories
    python pipelines/ingest/ingest_datastories.py --config /path/to/config.yaml

Output: data_stories.json

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


def ingest_story(
    story_dir: Path,
    cfg: dict,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
) -> list[dict]:
    slug = story_dir.name
    url = f"{cfg['url_prefix']}/{slug}/"

    candidates = [story_dir / "index.en.md", story_dir / "index.md"]
    filepath = next((p for p in candidates if p.exists()), None)
    if not filepath:
        print(f"  No usable index file in {slug}", file=sys.stderr)
        return []

    try:
        post = frontmatter.load(filepath)
    except Exception as e:
        print(f"  ERROR parsing {filepath}: {e}", file=sys.stderr)
        return []

    title = str(post.get("title", slug))
    date_raw = str(post.get("date", ""))
    date = date_raw[:10] if date_raw else ""
    year = date[:4] if date else ""
    description = str(post.get("description", ""))

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
                "id": f"data_stories/{slug}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": "data_stories",
                "content_type": cfg.get("content_type", "Data Story"),
                "url": url,
                "tags": [year] if year else [],
                "author": "",
                "categories": [],
                "tools_mentioned": extract_mentioned(full_text, known_tools),
                "collections_mentioned": extract_mentioned(full_text, known_collections),
                "modified_date": date,
                "source_commit": "",
                "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
                "text": full_text,
                "char_count": len(full_text),
            })
            chunk_idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(description="Ingest Media Suite Data Stories into the knowledge base")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--repo", type=Path, help="Path to cloned data-stories repo (overrides config)")
    parser.add_argument("--output", type=Path, help="Output JSON (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ds_cfg = cfg.get("data_stories", {})

    if not ds_cfg:
        print("No data_stories section in config.yaml.", file=sys.stderr)
        sys.exit(1)

    repo_path = args.repo or Path(ds_cfg["repo_path"])
    output_path = args.output or (args.config.parent / ds_cfg.get("output", "data_stories.json"))
    skip_slugs = set(ds_cfg.get("skip_slugs", []))
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]

    content_dir = repo_path / "content" / "blog"
    if not content_dir.exists():
        print(f"ERROR: content/blog not found at {content_dir}", file=sys.stderr)
        sys.exit(1)

    story_dirs = sorted(d for d in content_dir.iterdir() if d.is_dir())

    print(f"Ingesting from: {repo_path.resolve()}")
    print("-" * 60)

    all_chunks: list[dict] = []

    for story_dir in story_dirs:
        slug = story_dir.name
        if slug in skip_slugs:
            print(f"  {slug}: skipped (in skip_slugs)")
            continue

        chunks = ingest_story(
            story_dir, ds_cfg,
            chunk_target, chunk_overlap,
            known_tools, known_collections,
        )
        if chunks:
            print(f"  {slug}: {len(chunks)} chunks")
            all_chunks.extend(chunks)
        else:
            print(f"  {slug}: no content extracted")

    print("-" * 60)
    print(f"Total: {len(all_chunks)} chunks from {len(story_dirs) - len(skip_slugs)} stories")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Written to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
