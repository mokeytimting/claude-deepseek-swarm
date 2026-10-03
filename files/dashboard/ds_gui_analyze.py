import json

CACHE_MIN_INPUT = 5000
CACHE_LOW_RATE = 0.5
GROWTH_RATIO = 1.5
GROWTH_MIN_INPUT = 10000
GROWTH_TOTAL_RATIO = 3
GROWTH_TOTAL_MIN = 20000
TURN_WARN = 0.8
REPEAT_MIN = 3
ERROR_MIN_CALLS = 5
ERROR_RATE = 0.3
VERIFY_FAIL_MIN = 2
THINK_MIN_OUT = 2000
THINK_RATE = 0.7
BIG_ROUND_WARN = 50000
BIG_ROUND_HIGH = 100000
CACHE_WRITE_MIN = 20000

GROW_HINT = "工具輸出太長累積在對話裡；只讀需要的片段（read_file 用 offset/limit、grep 限制結果數量）"
SEV_ORDER = {"high": 0, "warn": 1, "info": 2}


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _finding(fid, severity, title, detail, hint):
    return {"id": fid, "severity": severity, "title": title, "detail": detail, "hint": hint}


def _sorted(findings):
    return sorted(findings, key=lambda f: SEV_ORDER.get(f.get("severity"), 3))


def _rounds(events):
    out = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        call = e.get("call")
        if not isinstance(call, dict):
            continue
        out.append((e.get("conv") or "main", _num(call.get("in"))))
    return out


def _by_conv(rounds):
    groups = {}
    for conv, value in rounds:
        groups.setdefault(conv, []).append(value)
    return list(groups.values())


def analyze_run(summary, events):
    summary = summary if isinstance(summary, dict) else {}
    events = events or []
    tokens = summary.get("tokens") if isinstance(summary.get("tokens"), dict) else None
    source = summary.get("source")
    out = []

    if tokens:
        total_in = _num(tokens.get("in"))
        if total_in >= CACHE_MIN_INPUT:
            rate = _num(tokens.get("hit")) / total_in
            if rate < CACHE_LOW_RATE:
                out.append(_finding("cache_low", "warn", "快取命中率偏低",
                                    f"輸入 {total_in:,} tokens，快取命中率只有 {rate * 100:.0f}%",
                                    "前面內容每輪都在變動；固定的系統提示與簡報放最前面，不要每輪更動"))

    rounds = _rounds(events)
    convs = _by_conv(rounds)
    growth, best = None, None
    for seq in convs:
        if len(seq) >= 4 and seq[-1] >= seq[0] * GROWTH_TOTAL_RATIO and seq[-1] >= GROWTH_TOTAL_MIN:
            ratio = seq[-1] / seq[0] if seq[0] > 0 else float("inf")
            if best is None or ratio > best:
                best, growth = ratio, seq
    if growth:
        out.append(_finding("context_growth", "warn", "對話越長越大",
                            f"輸入從第 1 輪 {growth[0]:,} tokens 長到第 {len(growth)} 輪 {growth[-1]:,} tokens",
                            GROW_HINT))

    jump = None
    for seq in convs:
        for i in range(1, len(seq)):
            prev, cur = seq[i - 1], seq[i]
            if cur > prev * GROWTH_RATIO and cur >= GROWTH_MIN_INPUT:
                span = cur - prev
                if jump is None or span > jump[0]:
                    jump = (span, i + 1, prev, cur)
    if jump:
        out.append(_finding("context_jump", "info", "單輪輸入突然變大",
                            f"第 {jump[1]} 輪輸入 {jump[3]:,} tokens，比上一輪的 {jump[2]:,} 大幅增加",
                            GROW_HINT))

    biggest = max([v for _, v in rounds] or [0])
    if biggest >= BIG_ROUND_HIGH:
        out.append(_finding("big_round", "high", "單輪輸入過大", f"最大單輪輸入 {biggest:,} tokens",
                            "單輪送出內容過大；拆小任務或開新對話"))
    elif biggest >= BIG_ROUND_WARN:
        out.append(_finding("big_round", "warn", "單輪輸入偏大", f"最大單輪輸入 {biggest:,} tokens",
                            "單輪送出內容過大；拆小任務或開新對話"))

    turns, max_turns = summary.get("turns"), summary.get("max_turns")
    if source == "ds" and turns is not None and _num(max_turns) > 0:
        turns, max_turns = _num(turns), _num(max_turns)
        if turns >= max_turns:
            out.append(_finding("turn_limit", "high", "輪數已達上限", f"已用 {turns} / {max_turns} 輪",
                                "任務太大或卡住；拆小或改用 Pro"))
        elif turns >= max_turns * TURN_WARN:
            out.append(_finding("turn_limit", "warn", "輪數接近上限", f"已用 {turns} / {max_turns} 輪",
                                "任務太大或卡住；拆小或改用 Pro"))

    seen, order = {}, []
    for e in events:
        if not isinstance(e, dict) or "tool" not in e or e.get("tool") == "finish":
            continue
        key = (e.get("tool"), json.dumps(e.get("args") or {}, sort_keys=True))
        if key not in seen:
            seen[key] = 0
            order.append(key)
        seen[key] += 1
    repeats = sorted([(k, seen[k]) for k in order if seen[k] >= REPEAT_MIN], key=lambda kc: -kc[1])
    if repeats:
        detail = "；".join(f"{k[0]} × {c}（{k[1][:60]}）" for k, c in repeats[:3])
        out.append(_finding("repeat_calls", "warn", "重複呼叫相同工具", detail, "可能在原地打轉；檢查簡報是否不清楚"))

    calls, errors = _num(summary.get("tool_calls")), _num(summary.get("errors"))
    if calls >= ERROR_MIN_CALLS and errors / calls >= ERROR_RATE:
        out.append(_finding("error_rate", "warn", "工具錯誤率偏高",
                            f"{calls} 次工具呼叫中有 {errors} 次錯誤（{errors / calls * 100:.0f}%）",
                            "先修掉常見錯誤再做下一輪；確認路徑、指令與參數是否正確"))

    runs = summary.get("verify_runs")
    if isinstance(runs, list):
        fails = sum(1 for x in runs if _num(x) != 0)
        if fails >= VERIFY_FAIL_MIN:
            out.append(_finding("verify_fail", "warn", "驗收多次失敗", f"驗收失敗 {fails} 次（共 {len(runs)} 次）",
                                "先在本機重跑驗收指令，把完整錯誤訊息交給代理"))
    if summary.get("escalated"):
        out.append(_finding("escalated_pro", "info", "Flash 修不好，已由 Pro 接手", "已觸發升級，後段由 Pro 完成",
                            "常常升級代表簡報或驗收條件不夠明確"))

    if tokens:
        think, output = _num(tokens.get("think")), _num(tokens.get("out"))
        if think > 0 and output >= THINK_MIN_OUT and think / output >= THINK_RATE:
            out.append(_finding("think_heavy", "info", "推理佔輸出大半",
                                f"推理 {think:,} / 輸出 {output:,} tokens（{think / output * 100:.0f}%）",
                                "推理佔輸出大半；規格明確的機械任務可加 --effort off"))
        write, hit = _num(tokens.get("write")), _num(tokens.get("hit"))
        if source == "claude" and write >= CACHE_WRITE_MIN and write > hit:
            out.append(_finding("cache_write_heavy", "info", "快取寫入偏多",
                                f"快取寫入 {write:,} tokens，高於快取讀取 {hit:,}",
                                "同一段內容一直重寫快取；把固定內容集中放最前面"))

    return _sorted(out)


def analyze_overview(items):
    items = list(items or [])
    totals = {"ds": {"in": 0, "hit": 0, "out": 0}, "claude": {"in": 0, "hit": 0, "out": 0}}
    groups, tops, issues, order = {}, [], {}, []
    total_in = 0
    for summary, events in items:
        summary = summary if isinstance(summary, dict) else {}
        source = "claude" if summary.get("source") == "claude" else "ds"
        tokens = summary.get("tokens") if isinstance(summary.get("tokens"), dict) else None
        value_in = _num(tokens.get("in")) if tokens else 0
        value_out = _num(tokens.get("out")) if tokens else 0
        if tokens:
            totals[source]["in"] += value_in
            totals[source]["hit"] += _num(tokens.get("hit"))
            totals[source]["out"] += value_out
            total_in += value_in
            tops.append({"id": summary.get("id"), "title": summary.get("title"), "source": source,
                         "in": value_in, "out": value_out})
        group = summary.get("group") if isinstance(summary.get("group"), dict) else {}
        key = group.get("key") or "none"
        row = groups.setdefault(key, {"key": key, "label": group.get("label") or key,
                                      "kind": group.get("kind") or "chat", "runs": 0, "in": 0, "out": 0})
        row["runs"] += 1
        row["in"] += value_in
        row["out"] += value_out
        for f in analyze_run(summary, events):
            fid = f.get("id")
            if fid not in issues:
                issues[fid] = {"id": fid, "severity": f.get("severity"), "title": f.get("title"),
                               "count": 0, "run_ids": []}
                order.append(fid)
            item = issues[fid]
            item["count"] += 1
            rid = summary.get("id")
            if rid is not None and rid not in item["run_ids"] and len(item["run_ids"]) < 10:
                item["run_ids"].append(rid)
    tops.sort(key=lambda x: -x["in"])
    top = [{**x, "share": round(x["in"] / total_in, 3) if total_in else 0.0} for x in tops[:5]]
    glist = sorted(groups.values(), key=lambda g: -g["in"])
    ilist = sorted([issues[k] for k in order], key=lambda i: (SEV_ORDER.get(i["severity"], 3), -i["count"]))
    return {"runs": len(items), "totals": totals, "top": top, "groups": glist, "issues": ilist}


def _text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b["text"]) for b in content
                   if isinstance(b, dict) and isinstance(b.get("text"), str))
    return 0


def analyze_session(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except (OSError, TypeError, ValueError) as e:
        return {"error": f"讀不到對話紀錄：{type(e).__name__}"}
    rounds, order = {}, []
    stats = {"tools": {}, "names": {}, "results": [], "images": 0}

    def scan(blocks):
        for b in blocks or []:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "tool_use":
                name = b.get("name") or "?"
                stats["tools"][name] = stats["tools"].get(name, 0) + 1
                if b.get("id"):
                    stats["names"][b["id"]] = name
            elif kind == "image":
                stats["images"] += 1
            elif kind == "tool_result":
                tid = b.get("tool_use_id")
                content = b.get("content")
                stats["results"].append({"tool": stats["names"].get(tid, "?"),
                                         "chars": _text_len(content), "tool_use_id": tid})
                scan(content if isinstance(content, list) else [])

    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        message = e.get("message") if isinstance(e.get("message"), dict) else {}
        kind = e.get("type") or message.get("role")
        if kind == "assistant":
            mid = message.get("id") or f"line{len(order)}"
            fresh = mid not in rounds
            if fresh:
                rounds[mid] = {}
                order.append(mid)
            if isinstance(message.get("usage"), dict):
                rounds[mid] = message["usage"]
            if fresh:
                scan(message.get("content") if isinstance(message.get("content"), list) else [])
        elif kind == "user":
            scan(message.get("content") if isinstance(message.get("content"), list) else [])

    sums = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
    processed, peak, first = 0, 0, None
    for mid in order:
        usage = rounds[mid]
        context = (_num(usage.get("input_tokens")) + _num(usage.get("cache_creation_input_tokens"))
                   + _num(usage.get("cache_read_input_tokens")))
        for key in sums:
            sums[key] += _num(usage.get(key))
        processed += context
        peak = max(peak, context)
        if first is None:
            first = context
    turns = len(order)
    tools = [{"name": n, "count": c}
             for n, c in sorted(stats["tools"].items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
    results = sorted(stats["results"], key=lambda r: -r["chars"])
    big = results[:5]
    findings = []
    if peak >= 150000:
        findings.append(_finding("long_context", "high", "對話上下文過長", f"尖峰上下文 {peak:,} tokens",
                                 "每一輪都會重送整段對話；開新對話並用交接檔延續"))
    elif peak >= 80000:
        findings.append(_finding("long_context", "warn", "對話上下文偏長", f"尖峰上下文 {peak:,} tokens",
                                 "每一輪都會重送整段對話；開新對話並用交接檔延續"))
    if stats["images"] >= 5:
        findings.append(_finding("many_images", "warn", "截圖過多", f"共 {stats['images']} 張圖片",
                                 "截圖很吃 token；改用文字方式驗證"))
    if big and big[0]["chars"] >= 20000:
        findings.append(_finding("big_tool_results", "warn", "工具輸出過大",
                                 f"最大工具輸出 {big[0]['chars']:,} 字（{big[0]['tool']}）",
                                 "工具輸出太大會留在上下文；只讀需要的部分"))
    if turns >= 100:
        findings.append(_finding("long_session", "info", "對話輪數很多", f"共 {turns} 輪",
                                 "考慮開新對話，用交接檔帶上必要狀態"))
    return {"turns": turns,
            "input": {"fresh": sums["input_tokens"], "cache_write": sums["cache_creation_input_tokens"],
                      "cache_read": sums["cache_read_input_tokens"], "output": sums["output_tokens"]},
            "processed": processed, "peak_context": peak, "first_context": first or 0, "images": stats["images"],
            "tools": tools, "big_results": big, "findings": _sorted(findings)}
