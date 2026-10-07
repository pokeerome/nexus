import json
import sys
import time

import httpx
from sqlalchemy import select

from database import SessionLocal
from models import Membership
from security import create_access_token

WORKSPACE_ID = int(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else "agent"
BASE_URL = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000"
QUESTIONS_FILE = sys.argv[4] if len(sys.argv) > 4 else "agent_questions.json"

NOT_FOUND_PHRASES = [
    "could not find", "couldn't find", "cannot find", "can't find",
    "do not contain", "does not contain", "do not provide", "does not provide",
    "no information", "not mention", "not specified", "do not have",
    "don't have", "not available", "not in the documents", "not included",
]

with open(QUESTIONS_FILE, encoding="utf-8") as f:
    cases = json.load(f)

# Make a login token for the owner of this workspace (this script runs on your computer)
db = SessionLocal()
membership = db.scalar(
    select(Membership).where(Membership.workspace_id == WORKSPACE_ID).order_by(Membership.id)
)
if membership is None:
    sys.exit(f"No members found for workspace {WORKSPACE_ID}")
headers = {"Authorization": f"Bearer {create_access_token(membership.user_id)}"}
url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/agent"


def ask(question):
    answer, calls, error = "", 0, None
    started = time.time()
    try:
        with httpx.stream(
            "POST", url, headers=headers, json={"question": question, "history": []}, timeout=180
        ) as r:
            if r.status_code != 200:
                return "", 0, f"HTTP {r.status_code}", time.time() - started
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event["type"] == "tool_call":
                    calls += 1
                elif event["type"] == "token":
                    answer += event["data"]
                elif event["type"] == "error":
                    error = event["data"]
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return answer, calls, error, time.time() - started


def is_correct(case, answer):
    text = answer.lower()
    if case.get("not_found"):
        return any(p in text for p in NOT_FOUND_PHRASES)
    return all(any(alt.lower() in text for alt in group) for group in case["facts"])


results = []
by_kind = {}
for case in cases:
    answer, calls, error, seconds = ask(case["question"])
    ok = error is None and is_correct(case, answer)
    results.append(
        {
            "question": case["question"],
            "kind": case["kind"],
            "correct": ok,
            "tool_calls": calls,
            "seconds": round(seconds, 1),
            "error": error,
            "answer": answer,
        }
    )
    by_kind.setdefault(case["kind"], []).append(ok)
    print(("PASS" if ok else "FAIL"), f"| {calls} tool calls | {seconds:.1f}s |", case["question"])
    if not ok:
        print("   ->", (error or answer)[:300].replace("\n", " "))

total = len(results)
correct = sum(r["correct"] for r in results)
summary = {
    "label": LABEL,
    "questions": total,
    "correct": correct,
    "accuracy": round(correct / total, 3),
    "avg_tool_calls": round(sum(r["tool_calls"] for r in results) / total, 2),
    "avg_seconds": round(sum(r["seconds"] for r in results) / total, 1),
    "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in by_kind.items()},
}
print()
print(json.dumps(summary, indent=2))

with open(f"eval_results_{LABEL}.json", "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "details": results}, f, indent=2, ensure_ascii=False)
print(f"Saved eval_results_{LABEL}.json")