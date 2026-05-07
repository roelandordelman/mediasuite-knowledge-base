# Knowledge Base Content Framework

This document defines how content enters, lives in, and exits the knowledge base.
It applies to all sources and all update types.

---

## 1. Principles

- **Stability over volume** — fewer high-quality, stable chunks outperform many stale or
  imprecise ones. Prefer authored content over scraped legacy content when both exist.
- **Traceability** — every chunk in the knowledge base must be traceable to a source,
  a source tier, and a lifecycle state.
- **Evaluation-driven** — user evaluation findings are a first-class trigger for adding
  or retiring content. The system should improve in response to real queries, not just
  upstream repo changes.
- **Regenerability** — the full pipeline must remain runnable from scratch at any time.
  Retirement and migration decisions must be reflected in config, not just in the store.

---

## 2. Content lifecycle

Every content item (chunk or source document) moves through these states:

```
draft → active → deprecated → retired
```

| State | Meaning | In ChromaDB? |
|---|---|---|
| `draft` | Being authored or evaluated; not yet indexed | No |
| `active` | In production; returned in queries | Yes |
| `deprecated` | Superseded by better content; still indexed but lower weight or filtered | Yes (flagged) |
| `retired` | Removed from the index; source document archived | No |

Transitions:
- `draft → active`: content passes a basic quality check and is indexed
- `active → deprecated`: a higher-quality replacement exists; the old content is flagged
- `deprecated → retired`: after a migration period (default: one release cycle), the old
  content is deleted from ChromaDB and its source is archived or removed from config

Deprecation should always have an explicit replacement. A chunk is not deprecated in
isolation — it is deprecated *because* something better exists.

---

## 3. Source tiers

Sources are grouped into tiers that reflect their stability and authoritativeness.
When content from different tiers covers the same topic, higher-tier content takes
precedence (via deprecation of lower-tier content, not silent override).

| Tier | Type | Examples | Update pathway |
|---|---|---|---|
| 1 | Authored / curated | `content/` directory in this repo | Pathway 2 |
| 2 | Synchronized structured sources | Zotero publications, data.beeldengeluid.nl | Pathway 1 |
| 3 | Legacy scraped sources | mediasuite-website `_help`, `_learn_*` | Pathway 1 (sunset candidate) |

**Migration direction**: over time, content moves from Tier 3 → Tier 1 as topics are
rewritten as stable authored documents. Tier 3 sources are not removed abruptly —
they are deprecated topic by topic as Tier 1 replacements are published.

Tier 2 (publications, data platform) is expected to remain; it is not legacy.

---

## 4. Update pathways

### Pathway 1 — Source sync (routine)

Upstream source repositories gain new content through normal editorial activity
(new release note, new publication added to Zotero, new API page).

**Trigger**: upstream repo change, or scheduled cadence (default: monthly)  
**Process**:
1. Pull latest version of the source repo / data source
2. Re-run the relevant ingest script → updated JSON
3. Run `build_index.py` — incremental, only new chunks are embedded
4. Run `evaluate/eval_retrieval.py` — verify no regression

**Responsible**: repository maintainer (currently: Roeland Ordelman)  
**Cadence**: monthly for mediasuite-website; after each Zotero update for publications

### Pathway 2 — Deliberate content authoring

New knowledge items are created that do not belong to any upstream source: explanatory
documents, curated answers to common user questions, system documentation
(how the knowledge base works, how the chatbot works), meta-content surfaced by
user evaluation.

**Trigger**: user evaluation finding, identified knowledge gap, editorial decision  
**Process**:
1. Author a markdown document in `content/<topic>/` following the content template
2. Add metadata (title, content_type, url_stub, tags) in the document front matter
3. Run `pipelines/ingest/ingest_content.py` → appends to `content.json`
4. Run `build_index.py` — incremental
5. Run evaluation; if the new content addresses the gap, close the evaluation finding

**Responsible**: repository maintainer or designated content author  
**Cadence**: as needed; no fixed schedule

---

## 5. Retirement path

Retirement is the controlled removal of content that is no longer accurate, relevant,
or has been superseded by higher-tier content.

### Triggers for retirement

- A Tier 1 authored document covers the same topic as one or more Tier 3 chunks
- An upstream source page has been deleted or substantially rewritten
- User evaluation shows a document is consistently retrieved but unhelpful or misleading
- The source itself is being sunset (e.g., a legacy help section removed from the website)

### Retirement process

1. **Identify** chunks to retire (by source slug, collection, or topic)
2. **Mark deprecated** in `config.yaml` under `deprecated_sources` or
   `deprecated_slugs` — this signals intent and is reviewable
3. **Verify replacement exists** — do not retire without a live replacement
4. **Delete from ChromaDB** — by chunk ID or collection filter
5. **Archive or remove** the source document from the ingest pipeline config
6. **Log in version_log.md** — note what was retired and why

### config.yaml structure for retirement

```yaml
deprecated_slugs:
  - slug: help/inspector-search
    reason: "replaced by content/tools/inspector.md (Tier 1)"
    deprecated_date: "2026-05-01"
    retire_after: "2026-06-01"
```

---

## 6. Migration strategy: legacy → stable

The mediasuite-website `_help` and `_learn_*` collections are Tier 3 sources. They
were the starting point but are not the target architecture. They are:
- Maintained by a separate editorial team with a different purpose
- Not structured for retrieval (titles and headings are written for browsing, not querying)
- Subject to change without notice to this knowledge base

**Migration goal**: replace Tier 3 topic coverage with authored Tier 1 documents,
one topic cluster at a time.

**Priority order for migration** (informed by evaluation hit rate and user query volume):
1. Topics where retrieval currently fails or returns low-relevance results
2. Topics with high query volume
3. Topics where the source page is unstable or frequently rewritten

**Migration is not a big-bang rewrite**. Each authored Tier 1 document that goes
active deprecates the specific Tier 3 chunks it replaces. The rest of Tier 3 stays
active until a replacement exists.

---

## 7. Governance

Governance operates at two levels. Currently only the Media Suite level is active;
CLARIAH-level governance is planned as the scope expands.

### Current: Media Suite level

| Decision | Trigger | Who |
|---|---|---|
| Add a new Tier 1 document | Evaluation gap or editorial decision | Maintainer |
| Deprecate a Tier 3 chunk cluster | Tier 1 replacement is active | Maintainer |
| Add a new Tier 2 source | New structured data source available | Maintainer |
| Retire a deprecated item | Deprecation period elapsed | Maintainer |
| Change sync cadence | Evaluation shows drift | Maintainer |

### Planned: CLARIAH level

As this knowledge base expands beyond the Media Suite to serve CLARIAH more broadly,
an editorial governance layer above the Media Suite maintainer is needed. Responsibilities
at this level would include:

- Approving new content domains and source types
- Setting quality standards for Tier 1 authored content
- Deciding when a topic is ready for CLARIAH-wide coverage vs. Media Suite only
- Aligning vocabulary and entity model with CLARIAH linked data vocabularies

**Existing foundation: tools.clariah.nl**  
There is already relevant prior work in CLARIAH toward a shared linked data vocabulary
for research tools, centred on [tools.clariah.nl](https://tools.clariah.nl). This
registry describes CLARIAH tools using CodeMeta, TaDiRaH, and softwaretypes vocabularies.
The entity model being built in this knowledge base (`clariah-vocab.ttl`,
`mediasuite-entities.ttl`) is being aligned with that vocabulary as a deliberate
stepping stone toward CLARIAH-level governance (see Phase 3 and Phase 4 in
`docs/roadmap.md`). When CLARIAH-level governance is established, the tools.clariah.nl
vocabulary and its maintainers are the natural starting point for that conversation.

This layer does not yet exist formally. When it is established, this section should be
updated with named roles and a decision process.

### Traceability

Evaluation findings that motivate content changes should be logged in
`evaluate/findings.md` (to be created) so that decisions are traceable at both levels.
