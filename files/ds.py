"""DeepSeek 工蜂指令列：一個 shell 指令完成「送出 → 等待 → 精簡摘要」，省去 Claude 的 MCP 往返。

用法（PowerShell，一次呼叫）：
    @'
    { "task_list": ["..."], "output_files": ["a.py"], "test_files": ["tests/test_a.py"] }
    '@ | Set-Content -Encoding utf8 ($f = "$env:TEMP\\ds_job_$([guid]::NewGuid().ToString('N')).json"); python C:\\mcp_tools\\ds.py run $f

任務檔名每次都要不同（多個對話同時派工時才不會互相覆蓋）；在暫存資料夾的任務檔讀完就刪除。
同一個輸出資料夾同時只能有一批任務在寫，第二批會被擋下並回報。

任務檔欄位同 submit_swarm_job 的參數（task_list、shared_context、output_files、test_files、test_cmd、
verify_cmd、efforts、models、task_attach、shared_attach、review…）。output_root / read_root 省略時用目前資料夾。
輸出：通過的任務一行帶過，有問題的任務才展開；推理題附 FINAL 行。
結束碼：0 = 全部通過或修正後通過；1 = 有任務需要 Claude 處理；2 = 任務檔或環境錯誤。
"""
import argparse
import asyncio
import inspect
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
logging.disable(logging.INFO)  # 不要 httpx 的請求紀錄（Claude 會讀進上下文）

OK_OUTCOMES = {"pass", "fixed"}
OUTCOME_LABEL = {"pass": "通過", "fixed": "修正後通過", "unreviewed": "未審查", "untested": "未測試",
                 "issues": "仍有問題", "truncated": "截斷", "error": "失敗"}


def _long_path(p: str) -> Path:
    """Windows 未開長路徑支援時，超過 260 字元的路徑讀不到；加上 \\\\?\\ 前綴繞過（實測 scratchpad 路徑 269 字元）。"""
    full = os.path.abspath(p)
    if os.name == "nt" and len(full) >= 240 and not full.startswith("\\\\?\\"):
        full = "\\\\?\\" + full
    return Path(full)


def _final_line(content: str) -> str:
    for line in reversed(content.split("===FLAGS===")[0].splitlines()):
        if line.strip().startswith("FINAL:"):
            return line.strip()
    return ""


def render_compact(d, job_id: str, job: dict) -> str:
    results = [r for r in job["results"] if r]
    counts = {}
    for r in results:
        counts[r.get("outcome")] = counts.get(r.get("outcome"), 0) + 1
    head = "｜".join(f"{OUTCOME_LABEL.get(k, k)} {v}" for k, v in counts.items())
    usage = job.get("usage") or {}
    out_tokens = sum(int(usage.get(a, {}).get("completion_tokens", 0) or 0) for a in ("flash", "pro"))
    lines = [f"[{job_id}] {int(job['finished'] - job['started'])}s｜{head}｜"
             f"DeepSeek 輸出 {out_tokens / 1000:.1f}k tokens，估計 ${d._estimate_cost(usage):.3f}（尖峰價）"]

    if job.get("final_check"):
        lines.append(job["final_check"])
    verify = job.get("verify") or {}
    if job.get("verify_cmd"):
        b, a = verify.get("before"), verify.get("after")
        word = lambda x: "?" if x is None else ("通過" if x[0] else "失敗")
        line = f"專案測試：原本{word(b)} → 現在{word(a)}"
        if a is not None and not a[0]:
            line += ("（原本就失敗）" if b is not None and not b[0] else " ⚠ 這批改壞了") + "\n" + a[1][-600:]
        lines.append(line)

    for r in results:
        outcome = r.get("outcome")
        changes = "、".join(f"{c['path']}(+{c.get('plus', 0)}/-{c.get('minus', 0)})" for c in r.get("changes", [])
                           if c.get("kind") != "unchanged")
        # FINAL 行只給推理題（不寫檔的任務）；寫檔任務的工蜂偶爾也寫 FINAL，會混淆摘要
        final = "" if r.get("changes") else _final_line(r.get("content", ""))
        tests = {"pass": "測試通過", "fail": "測試失敗", "skipped": "測試未執行",
                 "disputed": "測試通過（爭議測試經仲裁判定為測試錯）"}.get(r.get("tests", ""), "")
        if outcome in OK_OUTCOMES:
            dispute = f"｜請核對：{r['dispute']}" if r.get("dispute") else ""  # 同家族模型可能一起讀錯規格
            parts = [f"#{r['id']} ✔ {OUTCOME_LABEL[outcome]}", changes, tests + dispute, final]
            lines.append(" ".join(p for p in parts if p))
            continue
        # 需要 Claude 處理：展開細節
        lines.append(f"#{r['id']} ✘ {OUTCOME_LABEL.get(outcome, outcome)} model={r.get('model')} {changes} {tests}".rstrip())
        lines.append(f"   流程：{r.get('pipeline', '')}")
        if r.get("problem"):
            lines.append(f"   問題：{r['problem']}")
        if r.get("review_issues"):
            lines.append("   審查問題：" + "；".join(r["review_issues"][:3]))
        if r.get("syntax_errors"):
            lines.append("   語法錯：" + "；".join(r["syntax_errors"][:2]))
        if r.get("test_output"):
            lines.append("   測試輸出末段：\n" + r["test_output"][-500:])
        flags = d._extract_flags_summary(r.get("content", ""))
        if flags["high_concerns"]:
            lines.append("   高疑點：" + "；".join(flags["high_concerns"]))
        if final:
            lines.append("   " + final)
        if outcome in ("error", "truncated"):
            lines.append("   回覆末段：" + r.get("content", "")[-300:])
    lines.append(f"完整回覆：{Path(os.environ.get('DEEPSEEK_JOB_DIR', '') or Path.home() / '.deepseek_swarm_jobs') / job_id}")
    return "\n".join(lines)


LAST_JOB = ".ds_last_job.json"  # 每次派工存在輸出資料夾，供 retry 重用（Claude 不必重打任務）


async def run(spec_path: str, timeout: int) -> int:
    try:
        spec = json.loads(_long_path(spec_path).read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 任務檔讀取失敗：{type(e).__name__}: {e}")
        return 2
    # 暫存資料夾裡的任務檔讀完就刪：避免之後被別的派工誤用
    try:
        if Path(os.path.abspath(spec_path)).parent == Path(tempfile.gettempdir()).resolve():
            _long_path(spec_path).unlink()
    except OSError:
        pass
    return await run_spec(spec, timeout)


async def retry(which: str, note: str, new_tests: bool, timeout: int) -> int:
    """重派上一次派工中的指定任務：沿用原任務文字，加上修正要求，附上目前的實作與測試檔。"""
    path = Path(os.getcwd()) / LAST_JOB
    if not path.is_file():
        print(f"[ERROR] 目前資料夾沒有 {LAST_JOB}（要在上一次派工的輸出資料夾執行 retry）")
        return 2
    last = json.loads(path.read_text(encoding="utf-8-sig"))
    n = len(last["task_list"])
    try:
        picks = [int(x) - 1 for x in which.split(",") if x.strip()]
        assert picks and all(0 <= i < n for i in picks)
    except Exception:  # noqa: BLE001
        print(f"[ERROR] 任務編號要是 1–{n}，用逗號分隔，例：retry 2,3 --note \"...\"")
        return 2

    def col(key: str, default=""):
        vals = list(last.get(key) or [])
        vals += [default] * (n - len(vals))
        return [vals[i] for i in picks]

    # 停損：同一個任務最多 retry 2 次（實測同一缺陷 retry 4 次都一樣，燒掉 $2）
    counts = dict(last.get("_retry_counts") or {})
    over = [i + 1 for i in picks if counts.get(str(i + 1), 0) >= 2]
    if over:
        print(f"[STOP] 任務 {over} 已 retry 2 次仍未通過，不再重派。請 Claude 自己 Read 該檔、用 Edit 修掉，"
              f"並在回報寫明問題；或改寫任務後用 ds.py run 全新派工。")
        return 3
    root = Path(last.get("output_root") or os.getcwd())
    outs, tests, attaches = col("output_files"), col("test_files"), col("task_attach")
    spec = {k: v for k, v in last.items() if k not in (
        "task_list", "output_files", "test_files", "task_attach", "test_cmd", "efforts", "models")}
    spec["task_list"] = [t + f"\n\n【修正要求】{note}\n（附檔是目前版本的實作與測試；在它們的基礎上修正，其他行為不變。）"
                         for t in col("task_list")]
    spec["output_files"] = outs
    def existing(items) -> list:  # 逐檔檢查：多輸出檔時上一輪沒寫出來的檔不能附（會被當缺檔擋下整次 retry）
        parts = []
        for x in items:
            parts += [str(p) for p in x] if isinstance(x, (list, tuple)) else str(x or "").split(",")
        return [p.strip() for p in parts if p.strip() and (root / p.strip()).exists()]
    spec["task_attach"] = [",".join(existing((a, o, t))) for a, o, t in zip(attaches, outs, tests)]
    if new_tests:
        spec["test_files"] = tests
    else:  # 沿用現有測試當關卡（只能改實作）；測試本身有錯時用 --new-tests 重寫
        spec["test_cmd"] = [(f"python {t}" if t.endswith(".py") else f"node --test {t}") if t else "" for t in tests]
    if last.get("models"):
        spec["models"] = col("models", "auto")
    # 次數記在原本的任務檔（編號維持原派工的編號，下一次 retry 仍用同一組編號）
    for i in picks:
        counts[str(i + 1)] = counts.get(str(i + 1), 0) + 1
    last["_retry_counts"] = counts
    path.write_text(json.dumps(last, ensure_ascii=False, indent=1), encoding="utf-8")
    return await run_spec(spec, timeout, save_last=False)


def _open_dashboard() -> None:
    """即時儀表板：沒在跑就背景啟動，沒有分頁在看才開瀏覽器（DS_NO_GUI=1 關閉）。失敗不影響派工。"""
    gui_dir = Path(__file__).resolve().parent / "dashboard"
    if os.environ.get("DS_NO_GUI") or not (gui_dir / "ds_gui.py").is_file():
        return
    try:
        sys.path.insert(0, str(gui_dir))
        import ds_gui
        ds_gui.ensure_running()
    except Exception:  # noqa: BLE001
        pass


async def run_spec(spec: dict, timeout: int, save_last: bool = True) -> int:
    import deepseek_swarm as d
    if not d.API_KEY:
        print("[ERROR] 這個 shell 沒有 DEEPSEEK_API_KEY 環境變數；改用 MCP 工具 submit_swarm_job。")
        return 2
    spec.setdefault("output_root", os.getcwd())
    spec = {k: v for k, v in spec.items() if not k.startswith("_")}
    if save_last:  # 全新派工才存（retry 不覆蓋，編號與次數都沿用原派工）
        try:
            (Path(spec["output_root"]) / LAST_JOB).write_text(json.dumps(spec, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
        except OSError:
            pass
    spec.pop("job_file", None)
    allowed = set(inspect.signature(d.submit_swarm_job).parameters)
    unknown = sorted(set(spec) - allowed)
    if unknown:
        print(f"[ERROR] 任務檔有不認得的欄位 {unknown}；可用欄位：{sorted(allowed - {'job_file'})}")
        return 2
    _open_dashboard()
    msg = await d.submit_swarm_job(**spec)
    if not msg.startswith("[SUBMITTED]"):
        print(msg)
        return 2
    job_id = msg.split("job_id=")[1].split()[0]
    # 送出時的備註（附檔被略過、強度被改回 low 等）以前被丟掉，Claude 看不到；現在放在摘要最前面
    submit_notes = [ln for ln in msg.splitlines()[1:] if ln.startswith(("附檔備註", "注意"))]
    job = d.JOBS[job_id]
    deadline = time.time() + timeout
    while job["finished"] is None:
        if time.time() > deadline:
            print(f"[TIMEOUT] {job_id} 超過 {timeout}s 未完成")
            return 1
        await asyncio.sleep(0.5)
    print("\n".join(submit_notes + [render_compact(d, job_id, job)]))
    return 0 if all(r and r.get("outcome") in OK_OUTCOMES for r in job["results"]) else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "retry"])
    ap.add_argument("target", help="run：任務檔路徑；retry：要重派的任務編號，例 2 或 1,3")
    ap.add_argument("--note", default="", help="retry：修正要求（失敗訊息、要改什麼）")
    ap.add_argument("--new-tests", action="store_true", help="retry：重寫測試（預設沿用現有測試當關卡）")
    ap.add_argument("--timeout", type=int, default=1800)
    # 實測主代理會自己加 --output-root：與其報錯多花一輪，不如直接接受（等同任務檔的 output_root）
    ap.add_argument("--output-root", "--root", dest="output_root", default="")
    args = ap.parse_args()
    if args.output_root:
        os.chdir(args.output_root)
    try:
        if args.cmd == "run":
            sys.exit(asyncio.run(run(args.target, args.timeout)))
        if not args.note.strip():
            sys.exit("retry 需要 --note \"修正要求\"")
        sys.exit(asyncio.run(retry(args.target, args.note, args.new_tests, args.timeout)))
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:  # noqa: BLE001 — traceback 很長，會整段進 Claude 的上下文；改成一行
        print(f"[ERROR] ds.py 內部錯誤：{type(e).__name__}: {str(e)[:300]}（任務未送出或已中斷，可重送）")
        sys.exit(2)


if __name__ == "__main__":
    main()
