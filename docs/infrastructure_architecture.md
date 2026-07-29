# Infrastructure Architecture — Community-Hosted, NISV-Decoupled

**Document status:** draft
**Author:** Roeland Ordelman
**Created:** 2026-07-28
**Supersedes:** `docs/nisv_migration_risk.md` (kept for historical record — see §7)

---

## 1. Context and motivation

The original plan (see `docs/nisv_migration_risk.md`) was to migrate this stack
*toward* NISV, ending in NISV-hosted production infrastructure (Stage 3). That
plan is being replaced.

Motivation for the change: NISV, as the Media Suite's host institution, is
organisationally constrained in ways that bottleneck this kind of tooling
work — limited developer manpower, restrictive infrastructure policy, and
constraints reaching down to which programming languages/stacks can even be
used. Tying the continuity of public-interest tooling (documentation, a
knowledge base, a chatbot) to that institution's capacity means its pace is
capped by NISV's, not by the tooling's own potential contributor base.

The new direction: decouple the public-interest tooling layer from NISV
entirely — host it in the community, open to contribution from other CLARIAH
partner institutes, individual contributors, and interested researchers —
while the narrow layer that is genuinely rights-restricted (the audiovisual
archive itself, authenticated playout) stays exclusively with NISV, because
it legally has to.

## 2. The two-layer model

| Layer | Contains | Who can host/contribute | Access control |
|---|---|---|---|
| **A — Public-interest tooling** | Knowledge base, chatbot, wiki agent, documentation, code | Anyone — community, other CLARIAH institutes, individuals | None required |
| **B — Rights-restricted data/access** | The audiovisual archive, authenticated playout | NISV only (legal rights-holder) | Required (SURFconext / institutional) |

**Current state of this repository and its siblings (`mediasuite-knowledge-base`,
`media-suite-learn-chatbot`, `mediasuite-wiki-agent`): entirely Layer A.**
Verified 2026-07-28 by checking every ingested source — Media Suite
documentation, `data.beeldengeluid.nl` pages, Zotero/B&G publications, data
stories, and wiki content are all already public. The knowledge graph's
access-rights metadata (`euright:PUBLIC` / `NON_PUBLIC` on collections)
*describes* which NISV collections are restricted; it does not contain the
restricted material itself. **Layer B currently has zero components in this
project** — it's a placeholder for a future integration point (e.g. if the
chatbot ever links to or embeds an authenticated clip), not something that
exists today.

## 3. Sustainability framework

Three separate axes, not one — conflating them was the main source of
confusion before this framing existed:

1. **Access control** — does a component need to sit behind NISV
   authentication? Answer for this project, today: no, nothing does (see §2).
2. **Regenerability** — can a component be rebuilt on demand from a durably
   stored source (git + public APIs), or does it hold state that would be
   genuinely lost if its host disappeared? Verified empirically for the
   knowledge graph on 2026-07-28: Fuseki died (Docker broke), was
   reinstalled, and `pipelines/graph/build_graph.py` rebuilt it from the
   version-controlled `vocab/*.ttl` files to the exact same 1,072 triples.
   The same logic applies to ChromaDB (rebuildable via the ingestion
   pipelines) and is presumed true, but not yet verified as rigorously, for
   the wiki agent's Milvus index (rebuildable from the Wikidata/wiki harvest
   scripts). **Conclusion: the running services in this stack are disposable,
   cache-like layers over source-of-truth data — none of them individually
   need archival-grade hosting.**
3. **Continuity / bus factor** — this is the axis that actually matters most
   right now, and it's independent of where anything is hosted.
   `docs/source_sustainability.md` lists **"Owner: Roeland Ordelman"** against
   nearly every source, and all re-ingestion is manual. Hosting location (EU
   commercial vs. NISV vs. anywhere else) does not fix this. What fixes it is
   institutional/community ownership of the *repositories and the knowledge
   of how to regenerate everything* — a separate decision from where compute
   runs.

**Implication:** "decouple from NISV" and "fix the bus-factor problem" are two
different projects that happen to point the same direction. Moving hosting to
an EU provider without also moving repo/pipeline ownership out of one
person's personal GitHub account would solve the wrong half of the problem.

## 4. Component deployment (carried forward from the superseded doc)

The component-level technical analysis in `docs/nisv_migration_risk.md` §2–3
mostly still applies — it was never actually NISV-specific, it's generic
container-hosting analysis that happens to have been framed around an
eventual NISV OpenShift target. Restated here without that framing:

| Component | Role | Hosting need |
|---|---|---|
| Ollama | Embedding (`nomic-embed-text`) + generation (`llama3.1:8b`) | GPU helps but CPU works at a latency cost; EU-hosted GPU (or an EU LLM API as a non-fallback default, e.g. Mistral) is now the default assumption, not a Stage-3 contingency |
| ChromaDB | Vector store, HTTP | Regenerable (§3); no special persistence requirement |
| Apache Jena Fuseki | SPARQL triplestore | Regenerable (§3) from version-controlled Turtle |
| FastAPI (chatbot backend, KB entity API) | Stateless application logic | Lowest risk, standard container |
| Milvus (wiki agent) + wiki-agent API | Wiki semantic search | Presumed regenerable from harvest scripts (not yet verified as rigorously as the graph) |

**Hetzner** (the Stage-1 VPS choice in the superseded doc) is itself an EU
(German) hosting company — worth noting because it means the old "Stage 1"
prototype plan already happened to be compatible with this new direction. It
should be treated as the current placeholder choice, not a settled decision:
actual vendor selection is likely to depend on the outcome of the governance/
funding question in §6.

## 5. Repository and organisational ownership

The previous plan's Stage 2 step — "move `mediasuite-knowledge-base` and
`media-suite-learn-chatbot` to the `beeldengeluid` GitHub organisation" — is
now **reconsidered, not carried forward as-is**. Moving community-facing repos
into NISV's own org re-couples continuity to NISV, which is what this
direction is trying to avoid. The repos should move to a neutral home instead
— a CLARIAH-affiliated org, or an independent community org — exact home
still open, likely to depend on §6.

## 6. Open question: governance and funding model

Not yet resolved, and deliberately out of scope for this document. The core
question, in the user's own framing: **who pays which bill, and who takes
which decision** — for a public-interest tooling layer sustained by a
distributed community, without founding a new legal entity.

A separate investigation into existing precedents (fiscal sponsorship models,
comparable research-infrastructure or open-source governance splits) has been
commissioned as a standalone research task, not done inline here. Revisit this
section once that investigation returns findings; until then, treat §5 (repo
ownership) as unresolved.

## 7. Relationship to `docs/nisv_migration_risk.md`

That document is kept, not deleted — it's a historical record of the
original migrate-to-NISV plan and contains a component-by-component risk
analysis whose technical content is still valid (see §4 above, which restates
the reusable parts). It has been marked superseded at the top rather than
rewritten in place, so the reasoning trail for this pivot stays visible. See
`docs/roadmap.md`'s Learning log for a one-line summary of why the direction
changed and when.

## 8. Next steps

- [ ] Governance/funding investigation (external, in progress — see §6)
- [ ] Decide repo/org home once §6 resolves
- [ ] Verify wiki-agent Milvus index regenerability as rigorously as the graph
      was verified (§3, point 2)
- [ ] Revisit vendor choice (Hetzner vs. alternatives) once funding model is
      known
- [ ] No infrastructure work should proceed past what's already running
      locally until §6 resolves — building deployment artifacts against the
      wrong org/funding model would be wasted effort
