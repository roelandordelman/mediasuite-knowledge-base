"""
Interactively add test questions to test_questions.yaml.

For each question, runs a live retrieval query so you can see what the
index actually returns and pick URLs from the results.

Usage:
    python evaluate/add_question.py
    python evaluate/add_question.py --config config.yaml
"""

import argparse
import json
from pathlib import Path

import chromadb
import ollama
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
QUESTIONS_PATH = Path(__file__).parent / "test_questions.yaml"

CATEGORIES = ["answerable", "partial", "gap"]
CATEGORY_HINTS = {
    "answerable": "content exists, URL known — should always PASS",
    "partial":    "content exists but spread across pages or implicit — may FAIL",
    "gap":        "content does not exist in the KB yet — should always FAIL",
}


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def retrieve(question: str, cfg: dict, top_k: int = 7) -> list[dict]:
    vs = cfg["vector_store"]
    client = chromadb.HttpClient(host=vs["chroma_host"], port=vs["chroma_port"])
    collection = client.get_or_create_collection(vs["collection_name"])

    emb = ollama.embed(model=cfg["embedding"]["model"], input=[question])["embeddings"][0]
    results = collection.query(
        query_embeddings=[emb],
        n_results=top_k * 3,
        include=["metadatas", "distances"],
    )

    seen: dict[str, tuple[dict, float]] = {}
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        url = meta["url"]
        if url not in seen or dist < seen[url][1]:
            seen[url] = (meta, dist)

    deduped = sorted(seen.values(), key=lambda x: x[1])[:top_k]
    return [{"url": m["url"], "title": m["title"], "score": round(1 - d, 3)}
            for m, d in deduped]


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ").strip() or default


def append_question(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n  - question: {json.dumps(entry['question'])}\n")
        f.write(f"    category: {entry['category']}\n")
        if entry["expected_urls"]:
            f.write("    expected_urls:\n")
            for url in entry["expected_urls"]:
                f.write(f"      - {url}\n")
        if entry.get("notes"):
            f.write(f"    notes: {json.dumps(entry['notes'])}\n")


def add_one(cfg: dict) -> bool:
    print()
    question = prompt("Question")
    if not question:
        return False

    print("\nRetrieving top results…")
    try:
        hits = retrieve(question, cfg)
        print(f"\nTop {len(hits)} results:")
        for i, h in enumerate(hits, 1):
            print(f"  {i}. score={h['score']}  {h['url']}")
            print(f"       {h['title']}")
    except Exception as e:
        print(f"  (retrieval failed: {e} — continuing without preview)")
        hits = []

    print()
    print("Categories:")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"  {i}. {cat} — {CATEGORY_HINTS[cat]}")
    cat_input = prompt("Category (name or number)", "answerable")
    if cat_input.isdigit() and 1 <= int(cat_input) <= len(CATEGORIES):
        category = CATEGORIES[int(cat_input) - 1]
    elif cat_input in CATEGORIES:
        category = cat_input
    else:
        print(f"  Unknown category '{cat_input}', defaulting to 'answerable'")
        category = "answerable"

    expected_urls = []
    if category != "gap":
        print("\nExpected URLs (one per line, empty line to finish).")
        print("Enter a number to use a result URL from above, or paste a full URL:")
        while True:
            raw = input("  URL: ").strip()
            if not raw:
                break
            if raw.isdigit() and 1 <= int(raw) <= len(hits):
                expected_urls.append(hits[int(raw) - 1]["url"])
                print(f"  → {expected_urls[-1]}")
            elif raw.startswith("http"):
                expected_urls.append(raw)
            else:
                print("  (enter a number, a URL starting with http, or leave empty to finish)")

    notes = prompt("Notes (optional)")

    entry = {
        "question": question,
        "category": category,
        "expected_urls": expected_urls,
        "notes": notes,
    }

    print(f"\nAdding: [{category}] {question!r}")
    if expected_urls:
        for u in expected_urls:
            print(f"  → {u}")
    append_question(QUESTIONS_PATH, entry)
    print("Saved.")

    again = prompt("\nAdd another question? (y/n)", "y")
    return again.lower().startswith("y")


def main():
    parser = argparse.ArgumentParser(description="Add test questions interactively")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    cfg = load_config(args.config)
    print(f"Adding questions to: {QUESTIONS_PATH}")
    print("Press Enter with no question to quit.")

    while add_one(cfg):
        pass

    print("\nDone.")


if __name__ == "__main__":
    main()
