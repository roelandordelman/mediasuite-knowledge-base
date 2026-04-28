"""
Ingest data.beeldengeluid.nl into the knowledge base.

Scrapes dataset and API documentation pages from the Sound & Vision data platform
and converts them to the same chunk format used by the rest of the pipeline.

The site is server-side rendered Nuxt.js. Content lives between
id="article-heading" and id="teleports" in the raw HTML.

Usage:
    python pipelines/ingest/ingest_dataplatform.py
    python pipelines/ingest/ingest_dataplatform.py --output data_platform.json
    python pipelines/ingest/ingest_dataplatform.py --config /path/to/config.yaml

Requirements:
    pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"
CRAWL_DELAY = 1.0  # seconds between requests


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fetch_page(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "mediasuite-kb-bot/1.0"})
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None


def _slug_acronym(url: str, title: str) -> str:
    """If the URL's last path component is a short all-alpha slug (e.g. 'gtaa')
    that doesn't already appear in the title, append it as an acronym."""
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    if slug.isalpha() and len(slug) <= 6:
        acronym = slug.upper()
        if acronym.lower() not in title.lower():
            return f"{title} ({acronym})"
    return title


def extract_content(html: str, url: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse the article content from a data.beeldengeluid.nl page.

    Returns (title, [(section_heading, section_text), ...]).
    Content lives between id="article-heading" and id="teleports".
    """
    soup = BeautifulSoup(html, "html.parser")

    heading_div = soup.find(id="article-heading")
    teleports_div = soup.find(id="teleports")

    if not heading_div:
        print(f"  WARNING: no article-heading found for {url}", file=sys.stderr)
        return "", []

    # Collect all elements from article-heading up to (but not including) teleports
    content_elements = []
    current = heading_div
    while current:
        if current == teleports_div:
            break
        content_elements.append(current)
        current = current.next_sibling

    combined_html = "".join(str(el) for el in content_elements)
    content_soup = BeautifulSoup(combined_html, "html.parser")

    # Remove nav/footer/script/style noise
    for tag in content_soup(["script", "style", "nav", "footer", "button"]):
        tag.decompose()

    # Extract title: h1 in the heading area is the real collection/API name.
    # (h3 just contains the page-type label "Dataset" / "API".)
    title = ""
    heading_soup = BeautifulSoup(str(heading_div), "html.parser")
    h1 = heading_soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        # Fall back to <title> element
        title_el = soup.find("title")
        if title_el:
            title = title_el.get_text(strip=True)

    # Append URL slug as acronym hint when it's short and not already in the title
    # e.g. /datasets/gtaa → "Common Thesaurus Audiovisual Archives (GTAA)"
    title = _slug_acronym(url, title)

    # Split by h3/h4 section headings
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_parts: list[str] = []

    _NAV_LABELS = {"home", "datasets", "apis", "showcases", "about", "nl", "dataset", "api"}

    for el in content_soup.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "pre", "code", "hr"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(" ", strip=True)
            # Skip nav labels and page-type labels ("Dataset", "API")
            if text.lower() in _NAV_LABELS:
                continue
            # Skip the title heading itself
            if text == title:
                continue
            # Save previous section
            section_text = _clean_whitespace(" ".join(current_parts))
            if section_text:
                sections.append((current_heading, section_text))
            current_heading = text
            current_parts = []
        else:
            text = el.get_text(" ", strip=True)
            if text:
                current_parts.append(text)

    # Flush last section
    section_text = _clean_whitespace(" ".join(current_parts))
    if section_text:
        sections.append((current_heading, section_text))

    # If no sections found at all, return the full text as one section
    if not sections:
        full_text = _clean_whitespace(content_soup.get_text(" ", strip=True))
        if full_text:
            sections = [("", full_text)]

    return title, sections


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    # e.g. /datasets/amateurfilms → datasets-amateurfilms
    return parsed.path.strip("/").replace("/", "-")


def extract_mentioned(haystack: str, known: list[str]) -> list[str]:
    return [
        item for item in known
        if re.search(r"\b" + re.escape(item) + r"\b", haystack, re.IGNORECASE)
    ]


def ingest_page(
    url: str,
    content_type: str,
    chunk_target: int,
    chunk_overlap: int,
    known_tools: list[str],
    known_collections: list[str],
    title_override: str | None = None,
) -> list[dict]:
    print(f"  Fetching {url} …")
    html = fetch_page(url)
    if not html:
        return []

    title, sections = extract_content(html, url)
    if title_override:
        title = title_override
    if not title and not sections:
        print(f"  WARNING: no content extracted from {url}", file=sys.stderr)
        return []

    slug = slug_from_url(url)
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
                "id": f"data_platform/{slug}/{chunk_idx}",
                "title": title,
                "section": section_heading,
                "collection": "data_platform",
                "content_type": content_type,
                "url": url,
                "tags": [],
                "author": "",
                "categories": [],
                "tools_mentioned": extract_mentioned(search_text, known_tools),
                "collections_mentioned": extract_mentioned(search_text, known_collections),
                "modified_date": "",
                "source_commit": "",
                "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
                "text": full_text,
                "char_count": len(full_text),
            }
            records.append(record)
            chunk_idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(description="Ingest data.beeldengeluid.nl into the knowledge base")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, help="Output JSON file (overrides config)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dp_cfg = cfg.get("data_platform", {})
    pages = dp_cfg.get("pages", [])

    if not pages:
        print("No pages configured under data_platform.pages in config.yaml")
        sys.exit(1)

    output_path = args.output or (args.config.parent / dp_cfg.get("output", "data_platform.json"))

    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    print(f"Ingesting {len(pages)} pages from data.beeldengeluid.nl")
    print("-" * 60)

    all_records: list[dict] = []

    for i, page in enumerate(pages):
        url = page["url"]
        content_type = page.get("content_type", "Collection Documentation")
        title_override = page.get("title_override")
        records = ingest_page(url, content_type, chunk_target, chunk_overlap, known_tools, known_collections, title_override)
        print(f"    → {len(records)} chunks  (title: {records[0]['title']!r})" if records else "    → 0 chunks")
        all_records.extend(records)

        if i < len(pages) - 1:
            time.sleep(CRAWL_DELAY)

    print("-" * 60)
    print(f"\nTotal: {len(all_records)} chunks from {len(pages)} pages")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"Written to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
