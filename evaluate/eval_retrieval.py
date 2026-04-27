"""
Retrieval evaluation — measures how well ChromaDB finds the right sources.

For each question in test_questions.yaml, embeds the question, queries ChromaDB,
and checks whether any of the expected URLs appears in the top-k results.
A question PASSES if at least one expected URL is found.

Metrics reported:
  Hit@k   — fraction of questions where ≥1 expected URL appears in top k
  MRR     — mean reciprocal rank of the first expected URL found

Usage:
    python evaluate/eval_retrieval.py
    python evaluate/eval_retrieval.py --top-k 10
    python evaluate/eval_retrieval.py --category answerable
    python evaluate/eval_retrieval.py --category gap
"""

import argparse
import json
from pathlib import Path

import ollama
import chromadb
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
QUESTIONS_PATH = Path(__file__).parent / "test_questions.yaml"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_questions(path: Path, category: str | None = None) -> list[dict]:
    with open(path) as f:
        questions = yaml.safe_load(f)["questions"]
    if category:
        questions = [q for q in questions if q.get("category") == category]
    return questions


def embed(text: str, model: str) -> list[float]:
    return ollama.embed(model=model, input=[text])["embeddings"][0]


def deduplicate_by_url(
    metadatas: list[dict], distances: list[float]
) -> tuple[list[dict], list[float]]:
    """Keep only the highest-scoring (lowest-distance) chunk per source URL."""
    seen: dict[str, tuple[dict, float]] = {}
    for meta, dist in zip(metadatas, distances):
        url = meta["url"]
        if url not in seen or dist < seen[url][1]:
            seen[url] = (meta, dist)
    deduped = sorted(seen.values(), key=lambda x: x[1])
    return [m for m, _ in deduped], [d for _, d in deduped]


def reciprocal_rank(retrieved_urls: list[str], expected_urls: list[str]) -> float:
    """Return 1/rank of the first expected URL found, or 0 if none found."""
    for rank, url in enumerate(retrieved_urls, start=1):
        if any(url.startswith(exp) or exp.startswith(url) for exp in expected_urls):
            return 1.0 / rank
    return 0.0


def evaluate(cfg: dict, questions: list[dict], top_k: int, category: str | None = None) -> None:
    vs = cfg["vector_store"]
    embed_model = cfg["embedding"]["model"]

    client = chromadb.HttpClient(host=vs["chroma_host"], port=vs["chroma_port"])
    collection = client.get_or_create_collection(vs["collection_name"])

    hits = 0
    mrr_sum = 0.0
    results = []

    cat_label = f"  category={category}" if category else ""
    print(f"Evaluating {len(questions)} questions  (top-k={top_k}, deduped by URL{cat_label})\n")
    print(f"{'─' * 70}")

    for q in questions:
        question = q["question"]
        expected = q["expected_urls"]

        embedding = embed(question, embed_model)
        response = collection.query(
            query_embeddings=[embedding],
            n_results=top_k * 3,  # fetch extra so dedup still yields top_k
            include=["metadatas", "distances"],
        )

        metadatas, distances = deduplicate_by_url(
            response["metadatas"][0], response["distances"][0]
        )
        retrieved_urls = [m["url"] for m in metadatas[:top_k]]
        rr = reciprocal_rank(retrieved_urls, expected)
        hit = rr > 0

        hits += int(hit)
        mrr_sum += rr

        cat = q.get("category", "")
        cat_tag = f" [{cat}]" if cat else ""
        status = "PASS" if hit else "FAIL"
        print(f"[{status}]{cat_tag}  {question}")
        if not hit:
            print(f"  expected:  {expected}")
            print(f"  retrieved: {retrieved_urls[:3]}")
        results.append({"question": question, "hit": hit, "rr": rr})

    n = len(questions)
    print(f"\n{'─' * 70}")
    print(f"Hit@{top_k}:  {hits}/{n}  ({100 * hits / n:.0f}%)")
    print(f"MRR:     {mrr_sum / n:.3f}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--category", choices=["answerable", "partial", "gap"],
                        help="Only evaluate questions of this category")
    args = parser.parse_args()

    cfg = load_config(args.config)
    questions = load_questions(args.questions, args.category)
    if not questions:
        print(f"No questions found{f' for category={args.category}' if args.category else ''}.")
        return
    evaluate(cfg, questions, args.top_k, args.category)


if __name__ == "__main__":
    main()
