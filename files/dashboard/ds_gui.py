#!/usr/bin/env python3
"""Local web dashboard for ds_agent.py / ds_queue.py runs.

ds_agent.py and ds_queue.py call `ensure_running()` when a job starts: if the dashboard is not up it is
launched as a detached background process, and the browser opens itself (once, only when no tab is
watching). The server only reads what the jobs already write -- %TEMP%/ds_agent/<run>/log.jsonl plus a
small queues/*.json manifest -- so a crashed or closed dashboard never affects a job.

  python ds_gui.py            start in the foreground and open the browser
  python ds_gui.py --no-open  same, without opening a tab
Turn it off with "gui": false in ds_config.json, `--no-gui` on ds_agent.py, or DS_NO_GUI=1.
The log aggregation lives in ds_gui_data.py and the front-end PAGE string in ds_gui_page.py; this file
keeps the launcher, the HTTP server and the public API, re-exporting those names unchanged.
"""
import argparse
import ds_gui_analyze
import http.server
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from ds_gui_data import (  # noqa: F401  (re-exported: callers use ds_gui.<name>)
    CLAUDE_PROJECTS, CLAUDE_STALE_SEC, DEFAULT_PORT, DOC_CHARS, HERE, IDLE_EXIT_SEC, MAX_RUNS,
    OPEN_COOLDOWN, QUEUES_DIR, RUNS_DIR, STATE, VIEWER_TTL, group_for, list_queues, list_runs,
    norm_tokens, pid_alive, read_events, run_detail, run_doc, session_info, summarize,
    tokens_from_report,
)
from ds_gui_page import PAGE  # noqa: F401  (re-exported)


# ---------------------------------------------------------------- launcher (used by ds_agent / ds_queue)


def _port(cfg):
    try:
        return int((cfg or {}).get("gui_port", DEFAULT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _get(port, path, timeout=0.6):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_running(cfg=None):
    """Start the dashboard if it is not running; ask it to open a tab if nobody is watching. Never raises."""
    if os.environ.get("DS_NO_GUI") or (cfg or {}).get("gui") is False:
        return
    port, autoopen = _port(cfg), (cfg or {}).get("gui_autoopen", True)
    try:
        info = _get(port, "/api/ping")
        if info.get("app") == "ds_gui":
            if autoopen and not info.get("viewers"):
                _get(port, "/api/open")
            return
    except Exception:
        pass
    cmd = [sys.executable, str(HERE / "ds_gui.py"), "--port", str(port)] + ([] if autoopen else ["--no-open"])
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(HERE)}
    if os.name == "nt":
        exe = pathlib.Path(sys.executable).with_name("pythonw.exe")
        if exe.exists():
            cmd[0] = str(exe)
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        try:  # leave the caller's job object so the dashboard outlives the shell that ran the job
            subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)  # CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(cmd, creationflags=flags, **kw)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kw)
    # a second launcher racing this one simply fails to bind and exits; only the winner opens the browser


def _queue_path(out_dir):
    return QUEUES_DIR / (pathlib.Path(out_dir).parent.name + "-" + pathlib.Path(out_dir).name + ".json")


def queue_start(cfg, out_dir, intents):
    """ds_queue announces its tasks so the dashboard can show ones that have not started yet."""
    if os.environ.get("DS_NO_GUI") or (cfg or {}).get("gui") is False:
        return
    QUEUES_DIR.mkdir(parents=True, exist_ok=True)
    _queue_path(out_dir).write_text(json.dumps({
        "out_dir": str(out_dir), "pid": os.getpid(), "t0": time.time(), "state": "running",
        "session": os.environ.get("CLAUDE_CODE_SESSION_ID"), "workspace": intents[0]["workspace"] if intents else None,
        "label": pathlib.Path(out_dir).parent.name,
        "tasks": [{"id": t["id"], "after": t.get("after") or []} for t in intents]}), encoding="utf-8")
    ensure_running(cfg)


def queue_end(out_dir, ok, usd, minutes):  # usd is accepted but never stored: the dashboard shows tokens only
    p = _queue_path(out_dir)
    if p.is_file():
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(state="done" if ok else "failed", ok=ok, min=minutes, t1=time.time())
        p.write_text(json.dumps(d), encoding="utf-8")


# ---------------------------------------------------------------- server


def open_browser(force=False):
    if not force and time.time() - STATE["last_open"] < OPEN_COOLDOWN:
        return
    STATE["last_open"] = time.time()
    try:
        webbrowser.open(f"http://127.0.0.1:{STATE['port']}/", new=1)
    except Exception:
        pass


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):  # blocks DNS-rebinding pages from reading local logs
            return self._send(403, "forbidden", "text/plain")
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if u.path == "/api/ping":
                return self._json({"app": "ds_gui", "viewers": time.time() - STATE["last_poll"] < VIEWER_TTL})
            if u.path == "/api/open":
                open_browser()
                return self._json({"ok": True})
            if u.path == "/api/runs":
                STATE["last_poll"] = time.time()
                return self._json({"now": time.time(), "runs": list_runs(), "queues": list_queues()})
            if u.path == "/api/run":
                d = run_detail(q.get("id", ""), int(q.get("since", 0)))
                return self._json(d) if d is not None else self._json({"error": "not found"}, 404)
            if u.path == "/api/doc":
                return self._json({"text": run_doc(q.get("id", ""), q.get("kind", ""))})
            if u.path == "/api/analyze":
                rid = q.get("id", "")
                d = RUNS_DIR / rid
                if "/" in rid or "\\" in rid or not (d / "log.jsonl").is_file():
                    return self._json({"error": "not found"}, 404)
                return self._json({"findings": ds_gui_analyze.analyze_run(summarize(d), read_events(d / "log.jsonl"))})
            if u.path == "/api/analyze/overview":
                items = [(r, read_events(RUNS_DIR / r["id"] / "log.jsonl")) for r in list_runs()]
                return self._json(ds_gui_analyze.analyze_overview(items))
            if u.path == "/api/analyze/session":
                sid = q.get("id", "")
                if not re.fullmatch(r"[A-Za-z0-9-]+", sid or ""):
                    return self._json({"error": "bad id"})
                info = session_info(sid)
                if not info or not info.get("path"):
                    return self._json({"error": "找不到對話紀錄"})
                return self._json(ds_gui_analyze.analyze_session(info["path"]))
        except Exception as e:  # keep the server alive whatever a half-written log looks like
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        self._send(404, "not found", "text/plain")


def idle_watchdog(server):
    while True:
        time.sleep(60)
        if time.time() - STATE["last_poll"] > IDLE_EXIT_SEC:
            try:
                if not any(r["state"] == "running" for r in list_runs()):
                    server.shutdown()
                    return
            except Exception:
                pass


def serve(port, open_tab):
    STATE["port"] = port
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        return 1  # another dashboard already owns the port
    threading.Thread(target=idle_watchdog, args=(server,), daemon=True).start()
    if open_tab:
        open_browser(force=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(description="ds_agent / ds_queue 本機網頁儀表板")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-open", action="store_true", help="不自動開瀏覽器分頁")
    a = ap.parse_args()
    cfg = {}
    try:
        cfg = json.loads((HERE / "ds_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return serve(a.port or _port(cfg), not a.no_open)


if __name__ == "__main__":
    sys.exit(main())
