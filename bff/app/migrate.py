"""Apply bff/migrations/*.sql in filename order, once each.

Applied filenames are recorded in schema_migrations so re-running is safe.

    uv run python -m app.migrate
"""

from pathlib import Path

from sqlalchemy import text

from .db import get_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run() -> list[str]:
    engine = get_engine()
    applied: list[str] = []

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            create table if not exists schema_migrations (
                filename   text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        done = {row[0] for row in conn.execute(text("select filename from schema_migrations"))}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        with engine.begin() as conn:
            # One transaction per file: a failing file leaves nothing half-applied.
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
            conn.execute(
                text("insert into schema_migrations (filename) values (:filename)"),
                {"filename": path.name},
            )
        applied.append(path.name)

    return applied


if __name__ == "__main__":
    names = run()
    print("applied:", ", ".join(names) if names else "nothing, already up to date")
