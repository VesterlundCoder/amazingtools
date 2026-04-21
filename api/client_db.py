"""client_db.py — SQLite persistence for the Amazing Client module."""
from __future__ import annotations
import json, os, sqlite3, uuid
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "jobs.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(db: sqlite3.Connection):
    """Apply any missing column migrations to existing tables."""
    migrations = [
        ("ac_customers", "pinned_tools", "TEXT DEFAULT '[]'"),
    ]
    cur = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    for table, col, typedef in migrations:
        if table not in tables:
            continue
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")


def init_client_db():
    with _conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS ac_customers (
            id           TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            primary_domain TEXT DEFAULT '',
            industry     TEXT DEFAULT '',
            markets      TEXT DEFAULT '["SE"]',
            languages    TEXT DEFAULT '["sv"]',
            competitors  TEXT DEFAULT '[]',
            goals        TEXT DEFAULT '[]',
            service_mode TEXT DEFAULT 'ADVISORY',
            status       TEXT DEFAULT 'ONBOARDING',
            notes        TEXT DEFAULT '',
            pinned_tools TEXT DEFAULT '[]',
            created_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS ac_tasks (
            id           TEXT PRIMARY KEY,
            customer_id  TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT DEFAULT '',
            status       TEXT DEFAULT 'OPEN',
            impact       TEXT DEFAULT 'MEDIUM',
            owner_type   TEXT DEFAULT 'HUMAN',
            module_id    TEXT DEFAULT '',
            due_date     TEXT DEFAULT '',
            created_at   TEXT,
            FOREIGN KEY (customer_id) REFERENCES ac_customers(id)
        );
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
            created_at   TEXT,
            FOREIGN KEY (customer_id) REFERENCES ac_customers(id)
        );
        CREATE TABLE IF NOT EXISTS ac_comments (
            id           TEXT PRIMARY KEY,
            customer_id  TEXT NOT NULL,
            target_type  TEXT DEFAULT 'customer',
            target_id    TEXT DEFAULT '',
            body         TEXT NOT NULL,
            pinned       INTEGER DEFAULT 0,
            created_at   TEXT,
            FOREIGN KEY (customer_id) REFERENCES ac_customers(id)
        );
        CREATE TABLE IF NOT EXISTS ac_runs (
            id           TEXT PRIMARY KEY,
            customer_id  TEXT NOT NULL,
            job_id       TEXT DEFAULT '',
            module_id    TEXT DEFAULT '',
            module_name  TEXT DEFAULT '',
            status       TEXT DEFAULT 'QUEUED',
            summary      TEXT DEFAULT '',
            created_at   TEXT,
            FOREIGN KEY (customer_id) REFERENCES ac_customers(id)
        );
        """)
        _migrate(db)


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
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM ac_customers ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_customer(r) for r in rows]


def get_customer(cid: str) -> dict | None:
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM ac_customers WHERE id=?", (cid,)
        ).fetchone()
    return _row_to_customer(row) if row else None


def create_customer(data: dict) -> dict:
    cid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT INTO ac_customers
               (id,company_name,primary_domain,industry,markets,languages,
                competitors,goals,service_mode,status,notes,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid,
                data.get("company_name", ""),
                data.get("primary_domain", ""),
                data.get("industry", ""),
                json.dumps(data.get("markets", ["SE"])),
                json.dumps(data.get("languages", ["sv"])),
                json.dumps(data.get("competitors", [])),
                json.dumps(data.get("goals", [])),
                data.get("service_mode", "ADVISORY"),
                data.get("status", "ONBOARDING"),
                data.get("notes", ""),
                _now(),
            ),
        )
    return get_customer(cid)


def update_customer(cid: str, data: dict) -> dict | None:
    fields, vals = [], []
    for key in ("company_name", "primary_domain", "industry", "service_mode", "status", "notes"):
        if key in data:
            fields.append(f"{key}=?")
            vals.append(data[key])
    for key in ("markets", "languages", "competitors", "goals", "pinned_tools"):
        if key in data:
            fields.append(f"{key}=?")
            vals.append(json.dumps(data[key]))
    if not fields:
        return get_customer(cid)
    vals.append(cid)
    with _conn() as db:
        db.execute(f"UPDATE ac_customers SET {','.join(fields)} WHERE id=?", vals)
    return get_customer(cid)


def delete_customer(cid: str):
    with _conn() as db:
        db.execute("DELETE FROM ac_customers WHERE id=?", (cid,))


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
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM ac_tasks WHERE customer_id=? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_task(customer_id: str, data: dict) -> dict:
    tid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT INTO ac_tasks
               (id,customer_id,title,description,status,impact,owner_type,module_id,due_date,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                tid, customer_id,
                data.get("title", ""),
                data.get("description", ""),
                data.get("status", "OPEN"),
                data.get("impact", "MEDIUM"),
                data.get("owner_type", "HUMAN"),
                data.get("module_id", ""),
                data.get("due_date", ""),
                _now(),
            ),
        )
    with _conn() as db:
        return dict(db.execute("SELECT * FROM ac_tasks WHERE id=?", (tid,)).fetchone())


def update_task(tid: str, data: dict) -> dict | None:
    fields, vals = [], []
    for key in ("title", "description", "status", "impact", "owner_type", "due_date"):
        if key in data:
            fields.append(f"{key}=?")
            vals.append(data[key])
    if not fields:
        with _conn() as db:
            r = db.execute("SELECT * FROM ac_tasks WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None
    vals.append(tid)
    with _conn() as db:
        db.execute(f"UPDATE ac_tasks SET {','.join(fields)} WHERE id=?", vals)
        r = db.execute("SELECT * FROM ac_tasks WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


# ── Insights ─────────────────────────────────────────────────────────────────

def list_insights(customer_id: str) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM ac_insights WHERE customer_id=? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_insight(customer_id: str, data: dict) -> dict:
    iid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT INTO ac_insights
               (id,customer_id,module_id,run_id,title,body,severity,category,status,impact_score,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                iid, customer_id,
                data.get("module_id", ""),
                data.get("run_id", ""),
                data.get("title", ""),
                data.get("body", ""),
                data.get("severity", "MEDIUM"),
                data.get("category", ""),
                data.get("status", "OPEN"),
                data.get("impact_score", 0),
                _now(),
            ),
        )
        return dict(db.execute("SELECT * FROM ac_insights WHERE id=?", (iid,)).fetchone())


def update_insight_status(iid: str, status: str) -> dict | None:
    with _conn() as db:
        db.execute("UPDATE ac_insights SET status=? WHERE id=?", (status, iid))
        r = db.execute("SELECT * FROM ac_insights WHERE id=?", (iid,)).fetchone()
    return dict(r) if r else None


# ── Comments ─────────────────────────────────────────────────────────────────

def list_comments(customer_id: str, target_type: str | None = None) -> list[dict]:
    if target_type:
        with _conn() as db:
            rows = db.execute(
                "SELECT * FROM ac_comments WHERE customer_id=? AND target_type=? ORDER BY pinned DESC, created_at DESC",
                (customer_id, target_type),
            ).fetchall()
    else:
        with _conn() as db:
            rows = db.execute(
                "SELECT * FROM ac_comments WHERE customer_id=? ORDER BY pinned DESC, created_at DESC",
                (customer_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def create_comment(customer_id: str, data: dict) -> dict:
    cid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT INTO ac_comments (id,customer_id,target_type,target_id,body,pinned,created_at)
               VALUES (?,?,?,?,?,0,?)""",
            (cid, customer_id, data.get("target_type", "customer"),
             data.get("target_id", ""), data.get("body", ""), _now()),
        )
        return dict(db.execute("SELECT * FROM ac_comments WHERE id=?", (cid,)).fetchone())


def toggle_pin(comment_id: str) -> dict | None:
    with _conn() as db:
        db.execute(
            "UPDATE ac_comments SET pinned = CASE WHEN pinned=1 THEN 0 ELSE 1 END WHERE id=?",
            (comment_id,),
        )
        r = db.execute("SELECT * FROM ac_comments WHERE id=?", (comment_id,)).fetchone()
    return dict(r) if r else None


# ── Runs ─────────────────────────────────────────────────────────────────────

def list_runs(customer_id: str) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM ac_runs WHERE customer_id=? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_run_link(customer_id: str, data: dict) -> dict:
    rid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT INTO ac_runs (id,customer_id,job_id,module_id,module_name,status,summary,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, customer_id, data.get("job_id", ""),
             data.get("module_id", ""), data.get("module_name", ""),
             data.get("status", "QUEUED"), data.get("summary", ""), _now()),
        )
        return dict(db.execute("SELECT * FROM ac_runs WHERE id=?", (rid,)).fetchone())


def update_run_link(rid: str, status: str, summary: str = "") -> dict | None:
    with _conn() as db:
        db.execute(
            "UPDATE ac_runs SET status=?, summary=? WHERE id=?",
            (status, summary, rid),
        )
        r = db.execute("SELECT * FROM ac_runs WHERE id=?", (rid,)).fetchone()
    return dict(r) if r else None


# ── Summary stats ─────────────────────────────────────────────────────────────

def get_customer_stats(customer_id: str) -> dict:
    with _conn() as db:
        open_tasks = db.execute(
            "SELECT COUNT(*) FROM ac_tasks WHERE customer_id=? AND status NOT IN ('DONE','CANCELLED')",
            (customer_id,),
        ).fetchone()[0]
        open_insights = db.execute(
            "SELECT COUNT(*) FROM ac_insights WHERE customer_id=? AND status='OPEN'",
            (customer_id,),
        ).fetchone()[0]
        high_insights = db.execute(
            "SELECT COUNT(*) FROM ac_insights WHERE customer_id=? AND severity='HIGH' AND status='OPEN'",
            (customer_id,),
        ).fetchone()[0]
        total_runs = db.execute(
            "SELECT COUNT(*) FROM ac_runs WHERE customer_id=?", (customer_id,)
        ).fetchone()[0]
    return {
        "open_tasks":     open_tasks,
        "open_insights":  open_insights,
        "high_insights":  high_insights,
        "total_runs":     total_runs,
    }
