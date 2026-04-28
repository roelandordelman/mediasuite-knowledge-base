"""
Ingest data.beeldengeluid.nl into the knowledge base.

Clones/reads the beeldengeluid/data.beeldengeluid.nl GitHub repo and converts
the Markdown content files (content/en/datasets/, content/en/apis/) into the
same chunk format used by the rest of the pipeline.

This is preferable to web scraping: clean Markdown + YAML front matter,
git metadata for freshness tracking, no dependency on the site's HTML structure.

Usage:
    python pipelines/ingest/ingest_dataplatform.py
    python pipelines/ingest/ingest_dataplatform.py --repo /tmp/data.beeldengeluid.nl
    python pipelines/ingest/ingest_dataplatform.py --config /path/to/config.yaml

Requirements:
    pip install python-frontmatter pyyaml
    (same dependencies as ingest_mediasuite.py — no extra installs needed)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import frontmatter
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_git_file_info(repo_path: Path, filepath: Path) -> tuple[str, str]:
    try:
        relative = filepath.relative_to(repo_path)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H %ad", "--date=short", "--", str(relative)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            commit_hash, date = result.stdout.strip().split(" ", 1)
            return date, commit_hash
    except Exception:
        pass
    return "", ""


def clean_markdown(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_sections(body: str) -> list[tuple[str, str]]:
    # Match h2, h3, and h4 headings (data.beeldengeluid.nl uses all three)
    pattern = re.compile(r"^(#{2,4})\s+(.+)$", re.MULTILINE)
    sections = []
    last_end = 0
    current_heading = ""

    for match in pattern.finditer(body):
        chunk_text = body[last_end : match.start()].strip()
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


def ingest_file(
    filepath: Path,
    content_type: str,
    url_prefix: str,
    subdir: str,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
    repo_path: Path,
    title_overrides: dict[str, str] | None = None,
) -> list[dict]:
    try:
        post = frontmatter.load(filepath)
    except Exception as e:
        print(f"  WARNING: could not parse {filepath}: {e}", file=sys.stderr)
        return []

    modified_date, source_commit = get_git_file_info(repo_path, filepath)

    slug = filepath.stem
    url = f"{url_prefix}/{slug}"

    title = (title_overrides or {}).get(slug) or str(post.get("title", slug))
    subtitle = str(post.get("subtitle", ""))
    tags = post.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]

    body = post.content or ""

    # Prepend subtitle as intro text if it adds information not in the body
    if subtitle and subtitle not in body:
        body = subtitle + "\n\n" + body

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

        for text_chunk in chunk_text(section_text, chunk_target, chunk_overlap):
            full_text = f"[{context_prefix}]\n{text_chunk}"
            search_text = full_text

            record = {
                "id": f"data_platform/{subdir}/{slug}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": "data_platform",
                "content_type": content_type,
                "url": url,
                "tags": tags,
                "author": "",
                "categories": [],
                "tools_mentioned": extract_mentioned(search_text, known_tools),
                "collections_mentioned": extract_mentioned(search_text, known_collections),
                "modified_date": modified_date,
                "source_commit": source_commit,
                "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
                "text": full_text,
                "char_count": len(full_text),
            }
            records.append(record)
            chunk_idx += 1

    return records


def ingest_collection(
    repo_path: Path,
    subdir: str,
    content_type: str,
    url_prefix: str,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
    title_overrides: dict[str, str] | None = None,
) -> tuple[list[dict], int]:
    coll_dir = repo_path / "content" / "en" / subdir
    if not coll_dir.exists():
        print(f"  Skipping {subdir} (not found at {coll_dir})", file=sys.stderr)
        return [], 0

    files = sorted(coll_dir.glob("*.md"))
    all_chunks = []

    for f in files:
        chunks = ingest_file(
            f, content_type, url_prefix, subdir,
            chunk_target, chunk_overlap,
            known_tools, known_collections,
            repo_path, title_overrides,
        )
        if chunks:
            print(f"  {subdir}/{f.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)

    return all_chunks, len(files)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest data.beeldengeluid.nl GitHub repo into the knowledge base"
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--repo", type=Path, help="Path to cloned repo (overrides config)")
    parser.add_argument("--output", type=Path, help="Output JSON file (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dp_cfg = cfg.get("data_platform", {})

    repo_path = args.repo or Path(dp_cfg.get("repo_path", "/tmp/data.beeldengeluid.nl"))
    output_path = args.output or (args.config.parent / dp_cfg.get("output", "data_platform.json"))

    if not repo_path.exists():
        print(f"Repo not found at {repo_path}. Cloning…")
        subprocess.run(
            ["git", "clone", "--depth=1",
             "https://github.com/beeldengeluid/data.beeldengeluid.nl.git",
             str(repo_path)],
            check=True,
        )

    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    collections_cfg = dp_cfg.get("collections", {
        "datasets": {
            "content_type": "Collection Documentation",
            "url_prefix": "https://data.beeldengeluid.nl/datasets",
        },
        "apis": {
            "content_type": "API Documentation",
            "url_prefix": "https://data.beeldengeluid.nl/apis",
        },
    })

    print(f"Ingesting from: {repo_path.resolve()}")
    print("-" * 60)

    all_chunks: list[dict] = []
    stats = {}

    title_overrides = dp_cfg.get("title_overrides", {})

    for subdir, conf in collections_cfg.items():
        chunks, n_files = ingest_collection(
            repo_path, subdir,
            conf["content_type"], conf["url_prefix"],
            chunk_target, chunk_overlap,
            known_tools, known_collections,
            title_overrides,
        )
        all_chunks.extend(chunks)
        stats[subdir] = {"files": n_files, "chunks": len(chunks)}

    print("-" * 60)
    print("\nSummary:")
    for subdir, s in stats.items():
        print(f"  {subdir:20s} {s['files']:3d} files → {s['chunks']:4d} chunks")
    print(f"  {'TOTAL':20s} {sum(s['files'] for s in stats.values()):3d} files → "
          f"{len(all_chunks):4d} chunks")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"\nWritten to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
