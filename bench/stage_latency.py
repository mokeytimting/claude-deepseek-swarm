"""從工作紀錄的檔案時間估算各階段耗時分布（初版產出、測試工蜂），用來設定避險門檻。

用法：python bench/stage_latency.py [最近幾個 job，預設 30]
初版產出時間 ≈ tNN.v1.md 寫入時間 − job 開始時間（job 目錄名稱的時間戳）。
"""
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
JOB_DIR = Path.home() / ".deepseek_swarm_jobs"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
jobs = sorted((p for p in JOB_DIR.iterdir() if p.is_dir() and (p / "t01.v1.md").exists()),
              key=lambda p: p.stat().st_mtime)[-n:]
produce = []
for job in jobs:
    try:
        start = datetime.strptime(job.name[:15], "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        continue
    for f in job.glob("t*.v1.md"):
        produce.append((f.stat().st_mtime - start, job.name, f.name[:3]))
produce.sort()
secs = [s for s, _, _ in produce]
if not secs:
    sys.exit("沒有資料")
q = statistics.quantiles(secs, n=20)
print(f"初版產出 {len(secs)} 筆：中位 {statistics.median(secs):.0f}s｜p75 {q[14]:.0f}s｜p90 {q[17]:.0f}s｜"
      f"p95 {q[18]:.0f}s｜最大 {secs[-1]:.0f}s")
print("最慢 6 筆：", "；".join(f"{s:.0f}s {j[-6:]}/{t}" for s, j, t in produce[-6:]))
