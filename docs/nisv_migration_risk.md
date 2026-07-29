# NISV Infrastructure Migration — Risk Matrix

> **SUPERSEDED 2026-07-28** — the goal of migrating *toward* NISV production
> (Stage 3 below) has been replaced by a community-hosted, NISV-decoupled
> direction. See `docs/infrastructure_architecture.md` for the current plan.
> This document is kept as a historical record; its component-level risk
> analysis (§2–3) is still technically valid and is restated without the
> NISV-destination framing in the new doc §4. See `docs/roadmap.md`'s
> Learning log for why the direction changed.

**Document status:** draft — superseded, see notice above
**Author:** Roeland Ordelman  
**Created:** 2026-05-15  
**Last reviewed:** 2026-05-15  
**Purpose:** Assess migration risks before infrastructure access is granted;
inform the conversation with the NISV lead developer; document the
three-stage deployment model and fallback options per pipeline component.

---

## 1. Deployment model

Migration to NISV infrastructure is not a single cutover event. It follows
three stages that reflect increasing stability, access breadth, and
institutional ownership.

| Stage | Environment | Repos | Access | Goal |
|---|---|---|---|---|
| **1 — Personal cloud prototype** | Hetzner VPS (personal account) | `roelandordelman` GitHub org | Inner circle (5–10 researchers, restricted) | Validate deployment, gather first researcher feedback |
| **2 — Accepted prototype** | Hetzner VPS or NISV acceptance environment | `beeldengeluid` GitHub org | Broader CLARIAH researcher group | Structured user evaluation, DH Benelux and beyond |
| **3 — NISV production** | NISV OpenShift / RHEL infrastructure | `beeldengeluid` GitHub org | Production, NISV-maintained | Production-grade deployment integrated with beeldengeluid |

Stage 1 is the immediate target. Stages 2 and 3 depend on evaluation
findings and NISV infrastructure access. This document primarily concerns
the Stage 1 → Stage 3 trajectory and the risks at each transition.

**Design constraint:** the embedding model (`nomic-embed-text`) and generation
model (`llama3.1:8b`) must remain unchanged across all three stages. All
retrieval evaluation (86% Hit@10, 26/26 structural routing, 8/8 wiki eval)
is calibrated against this stack. Changing either model requires re-indexing,
re-embedding, and full re-evaluation — a deliberate research decision, not a
deployment convenience measure.

---

## 2. Pipeline components

The full stack consists of these services:

| Component | Role | Current deployment |
|---|---|---|
| **Ollama** | Embedding (`nomic-embed-text`) + generation (`llama3.1:8b`) | Local, via Ollama HTTP API |
| **ChromaDB** | Vector store, served over HTTP | Local, Docker |
| **Apache Jena Fuseki** | SPARQL triplestore (knowledge graph) | Local, Docker |
| **FastAPI** | Chatbot backend (`/ask` endpoint, conversation history) | Local, Uvicorn |
| **Milvus** | Wiki agent vector store (24,104 articles) | Local, Docker |
| **mediasuite-wiki-agent** | Wiki retrieval service (`/ask` on port 8002) | Local, FastAPI |
| **GitHub Actions** | Ingestion pipeline automation (planned) | Not yet active |

---

## 3. Component risk assessment

### 3.1 Ollama

**Risk:** Ollama requires sufficient CPU (or GPU) to serve `llama3.1:8b`
at acceptable latency. On CPU-only hardware, generation takes 15–30s per
response — acceptable for a prototype with informed researchers, noticeable
for broader evaluation.

**Stage 1 (Hetzner):** Run CPU-only. Latency is a known trade-off, not a
blocker. A Hetzner CCX23 (4 dedicated vCPU, 16GB RAM, ~€30/mo) is the
recommended spec — sufficient for `llama3.1:8b` inference and all other
services on the same host.

**Stage 3 (NISV OpenShift):** Key question for the NISV lead developer:
- Can Ollama run as a container in OpenShift? (It packages as a standard
  Docker image.)
- Is a GPU node available, or is CPU-only the only option?
- Are there restrictions on pulling model weights from ollama.com at
  container startup? If so, models must be pre-baked into the image or
  pulled to a persistent volume.

**Fallback if Ollama is blocked in OpenShift:** Replace with an API-hosted
model. Embedding: Nomic Atlas API (same model, no re-indexing required).
Generation: Mistral API (`mistral-small`, EU-based) or Groq
(`llama3.1:8b`, US-based, sub-second latency). This fallback is a last
resort — prefer resolving the Ollama container question first.

---

### 3.2 ChromaDB

**Risk:** ChromaDB is served over HTTP on port 8001. In a firewalled
environment, inter-service HTTP traffic may require explicit port allowlisting.
ChromaDB has no built-in authentication — access control depends entirely on
network policy.

**Stage 1 (Hetzner):** Run in Docker, bind to localhost or private network
interface only. The FastAPI backend calls it internally; no external exposure
needed.

**Stage 3 (NISV OpenShift):** ChromaDB runs as a pod; FastAPI calls it via
Kubernetes internal service DNS. No external exposure required. Standard
OpenShift networking should support this without special configuration.

**Question for NISV lead developer:** Is there a preferred persistent
volume type for ChromaDB data (the vector index must survive pod restarts)?

**Fallback:** No strong fallback needed — ChromaDB in Kubernetes is
well-documented. If persistent volumes are unavailable, the index can be
rebuilt from source on restart (acceptable for prototype, not for production).

---

### 3.3 Apache Jena Fuseki

**Risk:** Fuseki runs on port 3030 and serves SPARQL queries. Same network
considerations as ChromaDB. The knowledge graph (1057 triples) loads from
a Turtle file at startup — this is a fast operation.

**Stage 1 (Hetzner):** Run in Docker, internal only. No external exposure
needed.

**Stage 3 (NISV OpenShift):** Same as ChromaDB — internal Kubernetes
service. Fuseki packages as a standard Docker image (official Apache image).

**Question for NISV lead developer:** NISV may already run a Fuseki or
other SPARQL endpoint for other projects. Is there a shared triplestore
the knowledge graph could be loaded into as a named graph, rather than
running a dedicated Fuseki pod?

**Fallback:** None needed — Fuseki in Docker/Kubernetes is
straightforward.

---

### 3.4 FastAPI (chatbot backend)

**Risk:** Lowest-risk component. Standard Python/Uvicorn container,
stateless, no persistent storage of its own.

**Stage 1 (Hetzner):** Run in Docker behind a reverse proxy (Nginx or
Caddy) with HTTPS and HTTP Basic Auth for access restriction.

**Stage 3 (NISV OpenShift):** Standard OpenShift deployment. Expose via
OpenShift Route for HTTPS termination. No special requirements.

**Access restriction for Stage 1:** The system must not be open to the
internet. Options in order of simplicity:
1. HTTP Basic Auth on the Nginx reverse proxy (simplest, sufficient for
   inner circle)
2. IP allowlist (restricts to known researcher IPs — less flexible)
3. VPN (most secure, most friction for researchers)

Recommendation: HTTP Basic Auth for Stage 1, shared password distributed
to inner circle researchers. Revisit for Stage 2.

---

### 3.5 Milvus + mediasuite-wiki-agent

**Risk:** Milvus is the heaviest service in the stack — it holds 24,104
wiki articles and requires more memory than the other components. The wiki
agent is a separate FastAPI service (port 8002) that the chatbot calls
for Dutch media history questions.

**Stage 1 (Hetzner):** Include if the CCX23 spec (16GB RAM) is sufficient.
If memory is tight, the wiki path degrades gracefully — the chatbot
continues without wiki results if the wiki service is unreachable. This
is a safe exclusion for Stage 1 if needed.

**Stage 3 (NISV OpenShift):** Two pods (Milvus + wiki agent). Same
persistent volume question as ChromaDB applies to Milvus.

**Question for NISV lead developer:** Milvus has specific memory
requirements. What is the available memory budget per pod, or is there a
preferred lightweight vector store alternative already in use at NISV?

**Fallback:** The wiki path is optional. Disabling it for Stage 1 is
explicitly supported by the graceful degradation already built into the
chatbot. Stage 1 can run without Milvus and the wiki agent.

---

### 3.6 GitHub Actions (ingestion automation)

**Risk:** Automated re-ingestion (triggered by source repo updates or on
a schedule) is planned but not yet active. It is not a Stage 1 requirement
— manual re-ingestion is sufficient for the prototype.

**Stage 3 (NISV OpenShift):** Two questions for NISV lead developer:
1. Are GitHub Actions runners accessible from NISV infrastructure, or
   does the runner need to be self-hosted?
2. Can a GitHub Actions workflow SSH into an NISV server or call an
   OpenShift deployment API to trigger re-ingestion?

**Fallback:** If GitHub Actions cannot reach NISV infrastructure, use
a cron job on the NISV server itself that polls source repos and
re-runs ingestion on a schedule. This is simpler and has no external
dependency.

---

## 4. Questions for the NISV lead developer

Consolidated list of open questions to resolve before Stage 3 planning:

1. Can Ollama run as a standard Docker container in OpenShift? Is a GPU
   node available?
2. Are there restrictions on pulling model weights from ollama.com at
   container startup?
3. What persistent volume types are available for ChromaDB and Milvus
   data?
4. Is there a shared SPARQL/Fuseki endpoint the knowledge graph could
   load into as a named graph?
5. What is the memory budget per pod? (Relevant for Milvus sizing.)
6. Can GitHub Actions workflows reach NISV infrastructure, or is a
   self-hosted runner or cron-based approach required?
7. Is there an NISV acceptance environment available for Stage 2, or
   does Stage 2 remain on Hetzner until Stage 3?

---

## 5. Stage 1 deployment checklist (Hetzner)

Pre-conditions before inner circle researcher access:
   
- [ ] Provision Hetzner CCX23 (4 vCPU, 16GB RAM) — Ubuntu 24 LTS
- [ ] Install Docker and Docker Compose
- [ ] Write `docker-compose.yml` for: Ollama, ChromaDB, Fuseki, FastAPI,
      Nginx reverse proxy (Milvus + wiki agent optional for Stage 1)
- [ ] Pull Ollama models (`nomic-embed-text`, `llama3.1:8b`) on first run
- [ ] Run ingestion pipeline and verify chunk count (~2600+)
- [ ] Run `build_stats.py` — verify `stats.json` populated correctly
- [ ] Run full eval suite — confirm 86% Hit@10, 26/26 structural, 8/8 wiki
- [ ] Configure Nginx with HTTPS (Let's Encrypt) and HTTP Basic Auth
- [ ] Smoke test chatbot widget from an external browser
- [ ] Distribute access credentials to inner circle researchers
- [ ] Deploy chatbot widget on media-suite-community site pointing to
      Hetzner endpoint

---

## 6. Risk summary

| Component | Stage 1 risk | Stage 3 risk | Fallback available? |
|---|---|---|---|
| Ollama (CPU) | Low — known latency trade-off | Medium — GPU/container question open | Yes — API models (last resort) |
| ChromaDB | Low | Low | Rebuild from source |
| Fuseki | Low | Low — shared endpoint possible | None needed |
| FastAPI | Low | Low | None needed |
| Milvus + wiki agent | Low — optional for Stage 1 | Medium — memory budget unknown | Yes — graceful degradation built in |
| GitHub Actions | None — not needed for Stage 1 | Medium — network access unknown | Yes — cron on NISV server |

No component has a high risk rating. The two medium-risk items for Stage 3
(Ollama GPU availability, Milvus memory budget) are both resolvable in a
single conversation with the NISV lead developer.
