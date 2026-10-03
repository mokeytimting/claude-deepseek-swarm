"""把每個任務「初版」（審查、測試、修正之前）拿去跑隱藏測試，量出流水線各階段實際救回多少分。

用法：python bench/grade_v1.py [最近幾個 job，預設 3]
對應 run_bench 的任務順序（LEVELS 順序），只評寫檔的關卡。
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent))
from grading import grade_level  # noqa: E402
from levels import LEVELS  # noqa: E402
import deepseek_swarm as d  # noqa: E402

n_jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
jobs = sorted((p for p in d.JOB_DIR.iterdir() if p.is_dir() and (p / "t01.v1.md").exists()),
              key=lambda p: p.stat().st_mtime)[-n_jobs:]
for job in jobs:
    print(f"--- {job.name}")
    for i, lv in enumerate(LEVELS):
        if not lv["out"]:
            continue
        f = job / f"t{i + 1:02d}.v1.md"
        if not f.exists():
            continue
        v1 = f.read_text(encoding="utf-8")
        final = (job / f"t{i + 1:02d}.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            for name, text in lv.get("seed", {}).items():
                (ws / name).write_text(text, encoding="utf-8")
            blocks = d._extract_code_blocks(v1, 1)
            if blocks:
                (ws / lv["out"]).write_text(blocks[0][1] + "\n", encoding="utf-8")
            s1, note1 = grade_level(lv, ws)
        stages = []
        for tag in ("review", "test"):
            if (job / f"t{i + 1:02d}.{tag}.md").exists():
                stages.append(tag)
        changed = "（最終版與初版不同）" if v1.strip() != final.strip() else ""
        print(f"  {lv['id']:<4} 初版 {s1 * 100:5.1f}% {note1[:70]} {changed}")
