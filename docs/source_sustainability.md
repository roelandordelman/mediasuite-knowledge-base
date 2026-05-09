# Source Sustainability Audit

Last updated: May 2026.

Documents the update mechanism, cadence, failure characteristics, ownership, and rot risk
for every source in the knowledge base. Used to prioritise automation and maintenance work.

---

## Sustainability table

| Source | Update mechanism | Recommended cadence | Actual cadence | Failure mode | Owner | Rot risk |
|---|---|---|---|---|---|---|
| **mediasuite-website** (Jekyll docs, howtos, FAQs, tutorials, release notes) | Manual: `git clone` + `ingest_mediasuite.py` + `build_index.py` | On every merge to main in source repo (≈ 1–4×/month) | Ad hoc, manually triggered | Silent — clone failure leaves stale chunks in place; no alert | Roeland Ordelman | Medium — actively maintained by NISV; Jekyll structure stable but could change |
| **data.beeldengeluid.nl** (collection + API docs) | Manual: `git clone` + `ingest_dataplatform.py` + `build_index.py` | Monthly or on source repo update | Ad hoc, manually triggered | Silent — same as above | Roeland Ordelman | Medium — stable platform; repo could be deprecated if platform migrates CMS |
| **Research publications** (Zotero group 2288915 + OpenAlex enrichment) | Manual: `ingest_publications.py` (Zotero API + OpenAlex API + optional PDF download) | Monthly or when new items added to Zotero group | Ad hoc, manually triggered | Partial silent — API timeouts produce partial output; `--refresh` flag but no staleness alert | Roeland Ordelman (Zotero group: Media Suite community) | Medium — Zotero group community-maintained; OpenAlex API public and stable; supplementary DOIs need manual curation |
| **Data Stories** (beeldengeluid/data-stories) | Manual: `git clone` + `ingest_datastories.py` + `build_index.py` | On new story publication (rare — ≈ 1–3×/year) | Ad hoc, manually triggered | Silent | Roeland Ordelman | Low-medium — new stories are rare; Gatsby site format stable |
| **Community site / SANE docs** (media-suite-community) | Manual: `git clone` + `ingest_community.py` + `build_index.py` | On content change (very rare) | Ad hoc, manually triggered | Silent | Roeland Ordelman (repo owner) | Low — personal repo unlikely to disappear; SANE docs rarely updated |
| **Authored content** (content/ directory, Tier 1) | Direct file edit + `ingest_content.py` + `build_index.py`; lint check on run | On each new or edited Tier 1 document | Ad hoc, manually triggered | Explicit — lint warnings on missing fields or tech_stack mismatch; no silent failures | Roeland Ordelman | Very low — part of this repo; lifecycle (draft → active → deprecated → retired) enforced by ingest_content.py |
| **B&G Publications** (publications.beeldengeluid.nl OAI-PMH) | `ingest_beng_publications.py` with Sickle; incremental via OAI-PMH `from` parameter; state in `stores/beng_publications_state.json` | Weekly incremental poll | Not yet automated (scheduled for Phase 5/6 automation sprint) | Explicit — endpoint unavailable: log error and exit non-zero (no silent stale data); individual record parse error: log warning and continue | Media Suite team / NISV | Medium — public OAI-PMH endpoint on institutional infrastructure; URL could change on platform migration; deletedRecord policy is "transient" so deleted records require state tracking |

---

## Flags

**All current sources lack automated update triggers.** Every source is re-ingested only
when manually triggered. There is no staleness check, no scheduled job, and no alert when
a source falls out of date. This is acceptable for a local prototype but must be addressed
before Phase 6 external researcher evaluation.

**No GitHub Actions workflows exist yet.** The roadmap (Phase 6) includes setting up
automated re-ingestion on NISV infrastructure, but no CI/CD is in place. The planned
migration to `beeldengeluid` GitHub org is the right time to implement this.

**Specific per-source flags:**

- **mediasuite-website** — most frequent source of updates; most likely to be stale. Should
  be the first source to get an automated webhook or scheduled re-ingest.
- **Research publications / Zotero** — depends on community members adding items to Zotero
  group 2288915; no notification when new items are added. Consider watching Zotero group
  RSS feed as a trigger.
- **B&G Publications** — `deletedRecord: transient` means the OAI-PMH endpoint may not
  reliably report all deleted records. A periodic full re-harvest (monthly) should be used
  in addition to weekly incremental polls to keep data clean.
- **Data platform / Data Stories / SANE docs** — low update frequency; risk is mostly
  content going stale rather than the source disappearing. Acceptable for now.

---

## Update policy targets (Phase 5/6)

Once automated infrastructure is in place (GitHub Actions on NISV servers):

| Source | Target mechanism | Notes |
|---|---|---|
| mediasuite-website | GitHub Actions webhook on push to main | Trigger `ingest_mediasuite.py` → `build_index.py` |
| data.beeldengeluid.nl | Weekly scheduled job | Low update frequency; weekly is sufficient |
| Research publications | Monthly scheduled job | Zotero group changes infrequently |
| Data Stories | GitHub Actions webhook on push | New stories are rare; webhook avoids unnecessary polling |
| SANE / community docs | Monthly scheduled job | Very low update frequency |
| Authored content | On PR merge to this repo | `ingest_content.py` lint check as PR gate |
| B&G Publications | Weekly incremental OAI-PMH poll | Monthly full re-harvest to catch deletions |
