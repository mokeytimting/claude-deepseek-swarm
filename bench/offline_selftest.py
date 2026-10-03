"""離線回歸測試：用「照劇本回覆的假 DeepSeek」驗證流水線各種分支，不花錢、約 30 秒。
每次改 deepseek_swarm.py / ds.py 後先跑這支，全部 ✔ 再跑真實題庫（run_bench.py）。

用法：python bench/offline_selftest.py
涵蓋：程式碼擷取（多區塊不黏）、subprocess 放行規則、資料夾鎖、仲裁（採用第二份／爭議測試修正／修不好）、
      被擋測試自動改寫、forbid_patterns（掃描與兩種格式）、有測試時 high→low、避險請求、retry 停損、缺附檔擋下。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deepseek_swarm as d  # noqa: E402

if d.dashboard_events is not None:  # 假工蜂的紀錄不要出現在使用者的儀表板
    d.dashboard_events.RUNS_DIR = Path(tempfile.mkdtemp(prefix="ds_selftest_runs_"))

REAL_EXEC = d._execute_single_task
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {'✔' if ok else '✘'} {name}" + (f"｜{detail}" if detail else ""))


FLAGS = "\n===FLAGS===\n信心: 高\n假設: 無\n疑點: 無\n未完成: 無\n===END==="
def impl(v): return f"```python\ndef f():\n    return {v}\n```" + FLAGS
def test(v, extra=""): return ("```python\nimport unittest\nfrom f import f\n" + extra + "class T(unittest.TestCase):\n"
                               f"    def test_value(self):\n        self.assertEqual(f(), {v})\n"
                               "if __name__ == '__main__':\n    unittest.main()\n```")
def ok(c): return {"status": "ok", "content": c, "usage": d._empty_usage("flash")}
def trunc(): return {"status": "truncated", "content": "", "usage": d._empty_usage("flash")}


def role_of(prompt, system):
    if system == d.REVIEW_SYSTEM_PROMPT:
        return "review"
    if "你是測試修正工蜂" in prompt:
        return "dfix"
    if "你是測試工蜂" in prompt:
        return "test"
    if "你是修正工蜂" in prompt:
        return "fix"
    return "produce"


async def run_job(script, **kw):
    async def fake(task_id, prompt, model="auto", effort="max", pick_text="", system=d.SYSTEM_PROMPT, max_tokens=0):
        return dict(script[role_of(prompt, system)].pop(0), id=task_id, model=d._pick(model, pick_text))
    d._execute_single_task = fake
    root = Path(tempfile.mkdtemp())
    msg = await d.submit_swarm_job(task_list=["寫 f"], output_root=str(root), output_files=["f.py"], **kw)
    if not msg.startswith("[SUBMITTED]"):
        return msg, None, root
    jid = msg.split("job_id=")[1].split()[0]
    while d.JOBS[jid]["finished"] is None:
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.05)
    return msg, d.JOBS[jid]["results"][0], root


def file_value(root):
    return (root / "f.py").read_text(encoding="utf-8").strip().splitlines()[-1].strip()


def tests_green(root):
    return subprocess.run([sys.executable, "tests/test_f.py"], cwd=root, capture_output=True,
                          env=dict(os.environ, PYTHONPATH=str(root))).returncode == 0


async def main():
    print("== 程式碼擷取")
    two = "```python\ndef f():\n    return 1\n```\n以下是測試：\n```python\nimport unittest\n```" + FLAGS
    code = d._extract_code_blocks(two, 1)[0][1]
    check("工蜂多回一個測試區塊時不會黏進實作檔", "unittest" not in code and "```" not in code)
    unclosed = "```python\ndef f():\n    return 1\n" + FLAGS
    check("漏了結尾 ``` 仍取得程式碼", d._extract_code_blocks(unclosed, 1)[0][1].strip().endswith("return 1"))

    print("== 測試安全檢查（subprocess 放行規則）")
    tmp = Path(tempfile.mkdtemp())
    for name, code, allowed in [
        ("[sys.executable, ...] 放行", "import subprocess, sys\nsubprocess.run([sys.executable, 'a.py'])", True),
        ("cmd 變數放行", "import subprocess, sys\ncmd=[sys.executable,'a.py']\ncmd+=['x']\nsubprocess.run(cmd)", True),
        ("shell=True 擋下", "import subprocess, sys\nsubprocess.run([sys.executable,'a.py'], shell=True)", False),
        ("任意指令擋下", "import subprocess\nsubprocess.run(['rm','-rf','/'])", False),
        ("os.system 擋下", "import os\nos.system('dir')", False),
    ]:
        p = tmp / "t.py"
        p.write_text(code, encoding="utf-8")
        check(name, (not d._unsafe_test_reason(p)) == allowed)

    print("== 資料夾鎖")
    root = Path(tempfile.mkdtemp())
    check("第一次取得", d._acquire_root_lock(root, "jA") == "")
    d.JOBS["jA"] = {"finished": None}
    check("同一資料夾有 job 在跑時擋下", d._acquire_root_lock(root, "jB") != "")
    d.JOBS["jA"]["finished"] = 1
    (root / d.LOCK_NAME).write_text(json.dumps({"pid": 999999, "job_id": "dead"}), encoding="utf-8")
    check("持有者已結束的舊鎖可接手", d._acquire_root_lock(root, "jC") == "")

    print("== 流水線分支（假 DeepSeek）")
    _, r, root = await run_job({"produce": [ok(impl(1)), ok(impl(1))], "test": [ok(test(2))], "dfix": [ok(test(1))]},
                               test_files=["tests/test_f.py"])
    check("仲裁判定測試寫錯 → 修正測試、實作不動、整份全綠",
          r["outcome"] == "pass" and file_value(root) == "return 1" and tests_green(root), r["pipeline"][-40:])
    _, r, root = await run_job({"produce": [ok(impl(1)), ok(impl(2))], "test": [ok(test(2))]}, test_files=["tests/test_f.py"])
    check("實作錯 → 採用第二份實作", r["outcome"] == "fixed" and file_value(root) == "return 2")
    _, r, root = await run_job({"produce": [ok(impl(1)), ok(impl(1))], "test": [ok(test(2))], "dfix": [ok(test(3))]},
                               test_files=["tests/test_f.py"])
    check("爭議測試修不好 → 標仍有問題（摘要與實際一致）", r["outcome"] == "issues" and not tests_green(root))
    _, r, root = await run_job({"produce": [ok(impl(2))], "test": [ok(test(2, "import os\nos.system('echo')\n")), ok(test(2))]},
                               test_files=["tests/test_f.py"])
    check("生成的測試含 os.system → 自動改寫後執行", r["outcome"] == "pass" and tests_green(root))
    _, r, root = await run_job({"produce": [ok(impl(2))], "test": [trunc()]}, test_files=["tests/test_f.py"])
    check("測試工蜂失敗 → 未測試（不算通過）", r["outcome"] == "untested")
    dirty = '```python\n"""never uses eval()"""\ndef f():\n    return 1\n```' + FLAGS
    _, r, root = await run_job({"produce": [ok(dirty)], "fix": [ok(impl(1))]}, review="off",
                               forbid_patterns=[r"(?<![.\w])eval\s*\("])
    check("forbid_patterns：docstring 寫 eval( → 退回修正", r["outcome"] == "fixed")

    print("== 送出前檢查")
    d._execute_single_task = REAL_EXEC
    root = tempfile.mkdtemp()
    msg = await d.submit_swarm_job(task_list=["a"], output_root=root, output_files=["a.py"], task_attach=["不存在.md"])
    check("附檔找不到 → 不送出", msg.startswith("[ERROR] 附檔有問題"))
    msg = await d.submit_swarm_job(task_list=["a"], output_root=root, output_files=["a.py"], forbid_patterns=["x", ["y"]])
    check("forbid_patterns 混用格式 → 可讀錯誤", msg.startswith("[ERROR] forbid_patterns"))

    async def never(*a, **k):
        await asyncio.sleep(3600)
    d._execute_single_task = never
    msg = await d.submit_swarm_job(task_list=["a", "b"], output_root=tempfile.mkdtemp(), output_files=["a.py", "b.py"],
                                   test_files=["t/ta.py", ""], efforts=["high", "high"], forbid_patterns=[[], ["import ast"]])
    jid = msg.split("job_id=")[1].split()[0]
    check("有測試的 high 改回 low、沒測試的保留", d.JOBS[jid]["efforts"] == ["low", "high"])
    check("forbid_patterns 逐任務格式", d.JOBS[jid]["forbid"] == [[], ["import ast"]])
    d.JOBS[jid]["runner"].cancel()

    print("== 避險請求")
    state = {"n": 0}

    async def slow_then_fast(task_id, prompt, model="auto", effort="max", pick_text="", system=d.SYSTEM_PROMPT, max_tokens=0):
        state["n"] += 1
        me = state["n"]
        await asyncio.sleep(5 if me == 1 else 0.1)
        return {"id": task_id, "status": "ok", "model": "flash", "content": f"call{me}", "usage": d._empty_usage("flash")}
    d._execute_single_task = slow_then_fast
    saved = dict(d.HEDGE_SECS_BY_EFFORT)
    d.HEDGE_SECS_BY_EFFORT["low"] = 0.5
    r, _ = await d._hedged_task(1, "p", "flash", "low")
    d.HEDGE_SECS_BY_EFFORT.update(saved)
    check("第一份卡住 → 備份先回來就採用", r.get("hedge_winner") == "backup")

    print("== ds.py retry 停損")
    w = Path(tempfile.mkdtemp())
    (w / ".ds_last_job.json").write_text(json.dumps({"task_list": ["a"], "output_files": ["a.py"],
                                                    "_retry_counts": {"1": 2}}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(ROOT / "ds.py"), "retry", "1", "--note", "x"], cwd=w,
                       capture_output=True, text=True, encoding="utf-8")
    check("retry 2 次後擋下（[STOP]、退出碼 3）", p.returncode == 3 and "[STOP]" in p.stdout)

    d._execute_single_task = REAL_EXEC
    print(f"\n{'全部通過' if all(results) else '有失敗'}：{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


asyncio.run(main())
