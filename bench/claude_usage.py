"""第二關：量 Claude 端的用量（skill 寫得好不好，主要看這裡）。

流程：
  1. python bench/claude_usage.py --prompt
     → 產生 bench/e2e_prompt.md（固定題目，開頭有 [BENCH-E2E] 標記）
  2. 在 Claude 桌面 App 開「新對話」，選一個空資料夾，把 e2e_prompt.md 全文貼上送出，等它做完。
  3. python bench/claude_usage.py --label "改了 skill 第 X 節"
     → 自動找最近一次 [BENCH-E2E] 對話，統計 Claude 用量、評分它做出來的檔案，並和上一次比較。
其他：
  --session <對話 id 或 .jsonl 路徑>   指定某次對話
  --history                            只看歷史
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

from grading import grade_level  # noqa: E402
from levels import LEVELS, SHARED_CONTEXT, SUITE_VERSION  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"
SKILL = Path.home() / ".claude" / "skills" / "deepseek-orchestrator" / "SKILL.md"
HISTORY = BENCH / "history_claude.jsonl"
PROMPT_FILE = BENCH / "e2e_prompt.md"
MARKER = "[BENCH-E2E]"
E2E_LEVELS = ["L1", "L4", "L5"]

# 每百萬「一般輸入 token」的美元價格（官方價，2026-09）；等效 tokens × 這個價格 ＝ 估計花費
INPUT_PRICE = {"claude-opus-5-5": 4.0, "claude-opus-5": 5.0, "claude-sonnet-5": 2.0, "claude-haiku-4-5": 1.0,
               "claude-fable-5-1": 10.0}


def price_of(models) -> float:
    for m in models or []:
        for k, v in INPUT_PRICE.items():
            if str(m).startswith(k):
                return v
    return 4.0


# 相對於「一般輸入 token」的價格倍數（Anthropic 計價結構：快取讀 0.1×、5 分鐘快取寫 1.25×、1 小時快取寫 2×、輸出 5×）
W_IN, W_CW5, W_CW1H, W_CR, W_OUT = 1.0, 1.25, 2.0, 0.1, 5.0


def make_prompt() -> str:
    parts = [f"{MARKER} 請用 deepseek-orchestrator skill 在目前資料夾完成下列 {len(E2E_LEVELS)} 個檔案，"
             "做完要自己驗證能執行。規格已完整，不要問我問題，直接做到完成。",
             "", "## 共通規範", SHARED_CONTEXT]
    for lid in E2E_LEVELS:
        lv = next(x for x in LEVELS if x["id"] == lid)
        parts += ["", f"## 檔案：{lv['out']}", lv["task"]]
    return "\n".join(parts) + "\n"


def first_user_text(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                o = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "user" and not o.get("isSidechain"):
                c = o.get("message", {}).get("content")
                blocks = [c] if isinstance(c, str) else [b.get("text", "") for b in c or [] if isinstance(b, dict)]
                text = "\n".join(t for t in blocks if t and not t.lstrip().startswith("<"))
                if text.strip():
                    return text.strip()
    return ""


def find_session(arg: str) -> Path:
    if arg:
        p = Path(arg)
        if p.is_file():
            return p
        hits = list(PROJECTS.glob(f"*/{arg}.jsonl"))
        if not hits:
            sys.exit(f"找不到對話 {arg}")
        return hits[0]
    cands = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in cands[:200]:
        if MARKER in first_user_text(p)[:200]:
            return p
    sys.exit(f"最近的對話裡找不到以 {MARKER} 開頭的；請先照 --prompt 的步驟跑一次，或用 --session 指定。")


def analyze(path: Path) -> dict:
    files = [path] + sorted((path.parent / path.stem).glob("**/*.jsonl"))  # 含子代理的對話
    seen, tot = set(), dict(inp=0, cw5=0, cw1h=0, cr=0, out=0)
    calls = tool_calls = ds_calls = 0
    prompt_ids: set = set()
    cwd, t_first, t_last, models = "", None, None, set()
    for fp in files:
        for ln in fp.open(encoding="utf-8", errors="replace"):
            try:
                o = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ts = o.get("timestamp")
            if ts:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                t_first = t if t_first is None else min(t_first, t)
                t_last = t if t_last is None else max(t_last, t)
            if fp == path and o.get("cwd") and not cwd:
                cwd = o["cwd"]
            msg = o.get("message") or {}
            if o.get("type") == "user" and fp == path and o.get("promptId"):
                prompt_ids.add(o["promptId"])
            if o.get("type") != "assistant":
                continue
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tool_calls += 1
                    cmd = json.dumps(b.get("input") or {}, ensure_ascii=False)
                    if "deepseek" in b.get("name", "") or "ds.py run" in cmd:  # MCP 工具或 ds.py 指令列
                        ds_calls += 1
            key = msg.get("id") or o.get("requestId")
            u = msg.get("usage")
            if not u or key in seen:
                continue
            seen.add(key)
            calls += 1
            models.add(msg.get("model", "?"))
            cc = u.get("cache_creation") or {}
            cw1h = int(cc.get("ephemeral_1h_input_tokens", 0) or 0)
            cw_total = int(u.get("cache_creation_input_tokens", 0) or 0)
            tot["inp"] += int(u.get("input_tokens", 0) or 0)
            tot["cw1h"] += cw1h
            tot["cw5"] += max(0, cw_total - cw1h)
            tot["cr"] += int(u.get("cache_read_input_tokens", 0) or 0)
            tot["out"] += int(u.get("output_tokens", 0) or 0)
    equiv = (tot["inp"] * W_IN + tot["cw5"] * W_CW5 + tot["cw1h"] * W_CW1H
             + tot["cr"] * W_CR + tot["out"] * W_OUT)
    return {"session": path.stem, "cwd": cwd, "api_calls": calls, "tool_calls": tool_calls,
            "deepseek_calls": ds_calls, "user_turns": len(prompt_ids), "models": sorted(models),
            "wall": round((t_last or 0) - (t_first or 0)), **tot, "equiv": int(equiv)}


def grade_cwd(cwd: str) -> tuple[float, dict]:
    ws = Path(cwd)
    res = {}
    for lid in E2E_LEVELS:
        lv = next(x for x in LEVELS if x["id"] == lid)
        score, note = grade_level(lv, ws) if ws.is_dir() else (0.0, "資料夾不存在")
        res[lid] = {"score": round(score, 3), "note": note}
    return round(100 * sum(v["score"] for v in res.values()) / len(res), 1), res


def load_history() -> list[dict]:
    if not HISTORY.is_file():
        return []
    rows = [json.loads(x) for x in HISTORY.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    return [r for r in rows if r.get("suite_version") == SUITE_VERSION]


def k(n: int) -> str:
    return f"{n / 1000:.1f}k"


def print_history(rows: list[dict], limit: int = 12) -> None:
    print(f"\n歷史（最近 {min(limit, len(rows))} 次）")
    print(f"{'時間':<17}{'skill':<10}{'正確率':>7}{'等效tokens':>11}{'輸出':>8}{'API次':>6}{'DS派工':>7}{'分鐘':>6}  標籤")
    for r in rows[-limit:]:
        print(f"{r['ts']:<17}{r['skill_sha']:<10}{r['score']:>6.1f}%{k(r['equiv']):>11}{k(r['out']):>8}"
              f"{r['api_calls']:>6}{r['deepseek_calls']:>7}{r['wall'] / 60:>6.1f}  {r['label']}")


def verdict(cur: dict, prev: dict) -> str:
    ds = cur["score"] - prev["score"]
    if ds <= -5:
        return f"⚠ 退步：成品正確率下降 {-ds:.1f} 分"
    if ds >= 5:
        return f"✅ 進步：成品正確率提升 {ds:.1f} 分"
    ch = (cur["equiv"] - prev["equiv"]) / max(prev["equiv"], 1)
    if ch <= -0.10:
        return f"✅ 進步：正確率持平，Claude 用量 {ch * 100:.0f}%"
    if ch >= 0.10:
        return f"⚠ 退步：正確率持平，但 Claude 用量 +{ch * 100:.0f}%"
    return "＝ 持平（用量差異在 10% 內）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", action="store_true")
    ap.add_argument("--session", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--workdir", default="", help="評分用資料夾（子代理跑測試時，對話的 cwd 不是成品資料夾）")
    ap.add_argument("--history", action="store_true")
    args = ap.parse_args()

    if args.prompt:
        PROMPT_FILE.write_text(make_prompt(), encoding="utf-8")
        print(f"已寫入 {PROMPT_FILE}\n在新對話（空資料夾）貼上全文送出，做完後執行：python bench/claude_usage.py --label <這次改了什麼>")
        return
    if args.history:
        print_history(load_history(), 50)
        return

    path = find_session(args.session)
    hist = load_history()
    if any(r["session"] == path.stem for r in hist):
        print(f"注意：對話 {path.stem} 已經記錄過，這次會再記一筆。")
    a = analyze(path)
    a["usd"] = round(a["equiv"] / 1e6 * price_of(a["models"]), 4)
    if args.workdir:
        a["cwd"] = str(Path(args.workdir).resolve())
    score, per = grade_cwd(a["cwd"])
    row = {"ts": time.strftime("%Y-%m-%d %H:%M"), "label": args.label or path.stem[:8],
           "suite_version": SUITE_VERSION, "skill_sha": (__import__("hashlib").sha1(SKILL.read_bytes()).hexdigest()[:8]
                                                          if SKILL.is_file() else "-"),
           "score": score, "levels": per, **a}
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"對話 {a['session']}｜資料夾 {a['cwd']}｜模型 {', '.join(a['models'])}")
    print(f"成品正確率 {score}%：" + "；".join(f"{lid} {v['score'] * 100:.0f}% {v['note'][:40]}" for lid, v in per.items()))
    usd = a["usd"]
    print(f"Claude 估計花費：${usd:.3f}（{', '.join(a['models'])} 單價 ${price_of(a['models'])}/百萬輸入）")
    print(f"Claude 用量：等效輸入 {k(a['equiv'])} tokens（輸出 {k(a['out'])}、快取讀 {k(a['cr'])}、"
          f"快取寫 {k(a['cw5'] + a['cw1h'])}、一般輸入 {k(a['inp'])}）")
    print(f"API 呼叫 {a['api_calls']} 次｜工具呼叫 {a['tool_calls']}（DeepSeek {a['deepseek_calls']}）｜"
          f"你的訊息 {a['user_turns']} 則｜歷時 {a['wall'] / 60:.1f} 分")
    rows = load_history()
    print_history(rows)
    if len(rows) >= 2:
        print("\n結論（對上一次）：" + verdict(rows[-1], rows[-2]))
    else:
        print("\n這是第一筆紀錄，之後會以它為比較基準。")


if __name__ == "__main__":
    main()
