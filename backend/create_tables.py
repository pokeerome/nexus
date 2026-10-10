"""Sets up an empty database: the vector extension, all tables, and the keyword-search column.

Safe to run again: every step uses IF NOT EXISTS.
"""
from sqlalchemy import text

import models  # noqa: F401  (this import tells SQLAlchemy about the tables)
from database import Base, engine

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

print("Tables created")