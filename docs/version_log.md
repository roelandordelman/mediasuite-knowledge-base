# Version Log

A record of each significant knowledge base state: ingestion run, chunk counts,
eval scores, and config at the time. Provides a "before" snapshot for
infrastructure migrations and a baseline for regression detection.

---

## v0.5 — 2026-05-02

Pre-migration baseline. Phases 1–4 substantially complete; chatbot running
end-to-end locally with both narrative and structural retrieval paths.

### Sources ingested

| Source | Collection(s) | Chunks | Source commit |
|---|---|---|---|
| `beeldengeluid/mediasuite-website` | `_howtos`, `_faq`, `_help`, `_glossary`, `_labo-help`, `_learn_*`, `_release-notes` | 1,929 | `d080484c9754` |
| `beeldengeluid/data.beeldengeluid.nl` | `data_platform` (12 collection pages + 3 API pages) | 71 | `c046301389a3` |
| Zotero group 2288915 + `supplementary_dois` | `publications` | 189 | n/a (DOI-based) |
| `beeldengeluid/data-stories` | `data_stories` | 369 | (see chunk metadata) |
| `roelandordelman/media-suite-community` | `sane` | 18 | (see chunk metadata) |
| **Total** | | **2,568** | |

### Chunk breakdown by content type

| Content type | Chunks |
|---|---|
| Subject Tutorial | 784 |
| Tool Tutorial | 675 |
| Data Story | 369 |
| Research Example (→ rename to Research Publication) | 189 |
| Labo Help | 97 |
| How-to Guide | 92 |
| Release Notes | 88 |
| Collection Documentation | 48 |
| Help / Documentation | 46 |
| Learn (General) | 44 |
| Example Project | 44 |
| FAQ | 34 |
| API Documentation | 23 |
| SANE Documentation | 18 |
| Glossary | 13 |
| Tool Criticism | 4 |

### Knowledge graph

| Property | Value |
|---|---|
| Named graph | `https://mediasuite.clariah.nl/graph` |
| Triples | 1,058 |
| Entity types | ComponentTool (12), InfrastructureService (5), dcat:Dataset (15), Workflow (16+), DataProduct |
| SPARQL query templates | 11 |
| `entity_uri` assigned | 538 / 2,568 chunks (21%) |

### Embedding and vector store

| Property | Value |
|---|---|
| Embedding model | `nomic-embed-text` via Ollama |
| Index | ChromaDB (HTTP), collection `mediasuite` |
| Embed text strategy | `build_embed_text()` — chunk text + `Keywords: {tools_mentioned, categories, tags, collections_mentioned}` |

### Evaluation scores

| Eval | Score | Notes |
|---|---|---|
| Narrative Hit@10 | 94% (33/35) | `eval_retrieval.py`; 2 known gaps: SANE acronym, quantitative TV news |
| Narrative MRR | 0.647 | |
| Structural routing | 100% (26/26) | `eval_router.py`; embedding-based query→SPARQL routing |

### Known limitations at this version

- `content_type: "Research Example"` on publication chunks — should be renamed to `"Research Publication"`. Do when next re-ingest of publications is needed.
- `data_platform.json` Open Images API chunk: `collections_mentioned: ["Open Beelden"]` patched locally (gitignored). Not durable across re-ingest. Mitigated: question is `category: structural`; SPARQL `datasets_by_service` handles it correctly.
- Vector search fails for brand-name tool queries ("Similarity Tool", "FactRank"). Structural path (SPARQL `entity_description` + `entity_uri` filter) is the correct route for named-tool questions; chatbot router handles this.
- SANE acronym doesn't embed near SANE documentation. Descriptive phrasing ("work with sensitive audiovisual data in a secure environment") retrieves correctly. Fix: query expansion in chatbot.
