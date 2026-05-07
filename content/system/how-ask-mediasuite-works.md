---
title: "How Ask Media Suite works"
content_type: "System Documentation"
url_stub: "system/how-ask-mediasuite-works"
tags: [Ask Media Suite, chatbot, knowledge base chatbot, RAG system, retrieval-augmented generation, SPARQL, system architecture, chatbot development, how it works, how it was built, question answering system]
author: "Roeland Ordelman"
status: active
created: "2026-05-06"
last_reviewed: "2026-05-07"
sources:
  - "https://github.com/roelandordelman/mediasuite-knowledge-base/blob/main/CLAUDE.md"
  - "https://github.com/roelandordelman/mediasuite-knowledge-base/blob/main/docs/roadmap.md"
  - "https://github.com/roelandordelman/mediasuite-knowledge-base/blob/main/config.yaml"
  - "https://github.com/roelandordelman/media-suite-learn-chatbot"
tier: 1
tech_dependencies: [chromadb, fuseki, nomic-embed-text, mistral]
replaces: []
---

## What is this? *(Must)*

"Ask Media Suite" is a question-answering chatbot that helps researchers find information about the CLARIAH Media Suite — its tools, collections, workflows, and research publications. This document explains what the chatbot knows, how it finds answers, and where its knowledge comes from, so researchers can assess the reliability of its answers and understand why it sometimes does not find what they are looking for.

## What it does *(Must)*

The chatbot answers natural-language questions about the Media Suite in English. It can:

- Explain what tools the Media Suite offers and how to use them (Inspector, Workspace, Comparator, Similarity Tool, etc.)
- Describe what collections are available, who can access them, and under what conditions
- Explain workflows — sequences of tools and steps for common research tasks such as corpus building, annotation, or quantitative analysis
- Retrieve information from research publications that describe how scholars have used the Media Suite
- Answer follow-up questions in a conversation, using the prior exchange as context
- Point to source URLs so researchers can verify answers and read further

## What it cannot do / known limitations *(Must)*

- **Does not search Media Suite data** — it cannot query AV collections, retrieve media items, or run analyses. It answers questions *about* the Media Suite, not questions that require searching *within* it.
- **Knowledge is not real-time** — content is ingested at a fixed point in time. Recent changes to documentation or newly published papers may not yet be reflected.
- **Dutch-language queries are unreliable** — the underlying embedding model (nomic-embed-text) does not reliably bridge Dutch queries to English-language content. Ask in English for best results.
- **Acronyms without context may fail** — queries like "SANE" without the full name ("Secure Analysis Environment") may not retrieve the right content. Spell out acronyms when in doubt.
- **Coverage has gaps** — not all Media Suite topics are equally covered. If the chatbot cannot find a good answer, the topic may not yet be in the knowledge base.
- **Answer quality depends on retrieval quality** — when the retrieved sources are only partially relevant, the generated answer may be imprecise even if it sounds confident.

## How it works *(Should)*

The chatbot uses two retrieval paths that run in parallel for every question:

**Narrative path** (for how-to, explanatory, and publication questions):
1. The question is expanded into three alternative phrasings by a language model
2. Each phrasing is embedded and used to search a vector store containing text chunks from all knowledge sources
3. The top results are deduplicated by source URL and ranked by similarity score

**Structural path** (for factual, enumeration, and relational questions):
1. The question is matched against a catalogue of named SPARQL query templates using embedding similarity
2. If a match is found above a confidence threshold, the corresponding SPARQL query runs against a knowledge graph holding RDF triples about tools, collections, workflows, and services
3. The graph results are used to filter and retrieve supporting chunks from the vector store

Both paths always run — there is no classification step that commits the question to one path or the other. The language model synthesises an answer from whatever both paths return, with source links.

For follow-up questions, the chatbot detects conversational signals (pronouns, references to "the tool" or "it") and rewrites the question as a standalone query before retrieval, using the last three turns of conversation history.

If retrieval quality is low (best similarity score above a threshold indicating a weak match), the query is automatically reformulated with different vocabulary and retrieval is retried once (Corrective RAG).

## Where the information comes from *(Should)*

The knowledge base has two layers:

**Vector store** — text chunks from:
- Media Suite documentation, how-to guides, FAQs, glossary, tutorials, and release notes (from mediasuite.clariah.nl)
- Data platform documentation from data.beeldengeluid.nl
- Research publications from the Media Suite Zotero group, enriched with abstracts and open-access PDFs via OpenAlex
- Data stories (quantitative research use cases)
- SANE community documentation (Secure Analysis Environment workflows and available NISV collections)

**Knowledge graph** — RDF triples describing:
- Media Suite component tools and infrastructure services, mapped to TaDiRaH activity types
- Archival collections with access rights and licence information
- Top-level research workflows and sub-workflows
- Custom vocabulary aligned with CodeMeta, TaDiRaH, softwaretypes, and schema.org

Content is ingested from source repositories and re-indexed periodically. For current coverage statistics see the knowledge base coverage page.

## Background and development *(Should)*

Ask Media Suite was created by the CTO of CLARIAH as a personal research and development project, starting in early 2026. The immediate goal was to build a better help and learning interface for Media Suite researchers — one that answers questions directly rather than requiring researchers to navigate documentation pages manually.

The project was also conceived as a practical learning exercise in retrieval-augmented generation (RAG), vector embeddings, knowledge graphs, and chatbot architecture, with the intention that the resulting infrastructure and methodology would inform CLARIAH's broader knowledge infrastructure as it matures.

Development followed an incremental approach: a local prototype first, expanded to cover more content sources, then enriched with a knowledge graph layer, and progressively deployed toward production use. The system is developed openly and is intended to eventually move under the CLARIAH/beeldengeluid GitHub organisation and run on NISV infrastructure.

## Design decisions and rationale *(Could)*

**Both retrieval paths always run.** An earlier design classified questions as either "narrative" or "structural" and routed them to one path. This introduced a failure mode: misclassified questions never reached the right path. Running both paths unconditionally removes this failure mode and lets the language model synthesise from richer context.

**Routing uses embedding similarity, not a language model.** An earlier prototype used a language model to decide which SPARQL query to run. This was non-deterministic — the same question was routed differently between runs, and the model sometimes hallucinated template variables. Replacing this with cosine similarity against pre-embedded trigger questions made routing deterministic and reliable.

**Tag and category text is embedded alongside chunk content.** Appending tags, categories, and entity names to the text used for embedding (not to the stored chunk) closes vocabulary gaps cheaply — for example, a chunk about a computer vision workflow retrieves correctly for "computer vision" queries even if those words do not appear in the chunk body.

**Named entity detection bypasses similarity routing for tool and collection names.** When a question contains a known tool or collection name verbatim (e.g. "Similarity Tool", "Oral History"), the chatbot skips similarity-based routing and directly fires an entity description query. This handles brand-name queries that cosine similarity handles poorly.

## Related resources *(Could)*

- [Media Suite documentation](https://mediasuite.clariah.nl/documentation)
- [CLARIAH Media Suite community site](https://roelandordelman.github.io/media-suite-community/)
