"""Search quality check for CI.

Reads the sample documents in ci_eval/docs, asks the questions in ci_eval/questions.json,
and exits with an error if search gets worse than the limits below.
It uses a clean, empty database and real embeddings (a few thousand tokens, a fraction of a cent).
"""
import json
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).parent / "ci_eval"
K = 5

# Your hybrid search scored Hit@1 0.89, Hit@5 1.00, MRR 0.94 on these questions.
# The limits sit a little below that, so normal small changes pass and real damage fails.
MIN_HIT1 = float(os.getenv("CI_MIN_HIT1", "0.80"))
MIN_HIT5 = float(os.getenv("CI_MIN_HIT5", "0.95"))
MIN_MRR = float(os.getenv("CI_MIN_MRR", "0.88"))


def main() -> int:
    if os.getenv("ALLOW_CI_EVAL") != "1":
        print("Stopped: this script fills the database it connects to with sample data.")
        print("Set ALLOW_CI_EVAL=1 only for a throwaway database (CI does this).")
        return 2
    if not os.getenv("OPENAI_API_KEY"):
        print("Stopped: OPENAI_API_KEY is not set.")
        print("On GitHub: Settings > Secrets and variables > Actions > New repository secret.")
        return 2

    from sqlalchemy import text

    from database import Base, SessionLocal, engine
    from ingest import ingest_document
    from models import Document, Membership, User, Workspace
    from search import search_chunks

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS search_vector tsvector "
                "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS chunks_search_idx ON chunks USING GIN (search_vector)")
        )

    db = SessionLocal()
    user = User(email=f"ci-{uuid.uuid4().hex[:8]}@example.com", hashed_password="not-a-real-hash")
    workspace = Workspace(name="CI search check")
    db.add_all([user, workspace])
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db.commit()

    for path in sorted((HERE / "docs").iterdir()):
        doc = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename=path.name,
            stored_path=str(path),
            size_bytes=path.stat().st_size,
            status="queued",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        ingest_document(db, doc)
        db.refresh(doc)
        if doc.status != "ready":
            print(f"Stopped: could not read {path.name}: {doc.error_message}")
            return 1
    print(f"Read {len(list((HERE / 'docs').iterdir()))} documents.")

    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    hit1 = hit_k = 0
    reciprocal = 0.0
    misses = []
    for q in questions:
        results = search_chunks(db, workspace.id, q["question"], limit=K, mode="hybrid")
        rank = None
        for i, r in enumerate(results):
            if r["filename"] == q["expected_file"] and q["answer_text"].lower() in r["content"].lower():
                rank = i + 1
                break
        if rank == 1:
            hit1 += 1
        if rank is not None:
            hit_k += 1
            reciprocal += 1 / rank
        else:
            misses.append(q["question"])

    total = len(questions)
    scores = {"hit@1": hit1 / total, f"hit@{K}": hit_k / total, "mrr": reciprocal / total}
    limits = {"hit@1": MIN_HIT1, f"hit@{K}": MIN_HIT5, "mrr": MIN_MRR}

    print()
    print(f"{'metric':<8} {'score':>6} {'minimum':>8}")
    failed = []
    for name, value in scores.items():
        ok = value >= limits[name]
        print(f"{name:<8} {value:>6.2f} {limits[name]:>8.2f}  {'ok' if ok else 'TOO LOW'}")
        if not ok:
            failed.append(name)
    for question in misses:
        print("not found in the top 5:", question)

    Path("eval_results_ci.json").write_text(
        json.dumps({"questions": total, "scores": scores, "limits": limits, "misses": misses}, indent=2),
        encoding="utf-8",
    )
    if failed:
        print("\nSearch quality dropped below the limit:", ", ".join(failed))
        return 1
    print("\nSearch quality is fine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())