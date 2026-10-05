import json
import sys

from chat import rewrite_query
from database import SessionLocal
from search import search_chunks

WORKSPACE_ID = int(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else "followup"
K = 5

with open("followup_questions.json", encoding="utf-8") as f:
    cases = json.load(f)

db = SessionLocal()


def find_rank(query, case):
    results = search_chunks(db, WORKSPACE_ID, query, limit=K, mode="rerank")
    for i, r in enumerate(results):
        if (
            r["filename"] == case["expected_file"]
            and case["answer_text"].lower() in r["content"].lower()
        ):
            return i + 1
    return None


def summarize(ranks):
    total = len(ranks)
    return {
        "hit@1": round(sum(1 for r in ranks if r == 1) / total, 3),
        f"hit@{K}": round(sum(1 for r in ranks if r is not None) / total, 3),
        "mrr": round(sum(1 / r for r in ranks if r is not None) / total, 3),
    }


ranks_without = []
ranks_with = []
details = []

for case in cases:
    rewritten = rewrite_query(case["history"], case["question"])
    rank_without = find_rank(case["question"], case)
    rank_with = find_rank(rewritten, case)

    ranks_without.append(rank_without)
    ranks_with.append(rank_with)
    details.append(
        {
            "question": case["question"],
            "rewritten": rewritten,
            "rank_without_rewrite": rank_without,
            "rank_with_rewrite": rank_with,
        }
    )

    print("Follow-up:", case["question"])
    print("  Rewritten:", rewritten)
    print("  Rank without rewriting:", rank_without, "| with rewriting:", rank_with)

without = summarize(ranks_without)
with_rewrite = summarize(ranks_with)

print()
print("Cases:", len(cases))
print("WITHOUT rewriting:", without)
print("WITH rewriting:   ", with_rewrite)

with open(f"eval_results_{LABEL}.json", "w", encoding="utf-8") as f:
    json.dump(
        {"without_rewrite": without, "with_rewrite": with_rewrite, "details": details},
        f,
        indent=2,
    )
print(f"Saved eval_results_{LABEL}.json")
