import json
import re
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


def normalize(text):
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())


ranks_without = []
ranks_with = []
unchanged_ok = 0
unchanged_total = 0
details = []

for case in cases:
    rewritten = rewrite_query(case["history"], case["question"])
    entry = {"question": case["question"], "rewritten": rewritten}

    print("Question:", case["question"])
    print("  Rewritten:", rewritten)

    if case.get("expected_file"):
        rank_without = find_rank(case["question"], case)
        rank_with = find_rank(rewritten, case)
        ranks_without.append(rank_without)
        ranks_with.append(rank_with)
        entry["rank_without_rewrite"] = rank_without
        entry["rank_with_rewrite"] = rank_with
        print("  Rank without rewriting:", rank_without, "| with rewriting:", rank_with)

    if case.get("expect_unchanged"):
        same = normalize(rewritten) == normalize(case["question"])
        unchanged_total += 1
        unchanged_ok += int(same)
        entry["kept_unchanged"] = same
        print("  Kept unchanged (expected):", same)

    details.append(entry)

without = summarize(ranks_without)
with_rewrite = summarize(ranks_with)

print()
print("Retrieval cases:", len(ranks_with))
print("WITHOUT rewriting:", without)
print("WITH rewriting:   ", with_rewrite)
print(f"Topic changes kept unchanged: {unchanged_ok}/{unchanged_total}")

with open(f"eval_results_{LABEL}.json", "w", encoding="utf-8") as f:
    json.dump(
        {
            "without_rewrite": without,
            "with_rewrite": with_rewrite,
            "kept_unchanged": f"{unchanged_ok}/{unchanged_total}",
            "details": details,
        },
        f,
        indent=2,
    )
print(f"Saved eval_results_{LABEL}.json")