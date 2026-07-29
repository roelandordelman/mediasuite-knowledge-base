# Version Log

A record of each significant knowledge base state: ingestion run, chunk counts,
eval scores, and config at the time. Provides a "before" snapshot for
infrastructure migrations and a baseline for regression detection.

---

## v0.6 — 2026-07-28

Pre-migration baseline re-check, run before starting the Stage 1 (Hetzner) migration
prep. Supersedes v0.5 as the reference point for the NISV migration risk matrix's
design constraint. The KB-level narrative eval was re-run first; Fuseki was down at
that point (Docker needed reinstalling — see below), so structural and wiki eval were
completed in a second pass once Docker was fixed, same day.

### Sources ingested

Chunk counts from `data/stats.json` (regenerated via `pipelines/stats/build_stats.py`,
2026-07-28T06:21Z). Total chunks: **2,799** (up from 2,568 at v0.5, 2,793 at an
intermediate 2026-05-15 snapshot). Growth since v0.5 is almost entirely the
`publications_beeldengeluid` collection (174 chunks, B&G Publications via OAI-PMH,
added after v0.5) and continued growth of `content` (Tier 1 authored, 57 chunks, up
from 51 at the 05-15 snapshot). All other per-source counts are unchanged from v0.5.

### Knowledge graph

Refreshed via `pipelines/graph/build_graph.py` once Fuseki was back up: **1,072
triples**, matching the 2026-05-15 snapshot exactly (no drift). 569/2,799 chunks have
`entity_uri` assigned (`data/stats.json`).

### Evaluation scores

| Eval | Score | vs. documented baseline | Notes |
|---|---|---|---|
| Narrative Hit@10 (all) | **84% (31/37)**, MRR 0.585 | roadmap/risk-doc cite 86% (32/37); v0.5 cited 94% (33/35) on a smaller question set | `evaluate/eval_retrieval.py`, run 2026-07-28 |
| — `answerable` only | 82% (14/17), MRR 0.550 | | |
| — `partial` only | 77% (10/13), MRR 0.474 | | |
| — `gap` | 9/9 ran without hallucinated hits | | excluded from Hit@10 denominator by design |
| Structural routing | **88% (23/26)** | roadmap cites 26/26 (100%) | `media-suite-learn-chatbot/evaluate/eval_router.py`, run 2026-07-28 |
| Wiki path | **100% (8/8)** | matches documented baseline exactly | `media-suite-learn-chatbot/evaluate/eval_wiki.py`, run 2026-07-28 |

**On the structural eval's 23/26 vs. documented 26/26:** unlike the narrative
regression below, this is not treated as equivalent evidence of drift. `eval_router.py`
exercises the full `answer()` pipeline including LLM generation, and the roadmap's own
learning log already documents that generation is non-deterministic independent of
routing correctness ("~1 failure per run at 50% scoring threshold" from LLM phrasing
variance alone, 2026-05-02 entry). The 3 failures this run — *"Which workflows use the
Search Tool?"* (38%, 3/8 terms), *"What can I do in the Media Suite without a login?"*
(0%), *"Which collections in the Media Suite have a CC0 license?"* (0%) — are recorded
for reference but may not reproduce on a re-run. Contrast with the narrative eval below,
which is deterministic (no LLM in the retrieval-only path) — its regressions are real.

**Notable regressions vs. documented state** — the failure set has shifted, not just
the aggregate score:
- *"How can I use computer vision in the Media Suite?"* now fails. The roadmap
  documents this as fixed via tag-embedding (`build_embed_text()`), citing a 90%→94%
  Hit@10 jump specifically from this fix. It is failing again.
- *"How do I work with sensitive audiovisual data in a secure environment?"* (the
  documented SANE-acronym workaround phrasing) now fails. v0.5's known-limitations
  note explicitly says this phrasing "retrieves correctly."
- Two failures with no prior record: *"Who develops the Media Suite?"* and
  *"What is the GTAA?"*
- Conversely, two previously-documented failures now **pass**: the Workspace+Compare
  Tool phrasing question and both Similarity Tool phrasing questions.

**Notable regressions vs. documented state** — the failure set has shifted, not just
the aggregate score:
- *"How can I use computer vision in the Media Suite?"* now fails. The roadmap
  documents this as fixed via tag-embedding (`build_embed_text()`), citing a 90%→94%
  Hit@10 jump specifically from this fix. It is failing again.
- *"How do I work with sensitive audiovisual data in a secure environment?"* (the
  documented SANE-acronym workaround phrasing) now fails. v0.5's known-limitations
  note explicitly says this phrasing "retrieves correctly."
- Two failures with no prior record: *"Who develops the Media Suite?"* and
  *"What is the GTAA?"*
- Conversely, two previously-documented failures now **pass**: the Workspace+Compare
  Tool phrasing question and both Similarity Tool phrasing questions.

This pattern — previously-fixed gaps un-fixing themselves while new ones appear, with
no corresponding config change recorded — is consistent with the known open backlog
item "Fix incremental re-indexing — `build_index.py` skips by chunk ID; changed
chunks must be manually deleted before re-indexing" (`docs/roadmap.md`, Phase 3).
Root-cause investigation is a separate follow-up, not done as part of this entry.

### Known limitations at this version

- The narrative retrieval regressions described above are recorded but not yet
  root-caused. Likely candidate: stale ChromaDB entries from the incremental-indexing
  gap (`build_index.py` skips by ID, not content hash). **Deliberately deferred**:
  retrieval fine-tuning makes more sense after the migration than before it, so this
  is not being investigated as part of Stage 1 prep.
- A harmless-looking `RuntimeWarning: divide by zero/overflow/invalid value
  encountered in matmul` fires from `media-suite-learn-chatbot/api/query_index.py:293`
  and `:388` (cosine similarity against a zero-norm embedding somewhere) during both
  `eval_router.py` and `eval_wiki.py` runs. Did not affect any pass/fail outcome this
  run — noted, not investigated.
- All "Known limitations" from v0.5 remain unresolved except where superseded above
  (Research Example → Research Publication rename still pending).

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
