"""彙總仲裁觸發率（讀每個 job 的 manifest.json）：累積 10–20 次後再決定要不要調整仲裁。

用法：python bench/arb_stats.py [最近幾個 job，預設 50]
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
JOB_DIR = Path.home() / ".deepseek_swarm_jobs"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
mans = sorted(JOB_DIR.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)[-n:]
tasks = [t for m in mans for t in json.loads(m.read_text(encoding="utf-8")).get("tasks", []) if t.get("arbitration")]
tested = [t for t in tasks if t["arbitration"].get("first_failures") is not None]
failed = [t for t in tested if t["arbitration"]["first_failures"]]
results = Counter(t["arbitration"].get("result") or "未仲裁" for t in failed)
tokens = sum(t["arbitration"].get("tokens", 0) for t in failed)
label = {"test_wrong": "判定測試寫錯", "adopt_alt": "採用第二份實作", "inconclusive": "無定論→修正",
         "alt_failed": "第二份實作失敗→修正", "未仲裁": "未仲裁"}
print(f"最近 {len(mans)} 個 job：有執行測試的任務 {len(tested)} 個，第一次測試失敗 {len(failed)} 個"
      f"（{len(failed) / len(tested):.0%}）" if tested else "還沒有資料（新版 manifest 才有仲裁紀錄）")
for k, v in results.most_common():
    print(f"  {label.get(k, k)}：{v}")
if failed:
    print(f"  仲裁多花的 DeepSeek 輸出：{tokens / 1000:.1f}k tokens（平均每次 {tokens / len(failed) / 1000:.1f}k）")
