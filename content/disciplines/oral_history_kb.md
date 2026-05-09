---
title: "Oral History in the Media Suite"
content_type: "Explainer"
url_stub: "context/oral-history-media-suite"
tags: [oral-history, collections, ASR, DANS, transcripts, methodology, Netherlands]
author: ""
status: active
created: "2026-05-09"
last_reviewed: "2026-05-09"
sources:
  - "Oral History: Methodologies, Evolution, and Digital Frontiers (uploaded PDF)"
  - "Voices of the Past: Oral History in the Netherlands (uploaded PDF)"
  - "https://mediasuite.clariah.nl"
  - "https://dans.knaw.nl"
tier: 1
replaces: []
---

## What is this? *(Must)*

This document explains what oral history is, how it is represented in the Media
Suite, and what researchers can and cannot do with oral history collections through
the Media Suite interface. It is relevant for researchers who want to work with
interview recordings, life histories, or eyewitness accounts held across Dutch
heritage institutions.

## What it does *(Must)*

The Media Suite provides access to oral history collections held at multiple
institutions, including collections stored at DANS (Data Archiving and Networked
Services) and Beeld & Geluid (Netherlands Institute for Sound and Vision). Within
the Media Suite, researchers can:

- **Search** oral history collections using keyword search over metadata and, where
  available, automatic speech recognition (ASR) transcripts
- **Browse and play** interview recordings directly in the Resource Viewer, with
  access to timecoded transcript layers alongside the audio or video
- **Annotate** items and create bookmarks, saved queries, and personal corpora for
  research projects
- **Inspect collection metadata** using the Collection Inspector to understand
  coverage, completeness, and temporal distribution of the collections

The Media Suite also connects oral history content to linked data resources: where
persons mentioned in interviews are linked to the GTAA thesaurus or Wikidata,
researchers can find related items across collections.

The oral history collections in the Media Suite include material from projects such
as **Verteld Verleden** (Narrated Past), which created a distributed infrastructure
connecting collections at Beeld & Geluid, DANS, Atria, and the Meertens Institute.
The Dutch oral history landscape holds an estimated 50,000–60,000 hours of
audiovisual material across archives and institutions; the Media Suite provides
structured research access to a significant and growing portion of this.

## What it cannot do / known limitations *(Must)*

**Access restrictions.** A significant portion of oral history material is
restricted due to privacy considerations, ethical agreements with interviewees, or
copyright. Not all collections are viewable without institutional login via
SURFconext. Some collections require a formal data access request via DANS or the
holding institution. The Media Suite will show metadata for restricted items but
cannot always stream the recordings themselves.

**ASR quality varies.** Where ASR transcripts are available, they are generated
automatically and have known limitations: raw transcripts often lack punctuation
and speaker labels, may contain errors on names, dialects, or domain-specific
vocabulary, and should not be treated as standalone sources without reference to
the original recording. ASR quality benchmarks for different speech types are
published openly at
[opensource-spraakherkenning-nl.github.io](https://opensource-spraakherkenning-nl.github.io/ASR_NL_results).

**Transcript-only search is insufficient for oral history.** Scholars emphasise
that transcripts flatten the narrative and lose paralinguistic elements — tone,
pacing, pauses, gesture — that carry methodological significance. The Media Suite's
Resource Viewer is designed to keep audio and transcript together precisely for this
reason, but researchers should be aware that searching transcripts alone is not
equivalent to engaging with the interview as a source.

**Coverage is incomplete.** The Dutch oral history landscape is highly fragmented.
Many collections remain uncatalogued, poorly stored, or held in private archives not
yet connected to national infrastructure. The Media Suite reflects what has been
digitised, catalogued, and made accessible — not the full landscape of what exists.

**No automatic anonymisation.** Sensitive content — including material involving
living persons, traumatic testimony, or legally restricted personal data — is not
automatically filtered. Researchers are responsible for handling such material in
accordance with GDPR/AVG and the ethical agreements under which collections were
created.

## How it works *(Should)*

Oral history collections in the Media Suite are indexed via the same Elasticsearch
infrastructure used for broadcast and press collections, enabling full-text search
over metadata and ASR transcript layers simultaneously. Where transcripts exist,
they are stored with timecodes at the sentence and word level, enabling the
Resource Viewer to synchronise transcript display with audio or video playback —
so a researcher can click a transcript passage and jump to that moment in the
recording.

Access to DANS-hosted oral history collections is managed via SURFconext
authentication. Researchers affiliated with Dutch universities or research
institutions can log in with their institutional account and access collections
under the access conditions negotiated between the Media Suite and the data
provider.

Metadata from oral history collections is normalised to a common model for search
and filtering purposes. Where collections use institution-specific metadata schemas,
the Collection Inspector tool documents the available fields and their coverage,
allowing researchers to understand what is and is not described before building a
corpus.

## Where the information comes from *(Should)*

The oral history collections accessible in the Media Suite come from multiple
holding institutions. The primary sources are:

- **DANS** — the national research data archive, which holds a large share of
  academic oral history collections in the Netherlands, including material from
  projects on migration, labour history, and the Second World War
- **Beeld & Geluid (Sound & Vision)** — holds oral history material related to
  media history and broadcasting; its institutional policy focuses on media-related
  oral history while collaborating with DANS for long-term archiving of academic
  collections
- **Meertens Institute**, **Atria**, and other cultural heritage institutions —
  connected through infrastructure developed by projects including Verteld Verleden
  and Sprekende Geschiedenis

Metadata is harvested using OAI-PMH and updated periodically. The currency of the
index depends on the update schedule of the source institution. Researchers who need
to know the precise harvest date for a collection can check the dataset description
in the Media Suite data register or contact the Media Suite team.

## Design decisions and rationale *(Could)*

The decision to prioritise oral history collections for ASR processing reflects
their research value relative to their metadata completeness: oral history
recordings are often minimally catalogued (a title, a date, a name), making
content-based search via transcript the primary discovery mechanism. ASR for oral
history is technically harder than for broadcast news — interview speech is
conversational, accented, and often covers names and places not in standard
vocabularies — which is why quality varies and benchmarking is published openly.

The Media Suite's Resource Viewer was designed to keep recording and transcript
together specifically because the oral history research community has been clear
that transcript-only workflows are methodologically inadequate. The timeline
interface, which allows navigation by speech segment, reflects this design
principle.

Access to oral history via the Media Suite sits within the broader SANE (Secure
ANalysis Environment) development being built through SSHOC-NL, which will
eventually allow quantitative analysis of sensitive oral history datasets in a
controlled environment without the data leaving institutional infrastructure.

## Related resources *(Could)*

- [Media Suite oral history collections overview](https://mediasuite.clariah.nl/data)
- [DANS oral history portal](https://dans.knaw.nl)
- [Sprekende Geschiedenis — national oral history node](https://sprekende-geschiedenis.nl)
- [ASR quality benchmarks for Dutch speech](https://opensource-spraakherkenning-nl.github.io/ASR_NL_results)
- [Collection Inspector — Sound & Vision oral history](https://mediasuite.clariah.nl/tool/collection-inspector)
- [StoRe project — FAIR archiving guidelines for oral history](https://store-project.nl)
