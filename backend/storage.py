"""Small durable repository; no startup seeding or global open connections."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS analyses_issue ON analyses(issue_id, created_at);
                CREATE TABLE IF NOT EXISTS simulations (
                    id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
                    analysis_id TEXT NOT NULL REFERENCES analyses(id),
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS simulations_issue ON simulations(issue_id, created_at);
                CREATE TABLE IF NOT EXISTS topology_links (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS identifications (id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id), payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def issues(self):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute(
                "SELECT payload FROM issues ORDER BY created_at DESC, id DESC"
            )]

    def issue(self, issue_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM issues WHERE id=?", (issue_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def add_issue(self, issue: dict):
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO issues VALUES (?, ?, ?)",
                         (issue["id"], issue["createdAt"], json.dumps(issue, ensure_ascii=False)))
        return self.issue(issue["id"])

    def update_status(self, issue_id: str, status: str):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM issues WHERE id=?", (issue_id,)).fetchone()
            if not row:
                return None
            issue = json.loads(row[0])
            issue["status"] = status
            conn.execute("UPDATE issues SET payload=? WHERE id=?",
                         (json.dumps(issue, ensure_ascii=False), issue_id))
            return issue

    def add_analysis(self, analysis: dict):
        with self.connect() as conn:
            conn.execute("INSERT INTO analyses VALUES (?, ?, ?, ?)",
                         (analysis["id"], analysis["issueId"], analysis["createdAt"],
                          json.dumps(analysis, ensure_ascii=False)))
        return analysis

    def analysis(self, issue_id: str, analysis_id: str | None = None):
        with self.connect() as conn:
            if analysis_id:
                row = conn.execute("SELECT payload FROM analyses WHERE issue_id=? AND id=?",
                                   (issue_id, analysis_id)).fetchone()
            else:
                row = conn.execute("SELECT payload FROM analyses WHERE issue_id=? "
                                   "ORDER BY created_at DESC, id DESC LIMIT 1", (issue_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def add_simulation(self, simulation: dict):
        with self.connect() as conn:
            conn.execute("INSERT INTO simulations VALUES (?, ?, ?, ?, ?)",
                         (simulation["id"], simulation["issueId"], simulation["analysisId"],
                          simulation["createdAt"], json.dumps(simulation, ensure_ascii=False)))
        return simulation

    def simulations(self, issue_id: str):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute(
                "SELECT payload FROM simulations WHERE issue_id=? ORDER BY created_at DESC, id DESC",
                (issue_id,))]

    def update_location(self, issue_id, asset_id, detail):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM issues WHERE id=?', (issue_id,)).fetchone()
            if not row:
                return None
            issue = json.loads(row[0])
            issue.update(assetId=asset_id, locationDetail=detail, locationBasis='human-selected')
            issue['locationRevision'] = issue.get('locationRevision', 0) + 1
            conn.execute('UPDATE issues SET payload=? WHERE id=?', (json.dumps(issue, ensure_ascii=False), issue_id))
            return issue

    def links(self):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM topology_links ORDER BY id')]

    def put_link(self, link):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO topology_links VALUES (?,?)', (link['id'], json.dumps(link, ensure_ascii=False)))
        return link

    def delete_link(self, link_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM topology_links WHERE id=?', (link_id,))

    def add_identification(self, result):
        with self.connect() as conn:
            conn.execute('INSERT INTO identifications VALUES (?,?,?)', (result['id'], result['issueId'], json.dumps(result, ensure_ascii=False)))
        return result

    def identifications(self, issue_id):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM identifications WHERE issue_id=? ORDER BY rowid DESC', (issue_id,))]
