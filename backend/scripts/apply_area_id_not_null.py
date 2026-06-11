#!/usr/bin/env python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from core.database import engine

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE apartados ALTER COLUMN area_id SET NOT NULL"))

with engine.connect() as conn:
    nullable = conn.execute(
        text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'apartados'
              AND column_name = 'area_id'
            """
        )
    ).scalar()
    print("is_nullable:", nullable)
