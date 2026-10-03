"""評分：把隱藏測試放進工作資料夾執行，回傳 (得分比例, 說明)。"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# 測試裡用的迷你斷言庫（每個頂層敘述各自計分，一行錯不會拖垮整關）
HELPER = r'''
import math
def eq(a, b):
    assert a == b, f"預期 {b!r}，得到 {a!r}"
def close(a, b):
    assert isinstance(a, (int, float)) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"預期 {b!r}，得到 {a!r}"
def ok(x):
    assert x, "條件不成立"
def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return
    except Exception as e:
        raise AssertionError(f"{fn.__name__}{args!r} 應拋 {exc.__name__}，卻拋 {type(e).__name__}")
    raise AssertionError(f"{fn.__name__}{args!r} 應拋 {exc.__name__}，卻沒拋")
'''

RUNNER = r'''
import ast, sys
sys.path.insert(0, ".")
src = open(sys.argv[1], encoding="utf-8").read()
ns, ok, fails = {}, 0, []
stmts = ast.parse(src).body
for st in stmts:
    try:
        exec(compile(ast.Module([st], []), "test", "exec"), ns)
        ok += 1
    except BaseException as e:
        fails.append(f"第{st.lineno}行 {type(e).__name__}: {str(e)[:120]}")
for f in fails[:4]:
    print("FAIL", f)
print(f"SCORE {ok}/{len(stmts)}")
'''

FINAL_RE = re.compile(r"FINAL\s*[:：]\s*`?\s*(-?[\d,]+)")


def _run(cmd: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return -1, "逾時"


def grade_level(level: dict, ws: Path, content: str = "") -> tuple[float, str]:
    kind = level["kind"]
    if kind == "final":
        found = FINAL_RE.findall(content or "")
        want = level["answer"]()
        if not found:
            return 0.0, "沒有 FINAL 行"
        got = int(found[-1].replace(",", ""))
        return (1.0, f"FINAL={got} 正確") if got == want else (0.0, f"FINAL={got}，正解 {want}")

    out = ws / level["out"]
    if not out.is_file() or out.stat().st_size == 0:
        return 0.0, "沒有產出檔案"

    if kind == "py":
        (ws / "pytest_like.py").write_text(HELPER, encoding="utf-8")
        (ws / "_runner.py").write_text(RUNNER, encoding="utf-8")
        test = ws / f"_test_{level['id']}.py"
        test.write_text(level["test"].strip() + "\n", encoding="utf-8")
        _, text = _run([sys.executable, "_runner.py", test.name], ws)
        m = re.search(r"SCORE (\d+)/(\d+)", text)
        if not m:
            return 0.0, "評分程式沒有輸出：" + text.strip()[-150:]
        a, b = int(m.group(1)), int(m.group(2))
        fails = [ln[5:] for ln in text.splitlines() if ln.startswith("FAIL ")]
        return a / b, f"{a}/{b}" + (f"｜{fails[0]}" if fails else "")

    if kind == "js":
        test = ws / f"_test_{level['id']}.mjs"
        test.write_text(level["test"].strip() + "\n", encoding="utf-8")
        code, text = _run(["node", test.name], ws)
        if code == 0 and "ALL_OK" in text:
            return 1.0, "全部通過"
        first = next((ln for ln in text.splitlines() if "Error" in ln or "expected" in ln.lower()), text.strip()[:150])
        return 0.0, first.strip()[:150]

    if kind == "jsscore":  # JS 逐條計分（測試印 SCORE a/b）
        test = ws / f"_test_{level['id']}.mjs"
        test.write_text(level["test"].strip() + "\n", encoding="utf-8")
        _, text = _run(["node", test.name], ws)
        m = re.search(r"SCORE (\d+)/(\d+)", text)
        if not m:
            return 0.0, "評分程式沒有輸出：" + text.strip()[-150:]
        a, b = int(m.group(1)), int(m.group(2))
        fails = [ln[5:] for ln in text.splitlines() if ln.startswith("FAIL ")]
        return a / b, f"{a}/{b}" + (f"｜{fails[0]}" if fails else "")

    return 0.0, f"未知關卡類型 {kind}"
