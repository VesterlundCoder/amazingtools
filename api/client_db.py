"""client_db.py — SQLAlchemy persistence for the Amazing Client module.

Uses DATABASE_URL (PostgreSQL on Railway) or falls back to SQLite locally.
This is the critical fix: the old sqlite3 version lost all data on every
Railway restart because the container filesystem is ephemeral.
"""
from __future__ import annotations
import json, os, uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

DB_PATH = os.environ.get("DB_PATH", "jobs.db")
_DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///./{DB_PATH}")
if _DB_URL.startswith("postgres://"):
    _DB_URL = _DB_URL.replace("postgres://", "postgresql://", 1)
_IS_SQLITE = _DB_URL.startswith("sqlite")

if _IS_SQLITE:
    _engine = create_engine(
        _DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
else:
    _engine = create_engine(_DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_add_column(conn, table: str, col: str, typedef: str) -> None:
    """Idempotent ADD COLUMN — works for both SQLite and PostgreSQL."""
    try:
        if _IS_SQLITE:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
        else:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}"))
    except Exception:
        pass


def init_client_db():
    with _engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ac_customers (
                id             TEXT PRIMARY KEY,
                company_name   TEXT NOT NULL,
                primary_domain TEXT DEFAULT '',
                industry       TEXT DEFAULT '',
                location       TEXT DEFAULT '',
                markets        TEXT DEFAULT '["SE"]',
                languages      TEXT DEFAULT '["sv"]',
                competitors    TEXT DEFAULT '[]',
                goals          TEXT DEFAULT '[]',
                service_mode   TEXT DEFAULT 'ADVISORY',
                status         TEXT DEFAULT 'ONBOARDING',
                notes          TEXT DEFAULT '',
                pinned_tools   TEXT DEFAULT '[]',
                created_at     TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ac_tasks (
                id          TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'OPEN',
                impact      TEXT DEFAULT 'MEDIUM',
                owner_type  TEXT DEFAULT 'HUMAN',
                module_id   TEXT DEFAULT '',
                due_date    TEXT DEFAULT '',
                created_at  TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ac_insights (
                id           TEXT PRIMARY KEY,
                customer_id  TEXT NOT NULL,
                module_id    TEXT DEFAULT '',
                run_id       TEXT DEFAULT '',
                title        TEXT NOT NULL,
                body         TEXT DEFAULT '',
                severity     TEXT DEFAULT 'MEDIUM',
                category     TEXT DEFAULT '',
                status       TEXT DEFAULT 'OPEN',
                impact_score INTEGER DEFAULT 0,
                created_at   TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ac_comments (
                id          TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                target_type TEXT DEFAULT 'customer',
                target_id   TEXT DEFAULT '',
                body        TEXT NOT NULL,
                pinned      INTEGER DEFAULT 0,
                created_at  TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ac_runs (
                id          TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                job_id      TEXT DEFAULT '',
                module_id   TEXT DEFAULT '',
                module_name TEXT DEFAULT '',
                status      TEXT DEFAULT 'QUEUED',
                summary     TEXT DEFAULT '',
                created_at  TEXT
            )
        """))
        # Idempotent migrations for existing tables
        _safe_add_column(conn, "ac_customers", "pinned_tools", "TEXT DEFAULT '[]'")
        _safe_add_column(conn, "ac_customers", "location",     "TEXT DEFAULT ''")


# ── Customers ────────────────────────────────────────────────────────────────

def _row_to_customer(row) -> dict:
    d = dict(row)
    for f in ("markets", "languages", "competitors", "goals", "pinned_tools"):
        try:
            d[f] = json.loads(d[f] or "[]")
        except Exception:
            d[f] = []
    return d


def list_customers() -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM ac_customers ORDER BY created_at DESC")
        ).mappings().fetchall()
    return [_row_to_customer(r) for r in rows]


def get_customer(cid: str) -> dict | None:
    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM ac_customers WHERE id=:id"), {"id": cid}
        ).mappings().fetchone()
    return _row_to_customer(row) if row else None


def create_customer(data: dict) -> dict:
    cid = str(uuid.uuid4())
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO ac_customers
               (id,company_name,primary_domain,industry,location,markets,languages,
                competitors,goals,service_mode,status,notes,created_at)
               VALUES (:id,:cn,:pd,:ind,:loc,:mkt,:lng,:comp,:goals,:sm,:st,:notes,:ts)"""),
            {
                "id":    cid,
                "cn":    data.get("company_name", ""),
                "pd":    data.get("primary_domain", ""),
                "ind":   data.get("industry", ""),
                "loc":   data.get("location", ""),
                "mkt":   json.dumps(data.get("markets", ["SE"])),
                "lng":   json.dumps(data.get("languages", ["sv"])),
                "comp":  json.dumps(data.get("competitors", [])),
                "goals": json.dumps(data.get("goals", [])),
                "sm":    data.get("service_mode", "ADVISORY"),
                "st":    data.get("status", "ONBOARDING"),
                "notes": data.get("notes", ""),
                "ts":    _now(),
            },
        )
    return get_customer(cid)


def update_customer(cid: str, data: dict) -> dict | None:
    fields, vals = [], {}
    for key in ("company_name", "primary_domain", "industry", "location",
                "service_mode", "status", "notes"):
        if key in data:
            fields.append(f"{key}=:{key}")
            vals[key] = data[key]
    for key in ("markets", "languages", "competitors", "goals", "pinned_tools"):
        if key in data:
            fields.append(f"{key}=:{key}")
            vals[key] = json.dumps(data[key])
    if not fields:
        return get_customer(cid)
    vals["cid"] = cid
    with _engine.begin() as conn:
        conn.execute(text(f"UPDATE ac_customers SET {','.join(fields)} WHERE id=:cid"), vals)
    return get_customer(cid)


def delete_customer(cid: str):
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM ac_customers WHERE id=:id"), {"id": cid})


def toggle_pinned_tool(cid: str, tool_id: str) -> dict | None:
    c = get_customer(cid)
    if not c:
        return None
    tools = c.get("pinned_tools", [])
    if tool_id in tools:
        tools = [t for t in tools if t != tool_id]
    else:
        tools.append(tool_id)
    return update_customer(cid, {"pinned_tools": tools})


# ── Tasks ────────────────────────────────────────────────────────────────────

def list_tasks(customer_id: str) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM ac_tasks WHERE customer_id=:cid ORDER BY created_at DESC"),
            {"cid": customer_id},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def create_task(customer_id: str, data: dict) -> dict:
    tid = str(uuid.uuid4())
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO ac_tasks
               (id,customer_id,title,description,status,impact,owner_type,module_id,due_date,created_at)
               VALUES (:id,:cid,:title,:desc,:st,:imp,:ow,:mid,:dd,:ts)"""),
            {
                "id":    tid,
                "cid":   customer_id,
                "title": data.get("title", ""),
                "desc":  data.get("description", ""),
                "st":    data.get("status", "OPEN"),
                "imp":   data.get("impact", "MEDIUM"),
                "ow":    data.get("owner_type", "HUMAN"),
                "mid":   data.get("module_id", ""),
                "dd":    data.get("due_date", ""),
                "ts":    _now(),
            },
        )
    with _engine.connect() as conn:
        return dict(conn.execute(
            text("SELECT * FROM ac_tasks WHERE id=:id"), {"id": tid}
        ).mappings().fetchone())


def update_task(tid: str, data: dict) -> dict | None:
    fields, vals = [], {}
    for key in ("title", "description", "status", "impact", "owner_type", "due_date"):
        if key in data:
            fields.append(f"{key}=:{key}")
            vals[key] = data[key]
    if not fields:
        with _engine.connect() as conn:
            r = conn.execute(
                text("SELECT * FROM ac_tasks WHERE id=:id"), {"id": tid}
            ).mappings().fetchone()
        return dict(r) if r else None
    vals["tid"] = tid
    with _engine.begin() as conn:
        conn.execute(text(f"UPDATE ac_tasks SET {','.join(fields)} WHERE id=:tid"), vals)
    with _engine.connect() as conn:
        r = conn.execute(
            text("SELECT * FROM ac_tasks WHERE id=:id"), {"id": tid}
        ).mappings().fetchone()
    return dict(r) if r else None


# ── Insights ─────────────────────────────────────────────────────────────────

def list_insights(customer_id: str) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM ac_insights WHERE customer_id=:cid ORDER BY created_at DESC"),
            {"cid": customer_id},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def create_insight(customer_id: str, data: dict) -> dict:
    iid = str(uuid.uuid4())
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO ac_insights
               (id,customer_id,module_id,run_id,title,body,severity,category,status,impact_score,created_at)
               VALUES (:id,:cid,:mid,:rid,:title,:body,:sev,:cat,:st,:score,:ts)"""),
            {
                "id":    iid,
                "cid":   customer_id,
                "mid":   data.get("module_id", ""),
                "rid":   data.get("run_id", ""),
                "title": data.get("title", ""),
                "body":  data.get("body", ""),
                "sev":   data.get("severity", "MEDIUM"),
                "cat":   data.get("category", ""),
                "st":    data.get("status", "OPEN"),
                "score": data.get("impact_score", 0),
                "ts":    _now(),
            },
        )
    with _engine.connect() as conn:
        return dict(conn.execute(
            text("SELECT * FROM ac_insights WHERE id=:id"), {"id": iid}
        ).mappings().fetchone())


def update_insight_status(iid: str, status: str) -> dict | None:
    with _engine.begin() as conn:
        conn.execute(
            text("UPDATE ac_insights SET status=:st WHERE id=:id"), {"st": status, "id": iid}
        )
    with _engine.connect() as conn:
        r = conn.execute(
            text("SELECT * FROM ac_insights WHERE id=:id"), {"id": iid}
        ).mappings().fetchone()
    return dict(r) if r else None


# ── Comments ─────────────────────────────────────────────────────────────────

def list_comments(customer_id: str, target_type: str | None = None) -> list[dict]:
    if target_type:
        with _engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM ac_comments WHERE customer_id=:cid AND target_type=:tt "
                     "ORDER BY pinned DESC, created_at DESC"),
                {"cid": customer_id, "tt": target_type},
            ).mappings().fetchall()
    else:
        with _engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM ac_comments WHERE customer_id=:cid "
                     "ORDER BY pinned DESC, created_at DESC"),
                {"cid": customer_id},
            ).mappings().fetchall()
    return [dict(r) for r in rows]


def create_comment(customer_id: str, data: dict) -> dict:
    cid = str(uuid.uuid4())
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO ac_comments
               (id,customer_id,target_type,target_id,body,pinned,created_at)
               VALUES (:id,:cid,:tt,:tid,:body,0,:ts)"""),
            {
                "id":   cid,
                "cid":  customer_id,
                "tt":   data.get("target_type", "customer"),
                "tid":  data.get("target_id", ""),
                "body": data.get("body", ""),
                "ts":   _now(),
            },
        )
    with _engine.connect() as conn:
        return dict(conn.execute(
            text("SELECT * FROM ac_comments WHERE id=:id"), {"id": cid}
        ).mappings().fetchone())


def toggle_pin(comment_id: str) -> dict | None:
    with _engine.begin() as conn:
        conn.execute(
            text("UPDATE ac_comments SET pinned = CASE WHEN pinned=1 THEN 0 ELSE 1 END WHERE id=:id"),
            {"id": comment_id},
        )
    with _engine.connect() as conn:
        r = conn.execute(
            text("SELECT * FROM ac_comments WHERE id=:id"), {"id": comment_id}
        ).mappings().fetchone()
    return dict(r) if r else None


# ── Runs ─────────────────────────────────────────────────────────────────────

def list_runs(customer_id: str) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM ac_runs WHERE customer_id=:cid ORDER BY created_at DESC"),
            {"cid": customer_id},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def create_run_link(customer_id: str, data: dict) -> dict:
    rid = str(uuid.uuid4())
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO ac_runs
               (id,customer_id,job_id,module_id,module_name,status,summary,created_at)
               VALUES (:id,:cid,:jid,:mid,:mn,:st,:sum,:ts)"""),
            {
                "id":  rid,
                "cid": customer_id,
                "jid": data.get("job_id", ""),
                "mid": data.get("module_id", ""),
                "mn":  data.get("module_name", ""),
                "st":  data.get("status", "QUEUED"),
                "sum": data.get("summary", ""),
                "ts":  _now(),
            },
        )
    with _engine.connect() as conn:
        return dict(conn.execute(
            text("SELECT * FROM ac_runs WHERE id=:id"), {"id": rid}
        ).mappings().fetchone())


def update_run_link(rid: str, status: str, summary: str = "") -> dict | None:
    with _engine.begin() as conn:
        conn.execute(
            text("UPDATE ac_runs SET status=:st, summary=:sum WHERE id=:id"),
            {"st": status, "sum": summary, "id": rid},
        )
    with _engine.connect() as conn:
        r = conn.execute(
            text("SELECT * FROM ac_runs WHERE id=:id"), {"id": rid}
        ).mappings().fetchone()
    return dict(r) if r else None


# ── Summary stats ─────────────────────────────────────────────────────────────

def get_customer_stats(customer_id: str) -> dict:
    with _engine.connect() as conn:
        open_tasks = conn.execute(
            text("SELECT COUNT(*) FROM ac_tasks "
                 "WHERE customer_id=:cid AND status NOT IN ('DONE','CANCELLED')"),
            {"cid": customer_id},
        ).scalar()
        open_insights = conn.execute(
            text("SELECT COUNT(*) FROM ac_insights WHERE customer_id=:cid AND status='OPEN'"),
            {"cid": customer_id},
        ).scalar()
        high_insights = conn.execute(
            text("SELECT COUNT(*) FROM ac_insights "
                 "WHERE customer_id=:cid AND severity='HIGH' AND status='OPEN'"),
            {"cid": customer_id},
        ).scalar()
        total_runs = conn.execute(
            text("SELECT COUNT(*) FROM ac_runs WHERE customer_id=:cid"),
            {"cid": customer_id},
        ).scalar()
    return {
        "open_tasks":    open_tasks or 0,
        "open_insights": open_insights or 0,
        "high_insights": high_insights or 0,
        "total_runs":    total_runs or 0,
    }
