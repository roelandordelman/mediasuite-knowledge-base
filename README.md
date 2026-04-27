# mediasuite-knowledge-base

Knowledge base infrastructure for the [CLARIAH Media Suite](https://mediasuite.clariah.nl) —
ingests, chunks, embeds, and indexes Media Suite documentation and learning materials
so AI applications can query them via vector search.

Intentionally decoupled from any specific application. The first consumer is
[media-suite-learn-chatbot](https://github.com/roelandordelman/media-suite-learn-chatbot).

---

## Architecture

```mermaid
flowchart LR
    subgraph kb["mediasuite-knowledge-base (this repo)"]
        direction TB
        src["Jekyll docs\n(mediasuite-website)"]
        ingest["ingest_mediasuite.py"]
        json["knowledge_base.json"]
        embed["build_index.py\n(nomic-embed-text via Ollama)"]
        chroma[("ChromaDB\nHTTP server")]

        src --> ingest --> json --> embed --> chroma
    end

    subgraph chatbot["media-suite-learn-chatbot"]
        direction TB
        q["User question"]
        expand["Query expansion"]
        retrieve["Retrieval"]
        generate["Generation\n(Claude)"]
        widget["Chat widget"]

        q --> expand --> retrieve --> generate --> widget
    end

    chroma -->|"HTTP query"| retrieve
```

---

## Content sources

All content comes from [beeldengeluid/mediasuite-website](https://github.com/beeldengeluid/mediasuite-website) (Jekyll/Markdown).

| Collection | Content type | URL base |
|---|---|---|
| `_help` | Help / Documentation | mediasuite.clariah.nl/documentation |
| `_howtos` | How-to Guides | mediasuite.clariah.nl/documentation/howtos |
| `_faq` | FAQ | mediasuite.clariah.nl/documentation/faq |
| `_glossary` | Glossary | mediasuite.clariah.nl/documentation/glossary |
| `_learn_main` | Learn (General) | mediasuite.clariah.nl/learn |
| `_learn_tutorials_tool` | Tool Tutorials | mediasuite.clariah.nl/learn/tool-tutorials |
| `_learn_tutorials_subject` | Subject Tutorials | mediasuite.clariah.nl/learn/subject-tutorials |
| `_learn_tool_criticism` | Tool Criticism | mediasuite.clariah.nl/learn/tool-criticism |
| `_learn_example_projects` | Example Projects | mediasuite.clariah.nl/learn/example-projects |
| `_labo-help` | Labo Help | mediasuite.clariah.nl/labo/documentation |

Planned additions: GitHub Issues, research publications (via DOI), Jupyter notebooks, data platform documentation.

---

## Running the pipeline

```bash
# Install dependencies
pip install -r requirements.txt
ollama pull nomic-embed-text

# 1. Clone the content source
git clone --depth=1 https://github.com/beeldengeluid/mediasuite-website.git /tmp/mediasuite-website

# 2. Ingest → JSON
python pipelines/ingest/ingest_mediasuite.py

# 3. Start ChromaDB server (keep running in a separate terminal)
chroma run --path ./stores/chroma_db

# 4. Embed → ChromaDB
python pipelines/embed/build_index.py
```

All paths and connection details are configured in `config.yaml`.

---

## Chunk schema

```json
{
  "id":                    "collection/slug/chunk_index",
  "title":                 "page title from front matter",
  "section":               "heading the chunk falls under (may be empty)",
  "collection":            "_howtos",
  "content_type":          "How-to Guide",
  "url":                   "https://mediasuite.clariah.nl/documentation/howtos/...",
  "tags":                  ["tag1", "tag2"],
  "author":                "author if present",
  "categories":            ["subject category"],
  "tools_mentioned":       ["Collection Inspector", "Workspace"],
  "collections_mentioned": ["Sound & Vision Archive"],
  "created_date":          "2021-03-15",
  "modified_date":         "2023-11-02",
  "source_commit":         "a3f9b2c",
  "content_hash":          "sha256:e3b0c44...",
  "text":                  "[Title — Section]\nThe chunk text...",
  "char_count":            312
}
```

`url` is always preserved — it is what allows applications to deep-link to the relevant source.

List fields (`tags`, `categories`, `tools_mentioned`, `collections_mentioned`) are stored as JSON-encoded strings in ChromaDB and must be decoded with `json.loads()` by the consuming application.

---

## Chunk metadata, freshness and source persistence

A knowledge base is only as trustworthy as the information it contains — and
information changes. Documentation gets updated, pages move, tools are renamed,
features are added or removed. A chatbot that serves outdated or broken information
to researchers is worse than no chatbot at all, because it creates false confidence.

This raises three interconnected challenges:

**Freshness** — how do we know when a chunk was last updated, and how do we
handle cases where two sources say different things about the same topic? Silently
picking the most recent answer is one option, but surfacing the conflict explicitly
is more honest and more useful to a researcher who needs to trust their sources.

**Drift** — a page can keep its URL but quietly change its content. A chunk that
was accurate when ingested can become misleading without any visible signal. The
knowledge base needs a way to detect when the live source has diverged from what
was ingested, and flag or re-embed those chunks.

**Persistence** — URLs are mutable infrastructure. Pages move, sites get
restructured, URLs break. If the chatbot hands a researcher a dead link, that is
a trust failure. For a prototype this is tolerable; for a production system serving
real researchers it is not. The right solution is a persistent identifier layer —
stable, citable URLs that redirect to wherever the content currently lives,
consistent with how CLARIAH already handles identifiers for datasets.

### Metadata fields

| Field | Source | Purpose |
|---|---|---|
| `id` | generated | unique chunk identifier |
| `title` | front matter | page title |
| `section` | markdown heading | section within page |
| `collection` | Jekyll collection folder | content type grouping |
| `content_type` | config | human-readable type label |
| `url` | derived from file path | live URL on mediasuite.clariah.nl |
| `tags` | front matter | topic tags |
| `author` | front matter | content author |
| `categories` | front matter | subject categories |
| `tools_mentioned` | keyword extraction | Media Suite tools referenced |
| `collections_mentioned` | keyword extraction | Media Suite collections referenced |
| `created_date` | front matter `date` field | original publication date |
| `modified_date` | git log | date of last change to source file |
| `source_commit` | git log | git commit hash at time of ingestion |
| `content_hash` | SHA256 of chunk text | fingerprint for drift detection |
| `char_count` | generated | chunk length in characters |

### Why modification date matters

Documentation goes out of date. When two chunks contain conflicting information
about the same topic, the `modified_date` field allows the system to favour more
recently updated content, or — better — to surface the conflict explicitly to the
researcher so they can judge for themselves:

> "Two sources address this differently. The more recent one (updated 2023) says X.
> An older page (2021) says Y. Check the current documentation to confirm."

### Content drift detection

The `content_hash` field (SHA256 of the chunk text) enables efficient drift
detection on re-ingestion. Rather than re-embedding the entire knowledge base
when the source repository is updated, the pipeline compares hashes and only
re-embeds chunks whose content has actually changed. This keeps re-ingestion
fast as the knowledge base grows.

A future staleness check script will periodically fetch live URLs and flag
chunks where the ingested content no longer matches the live page.

### Source URL persistence — a known limitation

Currently, chunk identity is tied to the source URL. This creates two risks:

- **Link rot** — if a page moves or is removed, the URL the chatbot provides
  to researchers becomes a dead link
- **Content drift** — a page can keep its URL but change its content, making
  the chunk silently misleading

For the current prototype phase this is acceptable. For a production system,
the right solution is a **persistent identifier layer**: all chatbot-facing URLs
should go through a stable redirect layer that decouples the public URL from the
internal location. If a page moves, the redirect is updated rather than the
knowledge base.

```
https://mediasuite.clariah.nl/doc/annotate   ← stable PID-like URL
    → redirects to current live page
```

This is consistent with how CLARIAH already handles persistent identifiers for
datasets, and the same thinking should apply to documentation pages.

### Knowledge base versioning

Each ingestion run should be tagged with a date and the source commit it was
built from. The `source_commit` field on every chunk provides traceability back
to the exact state of the `mediasuite-website` repository at ingestion time.
Future versions of the pipeline will maintain a version log:

```
kb-version  ingested-at           source-commit  chunk-count
v0.1        2026-04-25            a3f9b2c        10719
v0.2        2026-05-10            d8e1f4a        11203
```

This supports research provenance — a researcher can record which version of the
knowledge base was active when they used the chatbot.

---

## Evaluation

```bash
python evaluate/eval_retrieval.py
python evaluate/eval_retrieval.py --top-k 10
```

Test questions and expected source URLs live in `evaluate/test_questions.yaml`. Add new questions there as the knowledge base grows — never let evaluation be an afterthought.

---

## Project structure

```
mediasuite-knowledge-base/
├── pipelines/
│   ├── ingest/
│   │   └── ingest_mediasuite.py
│   └── embed/
│       └── build_index.py
├── evaluate/
│   ├── eval_retrieval.py
│   └── test_questions.yaml
├── stores/
│   └── chroma_db/          # gitignored — regenerate via pipeline
├── config.yaml
├── requirements.txt
└── knowledge_base.json     # gitignored — generated by ingest
```

---

## How the chatbot connects

```yaml
# in media-suite-learn-chatbot/config.yaml
knowledge_base:
  collection_name: mediasuite
  chroma_host: localhost
  chroma_port: 8001
```
