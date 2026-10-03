"""彙總／比對測試結果（history.jsonl）。

用法：
    python bench/compare.py                         彙總自己的 bench/history.jsonl
    python bench/compare.py 朋友的history.jsonl      朋友的結果與自己的並排
    python bench/compare.py A.jsonl B.jsonl --json  輸出 JSON（給報告用）
只比題庫版本相同（suite_version）的紀錄；同一個標籤的多次執行合併成一組。
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BENCH = Path(__file__).resolve().parent


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def summarize(rows: list[dict], suite: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("suite_version") == suite:
            groups.setdefault(r["label"], []).append(r)
    out = []
    for label, rs in groups.items():
        walls = [r["wall"] for r in rs]
        levels: dict[str, list[float]] = {}
        for r in rs:
            for lid, lv in r["levels"].items():
                levels.setdefault(lid, []).append(lv["score"])
        out.append({
            "label": label, "runs": len(rs), "ts": rs[-1]["ts"],
            "score": round(statistics.mean(r["score"] for r in rs), 1),
            "wall_avg": round(statistics.mean(walls)), "wall_max": round(max(walls)),
            "wall_min": round(min(walls)),
            "cost": round(statistics.mean(r["cost"] or 0 for r in rs), 3),
            "levels": {k: round(100 * statistics.mean(v), 1) for k, v in levels.items()},
        })
    return out


def bootstrap_diff(a: list[float], b: list[float], n: int = 10000, seed: int = 0) -> tuple[float, float, float, float]:
    """B 相對 A 的平均差（%）與 95% 信賴區間，以及「B 比 A 小」的機率（bootstrap 重抽樣）。
    樣本少時（每組 2–3 次）區間會很寬：區間跨過 0 就代表還不能下結論。"""
    import random
    rng = random.Random(seed)
    base = statistics.mean(a)
    diffs = []
    for _ in range(n):
        ma = statistics.mean(rng.choice(a) for _ in a)
        mb = statistics.mean(rng.choice(b) for _ in b)
        diffs.append((mb - ma) / ma * 100 if ma else 0.0)
    diffs.sort()
    return ((statistics.mean(b) - base) / base * 100 if base else 0.0,
            diffs[int(0.025 * n)], diffs[int(0.975 * n)], sum(d < 0 for d in diffs) / n)


def diff_report(rows: list[dict], suite: int, label_a: str, label_b: str) -> None:
    ga = [r for r in rows if r.get("suite_version") == suite and r["label"].startswith(label_a)]
    gb = [r for r in rows if r.get("suite_version") == suite and r["label"].startswith(label_b)]
    if not ga or not gb:
        print(f"找不到標籤：{label_a if not ga else label_b}")
        return
    print(f"A = {label_a}（{len(ga)} 次）  B = {label_b}（{len(gb)} 次）")
    for key, name in (("score", "正確率"), ("wall", "時間"), ("cost", "費用")):
        a, b = [float(r[key] or 0) for r in ga], [float(r[key] or 0) for r in gb]
        d, lo, hi, p_less = bootstrap_diff(a, b)
        verdict = ("兩組相同" if lo == hi == 0 else "可下結論：B 較小" if hi < 0 else "可下結論：B 較大" if lo > 0
                   else "還不能下結論（區間跨過 0，要多跑幾次）")
        print(f"  {name}：B 比 A {d:+.1f}%（95% 區間 {lo:+.1f}% ～ {hi:+.1f}%，B 較小的機率 {p_less:.0%}）→ {verdict}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--suite", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff", nargs=2, metavar=("標籤A", "標籤B"), help="兩組設定的差異與 95% 信賴區間（標籤開頭比對）")
    args = ap.parse_args()
    if args.diff:
        f = Path(args.files[0]) if args.files else BENCH / "history.jsonl"
        diff_report(load(f), args.suite, *args.diff)
        return
    files = [Path(f) for f in args.files] or [BENCH / "history.jsonl"]
    result = {f.name if len(files) == 1 else str(f): summarize(load(f), args.suite) for f in files}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    for name, groups in result.items():
        print(f"=== {name}（題庫 v{args.suite}）")
        print(f"{'標籤':<34}{'次數':>4}{'正確率':>8}{'平均':>7}{'最快':>6}{'最慢':>6}{'費用':>8}")
        for g in groups:
            weak = "、".join(f"{k} {v}%" for k, v in sorted(g["levels"].items()) if v < 100)
            print(f"{g['label'][:32]:<34}{g['runs']:>4}{g['score']:>7.1f}%{g['wall_avg']:>6}s"
                  f"{g['wall_min']:>5}s{g['wall_max']:>5}s{g['cost']:>8.3f}" + (f"  失分：{weak}" if weak else ""))
        print()


if __name__ == "__main__":
    main()
