"""db.py — storage backend seam (SQLite for demo, PostgreSQL for production).

The audit trail, case store, and clinical-review store all obtain their
connections here instead of calling sqlite3 directly, so the persistence
backend is a configuration choice rather than a code change.

Backend selection:
  DATABASE_URL unset / "sqlite..."   → SQLite (default; one file per store)
  DATABASE_URL = postgresql://...    → PostgreSQL via psycopg (v3)

The application SQL uses SQLite's "?" placeholder and SQLite DDL. For
PostgreSQL we (1) translate "?" → "%s" on the way to the driver and (2)
translate the small, known set of CREATE TABLE statements to portable DDL
(INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY). The hash-chained
audit append is protected by begin_exclusive(), which maps to BEGIN IMMEDIATE
on SQLite and an EXCLUSIVE table lock on PostgreSQL so concurrent writers
cannot fork the chain.

NOTE: the SQLite path is exercised by the test suite. The PostgreSQL adapter is
structurally complete but must be validated with one integration pass against
the target instance (no Postgres server is available in CI). It is never
imported unless DATABASE_URL points at PostgreSQL.
"""

import os
import re
import sqlite3

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def backend() -> str:
    """Active backend: 'postgresql' or 'sqlite'."""
    if _DATABASE_URL.startswith(("postgres://", "postgresql://")):
        return "postgresql"
    return "sqlite"


def is_postgres() -> bool:
    return backend() == "postgresql"


# ---------------------------------------------------------------------------
# DDL translation (SQLite → PostgreSQL) for the known store schemas
# ---------------------------------------------------------------------------

def portable_ddl(sqlite_ddl: str) -> str:
    """Translate the project's SQLite CREATE TABLE statements to PostgreSQL.

    Scoped to the idioms actually used by the stores — not a general translator.
    """
    ddl = sqlite_ddl
    # Auto-incrementing surrogate key.
    ddl = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
                 "BIGSERIAL PRIMARY KEY", ddl, flags=re.IGNORECASE)
    # Reserved words (e.g. the audit log's "user" column) are already
    # double-quoted in the source schema, which is valid in both backends, so no
    # identifier rewriting is needed here.
    return ddl


# ---------------------------------------------------------------------------
# PostgreSQL connection wrapper — translates "?" placeholders to "%s"
# ---------------------------------------------------------------------------

def _to_pg_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(_to_pg_placeholders(sql), params)
        return self

    def executemany(self, sql, seq):
        self._cur.executemany(_to_pg_placeholders(sql), seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        # Callers needing the generated id should use RETURNING; lastrowid is
        # not portable. Exposed as None so attribute access does not explode.
        return None

    def __iter__(self):
        return iter(self._cur)


class _PgConnection:
    """Minimal sqlite3.Connection-compatible facade over a psycopg connection."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = _PgCursor(self._conn.cursor())
        return cur.execute(sql, params)

    def cursor(self):
        return _PgCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def connect(sqlite_path: str, schema_sql: str | None = None):
    """Return a connection to the active backend, ensuring *schema_sql* exists.

    *sqlite_path* is used only for the SQLite backend; PostgreSQL uses
    DATABASE_URL. The returned object supports the sqlite3-style API the stores
    rely on: .execute(sql, params) → cursor, .commit(), .rollback(), .close().
    """
    if is_postgres():
        import psycopg  # psycopg v3 — only required for the PostgreSQL backend
        conn = psycopg.connect(_DATABASE_URL)
        wrapped = _PgConnection(conn)
        if schema_sql:
            wrapped.execute(portable_ddl(schema_sql))
            wrapped.commit()
        return wrapped

    conn = sqlite3.connect(sqlite_path)
    if schema_sql:
        conn.executescript(schema_sql) if ";" in schema_sql.rstrip().rstrip(";") \
            else conn.execute(schema_sql)
        conn.commit()
    return conn


def begin_exclusive(conn, table: str) -> None:
    """Start a transaction that serialises appenders to *table*.

    SQLite: BEGIN IMMEDIATE (database-level write lock). PostgreSQL: BEGIN then
    LOCK TABLE ... IN EXCLUSIVE MODE. Used by the tamper-evident audit append so
    two writers cannot read the same tail hash and fork the chain.
    """
    if is_postgres():
        conn.execute(f"LOCK TABLE {table} IN EXCLUSIVE MODE")
    else:
        conn.execute("BEGIN IMMEDIATE")
