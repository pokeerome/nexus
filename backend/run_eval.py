import json
import sys

from database import SessionLocal
from search import search_chunks

WORKSPACE_ID = int(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else "run"
K = 5
MODE = sys.argv[3] if len(sys.argv) > 3 else "hybrid"

with open("eval_questions.json", encoding="utf-8") as f:
    questions = json.load(f)

db = SessionLocal()
hit_at_1 = 0
hit_at_k = 0
rank_score = 0.0
precision_total = 0.0
log = []

for q in questions:
    results = search_chunks(db, WORKSPACE_ID, q["question"], limit=K, mode=MODE)

    # The right result = a chunk from the expected file that contains the answer text
    rank = None
    for i, r in enumerate(results):
        if (
            r["filename"] == q["expected_file"]
            and q["answer_text"].lower() in r["content"].lower()
        ):
            rank = i + 1
            break

    relevant = sum(
        1
        for r in results
        if r["filename"] == q["expected_file"]
        and q["answer_text"].lower() in r["content"].lower()
    )
    precision_total += relevant / K

    if rank == 1:
        hit_at_1 += 1
    if rank is not None:
        hit_at_k += 1
        rank_score += 1 / rank
        if rank > 1:
            print(f"LOW (rank {rank}):", q["question"])
    else:
        print("MISS:", q["question"], "->", [r["filename"] for r in results])

    log.append(
        {
            "question": q["question"],
            "rank": rank,
            "top_files": [r["filename"] for r in results],
        }
    )

total = len(questions)
summary = {
    "label": LABEL,
    "questions": total,
    f"hit@1": round(hit_at_1 / total, 3),
    f"hit@{K}": round(hit_at_k / total, 3),
    f"p@{K}": round(precision_total / total, 3),
    "mrr": round(rank_score / total, 3),
}

print()
print(f"Questions: {total}")
print(f"Hit@1: {summary['hit@1']:.2f}")
print(f"Hit@{K}: {summary[f'hit@{K}']:.2f}")
print(f"P@{K}: {summary[f'p@{K}']:.2f}")
print(f"MRR: {summary['mrr']:.2f}")

with open(f"eval_results_{LABEL}.json", "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "details": log}, f, indent=2)
print(f"Saved eval_results_{LABEL}.json")