"""等待 DeepSeek 背景批次完成，完成後印出摘要（同 get_swarm_job 的 brief）。

用法：python wait_job.py <job_id> [--timeout 秒]
  省略 job_id 時等最新的一個 job。
  Claude 用 shell 背景執行它：整段等待只算一次工具呼叫，完成時自動通知。
結束碼：0=完成；1=逾時（印出目前進度）；2=找不到 job。
"""

import argparse
import os
import sys
import time
from pathlib import Path

JOB_DIR = Path(os.environ.get("DEEPSEEK_JOB_DIR", "").strip() or (Path.home() / ".deepseek_swarm_jobs"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id", nargs="?", default="")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    if args.job_id:
        job_dir = JOB_DIR / args.job_id
    else:
        dirs = sorted((d for d in JOB_DIR.glob("*") if d.is_dir()), key=lambda d: d.stat().st_mtime)
        if not dirs:
            print(f"[ERROR] {JOB_DIR} 內沒有任何 job")
            return 2
        job_dir = dirs[-1]

    summary = job_dir / "summary.txt"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if summary.is_file():
            print(summary.read_text(encoding="utf-8"))
            return 0
        if not job_dir.exists() and time.time() > deadline - args.timeout + 30:
            print(f"[ERROR] 找不到 {job_dir}")
            return 2
        time.sleep(3)

    done = len(list(job_dir.glob("t[0-9][0-9].md")))
    print(f"[TIMEOUT] {job_dir.name} 等待 {args.timeout}s 仍未完成；已完成任務檔 {done} 個。"
          f"用 get_swarm_job 看各任務階段。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
