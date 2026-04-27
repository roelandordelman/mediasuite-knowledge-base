"""
Media Suite Knowledge Base Ingestion
=====================================
Converts beeldengeluid/mediasuite-website (Jekyll/Markdown) into a chunked
JSON file ready for embedding + RAG.

Usage:
    python pipelines/ingest/ingest_mediasuite.py
    python pipelines/ingest/ingest_mediasuite.py --repo /tmp/mediasuite-website
    python pipelines/ingest/ingest_mediasuite.py --config /path/to/config.yaml

Output: knowledge_base.json with chunk objects matching the schema in CLAUDE.md.

Requirements:
    pip install python-frontmatter pyyaml
"""

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


def slug_from_filename(filename: str) -> str:
    return Path(filename).stem


def build_url(url_prefix: str, slug: str) -> str:
    return f"{url_prefix}/{slug}"


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


def get_git_file_info(repo_path: Path, filepath: Path) -> tuple[str, str]:
    """Return (modified_date, source_commit) from git log for a file.

    Note: a shallow clone (--depth=1) gives the same date for all files since
    there is only one commit in the local history. Clone without --depth for
    accurate per-file modification dates.
    """
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


def extract_mentioned(haystack: str, known: list[str]) -> list[str]:
    """Return items from known whose name appears (word-boundary match) in haystack."""
    return [
        item for item in known
        if re.search(r'\b' + re.escape(item) + r'\b', haystack, re.IGNORECASE)
    ]


def ingest_file(
    filepath: Path,
    collection_key: str,
    conf: dict,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
    repo_path: Path,
) -> list[dict]:
    try:
        post = frontmatter.load(filepath)
    except Exception as e:
        print(f"  WARNING: could not parse {filepath}: {e}", file=sys.stderr)
        return []

    modified_date, source_commit = get_git_file_info(repo_path, filepath)

    slug = slug_from_filename(filepath.name)
    url = build_url(conf["url_prefix"], slug)

    title = str(post.get("title", slug))
    author = str(post.get("author", ""))
    tags = post.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    categories = post.get("categories", [])
    if isinstance(categories, str):
        categories = [categories]
    introduction = str(post.get("introduction", ""))

    body = post.content or ""
    if introduction and introduction not in body:
        body = introduction + "\n\n" + body

    body_clean = clean_markdown(body)
    if not body_clean.strip():
        return []

    sections = split_into_sections(body_clean) or [("", body_clean)]

    # Build a searchable string from all tags for entity extraction
    tags_text = " ".join(tags)

    records = []
    chunk_idx = 0

    for section_heading, section_text in sections:
        context_prefix = title
        if section_heading:
            context_prefix += f" — {section_heading}"

        for text_item in chunk_text(section_text, chunk_target, chunk_overlap):
            full_text = f"[{context_prefix}]\n{text_item}"
            search_text = f"{full_text} {tags_text}"

            record = {
                "id": f"{collection_key}/{slug}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": collection_key,
                "content_type": conf["content_type"],
                "url": url,
                "tags": tags,
                "author": author,
                "categories": categories,
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


def ingest_repo(
    repo_path: Path,
    collections_cfg: dict,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
) -> tuple[list[dict], dict]:
    all_chunks = []
    stats = {}

    for collection_key, conf in collections_cfg.items():
        if not conf.get("include", True):
            continue

        coll_dir = repo_path / collection_key
        if not coll_dir.exists():
            print(f"  Skipping {collection_key} (not found)", file=sys.stderr)
            continue

        files = sorted(coll_dir.glob("*.markdown")) + sorted(coll_dir.glob("*.md"))
        file_chunks = []

        for f in files:
            chunks = ingest_file(
                f, collection_key, conf,
                chunk_target, chunk_overlap,
                known_tools, known_collections,
                repo_path,
            )
            file_chunks.extend(chunks)
            if chunks:
                print(f"  {collection_key}/{f.name}: {len(chunks)} chunks")

        all_chunks.extend(file_chunks)
        stats[collection_key] = {"files": len(files), "chunks": len(file_chunks)}

    return all_chunks, stats


def main():
    parser = argparse.ArgumentParser(description="Ingest mediasuite-website into RAG-ready JSON")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="Path to config.yaml")
    parser.add_argument("--repo", type=Path,
                        help="Path to cloned mediasuite-website repo (overrides config)")
    parser.add_argument("--output", type=Path,
                        help="Output JSON file path (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    repo_path = args.repo or Path(cfg["source"]["repo_path"])
    output_path = args.output or (args.config.parent / cfg["output"]["knowledge_base_json"])

    if not repo_path.exists():
        print(f"ERROR: repo not found at {repo_path}", file=sys.stderr)
        sys.exit(1)

    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    print(f"Ingesting from: {repo_path.resolve()}")
    print("-" * 60)

    chunks, stats = ingest_repo(
        repo_path, cfg["collections"],
        chunk_target, chunk_overlap,
        known_tools, known_collections,
    )

    print("-" * 60)
    print("\nSummary:")
    total_files = sum(s["files"] for s in stats.values())
    total_chunks = sum(s["chunks"] for s in stats.values())
    for coll, s in stats.items():
        print(f"  {coll:35s} {s['files']:3d} files → {s['chunks']:4d} chunks")
    print(f"  {'TOTAL':35s} {total_files:3d} files → {total_chunks:4d} chunks")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"\nWritten to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
