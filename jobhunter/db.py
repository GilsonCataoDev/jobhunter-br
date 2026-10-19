"""SQLite: vagas vistas, decisão do filtro e status."""
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("JOBHUNTER_DB", os.path.join(os.path.dirname(__file__), "data", "jobs.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    url TEXT,
    description TEXT,
    workplace TEXT,
    kind TEXT,
    published TEXT,
    deadline TEXT,
    tier INTEGER,
    status TEXT NOT NULL DEFAULT 'new',   -- new | rejected | shortlisted | notified
    reason TEXT DEFAULT '',
    warnings TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

-- Fase 2: status de jobs passa a incluir offered | approved | skipped
CREATE TABLE IF NOT EXISTS pending_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    question TEXT NOT NULL,
    qnorm TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',   -- JSON
    reason TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',  -- open | answered
    answer TEXT,
    created TEXT NOT NULL,
    answered_at TEXT,
    UNIQUE(job_id, qnorm)
);
-- Fase 3: cada tentativa do executor (inclusive dry-run)
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,        -- sent | dry_run_ready | pending | already_applied | needs_human | error
    detail TEXT DEFAULT '',
    shot TEXT DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 1,
    at TEXT NOT NULL
);
-- Respostas que o usuário deu a perguntas NÃO sensíveis: reaproveitadas nas próximas vagas.
CREATE TABLE IF NOT EXISTS learned_answers (
    qnorm TEXT PRIMARY KEY,
    answer TEXT NOT NULL,
    created TEXT NOT NULL
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = path or DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def known_status(con):
    return {r["id"]: r["status"] for r in con.execute("SELECT id, status FROM jobs")}


def update_decision(con, job_id, status, reason, warnings, tier):
    con.execute("UPDATE jobs SET status=?, reason=?, warnings=?, tier=?, last_seen=? WHERE id=?",
                (status, reason, warnings, tier, now(), job_id))


def touch(con, job_id):
    con.execute("UPDATE jobs SET last_seen=? WHERE id=?", (now(), job_id))


def insert(con, job, status, reason="", warnings="", tier=None):
    con.execute(
        """INSERT INTO jobs (id, source, title, company, url, description, workplace, kind, published, deadline,
                             tier, status, reason, warnings, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job["id"], job["source"], job["title"], job["company"], job["url"], job["description"], job["workplace"],
         job["kind"], job["published"], job["deadline"], tier, status, reason, warnings, now(), now()),
    )


def set_status(con, job_id, status):
    con.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))


def shortlisted(con):
    return con.execute(
        "SELECT * FROM jobs WHERE status='shortlisted' ORDER BY tier, published DESC").fetchall()


# ---- Fase 2: pendências e respostas aprendidas ----
def get_job(con, job_id):
    return con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def jobs_with_status(con, status, limit=50):
    return con.execute("SELECT * FROM jobs WHERE status=? ORDER BY tier, published DESC LIMIT ?",
                       (status, limit)).fetchall()


def add_pending(con, job_id, question, qnorm, options, reason):
    """Idempotente: a mesma pergunta na mesma vaga não duplica."""
    import json
    con.execute("INSERT OR IGNORE INTO pending_questions (job_id, question, qnorm, options, reason, created) "
                "VALUES (?,?,?,?,?,?)", (job_id, question, qnorm, json.dumps(options, ensure_ascii=False), reason, now()))


def open_pending(con, job_id=None):
    if job_id:
        return con.execute("SELECT * FROM pending_questions WHERE status='open' AND job_id=? ORDER BY id", (job_id,)).fetchall()
    return con.execute("SELECT * FROM pending_questions WHERE status='open' ORDER BY id").fetchall()


def answer_pending(con, pending_id, answer, learn=True):
    """Grava a resposta. Se learn=True, reaproveita em perguntas iguais (nunca para dado sensível: o chamador decide)."""
    row = con.execute("SELECT * FROM pending_questions WHERE id=?", (pending_id,)).fetchone()
    if not row:
        return None
    con.execute("UPDATE pending_questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                (answer, now(), pending_id))
    if learn:
        con.execute("INSERT OR REPLACE INTO learned_answers (qnorm, answer, created) VALUES (?,?,?)",
                    (row["qnorm"], answer, now()))
    return row


def learned(con, qnorm):
    r = con.execute("SELECT answer FROM learned_answers WHERE qnorm=?", (qnorm,)).fetchone()
    return r["answer"] if r else None


# ---- Fase 3: tentativas e limite diário ----
def log_attempt(con, job_id, status, detail="", shot="", dry_run=True):
    con.execute("INSERT INTO attempts (job_id, status, detail, shot, dry_run, at) VALUES (?,?,?,?,?,?)",
                (job_id, status, detail[:500], shot, 1 if dry_run else 0, now()))


def sent_today(con):
    """Envios REAIS de hoje (UTC). Dry-run não conta."""
    hoje = now()[:10]
    return con.execute("SELECT COUNT(*) FROM attempts WHERE status='sent' AND dry_run=0 AND substr(at,1,10)=?",
                       (hoje,)).fetchone()[0]


def approved_ready(con):
    """Aprovadas e SEM pendência aberta, mais antigas primeiro."""
    return con.execute(
        """SELECT j.* FROM jobs j WHERE j.status='approved'
           AND j.source='gupy' AND j.url LIKE '%.gupy.io/%'  -- o robô só sabe o fluxo da Gupy
           AND NOT EXISTS (SELECT 1 FROM pending_questions p WHERE p.job_id=j.id AND p.status='open')
           ORDER BY j.tier, j.published""").fetchall()
