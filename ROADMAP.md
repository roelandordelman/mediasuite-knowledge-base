# Roadmap — mediasuite-knowledge-base

This roadmap tracks the development of the knowledge base from local prototype
to production-ready CLARIAH infrastructure. It is ordered from simple to
advanced, and is deliberately kept as a living document — items are added,
reprioritised, or reframed based on what we learn along the way. Completed
items are kept visible so the learning journey is traceable.

If something turns out to be harder, less useful, or superseded by a better
approach than expected, that is noted inline rather than silently removed.

---

## Phase 1 — Local prototype ✓

The goal of this phase is a working end-to-end RAG pipeline running locally,
good enough to test retrieval quality and answer quality on real questions.

- [x] Ingest Media Suite website content from `beeldengeluid/mediasuite-website`
- [x] Parse Jekyll/Markdown front matter — preserve title, section, collection, URL
- [x] Deduplicate chunks across collections (cross-posted tutorials)
- [x] Embed chunks using `nomic-embed-text` via Ollama
- [x] Store vectors and metadata in ChromaDB
- [x] Serve ChromaDB over HTTP (decouple knowledge base from application)
- [x] Build retrieval evaluation script with Hit@10 and MRR metrics
- [x] Structured test question set with `answerable` / `partial` / `gap` categories
- [x] Extract `tools_mentioned` and `collections_mentioned` per chunk
- [x] Add `modified_date` and `source_commit` from git log per source file
- [x] Add `content_hash` (SHA256) per chunk for drift detection
- [x] Separate knowledge base repo from chatbot application repo
- [x] Knowledge base connects to chatbot via HTTP only — no shared filesystem

---

## Phase 2 — Knowledge base enrichment

The goal of this phase is to expand the knowledge base with additional sources
that make it significantly more useful to researchers.

- [ ] Ingest GitHub Issues from `beeldengeluid/mediasuite-website` as authentic Q&A
- [ ] Ingest research publications via DOIs
  - [ ] Use Unpaywall API to find open access PDFs
  - [ ] Filter for Media Suite relevance (two-pass: abstract scan → passage extraction)
  - [ ] Generate per-paper summary of how the Media Suite was used
  - [ ] Tag as `content_type: Research Example` with DOI as persistent identifier
- [ ] Ingest Jupyter notebook markdown cells from Media Suite example notebooks
- [ ] Ingest data platform documentation from `data.beeldengeluid.nl`
- [ ] Ingest workshop and tutorial materials (PDFs, slide decks)
- [ ] Expand `known_tools` and `known_collections` lists in `config.yaml` based on corpus analysis
- [ ] Validate entity extraction quality — check `tools_mentioned` / `collections_mentioned` for false positives

---

## Phase 3 — Retrieval quality improvements

The goal of this phase is to improve retrieval precision and recall based on
what we learn from evaluation and real researcher questions.

- [ ] Expand test question set to 30+ questions across all three categories
- [ ] Add end-to-end answer quality evaluation in the chatbot repo
- [ ] Implement recency boost — favour recently modified chunks when scores are close
- [ ] Implement staleness check — periodically compare live page content against ingested chunks
- [ ] Add re-ingestion pipeline that only re-embeds changed chunks (using `content_hash`)
- [ ] Investigate query expansion / rewriting to address vocabulary mismatch
  - [ ] Evaluate HyDE (Hypothetical Document Embedding) approach
  - [ ] Evaluate simple LLM-based query rewriting before embedding
- [ ] Tune chunk size and overlap based on retrieval evaluation results
- [ ] Investigate re-ranking — use a cross-encoder to re-rank top-k results before generation

---

## Phase 4 — Structured data and knowledge graph

The goal of this phase is to add a structured layer alongside the vector store,
enabling precise relational queries that semantic search cannot answer well.

- [ ] Define entity model: Tool, Collection, Tutorial, ResearchExample, Researcher
- [ ] Extract entities and relations from chunks using local LLM
- [ ] Build RDF graph from extracted entities
- [ ] Store in Apache Jena Fuseki triplestore with SPARQL endpoint
- [ ] Align entity vocabulary with existing CLARIAH linked data vocabularies
- [ ] Implement hybrid retrieval — combine vector search and SPARQL for complex queries
- [ ] Evaluate when graph retrieval outperforms vector retrieval and vice versa
- [ ] Export knowledge graph as Turtle/RDF for reuse beyond the chatbot

---

## Phase 5 — Source persistence and provenance

The goal of this phase is to make the knowledge base trustworthy enough for
production use, where researchers need to cite sources and rely on stable links.

- [ ] Add version log — record each ingestion run with date, source commit, chunk count
- [ ] Implement persistent URL redirect layer for all chatbot-facing source URLs
- [ ] Raise documentation PID question within CLARIAH infrastructure team
- [ ] Implement per-chunk provenance metadata suitable for research citation
- [ ] Add API endpoint to query knowledge base version history
- [ ] Define deprecation policy for outdated chunks

---

## Phase 6 — User evaluation and iteration

The goal of this phase is to put the system in front of real researchers and
use what we learn to drive further development.

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

This section captures things that turned out differently than expected.
Updated as the project progresses.

| Date | Finding | Impact on roadmap |
|---|---|---|
| 2026-04-25 | 43% → 86% Hit@10 jump came from fixing test questions, not the retrieval system | Evaluation quality matters as much as retrieval quality — added emphasis on test set curation |
| 2026-04-25 | ChromaDB metadata only supports scalar values — lists must be JSON-encoded | Added note to chunk schema documentation; chatbot query layer must `json.loads()` list fields |
| 2026-04-25 | Deduplication improved MRR from 0.333 to 0.357 — modest but meaningful | Post-retrieval deduplication by URL confirmed as standard step |
| 2026-04-25 | LLM answer quality poor even when retrieval was correct | Retrieval and generation are separate failure modes — need separate evaluation |
