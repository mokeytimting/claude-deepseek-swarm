"""ds_gui_data：儀表板的常數、dashboard 狀態，以及 run/session/queue 紀錄的讀取與彙整。"""
import json
import os
import pathlib
import re
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
RUNS_DIR = pathlib.Path(tempfile.gettempdir()) / "ds_agent"
QUEUES_DIR = RUNS_DIR / "queues"
DEFAULT_PORT = 8765
MAX_RUNS = 40
VIEWER_TTL = 90        # a tab counts as watching if it polled within this many seconds (hidden tabs are throttled)
OPEN_COOLDOWN = 20     # never open the browser more often than this
IDLE_EXIT_SEC = 6 * 3600   # server quits after six hours with no running job and no viewer
DOC_CHARS = 20_000
CLAUDE_STALE_SEC = 900  # a Claude built-in subagent with no hook activity for this long is shown as interrupted

# ---------------------------------------------------------------- reading runs


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


_cache = {}  # log path -> (size, mtime, events)


def read_events(path):
    st = path.stat()
    hit = _cache.get(path)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime:
        return hit[2]
    events = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except ValueError:
                pass  # a line still being written
    _cache[path] = (st.st_size, st.st_mtime, events)
    return events


CLAUDE_PROJECTS = pathlib.Path.home() / ".claude" / "projects"
_sessions = {}  # session id -> (fetched at, info)


def session_info(sid):
    """Where a Claude session lives: its working folder (the 'project') and title, read from the transcript
    Claude Code keeps under ~/.claude/projects. Sessions started in a scratch workspace are chats without a project."""
    if not sid:
        return None
    hit = _sessions.get(sid)
    if hit and time.time() - hit[0] < 30:  # titles get set a little after the session starts
        return hit[1]
    info = None
    try:
        for f in CLAUDE_PROJECTS.glob(f"*/{sid}.jsonl"):
            cwd = prompt = None
            with open(f, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh):
                    if n > 300 or (cwd and prompt):
                        break
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    cwd = cwd or e.get("cwd")
                    m = e.get("message") if isinstance(e.get("message"), dict) else {}
                    if not prompt and e.get("type") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
                        prompt = m["content"].strip().splitlines()[0][:40]
            title = None
            try:
                title = json.loads((f.parent / sid / "custom-title.json").read_text(encoding="utf-8")).get("customTitle")
            except (OSError, ValueError):
                pass
            info = {"cwd": cwd, "title": title or prompt or sid[:8], "path": str(f),
                    "is_project": bool(cwd) and not re.search(r"scratch", cwd, re.I)}
            break
    except OSError:
        pass
    _sessions[sid] = (time.time(), info)
    return info


def group_for(session, workspace):
    """{key, label, kind, path}: runs of one project go together; a session without a project goes by conversation."""
    si = session_info(session)
    if si and si["is_project"]:
        path = si["cwd"]
    elif si:
        return {"key": "chat:" + session, "label": si["title"], "kind": "chat", "path": None}
    elif session:
        return {"key": "chat:" + session, "label": session[:8], "kind": "chat", "path": None}
    else:
        path = workspace  # started by hand, outside any Claude session
    if not path:
        return {"key": "none", "label": "未歸類", "kind": "chat", "path": None}
    p = str(path).replace("\\", "/").rstrip("/")
    return {"key": "proj:" + p.lower(), "label": p.rsplit("/", 1)[-1] or p, "kind": "project", "path": p}


def norm_tokens(t):
    """Both usage shapes -> {in, hit, miss, out, think, write}: in = all input, hit = served from cache,
    miss = uncached input (for Claude that includes cache writes), out = output (DeepSeek: incl. thinking)."""
    if not isinstance(t, dict):
        return None
    if "input_tokens" in t or "cache_read_input_tokens" in t:  # Anthropic
        write, hit = int(t.get("cache_creation_input_tokens") or 0), int(t.get("cache_read_input_tokens") or 0)
        miss = int(t.get("input_tokens") or 0) + write
        return {"in": miss + hit, "hit": hit, "miss": miss, "out": int(t.get("output_tokens") or 0), "think": 0, "write": write}
    inp, hit = int(t.get("prompt_tokens") or 0), int(t.get("prompt_cache_hit_tokens") or 0)  # DeepSeek
    return {"in": inp, "hit": hit, "miss": inp - hit, "out": int(t.get("completion_tokens") or 0),
            "think": int(t.get("reasoning_tokens") or 0), "write": 0}


def tokens_from_report(path):
    """Runs logged before token counts existed: ds_agent's report.md has a 'Token：輸入 N（快取命中 M）｜輸出 K（其中推理 R）' line."""
    try:
        m = re.search(r"Token：輸入 (\d+)（快取命中 (\d+)）｜輸出 (\d+)（其中推理 (\d+)）",
                      pathlib.Path(path).read_text(encoding="utf-8", errors="replace")[:3000])
    except (OSError, TypeError):
        return None
    return {"prompt_tokens": int(m[1]), "prompt_cache_hit_tokens": int(m[2]), "completion_tokens": int(m[3]),
            "reasoning_tokens": int(m[4])} if m else None


def summarize(run_dir):
    log = run_dir / "log.jsonl"
    events = read_events(log)
    mtime = log.stat().st_mtime
    start = next((e for e in events if e.get("event") == "start"), {})
    end = next((e for e in reversed(events) if e.get("event") == "end"), None)
    t0 = start.get("t") or next((e["t"] for e in events if "t" in e), None) or mtime
    usage = next((e for e in reversed(events) if e.get("event") == "usage"), {})
    work_turn = max([e.get("turn", 0) for e in events if e.get("phase", "work") == "work" and "turn" in e] or [0])
    tools = [e for e in events if "tool" in e]
    phases = []
    for e in events:
        ph = e.get("phase", "work")
        if e.get("event") == "verify":
            ph = "verify"
        if e.get("event") not in ("start", "end") and (not phases or phases[-1] != ph) and ph not in phases:
            phases.append(ph)
    last = next((e for e in reversed(events) if e.get("event") not in ("usage", "end")), {})
    if end:
        state = "done" if end.get("ok") else "failed"
    elif start.get("source") == "claude":  # built-in subagent: no pid to check, so recent activity means alive
        state = "running" if time.time() - mtime < CLAUDE_STALE_SEC else "interrupted"
    elif pid_alive(start.get("pid")) and time.time() - mtime < 3600:
        state = "running"
    else:
        state = "interrupted"
    recent = [e for e in events if e.get("event") not in ("start", "end")][-12:]
    finished = {e["event"] for e in events if e.get("event") in ("spec", "probe", "review")}
    active = [p for p in ("spec", "work", "probe", "review") if p not in finished and any(e.get("phase") == p for e in recent)]
    return {
        "id": run_dir.name, "state": state, "has_start": bool(start), "session": start.get("session"), "source": start.get("source", "ds"),
        "agent_type": start.get("agent_type"),
        "title": next((e["title"] for e in reversed(events) if e.get("event") == "title"), None) or start.get("title") or run_dir.name,
        "workspace": start.get("workspace"), "mode": start.get("mode"), "model": start.get("model"),
        "verify_cmd": start.get("verify"), "intent": start.get("intent"), "pid": start.get("pid"),
        "task": start.get("task"), "queue": start.get("queue"), "max_turns": start.get("max_turns"),
        "t0": t0, "t1": end["t"] if end and "t" in end else (mtime if state != "running" else None),
        "turns": work_turn, "tool_calls": len(tools), "errors": sum(1 for e in tools if str(e.get("result", "")).startswith("ERROR")),
        "tokens": norm_tokens((end or {}).get("tokens") or usage.get("tokens")
                              or (tokens_from_report(end.get("report")) if end else None)),
        "phases": phases, "active": active if state == "running" else [],
        "escalated": any(e.get("event") == "escalate_to_pro" for e in events),
        "last_t": last.get("t") or mtime,
        "last": (last.get("tool") or last.get("event") or ""),
        "verify_runs": [e.get("exit") for e in events if e.get("event") == "verify"],
        "end": end,
    }


def list_runs():
    if not RUNS_DIR.is_dir():
        return []
    dirs = sorted((d for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "log.jsonl").is_file()),
                  key=lambda d: d.name, reverse=True)[:MAX_RUNS]
    out = []
    for d in dirs:
        try:
            r = summarize(d)
        except OSError:
            continue
        if r["has_start"]:  # logs from before the dashboard existed have no start event; skip them
            r["group"] = group_for(r["session"], r["workspace"])
            si = session_info(r["session"])
            r["session_title"] = si["title"] if si else None
            out.append(r)
    return out


def list_queues():
    out = []
    if QUEUES_DIR.is_dir():
        for p in sorted(QUEUES_DIR.glob("*.json"), reverse=True)[:10]:
            try:
                q = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if q.get("state") == "running" and not pid_alive(q.get("pid")):
                q["state"] = "interrupted"
            q["group"] = group_for(q.get("session"), q.get("workspace"))
            out.append(q)
    return out


def run_detail(run_id, since):
    d = RUNS_DIR / run_id
    if "/" in run_id or "\\" in run_id or not (d / "log.jsonl").is_file():
        return None
    events = read_events(d / "log.jsonl")
    rows, seen = [], set()
    for i, e in enumerate(events):
        base = {"i": i, "t": e.get("t"), "phase": e.get("phase", "work"), "conv": e.get("conv", "main")}
        if e.get("event") == "usage":
            c = e.get("call")
            if c and not (c.get("msg") and c["msg"] in seen):  # parallel tool calls of one Claude message log it twice
                seen.add(c.get("msg"))
                if i >= since:
                    rows.append({**base, "kind": "round", "turn": e.get("turn"), "call": c})
            continue
        if i < since:
            continue
        if "tool" in e:
            rows.append({**base, "kind": "tool", "tool": e["tool"], "args": e.get("args") or {},
                         "result": e.get("result", ""), "model": e.get("model"), "turn": e.get("turn")})
        else:
            data = {k: v for k, v in e.items() if k not in ("t", "phase", "event")}
            if "tokens" in data:
                data["tokens"] = norm_tokens(data["tokens"])
            rows.append({**base, "kind": "event", "event": e.get("event"), "data": data})
    if since == 0:
        rows = rows[-400:]
    return {"events": rows, "total": len(events)}


def run_doc(run_id, kind):
    d = RUNS_DIR / run_id
    if "/" in run_id or "\\" in run_id or not d.is_dir():
        return ""
    path = None
    if kind == "brief":
        path = d / "brief.md"
    elif kind == "spec":
        path = d / "SPEC.md"
    elif kind == "report":
        events = read_events(d / "log.jsonl") if (d / "log.jsonl").is_file() else []
        end = next((e for e in reversed(events) if e.get("event") == "end"), {})
        for cand in (d / "ds_report_full.md", pathlib.Path(end["report"]) if end.get("report") else None):
            if cand and cand.is_file():
                path = cand
                break
    if path and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")[:DOC_CHARS]
    return ""

# ---------------------------------------------------------------- dashboard state

STATE = {"last_poll": 0.0, "last_open": 0.0, "port": DEFAULT_PORT}
