# Roadmap

Development roadmap for the **mediasuite-knowledge-base** and **media-suite-learn-chatbot** projects. Ordered from simple to advanced, and kept as a living document — items are added, reprioritised, or reframed based on what we learn along the way. Completed items are kept visible so the learning journey is traceable.

If something turns out to be harder, less useful, or superseded by a better approach than expected, that is noted inline rather than silently removed.

---

## Current status (May 2026)

Phases 1–4 are substantially complete. The knowledge base ingests five content
sources (~2600 chunks across Media Suite documentation, data platform, research
publications, data stories, and SANE community docs), achieves 94% Hit@10 on the
narrative evaluation set and 26/26 (100%) on structural routing. The knowledge
graph holds 1057 triples across 5 entity types with 11 named SPARQL query
templates and deterministic embedding-based routing. The chatbot runs end-to-end
locally with parallel narrative and structural retrieval paths and a conversational
history API.

**Next priorities:** fix two known retrieval gaps (Open Images API, Similarity
Tool), complete Phase 5 version log, and plan the NISV infrastructure migration
before external researcher evaluation begins.

---

## Phase 1 — Local prototype ✓

The goal of this phase is a working end-to-end RAG pipeline running locally,
good enough to test retrieval quality and answer quality on real questions.

- [x] Ingest Media Suite website content from `beeldengeluid/mediasuite-website`
- [x] Parse Jekyll/Markdown front matter — preserve title, section, collection, URL
- [x] Deduplicate chunks across collections (cross-posted tutorials)
- [x] Fix chunk_text bug — 1-char-step loop was producing 32% junk chunks
- [x] Embed chunks using `nomic-embed-text` via Ollama
- [x] Store vectors and metadata in ChromaDB
- [x] Serve ChromaDB over HTTP (decouple knowledge base from application)
- [x] URL deduplication in retrieval — keep highest-scoring chunk per source URL
- [x] Build retrieval evaluation script with Hit@10 and MRR metrics
- [x] Structured test question set with expected URLs per question
- [x] Extract `tools_mentioned` and `collections_mentioned` per chunk
- [x] Separate knowledge base repo from chatbot application repo
- [x] Knowledge base connects to chatbot via HTTP only — no shared filesystem
- [x] Add `modified_date` and `source_commit` from git log per source file
- [x] Add `content_hash` (SHA256) per chunk for drift detection

---

## Phase 2 — Knowledge base enrichment ✓

The goal of this phase is to expand the knowledge base with additional sources
that make it significantly more useful to researchers.

- [~] ~~Ingest GitHub Issues from `beeldengeluid/mediasuite-website`~~ — evaluated and skipped; issues are mostly bug reports and dependency bumps, not useful Q&A content
- [x] Ingest `_release-notes/` from `beeldengeluid/mediasuite-website` (24 files, v2–v7.5+) — 88 chunks of version changelogs; good retrieval for collection/feature history questions
- [x] Ingest research publications
  - [x] Use Zotero group 2288915 as primary source (~90 academic papers); OpenAlex for abstract + OA PDF enrichment
  - [x] Filter for Media Suite relevance (two-pass: abstract scan → passage extraction from PDF)
  - [x] Generate per-paper summary of how the Media Suite was used (Mistral via Ollama)
  - [x] `supplementary_dois` config mechanism for high-relevance papers not yet in Zotero
  - [x] Tag as `content_type: Research Publication` with DOI as persistent identifier
- [~] ~~Ingest Jupyter notebook markdown cells from Media Suite example notebooks~~ — evaluated [`beeldengeluid/task-oriented-notebooks`](https://github.com/beeldengeluid/task-oriented-notebooks); markdown cells too thin for useful chunking; revisit if a richer notebook repo emerges
- [x] Ingest data platform documentation from `data.beeldengeluid.nl` — 12 collection pages + 3 API pages
- [x] Ingest Zenodo CLARIAH community publications — 72 records checked; 5 new DOIs added to `supplementary_dois`
- [x] Ingest Data Stories from [beeldengeluid/data-stories](https://github.com/beeldengeluid/data-stories) — 7 English stories, 369 chunks; closes gap on quantitative research use cases
- [x] Ingest SANE documentation from [roelandordelman/media-suite-community](https://github.com/roelandordelman/media-suite-community) — 18 chunks covering SANE workflow and available NISV collections
- [~] ~~Ingest internal planning documents (Dutch)~~ — Dutch content doesn't bridge to English queries via nomic-embed-text; `ingest_local_docs.py` remains available for English-language local docs
- [ ] Ingest workshop and tutorial materials (PDFs, slide decks) — partially addressed via Zenodo supplementary_dois
- [ ] Expand `known_tools` and `known_collections` lists in `config.yaml` based on corpus analysis
- [ ] Validate entity extraction quality — check `tools_mentioned` / `collections_mentioned` for false positives

---

## Phase 3 — Retrieval quality + RAG pipeline ✓ (ongoing)

The goal of this phase is to improve retrieval precision and recall based on
what we learn from evaluation and real researcher questions, and to build a
production-quality RAG pipeline.

### Knowledge base side

- [x] Expand test question set to 30+ questions across all three categories (35 questions including 8 publication research questions, April 2026)
- [x] `chunk_title_overrides` config mechanism — override the `[Title]` prefix in chunk text for vocabulary mismatch cases
- [x] All-caps chapter heading detection for PDF section extraction
- [x] Boilerplate detection in PDF extraction
- [x] Embed tags alongside chunk text in `build_index.py` — `build_embed_text()` appends categories + tags + tools_mentioned + collections_mentioned; fixed "computer vision" vocabulary gap; Hit@10 90% → 94%
- [x] Add `entity_uri` field to chunk schema — backfilled on all 2568 existing chunks; 534/2568 (20%) assigned; enables SPARQL → ChromaDB entity-filter lookup
- [ ] Implement recency boost — favour recently modified chunks when scores are close
- [ ] Implement staleness check — periodically compare live page content against ingested chunks
- [ ] Fix incremental re-indexing — `build_index.py` skips by chunk ID; changed chunks must be manually deleted before re-indexing
- [ ] Enrich chunk context prefix with UI tool names to fix vocabulary mismatch (e.g. "Collection Inspector" vs "Inspect tool" in docs)
- [ ] Investigate query expansion / rewriting to address vocabulary mismatch (e.g. "time periods" vs "date intervals")
  - [ ] Evaluate HyDE (Hypothetical Document Embedding) approach
- [ ] Tune chunk size and overlap based on retrieval evaluation results
- [ ] Investigate re-ranking — use a cross-encoder to re-rank top-k results before generation
- [ ] Share vocabulary sketch with tools.clariah.nl maintainers for feedback on alignment with CodeMeta + TaDiRaH + softwaretypes

### Chatbot side (media-suite-learn-chatbot)

- [x] Build FastAPI backend with POST /ask endpoint and conversation history
- [x] Embeddable vanilla JS chat widget (single `<script>` tag, no framework)
- [x] Both retrieval paths always run — no classification step; LLM used only for query expansion and answer generation
- [x] Narrative path: LLM query expansion (3 phrasings) → embed → ChromaDB semantic search; priority slots for FAQ/Help/How-to chunks
- [x] Structural path: embedding-based SPARQL query selection (QueryIndex singleton) — deterministic cosine similarity against pre-embedded trigger questions, no LLM in routing
- [x] Named SPARQL query catalogue: 11 templates covering tools, collections, workflows, services, entity descriptions
- [x] WORKFLOW_ALIASES: short descriptive labels for workflows whose graph names embed poorly against concise user questions
- [x] Entity-URI filter: SPARQL result URIs fed back into ChromaDB for targeted chunk retrieval
- [x] Structural eval (`eval_router.py`): 26/26 questions (100%); expected_terms scoring with --verbose and --debug modes
- [x] Narrative eval (`eval_retrieval.py`): 14/14 questions (100%); URL presence in top-k
- [x] `annotated: false` flag in `test_questions.yaml` — unannotated questions shown as `[PENDING]` with actual chatbot output, making incremental review and annotation easy without blocking the eval run
- [x] Fix two known retrieval gaps in the knowledge base:
  - [x] Open Images API: `apis/open-images` chunk re-embedded with `collections_mentioned: ["Open Beelden"]`; `datasets_by_service` SPARQL query added; structural path confirmed working via entity_uri filter
  - [x] Similarity Tool: `labo/documentation/similarity` added to `url_entity_map`; `"Similarity Tool"` added to `known_tools` and `tools_mentioned`; chunk_title_overrides updated; all 11 chunks re-embedded. Note: vector search still fails for brand-name queries — structural path (SPARQL entity_description + entity_uri filter) is the correct route; documented in test_questions.yaml
- [ ] Conversation history: pass prior turns to LLM for follow-up question handling
- [ ] History-aware query reformulation — rewrite follow-up questions as standalone queries before embedding
- [ ] Retrieval confidence scoring — ask clarifying question rather than generating a weak answer when top-k score is low
- [ ] Proactive follow-up suggestions after each answer
- [ ] Evaluate conversational quality with multi-turn test scenarios

### Agentic RAG (staged)

Background and rationale in [media-suite-learn-chatbot/docs/agentic_rag.md](https://github.com/roelandordelman/media-suite-learn-chatbot/blob/main/docs/agentic_rag.md).

The current pipeline is a fixed sequence: expand → embed → retrieve → generate. It handles simple, well-formed questions well, but has no mechanism to detect or recover from a poor retrieval. Agentic RAG replaces the fixed pipeline with a reasoning loop. Planned in three stages:

- [ ] **Stage 1 — CRAG (Corrective RAG)**: add a relevance scoring step after retrieval; if top-k chunks score below threshold, reformulate query and retry once before generating. Small addition to `api/rag.py`; meaningful improvement on ambiguous or poorly phrased questions without architectural change.
- [ ] **Stage 2 — Hybrid routing**: route simple well-formed questions to the standard pipeline (fast) and complex multi-part questions to a ReAct loop (thorough). Dependency: measure latency of ReAct loop with local llama3.1:8b first — a 3–4 step ReAct loop could take 20–40s, which is noticeable in a chat interface.
- [ ] **Stage 3 — Full ReAct agent**: replace fixed pipeline with a reasoning loop; ChromaDB, Fuseki, and future MCP-connected sources become tools the agent invokes with its own queries. Natural evolution of the current architecture — the named SPARQL catalogue and query expansion logic become the agent's tools, not the structure it replaces. Build on top of a stable, comprehensive knowledge base and query catalogue, not before.

---

## Phase 4 — Structured data and knowledge graph ✓ (mostly done)

The goal of this phase is to add a structured layer alongside the vector store,
enabling precise relational queries that semantic search cannot answer well.

- [x] Set up Apache Jena Fuseki triplestore locally — TDB2 dataset `mediasuite`, 1057 triples; SPARQL endpoint at `http://localhost:3030/mediasuite/sparql`
- [x] Write Media Suite entity descriptions in Turtle — `vocab/mediasuite-entities.ttl` (MediaSuite as `clariah:ResearchEnvironment`, 11 component tools, 4 infrastructure services) and `vocab/mediasuite-collections.ttl` (15 collections with EU access-right vocabulary URIs and confirmed license URIs)
- [x] Write workflow descriptions in Turtle — 18 top-level workflows + 5 sub-workflows in `vocab/mediasuite-workflows.ttl`; `clariah:workflowStatus` values; `clariah:optional` on 14 optional steps
- [x] Write SPARQL queries for structural retrieval patterns — 11 named query templates in `pipelines/graph/sparql_queries.py` (also mirrored in chatbot repo `api/sparql_queries.py`); all verified against live Fuseki
- [x] Add `entity_uri` field to chunk schema — see Phase 3
- [x] Implement hybrid retrieval in chatbot — both structural (SPARQL→Fuseki→entity URIs→ChromaDB) and narrative (expand→embed→ChromaDB) paths run in parallel; LLM synthesises from both contexts
- [x] Define `clariah-vocab.ttl` — custom terms with rdfs:label, rdfs:comment, alignment links to codemeta, softwaretypes, schema, tadirah; includes `clariah:Sampling` as TaDiRaH gap extension
- [x] Map `known_tools` to TaDiRaH activity URIs in `config.yaml` — `tool_entities` block with entity_uri, entity_type, tadirah_activities per tool
- [ ] Extract entities and relations from chunks using local LLM — augment Turtle descriptions with relations inferred from chunk text
- [ ] Evaluate when graph retrieval outperforms vector retrieval — partially answered via eval suite: SPARQL wins for enumeration, filtering, ordered traversal; vector search wins for how-to and narrative questions; full analysis pending
- [ ] Export knowledge graph as Turtle/RDF for reuse beyond the chatbot — align with tools.clariah.nl descriptor format

---

## Phase 5 — Source persistence and provenance

The goal of this phase is to make the knowledge base trustworthy enough for
production use, where researchers need to cite sources and rely on stable links.

- [ ] **Add version log (near term)** — record each ingestion run with date, source commit,
  chunk count, and Hit@10 score; informal versioning (v0.5 etc.) already in use in the
  learning log, formalise before NISV migration
- [ ] Implement persistent URL redirect layer for all chatbot-facing source URLs
- [ ] Raise documentation PID question within CLARIAH infrastructure team
- [ ] Implement per-chunk provenance metadata suitable for research citation
- [ ] Add API endpoint to query knowledge base version history
- [ ] Define deprecation policy for outdated chunks
- [ ] Expose knowledge base as an MCP server
  - [ ] Implement `search`, `get_by_url`, `list_collections` tools
  - [ ] Register as a CLARIAH shared MCP server
  - [ ] Document for use by other CLARIAH applications

---

## Phase 6 — Deployment and user evaluation

The goal of this phase is to deploy the chatbot and put it in front of real researchers.
The NISV infrastructure migration is a prerequisite for external researcher testing —
it must happen before researchers outside the immediate project are asked to use the system.

### NISV infrastructure migration

Migrating to NISV infrastructure (servers, repositories, and potentially compute)
is necessary for two reasons: (1) external researchers cannot be asked to depend on
a system running on a personal laptop, and (2) heavier models, larger pipelines,
or GPU-accelerated embedding will require more compute than is available locally.

**Important caveat:** once the repos move under `beeldengeluid` GitHub organisation
and the pipeline runs on NISV servers, access to some parts of the pipeline may be
restricted by NISV security policies. This risk should be assessed and documented
before migration begins — identify which pipeline components (Ollama, ChromaDB,
Fuseki, FastAPI, GitHub Actions) may be affected and what the mitigations are.

- [ ] Assess NISV security constraints on pipeline components before migration
  - [ ] Identify which services (Ollama, ChromaDB HTTP, Fuseki, FastAPI) can run on NISV infra
  - [ ] Identify which GitHub Actions workflows will still be accessible post-migration
  - [ ] Document fallback options if key components are blocked (e.g. cloud model API instead of local Ollama)
- [ ] Move `mediasuite-knowledge-base` to `beeldengeluid` GitHub organisation
- [ ] Move `media-suite-learn-chatbot` to `beeldengeluid` GitHub organisation
- [ ] Deploy ChromaDB and Fuseki on NISV server infrastructure
- [ ] Deploy FastAPI chatbot backend on NISV server
- [ ] Set up automated re-ingestion pipeline (GitHub Actions or cron) triggered by source repo updates
- [ ] Assess whether heavier embedding or generation models are feasible with available NISV compute

### User evaluation

- [ ] Deploy chatbot widget on the [Media Suite Community site](https://roelandordelman.github.io/media-suite-community/)
- [ ] Define evaluation methodology — what does "good" look like for researchers?
- [ ] Recruit a small group of Media Suite researchers for informal testing
- [ ] Collect and analyse real questions asked to the chatbot
- [ ] Compare real questions against test question set — identify gaps
- [ ] Iterate on knowledge base content based on evaluation findings
- [ ] Iterate on retrieval and generation based on evaluation findings
- [ ] Document findings in a short report for CLARIAH

---

## Phase 7 — Expansion to CLARIAH

The goal of this phase is to generalise the infrastructure beyond the Media
Suite to serve the broader CLARIAH research community.

- [ ] Assess which CLARIAH tools and collections would benefit from the same approach
- [ ] Abstract ingest pipeline to support multiple source repositories
- [ ] Define shared vocabulary and entity model across CLARIAH tools
- [ ] Rename / restructure as `clariah-knowledge-base` or integrate with existing infrastructure
- [ ] Explore integration with CLARIAH FAIR data infrastructure
- [ ] Publish the pipeline and methodology as a reusable open source component

---

## Learning log

Things that turned out differently than expected. Updated as the project progresses.

| Date | Finding | Impact |
|---|---|---|
| 2026-04-25 | 43% → 86% Hit@10 jump came from fixing test questions, not the retrieval system | Evaluation quality matters as much as retrieval quality — added emphasis on test set curation |
| 2026-04-25 | ChromaDB metadata only supports scalar values — lists must be JSON-encoded | Added note to chunk schema; chatbot query layer must `json.loads()` list fields |
| 2026-04-25 | Deduplication improved MRR from 0.333 to 0.357 — modest but meaningful | Post-retrieval deduplication by URL confirmed as standard step |
| 2026-04-25 | LLM answer quality poor even when retrieval was correct | Retrieval and generation are separate failure modes — need separate evaluation |
| 2026-04-28 | OpenAlex text search returned only 16 relevant papers; switching to Zotero group 2288915 gave ~90 academic papers | Zotero is the canonical source; OpenAlex is enrichment only |
| 2026-04-28 | References/acknowledgments sections were inflating chunk counts (57 chunks from one paper) | Added `never_keep` filter; kept sections now capped at 3000 chars |
| 2026-04-28 | 30 Zotero papers had no URL field — chatbot could not deep-link | Fixed by using `item["links"]["alternate"]["href"]` (Zotero web link) as fallback |
| 2026-04-28 | Brochure/report PDFs use all-caps branded chapter names — HEADING_RE only matched academic section names | Added ALL_CAPS_HEADING_RE and boilerplate line detection; 2014–2024 brochure went from 6 to 50 chunks |
| 2026-04-28 | `ollama.embeddings` (old single API) returns unnormalized vectors (magnitude ~21.6); `ollama.embed` (batch API) returns unit-normalized vectors — using the wrong API for query embedding silently corrupts ranking | Always use `ollama.embed` for both indexing and querying |
| 2026-04-28 | `chunk_title_overrides` alone cannot fix vocabulary mismatch when the chunk body is dominated by specialist terminology | Vocabulary gaps need tag embedding or query expansion; title overrides help but don't substitute for body vocabulary |
| 2026-04-30 | Appending categories + tags + tools_mentioned to embed text (v0.5) fixed the computer vision vocabulary gap; Hit@10 90% → 94%; stored document stays clean | Tag/category enrichment is a low-cost, high-signal fix for vocabulary gaps; apply before reaching for query expansion |
| 2026-04-28 | "SANE" as a bare acronym embeds as the common English adjective, not "Secure Analysis Environment" — SANE documentation ranks outside top 30 for "How can I use SANE?" | Acronym-heavy queries need chatbot-side query expansion; title override to full name partially helps |
| 2026-04-28 | Data stories are narrative/result-focused — terms like "quantitative analysis" don't appear prominently in chunk bodies even when the story is literally a quantitative analysis | Research output content needs tag embedding or query expansion to match methodological vocabulary |
| 2026-04-28 | Internal planning documents in Dutch (Jaarplan 2026) don't surface for English queries — nomic-embed-text doesn't reliably bridge Dutch content to English queries | Dutch-language sources require translation/summarisation before indexing |
| 2026-05-02 | LLM-based SPARQL routing was non-deterministic: 3–5/10 structural questions; same question routed differently between runs; LLM hallucinated unresolvable template variables | Replaced with embedding-based QueryIndex (cosine similarity against pre-embedded trigger questions); routing now deterministic; structural eval 26/26 (100%) |
| 2026-05-02 | Workflow graph names like "Quantitative analysis of restricted data via SANE" embed too far from concise user questions like "SANE workflow steps" | WORKFLOW_ALIASES dict provides short descriptive labels embedded as additional entities; supports multiple aliases per workflow |
| 2026-05-02 | Routing both paths unconditionally (no classification step) removes a failure mode — questions classified as narrative never reached the graph | Current design: both structural and narrative paths always run; LLM synthesises from whatever both return; structural returns empty string if no query exceeds threshold |
| 2026-05-02 | `collections_by_access` query + LLM could not reliably distinguish PUBLIC from NON_PUBLIC access codes — answered "university-only" questions with open collections | Added dedicated `restricted_collections` query with explicit `FILTER(?accessRights != euright:PUBLIC)`; now 100% on this question class |
| 2026-05-02 | LLM non-determinism in answer generation is distinct from routing non-determinism — correct SPARQL context in, wrong terms out (~1 failure per run at 50% scoring threshold) | Routing is deterministic; answer generation is not; expected_terms in eval must cover the range of correct phrasings the LLM may produce |
