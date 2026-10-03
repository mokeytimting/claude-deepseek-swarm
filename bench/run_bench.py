"""DeepSeek 工蜂測試關卡（不經過 Claude，直接呼叫伺服器程式）。

用法（在安裝資料夾，也就是 deepseek_swarm.py 所在的資料夾執行）：
  python bench/run_bench.py --label "加了XX功能"            測目前的 deepseek_swarm.py
  python bench/run_bench.py --server deepseek_swarm.pre-extras.backup.py --label 舊版
  python bench/run_bench.py --repeat 2                      同一版跑兩次取平均（降低運氣成分）
  python bench/run_bench.py --levels L1,L3                  只跑部分關卡
  python bench/run_bench.py --history                       只看歷史紀錄
每次結果附加到 bench/history.jsonl，並自動和「上一次」「最佳一次」比較。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
sys.path.insert(0, str(BENCH))

from grading import grade_level  # noqa: E402
from levels import LEVELS, SHARED_CONTEXT, SUITE_VERSION  # noqa: E402

HISTORY = BENCH / "history.jsonl"
RUNS = BENCH / "runs"
SKILL = Path.home() / ".claude" / "skills" / "deepseek-orchestrator" / "SKILL.md"
CODE_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.S)
JOB_TIMEOUT = 1800
GEN_TESTS = False  # --tests 時設為 True


def sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:8] if path.is_file() else "-"


def load_server(path: Path):
    spec = importlib.util.spec_from_file_location(f"ds_under_test_{sha(path)}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prepare_ws(levels: list[dict], ws: Path) -> None:
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    for lv in levels:
        for name, text in lv.get("seed", {}).items():
            (ws / name).write_text(text, encoding="utf-8")


async def run_with_job(mod, levels, ws, effort, review) -> dict:
    """新版伺服器：用 submit_swarm_job 走完整流水線（含審查、自動修正、寫檔）。"""
    kwargs = dict(
        task_list=[lv["task"] for lv in levels],
        shared_context=SHARED_CONTEXT,
        effort="" if effort == "auto" else effort,  # 空白=伺服器自動選強度（舊版伺服器不支援）
        output_root=str(ws),
        output_files=[lv["out"] for lv in levels],
        task_attach=[lv.get("attach", "") for lv in levels],
        read_root=str(ws),
    )
    params = inspect.signature(mod.submit_swarm_job).parameters
    if "review" in params:
        kwargs["review"] = review
    if GEN_TESTS and "test_files" in params:
        # 伺服器端測試：測試檔放 gen_tests/，不會和隱藏測試混在一起
        kwargs["test_files"] = [
            (f"gen_tests/test_{Path(lv['out']).stem}.py" if lv["out"].endswith(".py")
             else f"gen_tests/{Path(lv['out']).stem}.test.mjs") if lv["out"] else ""
            for lv in levels
        ]
    kwargs = {k: v for k, v in kwargs.items() if k in params}
    t0 = time.time()
    msg = await mod.submit_swarm_job(**kwargs)
    m = re.search(r"job_id=(\S+)", msg)
    if not m:
        raise RuntimeError("送出失敗：" + msg[:300])
    job_id = m.group(1)
    job = mod.JOBS[job_id]
    done_at = [None] * len(levels)
    while job.get("finished") is None and time.time() - t0 < JOB_TIMEOUT:
        for i, r in enumerate(job["results"]):
            if r is not None and done_at[i] is None:
                done_at[i] = time.time() - t0
        await asyncio.sleep(0.5)
    wall = time.time() - t0
    per = []
    for i, r in enumerate(job["results"]):
        r = r or {}
        per.append({
            "secs": round(done_at[i] or wall, 1),
            "model": r.get("model", "?"),
            "outcome": r.get("outcome") or r.get("status", "timeout"),
            "pipeline": r.get("pipeline", ""),
            "content": r.get("content", ""),
        })
    usage = job.get("usage") or {}
    cost = mod._estimate_cost(usage) if hasattr(mod, "_estimate_cost") else None
    return {"mode": "job", "job_id": job_id, "wall": round(wall, 1), "per": per,
            "usage": usage, "cost": cost}


async def run_with_quick(mod, levels, ws, effort) -> dict:
    """舊版伺服器（沒有 submit_swarm_job）：每關各叫一次 quick_worker_solve，自己寫檔。"""
    params = inspect.signature(mod.quick_worker_solve).parameters
    t0 = time.time()

    async def one(lv):
        task = lv["task"]
        if lv.get("attach"):
            task += f"\n\n【附檔 {lv['attach']}】\n```python\n{(ws / lv['attach']).read_text(encoding='utf-8')}\n```"
        kw = {"task": task, "context": SHARED_CONTEXT, "effort": effort}
        text = await mod.quick_worker_solve(**{k: v for k, v in kw.items() if k in params})
        secs = time.time() - t0
        if lv["out"]:
            blocks = CODE_RE.findall(text)
            if blocks:
                (ws / lv["out"]).write_text(blocks[0] + "\n", encoding="utf-8")
        head = text.splitlines()[0] if text else ""
        mm = re.search(r"model=(\w+)", head)
        return {"secs": round(secs, 1), "model": mm.group(1) if mm else "?",
                "outcome": head[:20], "pipeline": "quick", "content": text}

    per = await asyncio.gather(*(one(lv) for lv in levels))
    return {"mode": "quick", "wall": round(time.time() - t0, 1), "per": list(per), "usage": {}, "cost": None}


def tokens_of(usage: dict) -> int:
    return sum(int(b.get("prompt_tokens", 0)) + int(b.get("completion_tokens", 0))
               for b in usage.values() if isinstance(b, dict))


async def one_round(mod, levels, ws, effort, review) -> dict:
    prepare_ws(levels, ws)
    if hasattr(mod, "submit_swarm_job") and hasattr(mod, "JOBS"):
        res = await run_with_job(mod, levels, ws, effort, review)
    else:
        res = await run_with_quick(mod, levels, ws, effort)
    lv_out = {}
    for lv, p in zip(levels, res["per"]):
        score, note = grade_level(lv, ws, p.pop("content"))
        lv_out[lv["id"]] = {**p, "score": round(score, 3), "note": note}
        (ws / f"_{lv['id']}_note.txt").write_text(note, encoding="utf-8")
    res["levels"] = lv_out
    res["score"] = round(100 * sum(v["score"] for v in lv_out.values()) / len(lv_out), 1)
    res["passed"] = sum(1 for v in lv_out.values() if v["score"] >= 1)
    res["tokens"] = tokens_of(res["usage"])
    return res


# ------------------------------------------------------------------ 比較與顯示
def load_history() -> list[dict]:
    if not HISTORY.is_file():
        return []
    rows = [json.loads(ln) for ln in HISTORY.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r for r in rows if r.get("suite_version") == SUITE_VERSION]


def fmt_cost(c) -> str:
    return "-" if c is None else f"${c:.4f}"


def pct(new, old) -> str:
    if new is None or old in (None, 0):
        return ""
    d = (new - old) / old * 100
    return f"({'+' if d >= 0 else ''}{d:.0f}%)"


def verdict(cur: dict, prev: dict) -> str:
    ds = cur["score"] - prev["score"]
    if ds <= -5:
        return f"⚠ 退步：正確率下降 {-ds:.1f} 分（準確率優先，其他改善不抵銷）"
    if ds >= 5:
        return f"✅ 進步：正確率提升 {ds:.1f} 分"
    better, worse = [], []
    for key, name in (("wall", "時間"), ("cost", "DeepSeek 費用")):
        a, b = cur.get(key), prev.get(key)
        if a is None or not b:
            continue
        ch = (a - b) / b
        if ch <= -0.10:
            better.append(f"{name} {ch * 100:.0f}%")
        elif ch >= 0.10:
            worse.append(f"{name} +{ch * 100:.0f}%")
    if better and not worse:
        return "✅ 進步：正確率持平，" + "、".join(better)
    if worse and not better:
        return "⚠ 退步：正確率持平，但 " + "、".join(worse)
    if better and worse:
        return "↔ 取捨：" + "、".join(better + worse)
    return "＝ 持平（差異在 10% 內，可能只是隨機波動；用 --repeat 2 再確認）"


def summarize_run(rows: list[dict]) -> dict:
    """同一次執行的多個 repeat 取平均。"""
    n = len(rows)
    avg = lambda k: None if any(r.get(k) is None for r in rows) else sum(r[k] for r in rows) / n  # noqa: E731
    first = rows[0]
    return {"run_id": first["run_id"], "label": first["label"], "server_sha": first["server_sha"],
            "skill_sha": first["skill_sha"], "ts": first["ts"], "repeats": n,
            "score": round(avg("score"), 1), "passed": round(avg("passed"), 1),
            "wall": round(avg("wall"), 1), "cost": avg("cost"), "tokens": int(avg("tokens") or 0),
            "n_levels": len(first["levels"])}


def grouped_runs(history: list[dict]) -> list[dict]:
    order, groups = [], {}
    for r in history:
        if r["run_id"] not in groups:
            order.append(r["run_id"])
            groups[r["run_id"]] = []
        groups[r["run_id"]].append(r)
    return [summarize_run(groups[k]) for k in order]


def print_history(runs: list[dict], limit: int = 12) -> None:
    print(f"\n歷史（題庫 v{SUITE_VERSION}，最近 {min(limit, len(runs))} 次）")
    print(f"{'時間':<17}{'版本':<10}{'正確率':>7}{'通過':>7}{'時間s':>8}{'費用':>10}{'tokens':>9}  標籤")
    for r in runs[-limit:]:
        print(f"{r['ts']:<17}{r['server_sha']:<10}{r['score']:>6.1f}%{r['passed']:>4g}/{r['n_levels']:<2}"
              f"{r['wall']:>8.0f}{fmt_cost(r['cost']):>10}{r['tokens']:>9}  {r['label']}"
              + (f" ×{r['repeats']}" if r["repeats"] > 1 else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=str(ROOT / "deepseek_swarm.py"))
    ap.add_argument("--label", default="")
    ap.add_argument("--levels", default="")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--effort", default="max", choices=["max", "high", "low", "none", "auto"])
    ap.add_argument("--tests", action="store_true", help="啟用伺服器端測試（test_files）")
    ap.add_argument("--review", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--history", action="store_true")
    args = ap.parse_args()

    if args.history:
        print_history(grouped_runs(load_history()), limit=50)
        return

    server = Path(args.server)
    if not server.is_absolute():
        server = (ROOT / server) if (ROOT / server).is_file() else server.resolve()
    want = {x.strip().upper() for x in args.levels.split(",") if x.strip()}
    levels = [lv for lv in LEVELS if not want or lv["id"] in want or lv["id"][:2] in want]
    if not levels:
        sys.exit("沒有符合的關卡")

    global GEN_TESTS
    GEN_TESTS = args.tests
    mod = load_server(server)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    label = args.label or server.stem
    print(f"測試 {server.name}（{sha(server)}）｜{len(levels)} 關 × {args.repeat} 次｜effort={args.effort} "
          f"review={args.review} tests={'on' if args.tests else 'off'}")

    async def run_all():  # 全部在同一個事件迴圈跑，伺服器的 HTTP 連線才不會失效
        out = []
        for k in range(args.repeat):
            ws = RUNS / f"{run_id}_r{k + 1}"
            out.append((ws, await one_round(mod, levels, ws, args.effort, args.review)))
        return out

    rows = []
    for k, (ws, res) in enumerate(asyncio.run(run_all())):
        row = {"run_id": run_id, "ts": time.strftime("%Y-%m-%d %H:%M"), "label": label,
               "suite_version": SUITE_VERSION, "server": server.name, "server_sha": sha(server),
               "skill_sha": sha(SKILL), "effort": args.effort, "review": args.review, "tests": args.tests,
               "repeat": k + 1,
               **{k2: res[k2] for k2 in ("mode", "wall", "cost", "tokens", "score", "passed", "levels", "usage")}}
        rows.append(row)
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

        print(f"\n第 {k + 1} 次｜模式={res['mode']}｜正確率 {res['score']}%｜通過 {res['passed']}/{len(levels)}"
              f"｜{res['wall']:.0f}s｜{fmt_cost(res['cost'])}｜tokens {res['tokens']}｜檔案在 {ws}")
        for lv in levels:
            v = res["levels"][lv["id"]]
            mark = "✔" if v["score"] >= 1 else ("△" if v["score"] > 0 else "✘")
            print(f"  {mark} {lv['id']:<4}{lv['name']:<14}{v['score'] * 100:>5.0f}%  {v['secs']:>5.0f}s  "
                  f"{v['model']:<6}{v['outcome']:<9}{v['note'][:70]}")

    runs = grouped_runs(load_history())
    cur = runs[-1]
    comparable = [r for r in runs[:-1] if r["n_levels"] == cur["n_levels"]]
    print_history(runs)
    if comparable:
        prev = comparable[-1]
        best = max(comparable, key=lambda r: (r["score"], -(r["wall"] or 0)))
        print(f"\n對上一次（{prev['label']}）：正確率 {cur['score']} vs {prev['score']}｜"
              f"時間 {cur['wall']:.0f}s {pct(cur['wall'], prev['wall'])}｜"
              f"費用 {fmt_cost(cur['cost'])} {pct(cur['cost'], prev['cost'])}")
        print("結論：" + verdict(cur, prev))
        if best["run_id"] != prev["run_id"]:
            print(f"對歷史最佳（{best['label']}）：" + verdict(cur, best))
    else:
        print("\n這是第一次紀錄（或關卡數不同），之後的執行會以它為比較基準。")


if __name__ == "__main__":
    main()
