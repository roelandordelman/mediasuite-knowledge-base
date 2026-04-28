"""
Ingest research publications that used the CLARIAH Media Suite.

Pipeline:
  1. Discover papers via OpenAlex API ("clariah media suite")
  2. Download open-access PDFs (cached locally)
  3. Extract text with pdfplumber; detect sections
  4. Filter for papers that genuinely use Media Suite as a research tool
  5. Extract: abstract, conclusion, MS-relevant passages, methodology
  6. Generate a 2-3 sentence summary via Ollama (mistral)
  7. Output chunks as content_type "Research Example"

Intermediate results cached in publications.cache_dir to make reruns cheap.

Usage:
    python pipelines/ingest/ingest_publications.py
    python pipelines/ingest/ingest_publications.py --no-generate   # skip summaries
    python pipelines/ingest/ingest_publications.py --limit 10       # test on first 10

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

# Media Suite identity terms — a paper must mention at least one in the abstract
# to be considered genuinely about using the Media Suite
MS_IDENTITY_TERMS = [
    "media suite",
    "mediasuite",
    "clariah media",
]

# Section heading patterns (case-insensitive, matched against stripped lines)
HEADING_RE = re.compile(
    r"^(?:\d+\.?\s*)?"
    r"(abstract|introduction|background|related work|"
    r"research method(?:ology)?|method(?:ology)?|data and method|"
    r"approach|materials? and method|"
    r"results?|findings?|analysis|discussion|"
    r"conclusion|summary|acknowledgment|references?)s?\.?$",
    re.IGNORECASE,
)

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


# ── OpenAlex discovery ──────────────────────────────────────────────────────

def reconstruct_abstract(inverted_index: dict) -> str:
    """OpenAlex stores abstracts as inverted indexes. Reconstruct plain text."""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


def fetch_openalex_papers(query: str, email: str, types_include: list[str]) -> list[dict]:
    """Return all OA papers matching the query from OpenAlex."""
    base = "https://api.openalex.org/works"
    params = {
        "search": query,
        "filter": "open_access.is_oa:true",
        "per_page": 100,
        "select": "id,title,doi,open_access,best_oa_location,publication_year,type,authorships,abstract_inverted_index",
        "mailto": email,
    }
    papers = []
    page = 1
    while True:
        params["page"] = page
        resp = requests.get(base, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data["results"]
        if not results:
            break
        for w in results:
            wtype = w.get("type", "")
            if wtype not in types_include:
                continue
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            oa_url = (w.get("open_access") or {}).get("oa_url") or ""
            # Prefer best_oa_location.pdf_url (direct PDF) over oa_url (may be landing page)
            best_loc = w.get("best_oa_location") or {}
            pdf_url = best_loc.get("pdf_url") or oa_url
            abstract = reconstruct_abstract(w.get("abstract_inverted_index") or {})
            authors = [
                a["author"]["display_name"]
                for a in (w.get("authorships") or [])
                if a.get("author", {}).get("display_name")
            ]
            papers.append({
                "openalex_id": w.get("id", ""),
                "title": w.get("title") or "",
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else oa_url,
                "oa_pdf_url": pdf_url,
                "year": w.get("publication_year") or "",
                "type": wtype,
                "authors": authors,
                "abstract": abstract,
            })
        if page * 100 >= data["meta"]["count"]:
            break
        page += 1
        time.sleep(0.2)  # polite rate limiting

    return papers


# ── Relevance filtering ─────────────────────────────────────────────────────

def is_ms_relevant(paper: dict, known_tools: list[str], known_collections: list[str]) -> bool:
    """Return True if the abstract indicates genuine Media Suite usage."""
    haystack = (paper["abstract"] + " " + paper["title"]).lower()
    if not any(term in haystack for term in MS_IDENTITY_TERMS):
        return False
    # Exclude papers where Media Suite is merely cited in passing
    # Heuristic: must have ≥2 MS-related signals, or at least 1 tool/collection name
    signals = sum(haystack.count(term) for term in MS_IDENTITY_TERMS)
    tool_hit = any(t.lower() in haystack for t in known_tools)
    coll_hit = any(c.lower() in haystack for c in known_collections)
    return signals >= 2 or tool_hit or coll_hit


# ── PDF download and text extraction ───────────────────────────────────────

def doi_slug(identifier: str) -> str:
    # OpenAlex work URL (https://openalex.org/W...) → extract just the ID
    m = re.search(r"/(W\d+)$", identifier, re.IGNORECASE)
    if m:
        return m.group(1)
    return re.sub(r"[^a-zA-Z0-9]", "-", identifier)


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
        if "pdf" not in content_type and not url.lower().endswith(".pdf"):
            # Might be HTML landing page — skip
            if "html" in content_type:
                return False
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"    DOWNLOAD FAILED: {e}", file=sys.stderr)
        return False


def extract_text_sections(pdf_path: Path) -> tuple[str, dict[str, str]]:
    """
    Extract full text and split into named sections.
    Returns (full_text, {section_name: section_text}).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as e:
        print(f"    PDF PARSE FAILED: {e}", file=sys.stderr)
        return "", {}

    full_text = "\n".join(pages_text)
    if len(full_text.strip()) < 200:
        return full_text, {}  # image-based PDF or nearly empty

    lines = full_text.split("\n")
    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if HEADING_RE.match(stripped) and len(stripped) < 60:
            current = stripped.lower().split()[0]  # normalise: "1. Introduction" → "introduction"
            if current not in sections:
                sections[current] = []
        else:
            sections[current].append(stripped)

    return full_text, {k: " ".join(v) for k, v in sections.items() if v}


# ── Passage extraction ──────────────────────────────────────────────────────

MAX_SECTION_CHARS = 3000  # cap per extracted passage — avoids dumping the full paper


def extract_relevant_passages(
    sections: dict[str, str],
    known_tools: list[str],
    known_collections: list[str],
) -> dict[str, str]:
    """
    Keep abstract, conclusion always.
    Keep any section containing Media Suite identity terms or tool/collection names.
    Cap each passage at MAX_SECTION_CHARS to avoid indexing entire papers when
    section-heading detection misses most headings.
    """
    always_keep = {"abstract", "conclusion", "summary", "preamble"}
    ms_terms_lower = MS_IDENTITY_TERMS + [t.lower() for t in known_tools] + [c.lower() for c in known_collections]

    kept = {}
    for name, text in sections.items():
        text_lower = text.lower()
        if any(k in name for k in always_keep):
            kept[name] = text[:MAX_SECTION_CHARS]
        elif any(term in text_lower for term in ms_terms_lower):
            kept[name] = text[:MAX_SECTION_CHARS]
    return kept


# ── Summary generation ──────────────────────────────────────────────────────

def generate_summary(
    paper: dict,
    relevant_passages: dict[str, str],
    model: str,
) -> str:
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
    slug = doi_slug(paper["doi"]) if paper["doi"] else doi_slug(paper["openalex_id"])
    title = paper["title"]
    authors_str = "; ".join(paper["authors"][:3])
    year = str(paper["year"])
    url = paper["url"]
    tags = [paper["type"], year]

    records = []

    def add_chunk(section_label: str, text: str, chunk_id_suffix: str) -> None:
        if not text.strip():
            return
        context_prefix = f"{title}"
        if section_label:
            context_prefix += f" — {section_label}"
        full_text = f"[{context_prefix}]\n{text.strip()}"
        search_text = full_text
        records.append({
            "id": f"publications/{slug}/{chunk_id_suffix}",
            "title": title,
            "section": section_label,
            "collection": "publications",
            "content_type": "Research Example",
            "url": url,
            "tags": tags,
            "author": authors_str,
            "categories": [],
            "tools_mentioned": extract_mentioned(search_text, known_tools),
            "collections_mentioned": extract_mentioned(search_text, known_collections),
            "modified_date": year,
            "source_commit": paper["doi"],
            "content_hash": hashlib.sha256(full_text.encode()).hexdigest(),
            "text": full_text,
            "char_count": len(full_text),
        })

    # Summary chunk first (most useful for "how did researchers use X?" queries)
    if summary:
        add_chunk("Research Summary", summary, "summary")

    # Abstract
    if paper["abstract"]:
        add_chunk("Abstract", paper["abstract"], "abstract")

    # Relevant passages from PDF (skipping abstract which is already covered)
    for i, (section_name, text) in enumerate(relevant_passages.items()):
        if section_name in ("abstract", "preamble") and paper["abstract"]:
            continue
        if len(text) <= chunk_target:
            add_chunk(section_name.title(), text, f"section-{i}")
        else:
            # Split long sections
            words = text.split()
            target_words = chunk_target // 5
            overlap_words = chunk_overlap // 5
            j = 0
            sub = 0
            while j < len(words):
                chunk_words = words[j : j + target_words]
                add_chunk(section_name.title(), " ".join(chunk_words), f"section-{i}-{sub}")
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
    parser.add_argument("--limit", type=int, help="Process only first N relevant papers (for testing)")
    parser.add_argument("--no-generate", action="store_true", help="Skip Ollama summary generation")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF download; use abstracts only")
    args = parser.parse_args()

    cfg = load_config(args.config)
    pub_cfg = cfg.get("publications", {})
    cache_dir = Path(pub_cfg.get("cache_dir", "/tmp/publications_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "pdfs").mkdir(exist_ok=True)

    output_path = args.output or (args.config.parent / pub_cfg.get("output", "publications.json"))
    query = pub_cfg.get("openalex_query", "clariah media suite")
    email = pub_cfg.get("openalex_email", "")
    gen_model = pub_cfg.get("generation_model", "mistral")
    types_include = pub_cfg.get("types_include", ["article", "book-chapter", "report", "preprint"])
    chunk_target = cfg["chunking"]["target_chars"]
    chunk_overlap = cfg["chunking"]["overlap_chars"]
    known_tools = cfg.get("known_tools", [])
    known_collections = cfg.get("known_collections", [])

    # Phase 1: Discover papers (cached)
    papers_cache = cache_dir / "papers.json"
    if papers_cache.exists():
        papers = json.loads(papers_cache.read_text())
        print(f"Loaded {len(papers)} papers from cache ({papers_cache})")
    else:
        print(f"Querying OpenAlex for: {query!r} …")
        papers = fetch_openalex_papers(query, email, types_include)
        papers_cache.write_text(json.dumps(papers, ensure_ascii=False, indent=2))
        print(f"  Found {len(papers)} papers matching types {types_include}")

    # Phase 2: Filter for relevance
    relevant = [p for p in papers if is_ms_relevant(p, known_tools, known_collections)]
    print(f"  {len(relevant)} papers pass relevance filter (MS mentioned in abstract/title)")

    if args.limit:
        relevant = relevant[: args.limit]
        print(f"  (limited to first {args.limit} for testing)")

    print("-" * 60)

    all_chunks: list[dict] = []
    n_processed = 0
    n_skipped = 0

    for i, paper in enumerate(relevant):
        title_short = paper["title"][:65]
        print(f"\n[{i+1}/{len(relevant)}] {title_short}")
        print(f"  {paper['year']}  {paper['type']}  {paper['url']}")

        relevant_passages: dict[str, str] = {}

        if not args.no_pdf and paper["oa_pdf_url"]:
            slug = doi_slug(paper["doi"]) if paper["doi"] else doi_slug(paper["openalex_id"])
            pdf_path = cache_dir / "pdfs" / f"{slug}.pdf"

            downloaded = download_pdf(paper["oa_pdf_url"], pdf_path)
            if downloaded and pdf_path.exists():
                full_text, sections = extract_text_sections(pdf_path)
                if sections:
                    relevant_passages = extract_relevant_passages(sections, known_tools, known_collections)
                    print(f"  Extracted {len(sections)} sections; keeping {len(relevant_passages)}: {list(relevant_passages)[:5]}")
                else:
                    print(f"  No sections extracted (image-based PDF or parse failure)")
            else:
                print(f"  PDF unavailable — using abstract only")
        elif not args.no_pdf:
            print(f"  No OA PDF URL — using abstract only")

        # Generate summary
        summary = ""
        if not args.no_generate and (paper["abstract"] or relevant_passages):
            print(f"  Generating summary with {gen_model} …")
            summary = generate_summary(paper, relevant_passages or {"abstract": paper["abstract"]}, gen_model)
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
