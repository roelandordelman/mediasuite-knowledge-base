"""
Ingest Tier 1 authored content from the content/ directory.

Reads markdown files with YAML front matter following content/_template.md.
Only files with status: active are indexed. Drafts are reported but skipped.

Lint checks:
- Required front matter fields are present and non-empty.
- tech_dependencies (if declared) match the tech_stack section in config.yaml.

Usage:
    python pipelines/ingest/ingest_content.py
    python pipelines/ingest/ingest_content.py --content-dir content
    python pipelines/ingest/ingest_content.py --output content.json

Output: content.json

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
CONTENT_DIR = Path(__file__).parents[2] / "content"

REQUIRED_FIELDS = ["title", "content_type", "url_stub", "status"]

MOSCOW_RE = re.compile(r"\s*\*?\((?:Must|Should|Could|Won't)\)\*?", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def clean_markdown(text: str) -> str:
    text = HTML_COMMENT_RE.sub("", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_sections(body: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    sections = []
    last_end = 0
    current_heading = ""

    for match in pattern.finditer(body):
        chunk_text = body[last_end : match.start()].strip()
        if chunk_text:
            sections.append((current_heading, chunk_text))
        raw_heading = match.group(2).strip()
        current_heading = MOSCOW_RE.sub("", raw_heading).strip()
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
        item
        for item in known
        if re.search(r"\b" + re.escape(item) + r"\b", haystack, re.IGNORECASE)
    ]


def lint_document(post: frontmatter.Post, path: Path, tech_stack: dict) -> list[str]:
    warnings = []

    for field in REQUIRED_FIELDS:
        if not post.get(field):
            warnings.append(f"missing required field: {field}")

    declared_deps = post.get("tech_dependencies", [])
    if declared_deps and tech_stack:
        stack_values = {str(v).lower() for v in tech_stack.values()}
        for dep in declared_deps:
            if dep.lower() not in stack_values:
                warnings.append(
                    f"tech_dependency '{dep}' not found in config.yaml tech_stack "
                    f"— stack may have changed, review document"
                )

    return warnings


def make_chunks(
    post: frontmatter.Post,
    known_tools: list[str],
    known_collections: list[str],
    chunk_target: int,
    chunk_overlap: int,
    base_url: str,
) -> list[dict]:
    url_stub = post["url_stub"]
    title = post["title"]
    content_type = post["content_type"]
    tags = post.get("tags", [])
    author = post.get("author", "")
    url = f"{base_url.rstrip('/')}/{url_stub}" if base_url else url_stub

    body = clean_markdown(post.content)
    sections = split_into_sections(body)

    records = []
    chunk_idx = 0

    for section_heading, section_text in sections:
        context_prefix = title
        if section_heading:
            context_prefix += f" — {section_heading}"

        for sub_text in chunk_text(section_text, chunk_target, chunk_overlap):
            full_text = f"[{context_prefix}]\n{sub_text.strip()}"
            records.append({
                "id": f"content/{url_stub}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": "content",
                "content_type": content_type,
                "url": url,
                "tags": tags if isinstance(tags, list) else [tags],
                "author": author,
                "categories": [],
                "tools_mentioned": extract_mentioned(full_text, known_tools),
                "collections_mentioned": extract_mentioned(full_text, known_collections),
                "modified_date": str(post.get("last_reviewed", "")),
                "source_commit": "",
                "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
                "tier": post.get("tier", 1),
                "status": post.get("status", ""),
                "last_reviewed": str(post.get("last_reviewed", "")),
                "source_slug": url_stub,
                "tech_dependencies": json.dumps(
                    post.get("tech_dependencies", []), ensure_ascii=False
                ),
                "text": full_text,
                "char_count": len(full_text),
            })
            chunk_idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Tier 1 authored content from the content/ directory"
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--content-dir", type=Path, default=CONTENT_DIR)
    parser.add_argument("--output", type=Path, help="Output JSON (overrides config)")
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Index draft documents in addition to active ones (for testing)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    content_cfg = cfg.get("content", {})
    tech_stack = cfg.get("tech_stack", {})

    output_path = (
        args.output
        or args.config.parent / content_cfg.get("output", "content.json")
    )
    base_url = content_cfg.get("base_url", "")
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]

    md_files = sorted(
        p for p in args.content_dir.rglob("*.md") if not p.name.startswith("_")
    )

    if not md_files:
        print(f"No markdown files found in {args.content_dir}", file=sys.stderr)
        sys.exit(0)

    all_chunks: list[dict] = []
    counts = {"active": 0, "draft": 0, "deprecated": 0, "retired": 0, "skipped": 0}

    for path in md_files:
        rel = path.relative_to(args.content_dir)
        post = frontmatter.load(path)
        status = post.get("status", "draft")

        warnings = lint_document(post, path, tech_stack)
        for w in warnings:
            print(f"  LINT {rel}: {w}", file=sys.stderr)

        if status == "retired":
            print(f"  SKIP {rel} (retired)")
            counts["retired"] += 1
            continue

        if status == "deprecated":
            print(f"  SKIP {rel} (deprecated)")
            counts["deprecated"] += 1
            continue

        if status == "draft" and not args.include_drafts:
            print(f"  SKIP {rel} (draft — use --include-drafts to index)")
            counts["draft"] += 1
            continue

        chunks = make_chunks(
            post, known_tools, known_collections, chunk_target, chunk_overlap, base_url
        )

        if not chunks:
            print(f"  WARN {rel}: no chunks produced — check content", file=sys.stderr)
            counts["skipped"] += 1
            continue

        all_chunks.extend(chunks)
        counts["active"] += 1
        print(f"  OK   {rel} → {len(chunks)} chunks")

    print(f"\nSummary:")
    print(f"  Active:     {counts['active']} documents indexed")
    print(f"  Draft:      {counts['draft']} skipped")
    print(f"  Deprecated: {counts['deprecated']} skipped")
    print(f"  Retired:    {counts['retired']} skipped")
    print(f"  Total chunks: {len(all_chunks)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"\nWritten to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
