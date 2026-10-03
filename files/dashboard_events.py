"""dashboard_events：把一次性工蜂的工作寫成「用量儀表板」看得懂的 run 紀錄。

儀表板（files/dashboard/ds_gui_data.py）讀的是 tempfile.gettempdir()/ds_agent/<run_id>/log.jsonl，
每一行是一個 JSON 事件，欄位照 _ref/ds_agent_ref.py 的 logj：t（時間）、phase、conv，加上 event。
ds_gui_data.summarize() 實際會用到的欄位：
    start 事件：pid、workspace、mode、model、session、title、task、queue、max_turns、verify、intent
    usage 事件：tokens（DeepSeek 格式：prompt_tokens／prompt_cache_hit_tokens／completion_tokens／reasoning_tokens）
    end   事件：ok（決定狀態 done／failed）、tokens、min、report
    norm_tokens() 只認得上面那組 DeepSeek 欄位名，所以 tokens 一律用這個格式寫。
    list_runs() 只收「目錄下有 log.jsonl」的 run，且必須有 start 事件。

這個模組只寫檔案，訊息一律交給 log() 送到 stderr；永不寫到標準輸出、永不往外丟例外，
呼叫端（deepseek_swarm.py）就算寫入失敗，工蜂工作照常完成。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

# 與 files/dashboard/ds_gui_data.py 的 RUNS_DIR 相同
RUNS_DIR = Path(tempfile.gettempdir()) / "ds_agent"
LOG_NAME = "log.jsonl"

TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "reasoning_tokens")
ALIASES = ("flash", "pro")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def log(msg: str) -> None:
    """只寫 stderr：MCP 用 stdout 通訊，絕不可污染。"""
    try:
        print(f"[dashboard-events] {msg}", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


def default_runs_dir() -> Path:
    """目前使用的 run 根目錄（測試可以改模組的 RUNS_DIR）。"""
    return Path(RUNS_DIR)


def _safe(text: object) -> str:
    out = _SAFE.sub("-", str(text if text is not None else "")).strip("-")
    return out[:80] or "run"


def new_run_id(job_id: object, index: object) -> str:
    """run 目錄名稱：ds_gui_data.run_detail 不接受含 / 或 \\ 的 id，所以字元全部過濾。"""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        idx = 1
    return f"{_safe(job_id)}-w{idx}"


def _buckets(usage: object) -> list:
    """吃兩種形狀：(1) deepseek_swarm 的 usage holder {flash:{...}, pro:{...}}
    (2) 單一扁平的 {prompt_tokens:...}（可帶 model）。
    回傳 [(alias, {4 個 token 欄位})]，沒有用量的別名不列。"""
    if not isinstance(usage, dict):
        return []
    out = []
    for alias in ALIASES:
        bucket = usage.get(alias)
        if isinstance(bucket, dict) and any(int(bucket.get(k, 0) or 0) for k in TOKEN_KEYS):
            out.append((alias, {k: int(bucket.get(k, 0) or 0) for k in TOKEN_KEYS}))
    if out:
        return out
    flat = {k: int(usage.get(k, 0) or 0) for k in TOKEN_KEYS}
    if any(flat.values()):
        alias = str(usage.get("model") or "").strip() or ALIASES[0]
        return [(alias, flat)]
    return []


def _total(buckets: list) -> dict:
    total = {k: 0 for k in TOKEN_KEYS}
    for _alias, bucket in buckets:
        for k in TOKEN_KEYS:
            total[k] += bucket.get(k, 0)
    return total


def _title(task: object) -> str:
    for line in str(task or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:160]
    return ""


def _event(event: str, t: float, **extra) -> dict:
    return {"t": round(float(t), 2), "phase": "work", "conv": "main", "event": event, **extra}


def build_events(*, t0: float, t1: float, model: str, task: str, workspace: str = "",
                 usage: object = None, ok: bool = True, status: str = "",
                 cost_usd: object = None, pid: object = None, index: object = 1) -> list:
    """組出 start／usage／end 事件（separate 出來方便測試與重用）。"""
    buckets = _buckets(usage)
    total = _total(buckets)
    model_label = str(model or "").strip() or ("+".join(a for a, _b in buckets) if buckets else "?")
    title = _title(task) or f"工蜂 #{index}"
    events = [_event(
        "start", t0,
        pid=int(pid) if pid else os.getpid(),
        workspace=str(workspace or ""),
        mode="swarm",
        model=model_label,
        title=title,
        task=title,
        queue=os.environ.get("DS_GUI_QUEUE", ""),
        session=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
        intent="",
        max_turns=0,
    )]
    for alias, bucket in buckets:
        events.append(_event("usage", t1, turn=1, model=alias, tokens=bucket,
                             call={"in": bucket["prompt_tokens"], "hit": bucket["prompt_cache_hit_tokens"],
                                   "out": bucket["completion_tokens"], "think": bucket["reasoning_tokens"]}))
    if len(buckets) > 1:  # 最後一筆 usage 會被 summarize 當成總計，所以用合計覆蓋
        events.append(_event("usage", t1, turn=1, model=model_label, tokens=total))
    end = _event("end", t1, ok=bool(ok), status=str(status or ""),
                 min=round(max(0.0, t1 - t0) / 60, 1))
    if any(total.values()):  # 完全沒有用量時不寫 tokens，儀表板才不會顯示假的 0
        end["tokens"] = total
    if cost_usd is not None:
        end["usd"] = round(float(cost_usd), 6)
    events.append(end)
    return events


def write_run(run_dir: object, events: list) -> str:
    """把事件寫進 <run_dir>/log.jsonl（先寫 .tmp 再改名，儀表板不會讀到半行）。"""
    d = Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    log_path = d / LOG_NAME
    tmp = d / (LOG_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, log_path)
    return str(d)


def record_worker(job_id: object, index: object, *, model: str = "", task: str = "",
                  workspace: object = "", usage: object = None, ok: bool = True,
                  status: str = "", elapsed_sec: object = None, cost_usd: object = None,
                  pid: object = None, run_id: str = "", runs_dir: object = None,
                  now: object = None, log_fn=None) -> str:
    """寫一份工蜂 run 紀錄。成功回傳 run 目錄字串，失敗回傳 ""（永不丟例外、永不寫 stdout）。

    job_id／index 只用來組目錄名（<job_id>-w<index>，重複執行會覆蓋同一份，是幂等的）。
    usage 可傳 deepseek_swarm 的 usage holder 或單一扁平 token dict。
    """
    warn = log_fn or log
    try:
        base = Path(runs_dir) if runs_dir else default_runs_dir()
        t1 = float(now if now is not None else time.time())
        t0 = t1 - max(0.0, float(elapsed_sec or 0.0))
        events = build_events(t0=t0, t1=t1, model=model, task=task, workspace=workspace,
                              usage=usage, ok=ok, status=status, cost_usd=cost_usd,
                              pid=pid, index=index)
        return write_run(base / (run_id or new_run_id(job_id, index)), events)
    except Exception as e:  # noqa: BLE001  儀表板紀錄絕不可影響工蜂
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return ""


def start_live(job_id, index, *, model="", task="", workspace="", pid=None,
               run_id="", runs_dir=None, now=None, log_fn=None) -> str:
    """建立即時 run：建目錄、用覆寫模式寫入只有一行 start 事件的 log.jsonl。

    start 事件欄位與 build_events 的 start 事件完全相同（t=now 或現在時間、
    title／task 用 _title(task) 或 f'工蜂 #{index}'、model 空字串時寫 '?'）。
    成功回傳 log.jsonl 的完整路徑字串，失敗回傳 ""（永不丟例外、永不寫 stdout）。
    """
    warn = log_fn or log
    try:
        base = Path(runs_dir) if runs_dir else default_runs_dir()
        d = base / (run_id or new_run_id(job_id, index))
        d.mkdir(parents=True, exist_ok=True)
        log_path = d / LOG_NAME
        t = float(now if now is not None else time.time())
        title = _title(task) or f"工蜂 #{index}"
        model_label = str(model or "").strip() or "?"
        event = _event(
            "start", t,
            pid=int(pid) if pid else os.getpid(),
            workspace=str(workspace or ""),
            mode="swarm",
            model=model_label,
            title=title,
            task=title,
            queue=os.environ.get("DS_GUI_QUEUE", ""),
            session=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
            intent="",
            max_turns=0,
        )
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return str(log_path)
    except Exception as e:  # noqa: BLE001
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return ""


def live_event(log_path, event, *, now=None, log_fn=None, **fields) -> bool:
    """在既有的 log.jsonl 尾端附加一行即時事件。

    log_path 為空或 None 時直接回 False（不呼叫 log_fn 也不寫檔）。
    事件固定帶 t／phase='work'／conv='main'／event，其餘由 fields 帶入；
    fields 內無法 JSON 序列化的值以 str 轉字串。成功回 True，失敗回 False。
    """
    if not log_path:
        return False
    warn = log_fn or log
    try:
        record = _event(event, float(now if now is not None else time.time()), **fields)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception as e:  # noqa: BLE001
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return False


def live_usage(log_path, usage, *, now=None, log_fn=None) -> bool:
    """寫一行 event='usage' 的即時事件：tokens 為四個欄位合計，model 為有用量的別名以 '+' 串接。

    usage 可為 usage holder 或扁平 dict（同 _buckets 規則）；完全沒有 token 時
    回 False 且不寫入任何內容。
    """
    warn = log_fn or log
    try:
        buckets = _buckets(usage)
    except Exception as e:  # noqa: BLE001
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return False
    if not buckets:
        return False
    try:
        total = _total(buckets)
        model_label = "+".join(alias for alias, _bucket in buckets)
    except Exception as e:  # noqa: BLE001
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return False
    return live_event(log_path, "usage", now=now, log_fn=log_fn, tokens=total, model=model_label)


def live_end(log_path, *, ok, status="", usage=None, cost_usd=None,
             elapsed_sec=None, now=None, log_fn=None) -> bool:
    """寫一行 event='end' 的即時事件。

    ok 一律存成 bool、status 存成字串；elapsed_sec 不是 None 時加 min=round(max(0, elapsed)/60, 1)；
    usage 有 token 時加 tokens=合計（沒有就不寫 tokens 欄位）；cost_usd 不是 None 時加 usd=round(float, 6)。
    成功回 True，失敗回 False（永不丟例外、永不寫 stdout）。
    """
    warn = log_fn or log
    try:
        extra = {"ok": bool(ok), "status": str(status or "")}
        if elapsed_sec is not None:
            extra["min"] = round(max(0.0, float(elapsed_sec)) / 60, 1)
        buckets = _buckets(usage)
        if buckets:
            extra["tokens"] = _total(buckets)
        if cost_usd is not None:
            extra["usd"] = round(float(cost_usd), 6)
    except Exception as e:  # noqa: BLE001
        try:
            warn(f"寫儀表板事件失敗（{type(e).__name__}: {e}）")
        except Exception:  # noqa: BLE001
            pass
        return False
    return live_event(log_path, "end", now=now, log_fn=log_fn, **extra)
