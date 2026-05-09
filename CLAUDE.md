# mediasuite-knowledge-base — Claude Code Context

## What this repository is

This is the **knowledge base infrastructure** for the CLARIAH Media Suite —
an independently maintained, reusable asset that ingests, processes, and stores
content from Media Suite documentation, learning materials, and research publications
in a form that AI applications can query.

It is intentionally decoupled from any specific application. The first application
built on top of it is the **media-suite-learn-chatbot**
(https://github.com/roelandordelman/media-suite-learn-chatbot), but the knowledge
base is designed to serve future applications, interfaces, and infrastructure.

This repository may later be absorbed into or aligned with a broader
`clariah-knowledge-base` as the scope expands beyond the Media Suite.

## Institutional context

This is a personal project by the CTO of CLARIAH, built to:
1. Create a better learn/help interface for the Media Suite via a chatbot
2. Develop practical understanding of RAG, embeddings, and chatbot architecture
3. Explore structured data and metadata enrichment of a knowledge base
4. Learn linked data in a concrete, practical Media Suite use case
5. Build toward user evaluation and eventual integration into CLARIAH infrastructure

Development is gradual: local prototype first, then expanding to the Media Suite,
then potentially to CLARIAH more broadly. User evaluation will be introduced as
soon as the system is stable enough to put in front of real researchers.

## Content sources (current)

### mediasuite-website (Jekyll/Siteleaf)
From https://github.com/beeldengeluid/mediasuite-website

| Collection | Content type | Live URL base |
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
| `_release-notes` | Release Notes | mediasuite.clariah.nl/documentation/release-notes |

### data.beeldengeluid.nl
From https://github.com/beeldengeluid/data.beeldengeluid.nl: 12 collection pages and 3 API pages.
Ingested via `ingest_dataplatform.py` → `data_platform.json`.

### Research publications (Zotero)
Primary source: Zotero group 2288915 (Media Suite community publications list, ~90 academic papers).
Enriched via OpenAlex for abstracts and open-access PDF URLs.
Supplemented by `supplementary_dois` in `config.yaml` for high-relevance papers not in Zotero
(including papers from the Zenodo CLARIAH community).
Ingested via `ingest_publications.py` → `publications.json`.

### Data Stories
From https://github.com/beeldengeluid/data-stories — 7 English stories on quantitative Media Suite
research. Dutch-only stories excluded. Ingested via `ingest_datastories.py` → `data_stories.json`.

### Community site / SANE documentation
From https://github.com/roelandordelman/media-suite-community — SANE workflow and available NISV
collection descriptions. Ingested via `ingest_community.py` → `community.json`.

### B&G Publications (OAI-PMH)
From https://publications.beeldengeluid.nl/oai — public OAI-PMH endpoint (`oai_dc`).
Two-stage relevance filter: keyword pre-filter on title + abstract + `dc:subject`, then LLM
verification (Mistral) per record. Records DOI-matching `publications.json` are skipped.
LLM decisions cached in `stores/beng_publications_llm_cache.json`.
Full harvest: 79 of 1,250 records kept. Ingested via `ingest_beng_publications.py` → `beng_publications.json`.

### Authored content (Tier 1)
Curated documents in `content/` for topics not covered by source sync.
Status lifecycle: `draft → active → deprecated → retired`.
Ingested via `ingest_content.py` → `content.json`. See `docs/content_framework.md`.

## Source sustainability

Update mechanisms, cadence, failure modes, owners, and rot risk for all sources are documented
in `docs/source_sustainability.md`. All sources currently require manual re-runs.

## Planned additional sources

- **Workshop and tutorial materials** — partially covered via Zenodo supplementary_dois
- **GitHub Issues** from beeldengeluid/mediasuite-website — evaluated; issues are mostly bug reports, not useful Q&A content; deprioritised

## Current stack

| Component | Tool | Notes |
|---|---|---|
| Embeddings | `nomic-embed-text` via Ollama | Local, no API key needed |
| Vector store | ChromaDB | Local, stored in `stores/chroma_db/` |
| Chunk format | JSON | See schema below |

## Planned stack additions

| Component | Tool | Notes |
|---|---|---|
| Knowledge graph | Apache Jena Fuseki | RDF triplestore, SPARQL endpoint |
| Entity extraction | Mistral via Ollama | Extract tools/collections mentioned |
| Linked data export | RDF/Turtle | Align with CLARIAH vocabularies |

## Project structure

```
mediasuite-knowledge-base/
│
├── pipelines/
│   ├── ingest/
│   │   ├── ingest_mediasuite.py         # mediasuite-website repo → knowledge_base.json
│   │   ├── ingest_dataplatform.py       # data.beeldengeluid.nl repo → data_platform.json
│   │   ├── ingest_publications.py       # Zotero + OpenAlex + PDFs → publications.json
│   │   ├── ingest_datastories.py        # beeldengeluid/data-stories → data_stories.json
│   │   ├── ingest_community.py          # media-suite-community → community.json
│   │   ├── ingest_beng_publications.py  # OAI-PMH (keyword+LLM filter) → beng_publications.json
│   │   └── ingest_content.py            # content/ directory (Tier 1) → content.json
│   │
│   └── embed/
│       └── build_index.py               # JSON chunks → embeddings → ChromaDB (incremental)
│
├── stores/
│   ├── chroma_db/                       # gitignored — regenerate via build_index.py
│   ├── beng_publications_state.json     # gitignored — OAI-PMH last_harvest timestamp
│   └── beng_publications_llm_cache.json # gitignored — Mistral relevance decisions per OAI ID
│
├── content/                             # Tier 1 authored documents
│   └── system/
│       └── how-ask-mediasuite-works.md
│
├── vocab/                               # RDF/Turtle vocabulary files
│   ├── clariah-vocab.ttl
│   ├── mediasuite-entities.ttl
│   ├── mediasuite-collections.ttl
│   └── mediasuite-workflows.ttl
│
├── docs/
│   ├── roadmap.md
│   ├── content_framework.md            # Tier 1/2/3 source governance model
│   ├── source_sustainability.md        # update mechanisms, cadence, rot risk per source
│   └── version_log.md
│
├── evaluate/
│   ├── eval_retrieval.py               # Hit@10 and MRR evaluation
│   └── test_questions.yaml             # test questions with expected URLs
│
├── knowledge_base.json                 # gitignored — generated by ingest_mediasuite.py
├── data_platform.json                  # gitignored — generated by ingest_dataplatform.py
├── publications.json                   # gitignored — generated by ingest_publications.py
├── data_stories.json                   # gitignored — generated by ingest_datastories.py
├── community.json                      # gitignored — generated by ingest_community.py
├── beng_publications.json              # gitignored — generated by ingest_beng_publications.py
├── content.json                        # gitignored — generated by ingest_content.py
├── config.yaml                         # all pipeline configuration
├── requirements.txt
├── CLAUDE.md                           # this file
└── README.md
```

## Key configuration notes

- `chunk_title_overrides` in `config.yaml` — overrides the `[Title]` prefix in chunk text for specific page slugs, to bridge vocabulary gaps between source page titles and researcher query language. After adding/changing an override, delete the affected chunks from ChromaDB manually before re-running `build_index.py` (incremental indexing skips by ID, not by content hash).
- `supplementary_dois` in `config.yaml` — DOIs to always include in the publications pipeline regardless of Zotero group membership. Used for high-relevance papers not yet added to Zotero, including papers from the Zenodo CLARIAH community.
- Always use `ollama.embed` (batch API) for both indexing and query embedding — `ollama.embeddings` (old single API) returns unnormalized vectors (~21× larger magnitude) which can silently distort ranking.

## Chunk schema

Every chunk in `knowledge_base.json` and in ChromaDB follows this base schema:

```json
{
  "id":                    "unique identifier: collection/slug/chunk_index",
  "title":                 "page title from front matter",
  "section":               "heading the chunk falls under (may be empty)",
  "collection":            "source collection identifier, e.g. _howtos or publications_beeldengeluid",
  "content_type":          "human-readable type: How-to Guide, FAQ, B&G Publication, ...",
  "url":                   "canonical URL for the source — always preserved",
  "tags":                  ["tags from front matter or dc:subject"],
  "author":                "author if present",
  "categories":            ["subject categories if present"],
  "tools_mentioned":       ["Inspector", "Workspace", ...],
  "collections_mentioned": ["Sound and Vision", "Oral History", ...],
  "text":                  "[Title — Section]\nThe chunk text...",
  "char_count":            312,
  "content_hash":          "SHA256 of text field — used for drift detection"
}
```

**B&G Publications additional fields** (present on chunks from `beng_publications.json`):

```json
{
  "oai_id":    "oai:publications.beeldengeluid.nl:2571",
  "doi":       "10.18146/tmg.810",
  "creators":  ["Lastname, Firstname", ...],
  "description": "abstract text",
  "date":      "2024-03-01",
  "language":  "en",
  "type":      "Article",
  "rights":    "",
  "keywords":  ["archive", "metadata", ...],
  "publisher": "Netherlands Institute for Sound and Vision",
  "source":    "publications_beeldengeluid"
}
```

The `url` field must always be preserved — it is what allows applications to
deep-link researchers to the relevant part of the Media Suite.

The `tools_mentioned` and `collections_mentioned` fields are used for structured
filtering in ChromaDB and will become the basis for the knowledge graph layer.

## Key conventions

- **URL preservation is non-negotiable** — every chunk must carry its source URL
- **Deduplication** — content that appears in multiple collections (e.g. tutorials
  cross-posted to both `_learn_tutorials_tool` and `_learn_tutorials_subject`) must
  be deduplicated; prefer the canonical collection
- **Storage-agnostic design** — the application layer (chatbot) must not depend on
  ChromaDB specifically; connection details go in `config.yaml`
- **Evaluation from day one** — add test questions and expected sources to
  `evaluate/` as the knowledge base grows; never let evaluation be an afterthought
- **Regenerability** — the full pipeline (git clone → ingest → embed) must be
  runnable from scratch with a single script or clear sequence of commands

## How to regenerate the knowledge base from scratch

```bash
# 1. Clone the content source
git clone --depth=1 https://github.com/beeldengeluid/mediasuite-website.git /tmp/mediasuite-website

# 2. Ingest → JSON
python pipelines/ingest/ingest_mediasuite.py \
    --repo /tmp/mediasuite-website \
    --output knowledge_base.json

# 3. Embed → ChromaDB
python pipelines/embed/build_index.py \
    --input knowledge_base.json \
    --db stores/chroma_db

# 4. (planned) Build knowledge graph
python pipelines/graph/build_graph.py \
    --input knowledge_base.json \
    --output stores/fuseki
```

## How applications connect

Applications reference this knowledge base via `config.yaml` in their own repo.
The connection type can be changed without touching the application logic:

```yaml
# in media-suite-learn-chatbot/config.yaml
knowledge_base:
  type: chroma_local
  path: ../mediasuite-knowledge-base/stores/chroma_db
  # type: chroma_http
  # url: http://kb-service:8000
```

## Making recommendations about external systems

When making observations or suggestions about external systems (e.g. third-party LOD
platforms, rights practices, metadata conventions), always rate each point explicitly as:

- **"Pretty certain"** — directly verified via primary sources (LOD endpoint, JSON-LD,
  official documentation, confirmed by domain expert)
- **"Something to look into further"** — plausible but not verified, or based on
  indirect evidence only

Follow this methodology when investigating a claim:
1. Check primary sources first: fetch the actual LOD/JSON-LD, read official documentation
2. Note when verification was not possible (e.g. registry unavailable, 404)
3. Cite the specific sources checked
4. Do not upgrade a claim from "look into further" to "pretty certain" based solely
   on AI-generated inference — only direct evidence or expert confirmation qualifies

This matters because observations made during knowledge base work may end up as notes
or recommendations visible to third parties (e.g. the NISV data team). Unfounded
suggestions cause unnecessary investigation work and erode trust.

## Relation to CLARIAH infrastructure

This repository is a personal project and prototype. As it matures, it is
intended to inform or contribute to CLARIAH's broader knowledge infrastructure.
The vocabulary and entity model used in the knowledge graph phase should be
aligned with existing CLARIAH linked data vocabularies where possible.

User evaluation should begin as soon as the chatbot application is stable enough
for real researchers to use — this evaluation data is as valuable as the
technical infrastructure itself.
