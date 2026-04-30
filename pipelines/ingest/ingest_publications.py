"""
Ingest research publications related to the CLARIAH Media Suite.

Pipeline:
  1. Fetch all items from the Media Studies CLARIAH WP5 Zotero group (public)
  2. Filter to academic publication types (journal articles, conference papers, etc.)
  3. Enrich with abstracts + OA PDF URLs from OpenAlex (by DOI, cached)
  4. Download open-access PDFs where available
  5. Extract text sections with pdfplumber
  6. Extract relevant passages (abstract, conclusion, MS-relevant sections)
  7. Generate a 2-3 sentence summary via Ollama (mistral)
  8. Output chunks as content_type "Research Example"

Usage:
    python pipelines/ingest/ingest_publications.py
    python pipelines/ingest/ingest_publications.py --no-generate   # skip summaries
    python pipelines/ingest/ingest_publications.py --limit 10      # test on first 10
    python pipelines/ingest/ingest_publications.py --no-pdf        # abstracts only
    python pipelines/ingest/ingest_publications.py --refresh       # re-fetch Zotero + OpenAlex

Requirements:
    pip install pdfplumber requests
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import ollama
import pdfplumber
import requests
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"

# Zotero item types treated as academic publications
ACADEMIC_TYPES = {
    "journalArticle",
    "conferencePaper",
    "bookSection",
    "book",
    "report",
    "document",
    "thesis",
    "preprint",
}

HEADING_RE = re.compile(
    r"^(?:\d+\.?\s*)?"
    r"(abstract|introduction|background|related work|"
    r"research method(?:ology)?|method(?:ology)?|data and method|"
    r"approach|materials? and method|"
    r"results?|findings?|analysis|discussion|"
    r"conclusion|summary|acknowledgment|references?)s?\.?$",
    re.IGNORECASE,
)

# Matches all-caps chapter headings found in brochures, reports, and deliverables
# (e.g. "COLLABORATE", "ACCESSING DATA", "VIEW AND ANNOTATE")
ALL_CAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z\s&/()\-]{2,44}$")

MAX_SECTION_CHARS = 3000

SUMMARY_PROMPT = """\
You are summarizing how the CLARIAH Media Suite was used in a research paper.
Write exactly 2-3 sentences describing:
- What research question or topic was studied
- Which Media Suite tools, collections, or features were used
- What the key finding or outcome was

Be specific and concrete. Do not start with "The paper" or "This paper".
Only use information given below — do not hallucinate.

Title: {title}

Abstract:
{abstract}

Relevant passages:
{passages}

Summary (2-3 sentences):"""


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Zotero discovery ────────────────────────────────────────────────────────

def fetch_zotero_items(group_id: str) -> list[dict]:
    """Fetch all top-level items from a public Zotero group."""
    base = f"https://api.zotero.org/groups/{group_id}/items/top"
    items = []
    start = 0
    while True:
        resp = requests.get(
            base,
            params={"format": "json", "limit": 100, "v": 3, "start": start},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        items.extend(batch)
        start += 100
        if len(batch) < 100:
            break
        time.sleep(0.1)
    return items


def _extract_year(date_str: str) -> str:
    m = re.search(r"\b(19|20)\d{2}\b", date_str or "")
    return m.group(0) if m else ""


def _norm_doi(raw: str) -> str:
    return re.sub(r"^https?://doi\.org/", "", (raw or "").strip(), flags=re.IGNORECASE).lower()


def _format_authors(creators: list[dict]) -> str:
    parts = []
    for c in creators:
        if c.get("creatorType") != "author":
            continue
        if c.get("lastName") and c.get("firstName"):
            parts.append(f"{c['lastName']}, {c['firstName']}")
        elif c.get("lastName"):
            parts.append(c["lastName"])
        elif c.get("name"):
            parts.append(c["name"])
    return "; ".join(parts)


def normalise_zotero_items(raw_items: list[dict]) -> list[dict]:
    papers = []
    seen_dois: set[str] = set()

    for item in raw_items:
        d = item.get("data", {})
        item_type = d.get("itemType", "")
        if item_type not in ACADEMIC_TYPES:
            continue
        doi = _norm_doi(d.get("DOI", ""))
        url = d.get("url", "")
        zotero_web_url = (item.get("links") or {}).get("alternate", {}).get("href", "")
        canonical_url = f"https://doi.org/{doi}" if doi else (url or zotero_web_url)

        # Deduplicate by DOI — Zotero sometimes has the same paper twice
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)

        papers.append({
            "zotero_key": item.get("key", ""),
            "item_type": item_type,
            "title": (d.get("title") or "").strip(),
            "authors": _format_authors(d.get("creators", [])),
            "year": _extract_year(d.get("date", "")),
            "doi": doi,
            "url": canonical_url,
            "abstract": (d.get("abstractNote") or "").strip(),
            "oa_pdf_url": "",
            "openalex_id": "",
        })
    return papers


# ── OpenAlex enrichment ─────────────────────────────────────────────────────

def reconstruct_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


def enrich_from_openalex(papers: list[dict], email: str) -> list[dict]:
    """Fetch abstract and OA PDF URL from OpenAlex for papers with DOIs."""
    base = "https://api.openalex.org/works"
    headers = {"User-Agent": f"mediasuite-kb-bot/1.0 (mailto:{email})"}
    n_enriched = 0

    for paper in papers:
        if not paper["doi"]:
            continue
        try:
            resp = requests.get(
                f"{base}/https://doi.org/{paper['doi']}",
                params={"select": "id,abstract_inverted_index,open_access,best_oa_location"},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()

            if not paper["abstract"]:
                abstract = reconstruct_abstract(data.get("abstract_inverted_index") or {})
                if abstract:
                    paper["abstract"] = abstract

            best_loc = data.get("best_oa_location") or {}
            pdf_url = best_loc.get("pdf_url") or (data.get("open_access") or {}).get("oa_url") or ""
            paper["oa_pdf_url"] = pdf_url
            paper["openalex_id"] = data.get("id", "")
            n_enriched += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"    OpenAlex lookup failed for {paper['doi']}: {e}", file=sys.stderr)

    print(f"  Enriched {n_enriched} papers with OpenAlex data")
    return papers


def fetch_supplementary_papers(dois: list[str], email: str, existing_dois: set[str]) -> list[dict]:
    """Fetch papers by DOI from OpenAlex for DOIs not already in the Zotero set."""
    base = "https://api.openalex.org/works"
    headers = {"User-Agent": f"mediasuite-kb-bot/1.0 (mailto:{email})"}
    papers = []

    for doi in dois:
        doi = _norm_doi(doi)
        if doi in existing_dois:
            continue
        try:
            resp = requests.get(
                f"{base}/https://doi.org/{doi}",
                params={
                    "select": (
                        "id,title,doi,authorships,publication_year,type,"
                        "abstract_inverted_index,open_access,best_oa_location"
                    )
                },
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 404:
                print(f"  WARNING: supplementary DOI not found on OpenAlex: {doi}", file=sys.stderr)
                continue
            resp.raise_for_status()
            d = resp.json()

            authors = "; ".join(
                f"{a['author']['display_name']}"
                for a in (d.get("authorships") or [])
                if a.get("author", {}).get("display_name")
            )
            abstract = reconstruct_abstract(d.get("abstract_inverted_index") or {})
            best_loc = d.get("best_oa_location") or {}
            pdf_url = best_loc.get("pdf_url") or (d.get("open_access") or {}).get("oa_url") or ""
            raw_doi = (d.get("doi") or "").replace("https://doi.org/", "")

            papers.append({
                "zotero_key": "",
                "item_type": d.get("type", "journalArticle"),
                "title": (d.get("title") or "").strip(),
                "authors": authors,
                "year": str(d.get("publication_year") or ""),
                "doi": raw_doi,
                "url": f"https://doi.org/{raw_doi}" if raw_doi else "",
                "abstract": abstract,
                "oa_pdf_url": pdf_url,
                "openalex_id": d.get("id", ""),
            })
            print(f"  Fetched supplementary: {d.get('title', doi)[:60]}")
            time.sleep(0.1)
        except Exception as e:
            print(f"  WARNING: could not fetch {doi}: {e}", file=sys.stderr)

    return papers


# ── PDF download and text extraction ───────────────────────────────────────

def _id_slug(identifier: str) -> str:
    m = re.search(r"/(W\d+)$", identifier, re.IGNORECASE)
    if m:
        return m.group(1)
    return re.sub(r"[^a-zA-Z0-9]", "-", identifier)


def paper_slug(paper: dict) -> str:
    if paper["doi"]:
        return _id_slug(paper["doi"])
    if paper["openalex_id"]:
        return _id_slug(paper["openalex_id"])
    return _id_slug(paper["zotero_key"])


def download_pdf(url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    try:
        resp = requests.get(
            url, timeout=30, stream=True,
            headers={"User-Agent": "mediasuite-kb-bot/1.0 (mailto:roeland.ordelman@pm.me)"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type and "pdf" not in content_type and not url.lower().endswith(".pdf"):
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"    DOWNLOAD FAILED: {e}", file=sys.stderr)
        return False


def extract_text_sections(pdf_path: Path) -> tuple[str, dict[str, str]]:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as e:
        print(f"    PDF PARSE FAILED: {e}", file=sys.stderr)
        return "", {}

    full_text = "\n".join(pages_text)
    if len(full_text.strip()) < 200:
        return full_text, {}

    # Detect repeated page headers/footers — lines appearing on >30% of pages
    from collections import Counter
    all_stripped = [l.strip() for p in pages_text for l in p.split("\n") if l.strip()]
    freq = Counter(all_stripped)
    n_pages = len(pages_text)
    boilerplate = {line for line, count in freq.items() if count >= max(3, n_pages * 0.3)}

    lines = full_text.split("\n")
    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in boilerplate:
            continue
        if len(stripped) < 60 and (
            HEADING_RE.match(stripped) or ALL_CAPS_HEADING_RE.match(stripped)
        ):
            current = stripped.lower()
            if current not in sections:
                sections[current] = []
        else:
            sections[current].append(stripped)

    return full_text, {k: " ".join(v) for k, v in sections.items() if v}


# ── Passage extraction ──────────────────────────────────────────────────────

def extract_relevant_passages(
    sections: dict[str, str],
    known_tools: list[str],
    known_collections: list[str],
) -> dict[str, str]:
    always_keep = {"abstract", "conclusion", "summary", "preamble"}
    never_keep = {"references", "acknowledgment", "acknowledgments", "bibliography"}
    ms_terms_lower = (
        ["media suite", "mediasuite", "clariah media"]
        + [t.lower() for t in known_tools]
        + [c.lower() for c in known_collections]
    )
    kept = {}
    for name, text in sections.items():
        if any(k in name for k in never_keep):
            continue
        if any(k in name for k in always_keep):
            kept[name] = text[:MAX_SECTION_CHARS]
        elif any(term in text.lower() for term in ms_terms_lower):
            kept[name] = text[:MAX_SECTION_CHARS]
    return kept


# ── Summary generation ──────────────────────────────────────────────────────

def generate_summary(paper: dict, relevant_passages: dict[str, str], model: str) -> str:
    passages_text = "\n\n".join(
        f"[{name.title()}]\n{text[:1500]}"
        for name, text in list(relevant_passages.items())[:4]
    )
    prompt = SUMMARY_PROMPT.format(
        title=paper["title"],
        abstract=paper["abstract"][:1500],
        passages=passages_text,
    )
    try:
        response = ollama.generate(model=model, prompt=prompt, options={"temperature": 0.2})
        return response["response"].strip()
    except Exception as e:
        print(f"    SUMMARY FAILED: {e}", file=sys.stderr)
        return ""


# ── Chunking ────────────────────────────────────────────────────────────────

def extract_mentioned(haystack: str, known: list[str]) -> list[str]:
    return [
        item for item in known
        if re.search(r"\b" + re.escape(item) + r"\b", haystack, re.IGNORECASE)
    ]


def make_chunks(
    paper: dict,
    relevant_passages: dict[str, str],
    summary: str,
    known_tools: list[str],
    known_collections: list[str],
    chunk_target: int,
    chunk_overlap: int,
) -> list[dict]:
    slug = paper_slug(paper)
    title = paper["title"]
    url = paper["url"]
    tags = [paper["item_type"], paper["year"]]

    records = []

    def add_chunk(section_label: str, text: str, chunk_id_suffix: str) -> None:
        if not text.strip():
            return
        context_prefix = title
        if section_label:
            context_prefix += f" — {section_label}"
        full_text = f"[{context_prefix}]\n{text.strip()}"
        records.append({
            "id": f"publications/{slug}/{chunk_id_suffix}",
            "title": title,
            "section": section_label,
            "collection": "publications",
            "content_type": "Research Example",  # TODO: rename to "Research Publication" — misleading; sounds like _learn_example_projects ("Example Project"). Change here + re-ingest + re-index when next publications run is needed anyway.
            "url": url,
            "tags": tags,
            "author": paper["authors"],
            "categories": [],
            "tools_mentioned": extract_mentioned(full_text, known_tools),
            "collections_mentioned": extract_mentioned(full_text, known_collections),
            "modified_date": paper["year"],
            "source_commit": paper["doi"],
            "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
            "text": full_text,
            "char_count": len(full_text),
        })

    if summary:
        add_chunk("Research Summary", summary, "summary")

    if paper["abstract"]:
        add_chunk("Abstract", paper["abstract"], "abstract")

    for i, (section_name, text) in enumerate(relevant_passages.items()):
        if section_name in ("abstract", "preamble") and paper["abstract"]:
            continue
        if len(text) <= chunk_target:
            add_chunk(section_name.title(), text, f"section-{i}")
        else:
            words = text.split()
            target_words = chunk_target // 5
            overlap_words = chunk_overlap // 5
            j = 0
            sub = 0
            while j < len(words):
                add_chunk(section_name.title(), " ".join(words[j : j + target_words]), f"section-{i}-{sub}")
                sub += 1
                if j + target_words >= len(words):
                    break
                j += target_words - overlap_words

    return records


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest research publications into the knowledge base")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, help="Output JSON (overrides config)")
    parser.add_argument("--limit", type=int, help="Process only first N papers (for testing)")
    parser.add_argument("--no-generate", action="store_true", help="Skip Ollama summary generation")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF download")
    parser.add_argument("--no-enrich", action="store_true", help="Skip OpenAlex enrichment")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch Zotero and OpenAlex data (ignore cache)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    pub_cfg = cfg.get("publications", {})
    cache_dir = Path(pub_cfg.get("cache_dir", "/tmp/publications_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "pdfs").mkdir(exist_ok=True)

    output_path = args.output or (args.config.parent / pub_cfg.get("output", "publications.json"))
    zotero_group = pub_cfg.get("zotero_group_id", "2288915")
    email = pub_cfg.get("openalex_email", "")
    gen_model = pub_cfg.get("generation_model", "mistral")
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    # Phase 1: Zotero
    zotero_cache = cache_dir / "zotero_items.json"
    if not args.refresh and zotero_cache.exists():
        raw_items = json.loads(zotero_cache.read_text())
        print(f"Loaded {len(raw_items)} Zotero items from cache")
    else:
        print(f"Fetching Zotero group {zotero_group} …")
        raw_items = fetch_zotero_items(zotero_group)
        zotero_cache.write_text(json.dumps(raw_items, ensure_ascii=False, indent=2))
        print(f"  Fetched {len(raw_items)} items")

    papers = normalise_zotero_items(raw_items)
    print(f"  {len(papers)} academic items after type filter")

    # Phase 2: OpenAlex enrichment (abstracts + OA PDF URLs)
    if not args.no_enrich:
        enrich_cache = cache_dir / "enriched.json"
        if not args.refresh and enrich_cache.exists():
            papers = json.loads(enrich_cache.read_text())
            print(f"Loaded enriched data from cache")
        else:
            print(f"Enriching from OpenAlex …")
            papers = enrich_from_openalex(papers, email)
            enrich_cache.write_text(json.dumps(papers, ensure_ascii=False, indent=2))

    # Phase 3: Supplementary papers (DOIs in config not in Zotero)
    supplementary_dois = pub_cfg.get("supplementary_dois", [])
    if supplementary_dois and not args.no_enrich:
        existing_dois = {p["doi"] for p in papers if p["doi"]}
        print(f"Fetching {len(supplementary_dois)} supplementary DOIs …")
        extra = fetch_supplementary_papers(supplementary_dois, email, existing_dois)
        papers.extend(extra)
        if extra:
            print(f"  Added {len(extra)} supplementary papers")

    with_abstract = sum(1 for p in papers if p["abstract"])
    print(f"  {with_abstract}/{len(papers)} papers have an abstract")

    pdf_dir = cache_dir / "pdfs"
    # Include papers without an abstract if a local PDF has been placed in the cache dir
    to_process = [
        p for p in papers
        if p["abstract"] or (pdf_dir / f"{paper_slug(p)}.pdf").exists()
    ]
    if args.limit:
        to_process = to_process[:args.limit]
        print(f"  (limited to first {args.limit})")

    print("-" * 60)

    all_chunks: list[dict] = []
    n_processed = 0
    n_skipped = 0

    for i, paper in enumerate(to_process):
        title_short = paper["title"][:65]
        print(f"\n[{i+1}/{len(to_process)}] {title_short}")
        print(f"  {paper['year']}  {paper['item_type']}  {paper['url']}")

        relevant_passages: dict[str, str] = {}

        slug = paper_slug(paper)
        pdf_path = pdf_dir / f"{slug}.pdf"
        # Use local PDF if present (even if no oa_pdf_url and no abstract yet)
        if not args.no_pdf and (paper["oa_pdf_url"] or pdf_path.exists()):
            if not pdf_path.exists():
                download_pdf(paper["oa_pdf_url"], pdf_path)
            if pdf_path.exists():
                full_text, sections = extract_text_sections(pdf_path)
                if sections:
                    relevant_passages = extract_relevant_passages(sections, known_tools, known_collections)
                    print(f"  Extracted {len(sections)} sections; keeping {len(relevant_passages)}: {list(relevant_passages)[:5]}")
                else:
                    print(f"  No sections extracted from PDF")
            else:
                print(f"  PDF unavailable — using abstract only")
        elif not args.no_pdf:
            print(f"  No OA PDF URL — using abstract only")

        summary = ""
        content_for_summary = relevant_passages or ({"abstract": paper["abstract"]} if paper["abstract"] else {})
        if not args.no_generate and content_for_summary:
            print(f"  Generating summary with {gen_model} …")
            summary = generate_summary(paper, content_for_summary, gen_model)
            if summary:
                print(f"  Summary: {summary[:100]}…")

        chunks = make_chunks(
            paper, relevant_passages, summary,
            known_tools, known_collections,
            chunk_target, chunk_overlap,
        )

        if chunks:
            all_chunks.extend(chunks)
            n_processed += 1
            print(f"  → {len(chunks)} chunks")
        else:
            n_skipped += 1
            print(f"  → skipped (no extractable content)")

    print("\n" + "-" * 60)
    print(f"Processed: {n_processed}  Skipped: {n_skipped}")
    print(f"Total chunks: {len(all_chunks)}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"Written to: {output_path.resolve()}")
    print(f"File size:  {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\nNext step: python pipelines/embed/build_index.py --input {output_path}")


if __name__ == "__main__":
    main()
