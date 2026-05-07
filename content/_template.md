---
# Tier 1 content template — copy and fill in for each new document.
# Must fields must be complete before setting status: active.
# Remove all comment lines before publishing.

title: ""
content_type: ""        # Explainer | System Documentation | FAQ | How-to Guide | Curated Answer
url_stub: ""            # e.g. system/how-ask-mediasuite-works — stable identifier, no spaces
tags: []                # e.g. [chatbot, retrieval, knowledge-base]
author: ""
status: draft           # draft | active | deprecated | retired
created: ""             # YYYY-MM-DD
last_reviewed: ""       # YYYY-MM-DD
sources: []             # URLs or repo paths used to compile this document
tier: 1
replaces: []            # optional: Tier 3 slugs this document supersedes, e.g. [_help/ask-tool]
---

<!--
AI AUTHORING INSTRUCTIONS
=========================
To draft this document using an AI tool:

1. Fill in the front matter above (title, content_type, url_stub, tags).
2. Provide this template to Claude along with the source links listed in `sources`.
3. Ask Claude to fill in each section below, following the MoSCoW guidance.
4. Review the draft: verify Must sections are accurate, trim Should/Could as needed.
5. Set status: active when the document passes review.

Prompt to use:
  "Using the sources listed below, fill in the sections of this content template
   for the Media Suite knowledge base. Follow the MoSCoW guidance in each section.
   Write for a researcher audience — assume familiarity with digital humanities tools
   but not with the technical internals of the system."

Sources: [paste your source links here]
-->

---

## What is this? *(Must)*

<!-- One short paragraph: what this document covers and why a researcher would read it.
     This becomes the retrieval summary — make it dense with the terms researchers use. -->

## What it does *(Must)*

<!-- Describe the system, tool, or workflow from the user's perspective.
     Focus on capabilities and behaviour, not implementation. -->

## What it cannot do / known limitations *(Must)*

<!-- Be explicit. Unanswered question types, gaps, known retrieval failures.
     This prevents the chatbot from confidently answering questions it shouldn't. -->

## How it works *(Should)*

<!-- High-level explanation of the mechanism. Enough for a researcher to understand
     why they get the answers they get. Not a code walkthrough. -->

## Where the information comes from *(Should)*

<!-- What sources feed this system? How current are they? How were they selected?
     Helps researchers assess reliability and coverage. -->

## Design decisions and rationale *(Could)*

<!-- Key choices made during development and why. Useful for future maintainers
     and for researchers who want to understand the system's perspective.
     Pull from the learning log in docs/roadmap.md where relevant. -->

## Related resources *(Could)*

<!-- Links to further reading: source repos, published papers, documentation pages.
     Use stable URLs. -->
