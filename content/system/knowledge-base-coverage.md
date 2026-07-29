---
title: "Knowledge base coverage"
content_type: "System Documentation"
url_stub: "system/knowledge-base-coverage"
tags: [knowledge base, coverage, statistics, sources, chatbot development]
author: "generated"
status: active
created: "2026-07-28"
last_reviewed: "2026-07-28"
tier: 1
---

## What is this?

This document describes the current state of the Ask Media Suite knowledge base: how many sources it covers, what types of content it contains, and how well retrieval is performing. It is regenerated automatically each time the knowledge base is rebuilt.

## Knowledge base build

The knowledge base was last built on 2026-07-28.

## Content coverage

The knowledge base contains 2,799 chunks across 19 content types.

| Content type | Chunks |
|---|---|
| Subject Tutorial | 784 |
| Tool Tutorial | 675 |
| Data Story | 369 |
| Research Example | 189 |
| B&G Publication | 174 |
| Labo Help | 97 |
| How-to Guide | 92 |
| Release Notes | 88 |
| Collection Documentation | 48 |
| Help / Documentation | 46 |
| Learn (General) | 44 |
| Example Project | 44 |
| Explainer | 36 |
| FAQ | 34 |
| API Documentation | 23 |
| System Documentation | 21 |
| SANE Documentation | 18 |
| Glossary | 13 |
| Tool Criticism | 4 |

## Retrieval evaluation

Retrieval quality is measured on a fixed test question set. Scores below are from the evaluation run (no evaluation run yet).

| Metric | Score |
|---|---|
| Hit@10 | not yet measured |
| Structural routing | not yet measured |

*Hit@10 = fraction of test questions where at least one expected source appears in the top 10 results. Higher is better; 1.0 = perfect.*

## Knowledge graph

The knowledge graph contains 1,072 RDF triples.

## Coverage updates

Coverage is updated each time the knowledge base is rebuilt by running `pipelines/stats/build_stats.py`.
