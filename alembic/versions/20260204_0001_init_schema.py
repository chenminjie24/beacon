"""initial relay schema"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260204_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in _load_sql_statements("sql/001_init.sql"):
        op.execute(statement)


def downgrade() -> None:
    # Reverse order keeps foreign-key dependencies valid.
    statements = [
        "DROP TABLE IF EXISTS request_nonces",
        "DROP TABLE IF EXISTS audit_events",
        "DROP TABLE IF EXISTS agent_heartbeats",
        "DROP TABLE IF EXISTS fills",
        "DROP TABLE IF EXISTS orders",
        "DROP TABLE IF EXISTS execution_tasks",
        "DROP TABLE IF EXISTS signals",
    ]
    for statement in statements:
        op.execute(statement)


def _load_sql_statements(relative_path: str) -> list[str]:
    root = Path(__file__).resolve().parents[2]
    sql_path = root / relative_path
    raw = sql_path.read_text(encoding="utf-8")
    statements: list[str] = []
    buffer: list[str] = []

    for line in raw.splitlines():
        if line.strip().startswith("--"):
            continue
        buffer.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buffer).strip()
            if stmt:
                statements.append(stmt)
            buffer = []

    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements
