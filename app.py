"""A small, server-rendered release tracker. State changes are written to SQLite."""
import os
import re
import sqlite3
from contextlib import closing
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import parse_qs

ROOT = Path(__file__).parent
PAGE = Template((ROOT / "index.html").read_text())
CSS = (ROOT / "style.css").read_bytes()
STAGES = ("Source", "Build", "Test", "Deploy", "Verify")
DESCRIPTIONS = ("Review the commit", "Build the image", "Check the release",
                "Roll out to EC2", "Confirm service health")
DB = os.environ.get("TRACKER_DB", "/data/tracker.sqlite3")
SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""


def respond(start, status, body=b"", kind="text/plain", headers=()):
    if isinstance(body, str):
        body = body.encode()
    start(status, [("Content-Type", kind + "; charset=utf-8"),
                   ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                   ("X-Content-Type-Options", "nosniff"), *headers])
    return [body]


def dashboard(db):
    cards = []
    rows = db.execute("SELECT * FROM runs ORDER BY id DESC")
    for row in rows:
        number, name, step, blocked, version, created = row
        done = step == len(STAGES)
        status = "Complete" if done else "Blocked" if blocked else "In progress"
        state = "done" if done else "blocked" if blocked else "active"
        steps = []
        for i, label in enumerate(STAGES):
            phase = "passed" if i < step else "current" if i == step else "pending"
            detail = "Passed" if i < step else status if i == step else "Queued"
            steps.append(f'<li class="{phase}"><span>{label}</span><small>{detail}</small></li>')
        controls = ""
        if not done:
            buttons = ('<button name="action" value="retry">Resume stage</button>' if blocked else
                       f'<button name="action" value="advance">Pass {STAGES[step]}</button>'
                       '<button class="secondary" name="action" value="block">Mark blocked</button>')
            controls = (f'<form action="runs/{number}" method="post">'
                        f'<input type="hidden" name="version" value="{version}">{buttons}</form>')
        cards.append(f'<article><header><div><small>RUN {number:03d} · {created} UTC</small>'
                     f'<h3>{escape(name)}</h3></div><strong class="badge {state}">{status}</strong></header>'
                     f'<ol class="stages">{"".join(steps)}</ol>{controls}</article>')
    route = "".join(f'<li><b>{i:02d}</b><span>{stage}</span><small>{detail}</small></li>'
                    for i, (stage, detail) in enumerate(zip(STAGES, DESCRIPTIONS), 1))
    return PAGE.substitute(route=route, count=len(cards),
                           cards="".join(cards) or '<p class="empty">Create your first run to track its five stages.</p>')


def application(env, start):
    path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
    if path == "/style.css" and method == "GET":
        return respond(start, "200 OK", CSS, "text/css")
    try:
        with closing(sqlite3.connect(DB, timeout=5)) as db:
            db.execute(SCHEMA)
            if method == "GET" and path == "/health":
                db.execute("SELECT id FROM runs LIMIT 1").fetchone()
                return respond(start, "200 OK", "healthy\n")
            if method == "GET" and path == "/":
                return respond(start, "200 OK", dashboard(db), "text/html")
            match = re.fullmatch(r"/runs/(\d{1,18})", path)
            if method != "POST" or (path != "/runs" and not match):
                return respond(start, "404 Not Found", "Unknown route")
            size = env.get("CONTENT_LENGTH", "")
            if not size.isdigit() or len(size) > 4 or not 0 < int(size) <= 2048:
                return respond(start, "400 Bad Request", "Invalid form size")
            fields = parse_qs(env["wsgi.input"].read(int(size)).decode("utf-8", "replace"))
            if path == "/runs":
                name = fields.get("name", [""])[0].strip()
                if not 1 <= len(name) <= 80:
                    return respond(start, "400 Bad Request", "Enter a release name of 1 to 80 characters")
                db.execute("INSERT INTO runs(name) VALUES (?)", (name,))
                destination = "./"
            else:
                action = fields.get("action", [""])[0]
                version = fields.get("version", [""])[0]
                if action not in ("advance", "block", "retry") or not version.isdecimal():
                    return respond(start, "400 Bad Request", "Invalid stage update")
                result = db.execute("""UPDATE runs SET step=step+?, blocked=?, version=version+1
                    WHERE id=? AND version=? AND step<? AND blocked=?""",
                    (int(action == "advance"), int(action == "block"), match[1],
                     version, len(STAGES), int(action == "retry")))
                if not result.rowcount:
                    return respond(start, "409 Conflict", "This run has changed. Go back and refresh.")
                destination = "../"
            db.commit()
            return respond(start, "303 See Other", headers=[("Location", destination)])
    except sqlite3.Error as error:
        print(error, file=env["wsgi.errors"])
        return respond(start, "503 Service Unavailable", "Database unavailable")
