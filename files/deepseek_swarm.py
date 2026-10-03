"""DeepSeek 工蜂 MCP 伺服器（stdio）。

注意：這是 stdio MCP 伺服器，stdout 專供協定通訊。
任何除錯訊息一律用 log() 印到 stderr，絕對不要在這裡 print()。

模型選擇：
  每個任務可指定 model = "auto" | "flash" | "pro"。
  auto 依任務文字自動挑選：偏重記憶的冷門知識（歷史、典故、專有名詞、法規、文獻等）用 pro，
  其餘（程式、推理、數學、寫作、含圖片）用 flash。
  某模型呼叫失敗時會自動改用另一個模型重試一次。
  一律開啟思考模式，推理強度 effort 預設 max。

長任務（避免 MCP 用戶端約 60 秒逾時）：
  submit_swarm_job 立即回傳 job_id，任務在背景執行；
  get_swarm_job 每次最多等待約 40 秒後回報進度，完成後回傳各任務狀態與 FLAGS。
  可用 output_root + output_files 讓伺服器直接把程式碼區塊寫成檔案。
  每個任務的完整回覆另存於 DEEPSEEK_JOB_DIR（預設 ~/.deepseek_swarm_jobs/<job_id>/）。

環境變數：
  DEEPSEEK_API_KEY        必填，DeepSeek API 金鑰
  DEEPSEEK_BASE_URL       選填，預設 https://api.deepseek.com
  DEEPSEEK_FLASH_MODEL    選填，flash 對應的實際模型名，預設 deepseek-flash
  DEEPSEEK_PRO_MODEL      選填，pro 對應的實際模型名，預設 deepseek-v4-pro
  DEEPSEEK_MAX_TOKENS     選填，單次輸出上限（含思考），預設 65536
  DEEPSEEK_TIMEOUT        選填，單次請求逾時秒數，預設 600
  DEEPSEEK_CONCURRENCY    選填，最大並發數，預設 10
  DEEPSEEK_PRICES         選填，JSON 價格（USD/百萬 token）
"""

import ast
import asyncio
import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from openai import AsyncOpenAI


def log(msg: str) -> None:
    print(f"[deepseek-swarm] {msg}", file=sys.stderr, flush=True)


# 用量儀表板的事件紀錄（可選）：檔案不在或載入失敗都只記一行 stderr，不影響工蜂工作
try:
    import dashboard_events
except Exception as _dash_err:  # noqa: BLE001
    dashboard_events = None
    log(f"儀表板事件紀錄無法載入（{type(_dash_err).__name__}: {_dash_err}）：工蜂照常執行，只是儀表板不會有紀錄")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        log(f"環境變數 {name}={raw!r} 不是正整數，改用預設值 {default}")
        return default


def _get_secret(name: str) -> str:
    """先讀行程環境變數；讀不到時（剛 setx、app 或終端機還沿用舊環境）改讀使用者環境變數的登錄檔。"""
    value = os.environ.get(name, "").strip()
    if value or sys.platform != "win32":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


API_KEY = _get_secret("DEEPSEEK_API_KEY")
BASE_URL = _get_secret("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
MODEL_MAP = {
    "flash": os.environ.get("DEEPSEEK_FLASH_MODEL", "").strip() or "deepseek-flash",
    "pro": os.environ.get("DEEPSEEK_PRO_MODEL", "").strip() or "deepseek-v4-pro",
}
AUTO_MODEL = "flash"
MAX_TOKENS = _env_int("DEEPSEEK_MAX_TOKENS", 65536)
TIMEOUT = _env_int("DEEPSEEK_TIMEOUT", 600)
CONCURRENCY = _env_int("DEEPSEEK_CONCURRENCY", 10)

DEFAULT_PRICES = {
    "flash": {"hit": 0.006, "miss": 0.3, "out": 1.2},
    "pro": {"hit": 0.044, "miss": 1.32, "out": 3.96},
}


def _load_prices() -> dict:
    raw = os.environ.get("DEEPSEEK_PRICES", "").strip()
    result = {
        alias: dict(DEFAULT_PRICES[alias])
        for alias in ("flash", "pro")
    }
    if not raw:
        return result
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log(f"DEEPSEEK_PRICES 不是有效 JSON，使用預設估計價格：{type(e).__name__}: {e}")
        return result
    if not isinstance(data, dict):
        log("DEEPSEEK_PRICES 必須是 JSON 物件，使用預設估計價格")
        return result
    for alias in ("flash", "pro"):
        bucket = data.get(alias)
        if not isinstance(bucket, dict):
            continue
        for key in result[alias]:
            value = bucket.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                result[alias][key] = float(value)
    return result


PRICES = _load_prices()

ModelChoice = Literal["auto", "flash", "pro"]
EffortChoice = Literal["max", "high", "low"]
VALID_MODELS = ("auto", "flash", "pro")
# 註：曾實驗 effort "none"（關閉思考）：推理題 3 次都答錯，程式題雖正確但時間與費用沒有比 low 好，已不開放。
VALID_EFFORTS = ("max", "high", "low")


def _env_effort(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip().lower()
    return value if value in VALID_EFFORTS else default


# 輔助角色的推理強度：預設跟著該任務的強度（Claude 逐任務決定）走；
# 環境變數有設時一律用環境變數（全域覆寫）。
REVIEW_EFFORT = _env_effort("DEEPSEEK_REVIEW_EFFORT", "")
TEST_EFFORT = _env_effort("DEEPSEEK_TEST_EFFORT", "")
FIX_EFFORT = _env_effort("DEEPSEEK_FIX_EFFORT", "")

# 審查員的輸出上限（含思考）。審查結果只有幾行，思考失控時提早截斷、改由另一模型 low 重審；
# 實測 pro 審查曾對 2 行修改想到 65k 上限、耗時 6.5 分鐘。
REVIEW_MAX_TOKENS = _env_int("DEEPSEEK_REVIEW_MAX_TOKENS", 16000)
# 註：曾試過依強度限制初次產出上限（low 24k）以壓住偶發的思考失控，實測反而截斷正常的困難任務、
# 換模型後準確率下降且費用 +22%，已撤回。

ROLE_EFFORT_MAP = {
    # 任務強度: (審查, 測試, 修正)
    # 低強度任務：審查、測試都輕量；需要修正代表出錯了，修正升一級。
    # （曾把測試固定 high，實測測試工蜂變成最慢的一段：50–90 秒，且沒有減少「測試寫錯」的情況）
    "low": ("low", "low", "high"),
    "none": ("low", "low", "high"),   # 不思考的產出：測試仍用 low 寫，修正升到 high
    "high": ("high", "high", "high"),
    "max": ("high", "high", "max"),   # 困難任務：審查/測試 high 已足夠，修正用 max
}


def _role_effort(role: str, task_effort: str) -> str:
    override = {"review": REVIEW_EFFORT, "test": TEST_EFFORT, "fix": FIX_EFFORT}[role]
    if override:
        return override
    review, test, fix = ROLE_EFFORT_MAP.get(task_effort, ROLE_EFFORT_MAP["high"])
    return {"review": review, "test": test, "fix": fix}[role]

if not API_KEY:
    log("警告：未設定 DEEPSEEK_API_KEY，所有工具呼叫都會回傳錯誤。")

SYSTEM_PROMPT = """你是頂尖執行工程師兼助教。請嚴格依據指示產出完整、無缺漏且可直接運行的成果，嚴禁使用 // TODO、「其餘省略」或任何形式的偷工減料。必須遵守任務中給定的函式簽章、型別與介面，不得自行更改。程式碼請放在標註語言的 Markdown 程式碼區塊中。

作答流程（在內部完成，不要寫進輸出）：
1. 完成初稿。
2. 逐條對照任務的要求與限制檢查一次，漏了就補。
3. 挑最關鍵的 2–3 個邊界情況驗證，有錯就修。做完直接輸出，不要反覆重審（之後另有審查員）。
不確定的事實不要編造，寫進疑點。
規格指定了例外型別時，語言內建可能丟出的其他例外（ZeroDivisionError、OverflowError、IndexError、KeyError 等）
要攔下改丟規格指定的例外；日期、數字等格式要照規格逐字嚴格檢查（例：YYYY-MM-DD 必須補零）。
每個檔案只輸出一個程式碼區塊；不要另外附測試或範例區塊。
規格禁止使用的函式、模組或寫法，連名稱都不要出現在輸出的任何地方（包括註解、docstring、字串），
也不要寫「本程式沒有使用 X」之類的聲明——原始碼掃描會把名稱本身判為違規。

輸出規則：只輸出最終成品，不要思考過程、草稿、開場白或解釋。
若任務要求 FINAL 行，把 `FINAL: <答案>` 放在成品最後一行（FLAGS 區塊之前），答案用純文字（例 13/28），不要 LaTeX 或 Markdown。
成品之後必須附上：
===FLAGS===
信心: 高|中|低
假設: <因資訊不足而自行決定的事；無則寫「無」>
疑點: [高|中|低] <位置> — <可能錯的原因> — <最快驗證法>（可多條；無則寫「無」並說明理由）
未完成: <沒做到的要求；無則寫「無」>
===END===
高=可能錯且後果嚴重（安全、金額、資料遺失、核心邏輯）；中=邊界情況或未驗證的假設；低=次要細節。寧可多標。"""

# 審查工蜂專用：不做多輪自審、不輸出 FLAGS，避免思考爆量截斷
REVIEW_SYSTEM_PROMPT = """你是程式審查員。依規格逐條檢查一次程式，只找依規格明確會出錯的問題。
思考保持精簡：不要重寫程式、不要反覆推演同一段。
只輸出指定格式，不要開場白、解釋或 FLAGS 區塊。"""

mcp = FastMCP("DeepSeek-Parallel-Swarm")
client = AsyncOpenAI(
    api_key=API_KEY or "missing-key",
    base_url=BASE_URL,
    timeout=TIMEOUT,
    max_retries=2,
)
semaphore = asyncio.Semaphore(CONCURRENCY)

TRUNCATION_WARNING = (
    "\n\n[警告：輸出達到長度上限被截斷，以上內容不完整。"
    "請將任務拆小後重新指派。]"
)


KNOWLEDGE_HINTS = re.compile(
    r"(歷史|史實|年代|哪一年|朝代|冷門|典故|出處|文獻|古籍|專有名詞|生平|法規|條文|判例|"
    r"物種|學名|考據|trivia|history|historical|obscure|citation|who was|which year|biography)",
    re.I,
)


def _pick(model: str, task_text: str = "") -> str:
    """把 auto/flash/pro 轉成 flash 或 pro；auto 依任務文字挑選。"""
    if model != "auto":
        return model
    return "pro" if KNOWLEDGE_HINTS.search(task_text or "") else AUTO_MODEL


def _final_alias(model_str: str) -> str:
    """從回傳的 model 字串中取出最終使用的別名（若失敗切換過則取最後一個）。"""
    if "→" in model_str:
        return model_str.split("→")[-1].strip()
    return model_str


def _empty_usage(alias: str = "flash") -> dict:
    return {
        "model": alias,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "reasoning_tokens": 0,
    }


def _extract_usage(alias: str, response) -> dict:
    """從 OpenAI response 取 usage，缺漏欄位視為 0。"""
    usage = _empty_usage(alias)
    if response is None:
        return usage
    resp_usage = getattr(response, "usage", None)
    if resp_usage is None:
        return usage
    usage["prompt_tokens"] = int(getattr(resp_usage, "prompt_tokens", 0) or 0)
    usage["completion_tokens"] = int(getattr(resp_usage, "completion_tokens", 0) or 0)
    usage["prompt_cache_hit_tokens"] = int(getattr(resp_usage, "prompt_cache_hit_tokens", 0) or 0)
    details = getattr(resp_usage, "completion_tokens_details", None)
    usage["reasoning_tokens"] = int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0
    return usage


def _empty_usage_bucket() -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "reasoning_tokens": 0,
    }


def _new_usage_holder() -> dict:
    return {
        "flash": _empty_usage_bucket(),
        "pro": _empty_usage_bucket(),
    }


def _accumulate_usage(holder: dict, usage: Optional[dict]) -> None:
    if not usage:
        return
    alias = str(usage.get("model", "")).strip()
    if alias not in ("flash", "pro"):
        return
    bucket = holder.setdefault(alias, _empty_usage_bucket())
    for key in _empty_usage_bucket():
        bucket[key] = bucket.get(key, 0) + int(usage.get(key, 0) or 0)


def _estimate_cost(holder: Optional[dict]) -> float:
    if not holder:
        return 0.0
    total = 0.0
    for alias in ("flash", "pro"):
        bucket = holder.get(alias, _empty_usage_bucket())
        price = PRICES[alias]
        prompt_tokens = int(bucket.get("prompt_tokens", 0) or 0)
        cache_hit_tokens = int(bucket.get("prompt_cache_hit_tokens", 0) or 0)
        completion_tokens = int(bucket.get("completion_tokens", 0) or 0)
        miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
        total += (cache_hit_tokens * price["hit"] + miss_tokens * price["miss"]
                  + completion_tokens * price["out"]) / 1_000_000
    return total


def _fmt_k(tokens: int) -> str:
    if tokens <= 0:
        return "0k"
    return f"{tokens / 1000:.1f}k"


def _usage_header(holder: Optional[dict]) -> str:
    holder = holder or _new_usage_holder()
    parts = []
    for alias in ("flash", "pro"):
        bucket = holder.get(alias, _empty_usage_bucket())
        parts.append(
            f"{alias} 輸入{_fmt_k(bucket.get('prompt_tokens', 0))}"
            f"(快取{_fmt_k(bucket.get('prompt_cache_hit_tokens', 0))})"
            f"/輸出{_fmt_k(bucket.get('completion_tokens', 0))}"
        )
    return "用量：" + "、".join(parts) + f"｜估計 ${_estimate_cost(holder):.4f}"


def _total_output_tokens(holder: Optional[dict]) -> int:
    if not holder:
        return 0
    return (int(holder.get("flash", {}).get("completion_tokens", 0) or 0)
            + int(holder.get("pro", {}).get("completion_tokens", 0) or 0))


def _render_changes(changes: list[dict], limit: int = 6) -> str:
    if not changes:
        return "變更：無"
    parts = []
    for change in changes[:limit]:
        rel = change.get("path", "")
        kind = change.get("kind", "")
        plus = int(change.get("plus", 0) or 0)
        minus = int(change.get("minus", 0) or 0)
        if kind == "modified":
            parts.append(f"modified {rel} (+{plus}/-{minus})")
        elif kind == "added":
            parts.append(f"added {rel} (+{plus})")
        else:
            parts.append(f"{kind} {rel}")
    return "變更：" + "、".join(parts)


async def _call_model(alias: str, prompt_text: str, effort: str, system: str = SYSTEM_PROMPT,
                      max_tokens: int = 0):
    # effort "none" = 關閉思考（DeepSeek thinking: disabled），只給機械工作或實驗用
    thinking = ({"thinking": {"type": "disabled"}} if effort == "none"
                else {"thinking": {"type": "enabled"}, "reasoning_effort": effort})
    return await client.chat.completions.create(
        model=MODEL_MAP[alias],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_text},
        ],
        max_tokens=max_tokens or MAX_TOKENS,
        # 放在 extra_body，避免舊版 openai SDK 不認得 reasoning_effort 參數
        extra_body=thinking,
    )


async def _execute_single_task(
    task_id: int, prompt_text: str, model: str = "auto", effort: str = "max",
    pick_text: str = "", system: str = SYSTEM_PROMPT, max_tokens: int = 0,
) -> dict:
    """執行單一任務。status 為 ok / truncated / error 三者之一。pick_text 供 auto 選模型。"""
    primary = _pick(model, pick_text)
    if not API_KEY:
        return {
            "id": task_id,
            "status": "error",
            "model": primary,
            "content": "未設定 DEEPSEEK_API_KEY 環境變數。",
            "usage": _empty_usage(primary),
        }

    fallback = "pro" if primary == "flash" else "flash"
    note = ""
    response = None
    used = primary

    async with semaphore:
        for alias in (primary, fallback):
            try:
                response = await _call_model(alias, prompt_text, effort, system, max_tokens)
                used = alias
                break
            except Exception as e:  # noqa: BLE001 — 任何失敗都要回報，不能讓整批掛掉
                log(f"子任務 #{task_id} 使用 {alias} 失敗：{type(e).__name__}: {e}")
                if alias == primary:
                    note = f"（{primary} 呼叫失敗，已自動改用 {fallback}）\n"
                else:
                    return {
                        "id": task_id,
                        "status": "error",
                        "model": f"{primary}→{fallback}",
                        "content": f"兩個模型都失敗。最後錯誤 {type(e).__name__}: {e}",
                        "usage": _empty_usage(fallback),
                    }

    if not response.choices:
        return {
            "id": task_id,
            "status": "error",
            "model": used,
            "content": note + "API 回傳空的 choices。",
            "usage": _empty_usage(used),
        }

    choice = response.choices[0]
    content = choice.message.content or ""  # 只回傳成品，不回傳 reasoning_content
    usage = _extract_usage(used, response)

    if choice.finish_reason == "length":
        return {
            "id": task_id,
            "status": "truncated",
            "model": used,
            "content": note + content + TRUNCATION_WARNING,
            "usage": usage,
        }
    if not content.strip():
        return {
            "id": task_id,
            "status": "error",
            "model": used,
            "content": note + "模型回傳空白內容。",
            "usage": usage,
        }

    return {"id": task_id, "status": "ok", "model": used, "content": note + content, "usage": usage}


# 避險請求（hedged requests，"The Tail at Scale"）：呼叫超過 HEDGE_SECS 還沒完成，就用同一模型再送一份，
# 先成功的採用、另一份取消。實測初版產出中位 10s、p95 44s，但偶發思考失控可拖到 311s；整批時間由最慢的任務決定。
HEDGE_SECS = _env_int("DEEPSEEK_HEDGE_SECS", 60)
# H：避險門檻依強度調整：high／max 本來就想得久，60 秒就送備份只會多花錢（實測 high 任務 4 個有 3 個觸發）
HEDGE_SECS_BY_EFFORT = {"low": HEDGE_SECS, "high": HEDGE_SECS * 2, "max": HEDGE_SECS * 3}
HEDGE = os.environ.get("DEEPSEEK_HEDGE", "1").strip() not in ("0", "false", "off")


async def _hedged_task(task_id: int, prompt_text: str, model: str, effort: str,
                       pick_text: str = "", on_hedge=None) -> tuple[dict, list[dict]]:
    """回傳 (採用的結果, 所有已完成呼叫的結果清單〔記用量用〕)。"""
    first = asyncio.create_task(_execute_single_task(task_id, prompt_text, model, effort, pick_text))
    tasks = [first]
    try:
        if not HEDGE:
            r = await first
            return r, [r]
        done, _ = await asyncio.wait({first}, timeout=HEDGE_SECS_BY_EFFORT.get(effort, HEDGE_SECS))
        if done:
            r = first.result()
            return r, [r]
        if on_hedge:
            on_hedge()
        backup = asyncio.create_task(_execute_single_task(task_id, prompt_text, _pick(model, pick_text), effort, ""))
        tasks.append(backup)
        pending, finished = {first, backup}, []
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                r = t.result()
                finished.append(r)
                if r["status"] == "ok":
                    r = dict(r, hedged=True, hedge_winner="backup" if t is backup else "primary")
                    return r, finished
        # 兩份都沒成功：回傳第一份（通常是截斷，交給既有的截斷處理）
        return finished[0], finished
    finally:
        # 不論正常返回或外層被取消，都把還在跑的請求取消掉，避免漏跑
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


MAX_ATTACH_BYTES = _env_int("DEEPSEEK_MAX_ATTACH_BYTES", 400_000)
SENSITIVE_RE = re.compile(
    r"(^|[\\/])(\.env[^\\/]*|.*\.(pem|key|pfx|p12|kdbx)|id_(rsa|dsa|ecdsa|ed25519)[^\\/]*|"
    r".*(secret|credential|password|token)s?[^\\/]*|\.git[\\/].*|\.ssh[\\/].*)$",
    re.I,
)

GENERIC_SECRET_RE = re.compile(
    r"((?:api[_-]?key|secret|token|password)\s*[:=]\s*)([\"']?)([^\"'\s]{8,})",
    re.I,
)
SECRET_PATTERNS = [
    re.compile(r"sk-(?:ant|proj|svcacct|or)-[A-Za-z0-9_-]{16,}"),  # Anthropic、OpenAI 專案/服務帳號、OpenRouter
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                            # 舊版 OpenAI、DeepSeek
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                           # Google AI Studio / Cloud
    re.compile(r"xai-[A-Za-z0-9]{20,}"),                            # xAI
    re.compile(r"hf_[A-Za-z0-9]{30,}"),                             # Hugging Face
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),                    # GitHub fine-grained token
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def _mask_secrets(text: str) -> tuple[str, int]:
    """遮蔽常見金鑰/秘密，回傳 (遮蔽後文字, 遮蔽處數)。"""
    masked = text
    counter = [0]

    for pattern in SECRET_PATTERNS:
        def repl_token(m, _pattern=pattern):
            counter[0] += 1
            return "[REDACTED]"
        masked = pattern.sub(repl_token, masked)

    def repl_generic(m):
        counter[0] += 1
        return m.group(1) + m.group(2) + "[REDACTED]"

    masked = GENERIC_SECRET_RE.sub(repl_generic, masked)
    return masked, counter[0]


MISSING_MARK = "[缺檔] "  # 附檔缺失的備註前綴：submit 看到就不送出


def _read_attachments(root: Optional[Path], patterns: list[str]) -> tuple[str, list[str]]:
    """唯讀附檔：依相對路徑或 glob 讀取 root 內的文字檔，回傳 (附加文字, 備註)。"""
    pats = [p.strip() for p in patterns if p and p.strip()]
    if not pats:
        return "", []
    notes, parts, seen, total = [], [], set(), 0
    for pat in pats:
        pp = Path(pat)
        # 絕對路徑：唯讀附上資料夾外的檔（規格常在別的 repo／下載資料夾）；敏感檔過濾與金鑰遮蔽照樣套用
        if pp.is_absolute():
            base = Path(pp.anchor)
            rest = str(pp.relative_to(base))
            matches = sorted(base.glob(rest)) if any(c in pat for c in "*?[") else [pp]
        elif root is None:
            notes.append(f"{MISSING_MARK}{pat}：相對路徑需要 output_root 或 read_root")
            continue
        else:
            matches = sorted(root.glob(pat)) if any(c in pat for c in "*?[") else [root / pat]
        matches = [m for m in matches if m.exists()]
        if not matches:
            notes.append(f"{MISSING_MARK}{pat} 找不到")
        for p in matches:
            p = p.resolve()
            if not p.is_file():
                notes.append(f"{MISSING_MARK}{pat} 不是檔案")
                continue
            rel = (p.relative_to(root).as_posix() if root is not None and root in p.parents else p.as_posix())
            if rel in seen:
                continue
            if SENSITIVE_RE.search(rel):
                notes.append(f"{rel} 疑似敏感檔案，未附上")
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                notes.append(f"{rel} 不是 UTF-8 文字檔，略過")
                continue
            text, masked_count = _mask_secrets(text)
            if masked_count:
                notes.append(f"{rel} 已遮蔽 {masked_count} 處疑似金鑰")
            if total + len(text) > MAX_ATTACH_BYTES:
                notes.append(f"{rel} 超過附檔總量上限 {MAX_ATTACH_BYTES}，略過")
                continue
            seen.add(rel)
            total += len(text)
            lang = p.suffix.lstrip(".") or "text"
            parts.append(f"--- 檔案：{rel} ---\n```{lang}\n{text}\n```")
    if not parts:
        return "", notes
    return "\n【附檔（唯讀，現有內容）】\n" + "\n".join(parts) + "\n", notes


def _split_patterns(spec) -> list[str]:
    if not spec:
        return []
    if isinstance(spec, str):
        return [s for s in spec.split(",") if s.strip()]
    return [s for s in spec if s and s.strip()]


def _context_prefix(context: str) -> str:
    """共用內容一律放在 prompt 最前面，且格式固定。

    DeepSeek 快取只比對「從開頭起完全相同」的前綴，共用內容在前，同批任務、
    修正工蜂（同一個系統提示）與審查員之間才能命中快取。
    """
    if context and context.strip():
        return f"【全域規範／背景資料／現有程式碼】\n{context.strip()}\n\n"
    return ""


def _build_prompt(task: str, context: str, label: str) -> str:
    return _context_prefix(context) + f"【{label}】\n{task.strip()}\n"


@mcp.tool()
async def quick_worker_solve(
    task: str,
    context: str = "",
    model: ModelChoice = "auto",
    effort: EffortChoice = "max",
    attach_files: Optional[list[str]] = None,
    read_root: str = "",
) -> str:
    """【單任務速解】單一函式、單一作業題、小型修改或修正重派。

    attach_files: 選填，read_root 內的相對路徑或 glob（例 ["js/player.js","js/*.js"]），伺服器唯讀附上檔案內容，
                  Claude 不必自己貼程式碼。敏感檔（.env、金鑰、憑證）自動略過。

    task: 具體任務指示。
    context: 相關背景、函式簽章、型別定義或現有程式碼。
    model: auto | flash | pro。auto 依任務內容自動挑（冷門知識類→pro，其餘→flash）；
           flash 較新、推理與程式較強、支援圖片；pro 參數量大，冷門知識記得較多。失敗時自動改用另一個模型。
    注意：用戶端約 60 秒逾時，長輸出請改用 submit_swarm_job。
    effort: 推理強度 max（預設）| high | low。
    工作規範（多輪自審、只輸出成品、FLAGS 疑點區塊）已由伺服器自動附加，不需寫在 task 裡。
    回傳第一行為狀態與實際使用模型，例如：[OK] model=flash；狀態有 OK / TRUNCATED / ERROR。
    """
    if not task or not task.strip():
        return "[ERROR] task 不可為空。"
    if model not in VALID_MODELS:
        return f"[ERROR] model 只能是 {VALID_MODELS}。"
    if effort not in VALID_EFFORTS:
        return f"[ERROR] effort 只能是 {VALID_EFFORTS}。"

    root = Path(read_root).resolve() if read_root else None
    attached, notes = _read_attachments(root, _split_patterns(attach_files))
    result = await _execute_single_task(
        1, _build_prompt(task + attached, context, "任務指示"), model, effort, task
    )
    tag = result["status"].upper()
    note = f"（附檔備註：{'；'.join(notes)}）\n" if notes else ""
    return f"[{tag}] model={result['model']}\n{note}{result['content']}"


@mcp.tool()
async def batch_parallel_swarm(
    task_list: list[str],
    shared_context: str = "",
    models: Optional[list[ModelChoice]] = None,
    effort: EffortChoice = "max",
) -> str:
    """【多工蜂並發】多檔案同時生成、多題平行求解、多模型投票。

    task_list: 子任務清單，每一項是一個完整且獨立的任務指示。
    shared_context: 所有子任務共用的介面、型別與規範。
    models: 與 task_list 一一對應的模型清單（auto|flash|pro）；省略或較短時其餘用 auto（依內容自動挑）。
    注意：用戶端約 60 秒逾時，長輸出請改用 submit_swarm_job。
            投票時混用模型可提高抓錯率，例如 3 份用 ["flash","flash","pro"]。
    effort: 推理強度 max（預設）| high | low，套用到整批。
    工作規範（多輪自審、只輸出成品、FLAGS 疑點區塊）已由伺服器自動附加。
    回傳開頭有成功／截斷／失敗統計，每個子任務區塊都標示狀態與實際使用模型。
    """
    tasks = [t for t in (task_list or []) if t and t.strip()]
    if not tasks:
        return "[ERROR] task_list 為空。"
    if effort not in VALID_EFFORTS:
        return f"[ERROR] effort 只能是 {VALID_EFFORTS}。"

    model_list = list(models or [])
    bad = [m for m in model_list if m not in VALID_MODELS]
    if bad:
        return f"[ERROR] models 只能包含 {VALID_MODELS}，收到 {bad}。"
    model_list += ["auto"] * (len(tasks) - len(model_list))

    jobs = [
        _execute_single_task(
            idx + 1,
            _build_prompt(task, shared_context, f"子任務 #{idx + 1}"),
            model_list[idx],
            effort,
            task,
        )
        for idx, task in enumerate(tasks)
    ]
    results = await asyncio.gather(*jobs)

    counts = {"ok": 0, "truncated": 0, "error": 0}
    for r in results:
        counts[r["status"]] += 1

    header = (
        f"=== 批次結果：共 {len(results)} 項｜成功 {counts['ok']}｜"
        f"截斷 {counts['truncated']}｜失敗 {counts['error']} ===\n"
    )
    blocks = [
        f"=== 子任務 #{r['id']} [{r['status'].upper()}] model={r['model']} ===\n{r['content']}\n"
        for r in results
    ]
    return header + "\n" + "\n".join(blocks)


# ---------------------------------------------------------------------------
# 背景工作：submit_swarm_job / get_swarm_job（避免 MCP 用戶端逾時）
# ---------------------------------------------------------------------------

JOB_DIR = Path(os.environ.get("DEEPSEEK_JOB_DIR", "").strip() or (Path.home() / ".deepseek_swarm_jobs"))
WAIT_JOB_SCRIPT = Path(__file__).resolve().parent / "wait_job.py"  # 不寫死路徑，搬到別台電腦也能用
JOBS: dict[str, dict] = {}
CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.S)
MAX_WAIT = 40


def _flags_of(content: str) -> str:
    if "===FLAGS===" not in content:
        return "(無 FLAGS 區塊，視為低信心)"
    return content.split("===FLAGS===")[-1].split("===END===")[0].strip()


def _single_block(content: str) -> Optional[tuple[str, str]]:
    """單一輸出檔時：取第一個 ``` 開頭行到最後一個單獨 ``` 行之間的全部內容。
    可正確處理程式碼本身含有 ``` 或 ===FLAGS=== 字樣的情況。"""
    text = content.replace("\r\n", "\n")
    if "\n===FLAGS===" in text:
        text = text.rsplit("\n===FLAGS===", 1)[0]
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("```")]
    ends = [i for i, l in enumerate(lines) if l.strip() == "```"]
    for s in starts:
        body = lines[s + 1:]
        # 略過只含檔名的區塊
        if len(body) >= 2 and body[1].strip() == "```" and re.fullmatch(r"\s*[\w./\\-]+\.\w+\s*", body[0]):
            continue
        # 選結尾：最早一個「後面接著文末／FLAGS／另一個程式碼區塊開頭」的單獨 ```；
        # 舊版取最後一個 ```，工蜂多回一個測試區塊時會把兩塊黏進實作檔（實測 6 個檔全中、retry 也修不好）
        e = None
        for x in (x for x in ends if x > s):
            nxt = next((l.strip() for l in lines[x + 1:] if l.strip()), None)
            later_opener = any(re.match(r"```\w", l) for l in lines[x + 1:])
            if nxt is None or nxt.startswith("```") or nxt.startswith("===") or later_opener:
                e = x
                break
        if e is None:
            e = max((x for x in ends if x > s), default=None)
        if e is None:
            # 模型漏了結尾 ```：取到 FLAGS 前（已切掉）或文末；之後的語法檢查會把關
            body_lines = lines[s + 1:]
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            if not body_lines:
                return None
            return lines[s][3:].strip(), "\n".join(body_lines)
        return lines[s][3:].strip(), "\n".join(lines[s + 1:e])
    return None


def _extract_code_blocks(content: str, nfiles: int = 0) -> list[tuple[str, str]]:
    """提取程式碼區塊，回傳 (語言標籤, 程式碼)，略過只含檔名的區塊。nfiles==1 時用 _single_block。"""
    if nfiles == 1:
        one = _single_block(content)
        if one is not None:
            return [one]
    blocks = []
    pattern = re.compile(r"```([^\n]*)\n(.*?)\n```", re.S)
    for match in pattern.finditer(content):
        lang = match.group(1).strip()
        code = match.group(2)
        # 略過只含檔名的區塊（例如 ```js\njs/player.js\n```）
        if re.fullmatch(r"\s*[\w./\\-]+\.\w+\s*", code):
            continue
        blocks.append((lang, code))
    return blocks


def _forbid_violations(code: str, rel: str, forbid: Optional[list]) -> list[str]:
    """掃描禁止樣式（含註解、docstring、字串）：規格禁止的函式／模組連名稱都不能出現，
    因為 lint、安全掃描、評分常以原始碼文字掃描（實測：工蜂在 docstring 寫「never uses eval()」被判違規）。"""
    out = []
    for pat in forbid or []:
        try:
            rx = re.compile(pat)
        except re.error:
            continue
        for n, line in enumerate(code.splitlines(), 1):
            if rx.search(line):
                out.append(f"{rel}：第 {n} 行出現禁止的樣式 {pat!r}（連註解、docstring、字串都不能出現）：{line.strip()[:80]}")
                break
    return out


async def _syntax_check(content: str, files: list[str], forbid: Optional[list] = None) -> tuple[list[str], list[str]]:
    """依檔案副檔名做語法檢查。回傳 (錯誤訊息清單, 備註清單)。錯誤每條截 400 字。"""
    errors = []
    notes = []
    blocks = _extract_code_blocks(content, len(files))
    if len(blocks) < len(files):
        errors.append(f"程式碼區塊只有 {len(blocks)} 個，少於指定的 {len(files)} 個檔案"
                      "（每個檔案要放在完整的 ``` 區塊裡，含結尾 ```）")
    node_path = shutil.which("node")
    for idx, rel in enumerate(files):
        if idx >= len(blocks):
            break
        lang, code = blocks[idx]
        errors.extend(_forbid_violations(code, rel, forbid))
        ext = Path(rel).suffix.lower()
        if ext in (".js", ".mjs", ".cjs"):
            if not node_path:
                notes.append("找不到 node，略過 JS 語法檢查")
                continue
            fd, tmp_path = tempfile.mkstemp(suffix=ext, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(code)
                try:
                    proc = await asyncio.create_subprocess_exec(
                        node_path, "--check", tmp_path,
                        stdin=asyncio.subprocess.DEVNULL,  # 見 _run_tests：不可繼承 MCP 的 stdin
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.communicate()
                        errors.append(f"{rel}：JS 語法檢查逾時（20秒）")
                        continue
                    if proc.returncode != 0:
                        msg = stderr.decode("utf-8", errors="replace").strip()
                        errors.append(f"{rel}：{msg[:400]}")
                except Exception as e:
                    errors.append(f"{rel}：JS 語法檢查失敗：{type(e).__name__}: {e}")
                finally:
                    os.unlink(tmp_path)
            except OSError as e:
                errors.append(f"{rel}：無法建立暫存檔：{e}")
        elif ext == ".py":
            try:
                compile(code, rel, "exec")
            except SyntaxError as e:
                errors.append(f"{rel}：{str(e)[:400]}")
        elif ext == ".json":
            try:
                json.loads(code)
            except json.JSONDecodeError as e:
                errors.append(f"{rel}：{str(e)[:400]}")
        # 其他副檔名略過
    return errors, notes


def _build_review_prompt(task: str, shared_context: str, content: str,
                         files: list[str], syntax_errors: list[str]) -> str:
    """構建審查 prompt（共用內容在最前面，讓同批審查員命中快取）。"""
    lines = [_context_prefix(shared_context) + "你是嚴格審查工蜂。請審查以下任務的產出內容。"]
    lines.append("\n【原任務】\n" + task.strip())
    blocks = _extract_code_blocks(content, len(files))
    lines.append("\n【產出內容的程式碼區塊】")
    for i, (lang, code) in enumerate(blocks):
        filename = files[i] if i < len(files) else f"區塊{i+1}"
        lines.append(f"--- 檔案：{filename} ---\n```{lang or 'text'}\n{code}\n```")
    if syntax_errors:
        lines.append("\n【語法檢查錯誤】")
        for e in syntax_errors:
            lines.append("- " + e)
    lines.append(
        "\n請只輸出以下格式：第一行 VERDICT: PASS 或 VERDICT: FIX，之後每行一個問題，"
        "格式 '[高|中|低] <位置> — <問題> — 重現：<具體輸入> → 預期 <規格要求的結果>，實際 <程式的結果> — <修法>'，最多 8 條。"
        "只列依規格明確會出錯的問題（真正的 bug、介面不一致、執行錯誤、違反需求），"
        "每條都必須給得出具體重現輸入；給不出就不要列。"
        "規格沒提到的極端情況（超大數值、非預期型別、Unicode、效能）不列，風格建議不列。"
        "沒有問題就只輸出 VERDICT: PASS。"
    )
    return "\n".join(lines)


def _parse_review(content: str) -> tuple[str, list[str], list[str]]:
    """解析審查結果，回傳 (verdict, all_issues, 需修正的問題)。

    需修正 = [高]，或附有具體重現輸入的 [中]；沒有重現輸入的 [中] 視為理論疑慮，不觸發修正。
    """
    verdict = "UNKNOWN"
    all_issues = []
    hm_issues = []
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    for line in lines[:3]:  # 容忍審查員在 VERDICT 前多一兩行
        if "VERDICT: PASS" in line:
            verdict = "PASS"
            break
        if "VERDICT: FIX" in line:
            verdict = "FIX"
            break
    for line in lines:
        if re.match(r"^\[(高|中|低)\]\s+.*—.*—.*", line):
            all_issues.append(line)
            reproducible = re.search(r"重現[:：]\s*(?!無)\S", line) is not None
            if line.startswith("[高]") or (line.startswith("[中]") and reproducible):
                hm_issues.append(line)
    return verdict, all_issues, hm_issues


def _build_fix_prompt(task: str, shared_context: str, current_content: str,
                      review_issues: list[str], syntax_errors: list[str]) -> str:
    """構建修正 prompt（共用內容在最前面，與產出工蜂共用快取前綴）。"""
    lines = [_context_prefix(shared_context) + "你是修正工蜂。請根據以下資訊修正產出內容，輸出修正後的完整檔案（程式碼區塊數量與順序同原本）與 FLAGS。"]
    lines.append("\n【原任務】\n" + task.strip())
    lines.append("\n【目前完整產出】\n" + current_content.strip())
    if review_issues:
        lines.append("\n【審查問題（高/中）】")
        for issue in review_issues:
            lines.append("- " + issue)
    if syntax_errors:
        lines.append("\n【語法檢查錯誤】")
        for e in syntax_errors:
            lines.append("- " + e)
    lines.append("\n請輸出修正後的完整內容，確保程式碼區塊數量和順序與原本一致，並包含 FLAGS 區塊。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 伺服器端測試：測試工蜂只看規格寫測試 → 寫檔後實際執行 → 失敗交給修正工蜂
# ---------------------------------------------------------------------------

TEST_TIMEOUT = _env_int("DEEPSEEK_TEST_TIMEOUT", 120)
TEST_FIX_ROUNDS = 2
# 測試工蜂模型：flash（預設）| pro | other（與產出者不同的模型）。
# 實測 flash 寫測試 102s/$0.15，pro 寫 126s/$0.26，正確率相同；獨立性主要來自測試工蜂看不到實作。
TEST_WRITER = os.environ.get("DEEPSEEK_TEST_WRITER", "").strip() or "flash"


def _test_import_hint(test_rel: str, impl_files: list[str]) -> str:
    """告訴測試工蜂怎麼匯入實作（Python 用模組名，JS 用相對路徑）。"""
    ext = Path(test_rel).suffix.lower()
    hints = []
    for rel in impl_files:
        p = Path(rel)
        if ext == ".py" and p.suffix.lower() == ".py":
            mod = ".".join(p.with_suffix("").parts)
            hints.append(f"- `{rel}` → `import {mod}` 或 `from {mod} import ...`")
        elif ext in (".js", ".mjs", ".cjs") and p.suffix.lower() in (".js", ".mjs", ".cjs"):
            rel_import = os.path.relpath(p, Path(test_rel).parent).replace("\\", "/")
            if not rel_import.startswith("."):
                rel_import = "./" + rel_import
            hints.append(f"- `{rel}` → `import {{ ... }} from '{rel_import}'`")
    return "\n".join(hints) or "- （實作檔語言與測試檔不同，請依規格自行判斷）"


# D：測試工蜂的邊界清單（外部測試包實測：semver 接受 "1.2.3 ||" 這種空分支沒被測到，最後靠 Claude 自己抓）
EDGE_CHECKLIST = os.environ.get("DEEPSEEK_EDGE_CHECKLIST", "1").strip() not in ("0", "false", "off")
EDGE_CHECKLIST_TEXT = (
    "- 邊界清單（逐項對照規格，規格有規定的都要測）：空輸入；語法裡每個分隔符號／重複結構的空片段"
    "（例如 `a||b` 中間空、開頭或結尾多一個分隔符號）；只有空白；每個欄位都是空的一列（例 CSV 的 `,,,`，它不是空白行）；每條格式規則各一個剛好違反的輸入；"
    "數值的 0、最小、最大與剛好超出；重複／順序錯誤；型別不對（規格有規定時）。\n"
    "- 每個規定要丟例外的函式，至少測一個「格式合法但語意非法」的輸入（例：0 的負次方、不補零的日期 2024-1-5、"
    "結束早於開始的區間），並確認丟的是規格指定的例外型別（不是 ZeroDivisionError 之類的內建例外）。\n")


def _build_test_prompt(task: str, shared_context: str, test_rel: str, impl_files: list[str]) -> str:
    ext = Path(test_rel).suffix.lower()
    if ext == ".py":
        framework = ("用標準庫 unittest；檔案最後要有 `if __name__ == \"__main__\": unittest.main()`。"
                     "執行方式：在專案根目錄執行 `python " + test_rel + "`（專案根目錄已在匯入路徑上）。")
    else:
        framework = ("用 Node 內建 `node:test` 與 `node:assert/strict`，ES module 語法。"
                     "執行方式：在專案根目錄執行 `node --test " + test_rel + "`。")
    return (
        _context_prefix(shared_context)
        + "你是測試工蜂。只根據下面的規格寫自動化測試，你看不到實作。\n"
        + "\n【規格（原任務）】\n" + task.strip() + "\n"
        + f"\n【測試檔】{test_rel}\n{framework}\n"
        + "【匯入實作】\n" + _test_import_hint(test_rel, impl_files) + "\n"
        + "\n【要求】\n"
        "- 只測規格明確寫出的行為：規格中的每個範例、每條錯誤規則、關鍵邊界。\n"
        + (EDGE_CHECKLIST_TEXT if EDGE_CHECKLIST else "") +
        "- 規格沒寫的不要測（錯誤訊息文字、未定義輸入的行為、效能、內部實作細節）。\n"
        "- 例外只檢查型別，不檢查訊息。\n"
        "- 命令列程式（CLI）：直接呼叫它的 `main(argv)`（或規格指定的進入點），用 contextlib.redirect_stdout／"
        "redirect_stderr 擷取輸出、捕捉 SystemExit 檢查結束碼；不要另開行程。"
        "規格明確要求以獨立行程執行時，只能用 `subprocess.run([sys.executable, <專案內的 .py>, ...], capture_output=True)`。\n"
        "- 只有當規格明確有一對互逆的操作（序列化/反序列化、format/parse、encode/decode）時，另加 1 個往返測試："
        "用 random.Random(0) 產生 100 組規格允許的輸入，檢查往返後相等，失敗時印出輸入。"
        "不要自行推導其他「性質」或不變量（實測常推錯而誤判實作）。\n"
        "- 不可讀寫專案以外的檔案、不連網、不改環境；需要暫存檔用 tempfile.TemporaryDirectory()。\n"
        "- 禁止使用（伺服器執行前會檢查，含這些就不執行）：socket、網路相關模組、ctypes、os.system/popen、"
        "shutil.rmtree、eval/exec、上面允許形式以外的 subprocess；JS 禁止 child_process、net、http(s)、fs.rm/rmSync、eval。\n"
        "- 每個測試名稱要看得出在測哪條規格。\n"
        "\n【輸出】單一程式碼區塊，內容是完整測試檔。"
    )


def _build_test_fix_prompt(task: str, shared_context: str, impl_content: str,
                           test_rel: str, test_code: str, failure: str, existing_cmd: str = "") -> str:
    if existing_cmd:
        # 既有測試（專案原有或 bug 重現測試）是驗收標準，只能改實作
        return (
            _context_prefix(shared_context)
            + "你是修正工蜂。實作已寫好，但專案既有的測試沒通過。這些測試是驗收標準，不可修改，只能改實作。\n"
            + "\n【原任務（規格）】\n" + task.strip() + "\n"
            + "\n【目前實作】\n" + impl_content.strip() + "\n"
            + f"\n【測試指令】{existing_cmd}\n"
            + "\n【測試執行輸出（節錄）】\n```\n" + failure + "\n```\n"
            + "\n【輸出】修正後的實作全部程式碼區塊（數量與順序同原本），最後附 FLAGS，在「假設」說明失敗原因與修法。"
        )
    return (
        _context_prefix(shared_context)
        + "你是修正工蜂。實作已寫好，但伺服器實際執行測試失敗。先判斷是實作錯還是測試錯（測試可能誤解規格），"
          "以規格為準修正錯的那一方。\n"
        + "\n【原任務（規格）】\n" + task.strip() + "\n"
        + "\n【目前實作】\n" + impl_content.strip() + "\n"
        + f"\n【目前測試 {test_rel}】\n```\n{test_code}\n```\n"
        + "\n【測試執行輸出（節錄）】\n```\n" + failure + "\n```\n"
        + "\n【輸出】依序輸出：實作的全部程式碼區塊（數量與順序同原本），最後再一個程式碼區塊是完整測試檔。"
          "沒改的那方也要完整輸出。最後附 FLAGS，在「假設」說明你判斷是誰錯、為什麼。"
    )


_PY_BLOCKED_MODULES = {
    "socket", "ctypes", "pty", "urllib", "http", "requests", "httpx", "ftplib", "smtplib",
    "telnetlib", "multiprocessing", "webbrowser", "winreg", "ssl", "aiohttp",
}
# subprocess 只放行一種形式：subprocess.run/call/check_call/check_output/Popen([sys.executable, ...])，且不可 shell=True。
# （CLI 規格常需要這樣測；實測一律封鎖時，工蜂照規格寫的測試被擋、任務停在「未測試」。）
_SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen"}
_SUBPROCESS_CONSTS = {"PIPE", "DEVNULL", "STDOUT", "CalledProcessError", "TimeoutExpired", "CompletedProcess"}


def _is_py_argv(node, assigns: dict) -> bool:
    """[sys.executable, ...] 字面清單；或只被指定為這種清單的變數（cmd = [sys.executable, ...]）。"""
    if isinstance(node, ast.Name):
        values = assigns.get(node.id, [])
        return bool(values) and all(_is_py_argv(v, {}) for v in values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):  # [sys.executable, x] + args
        return _is_py_argv(node.left, assigns)
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    head = node.elts[0]
    return (isinstance(head, ast.Attribute) and head.attr == "executable"
            and isinstance(head.value, ast.Name) and head.value.id == "sys")


def _safe_subprocess_call(node: ast.Call, assigns: dict) -> bool:
    if any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and k.value.value is False)
           for k in node.keywords):
        return False
    first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "args"), None)
    return first is not None and _is_py_argv(first, assigns)


def _subprocess_violation(tree: ast.AST) -> str:
    """subprocess 的使用必須全部是允許形式；回傳違規說明或空字串。"""
    aliases, from_names = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "subprocess":
                    aliases.add(a.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for a in node.names:
                if a.name not in _SUBPROCESS_CALLS | _SUBPROCESS_CONSTS:
                    return f"from subprocess import {a.name}"
                from_names[a.asname or a.name] = a.name
    if not aliases and not from_names:
        return ""
    assigns: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            assigns.setdefault(node.target.id, []).append(node.value)
        # cmd += [...] 只是往後加參數，開頭仍是 sys.executable，不影響判斷
    safe_funcs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = (f.attr if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in aliases
                    else from_names.get(f.id) if isinstance(f, ast.Name) else None)
            if name in _SUBPROCESS_CALLS:
                if not _safe_subprocess_call(node, assigns):
                    return f"subprocess.{name}（只允許 [sys.executable, ...] 形式且不可 shell=True）"
                safe_funcs.add(id(f))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            if node.attr in _SUBPROCESS_CONSTS or id(node) in safe_funcs:
                continue
            return f"subprocess.{node.attr}"
        if isinstance(node, ast.Name) and node.id in from_names and from_names[node.id] in _SUBPROCESS_CALLS:
            continue  # 已在上面逐一檢查過呼叫形式
    return ""
_PY_BLOCKED_CALLS = {  # (模組, 函式)
    ("os", "system"), ("os", "popen"), ("os", "rmdir"), ("os", "removedirs"), ("os", "kill"),
    ("os", "startfile"), ("shutil", "rmtree"), ("shutil", "move"),
}
_PY_BLOCKED_NAMES = {"eval", "exec", "__import__"}
_JS_BLOCKED_RE = re.compile(
    r"""(['"](?:node:)?(?:child_process|net|dgram|http|https|http2|tls|cluster|worker_threads)['"])"""
    r"""|\b(?:rmSync|rmdirSync|execSync|spawnSync)\b|\bfs\.(?:rm|rmdir)\s*\(|process\.kill\s*\(|\beval\s*\("""
    r"""|new\s+Function\s*\(""")


def _unsafe_test_reason(path: Path) -> str:
    """生成的測試碼執行前的靜態檢查（縱深防禦，不是沙箱）：命中高風險操作就回傳原因，不執行。
    只擋測試碼；實作碼本身也會在測試時執行，這部分仍需靠審查與使用者判斷。"""
    try:
        code = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"無法讀取測試檔：{e}"
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ""  # 語法錯交給執行時回報
        sub = _subprocess_violation(tree)
        if sub:
            return sub
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in _PY_BLOCKED_MODULES:
                        return f"import {a.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _PY_BLOCKED_MODULES:
                    return f"from {node.module} import"
                for a in node.names:  # from os import system 之類，呼叫時就只剩 system()，下面的檢查看不到
                    if (node.module, a.name) in _PY_BLOCKED_CALLS:
                        return f"from {node.module} import {a.name}"
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in _PY_BLOCKED_NAMES:
                    return f"{f.id}()"
                if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                        and (f.value.id, f.attr) in _PY_BLOCKED_CALLS):
                    return f"{f.value.id}.{f.attr}()"
        return ""
    m = _JS_BLOCKED_RE.search(code)
    return m.group(0) if m else ""


async def _run_tests(root: Path, test_rel: str, test_cmd: str = "") -> tuple[bool, str]:
    """在 root 執行測試，回傳 (是否通過, 輸出節錄)。"""
    ext = Path(test_rel).suffix.lower()
    shell_cmd = ""
    if test_cmd.strip() and re.search(r"&&|\|\||[|<>;]", test_cmd):
        # 含 shell 語法（例：驗收用「python -c ... && node ...」一次檢查多個檔）→ 交給 shell；指令由主代理撰寫
        shell_cmd = re.sub(r"(?<![\w/\\.:-])python3?(?:\.exe)?(?=\s)", lambda _m: f'"{sys.executable}"', test_cmd)
        cmd = []
    elif test_cmd.strip():
        cmd = [c.strip('"') for c in shlex.split(test_cmd, posix=(os.name != "nt"))]
        if cmd and cmd[0].lower() in ("python", "python3", "py", "python.exe"):
            cmd[0] = sys.executable  # 避免 PATH 上的 Windows Store 假 python
        elif cmd:
            cmd[0] = shutil.which(cmd[0]) or cmd[0]  # 讓 npm.cmd 之類的指令找得到
    elif ext == ".py":
        cmd = [sys.executable, test_rel]
    elif ext in (".js", ".mjs", ".cjs"):
        node_path = shutil.which("node")
        if not node_path:
            return False, "找不到 node，無法執行 JS 測試"
        cmd = [node_path, "--test", test_rel]
    else:
        return False, f"不支援的測試檔類型 {ext}，請提供 test_cmd"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # 並行任務不共用/寫入 __pycache__，避免讀到舊的位元組碼
    for key in list(env):  # 測試碼是模型寫的，不給它任何金鑰
        if re.search(r"(API_KEY|TOKEN|SECRET|PASSWORD)", key, re.I):
            env.pop(key)
    try:
        # stdin 一定要 DEVNULL：MCP 伺服器的 stdin 是 App 的 pipe，且有執行緒正卡在讀它；
        # Windows 上子程序繼承這個 handle 後，啟動時查詢 stdin 會被擋住，直到 App 送來下一則訊息
        # （實測：子程序完全不跑、測試 120 秒逾時）。
        if shell_cmd:
            proc = await asyncio.create_subprocess_shell(
                shell_cmd, cwd=str(root), env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(root), env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=TEST_TIMEOUT)
        except asyncio.TimeoutError:
            if os.name == "nt":  # kill() 只殺 cmd.exe／最外層行程，卡死的 python/node 子行程會留著吃 CPU、鎖檔
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                               capture_output=True)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.communicate()
            return False, f"測試執行逾時（{TEST_TIMEOUT} 秒）"
    except Exception as e:  # noqa: BLE001
        return False, f"無法執行測試：{type(e).__name__}: {e}"
    # Windows 子程序輸出是 \r\n，寫進摘要檔時會再被轉一次變成空行，先統一成 \n
    text = out.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    if len(text) > 2500:
        text = text[:600] + "\n…（中略）…\n" + text[-1800:]
    return proc.returncode == 0, text


# B：測試失敗時用第二份獨立實作仲裁（CodeT 式雙重執行一致性）。
# 實測（v2 題庫 33 個任務）：修正回合 4 次全是誤報（3 次測試寫錯、1 次審查誤讀規格），初版其實都正確。
ARBITRATE = os.environ.get("DEEPSEEK_ARBITRATE", "1").strip() not in ("0", "false", "off")
# C：有生成測試把關、且非 max 強度的任務不另外審查（同批實測審查 0 次抓到真 bug，卻在關鍵路徑上用最貴的 pro）
REVIEW_WITH_TESTS = os.environ.get("DEEPSEEK_REVIEW_WITH_TESTS", "0").strip() not in ("0", "false", "off")


def _failed_tests(output: str) -> set[str]:
    """從 unittest / pytest / node --test（spec 與 TAP 格式）輸出取出失敗的測試名稱。
    名稱要去掉耗時：兩份實作跑出的毫秒數不同，留著就永遠比對不上（Node 20+ 預設是 spec 格式「✖ 名稱 (1.2ms)」）。"""
    names = set(re.findall(r"^(?:FAIL|ERROR): (\S+)", output, re.M))
    names |= set(re.findall(r"^FAILED (\S+)", output, re.M))
    names |= {m.strip() for m in re.findall(r"^\s*not ok \d+ - ([^#\n]+)", output, re.M)}
    names |= {m.strip() for m in re.findall(r"^\s*✖ (.+?)(?: \([\d.]+m?s\))?\s*$", output, re.M)
              if m.strip() != "failing tests:"}
    return names


def _final_change(root: Path, rel: str, job_id: str, was_added: bool) -> dict:
    """依磁碟上的最終檔案重算變更（對原始備份比較），供多次寫入同一檔後使用。"""
    target = root / rel
    new_lines = target.read_text(encoding="utf-8", errors="replace").splitlines() if target.is_file() else []
    if was_added:
        return {"path": rel, "kind": "added", "plus": len(new_lines), "minus": 0}
    backup = JOB_DIR / job_id / "backup" / rel
    old_lines = (backup.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").splitlines()
                 if backup.is_file() else [])
    plus = minus = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
        if tag in ("replace", "delete"):
            minus += i2 - i1
        if tag in ("replace", "insert"):
            plus += j2 - j1
    return {"path": rel, "kind": "modified" if (plus or minus) else "unchanged", "plus": plus, "minus": minus}


def _extract_flags_summary(content: str) -> dict:
    """從 FLAGS 區塊提取信心、未完成、高疑點（最多 3 條）。"""
    flags = _flags_of(content)
    if flags == "(無 FLAGS 區塊，視為低信心)":
        return {"confidence": "低", "unfinished": "無", "high_concerns": []}
    lines = flags.splitlines()
    confidence = ""
    unfinished = ""
    high_concerns = []
    for line in lines:
        if line.startswith("信心:"):
            confidence = line.split(":", 1)[1].strip()
        elif line.startswith("未完成:"):
            unfinished = line.split(":", 1)[1].strip()
        elif line.startswith("疑點:") or line.startswith("疑點："):
            # 疑點可能一行多條，格式 [高|中|低] ... — ... — ...
            for part in re.findall(r"\[(高|中|低)\]\s+([^\[]+)", line):
                if part[0] == "高":
                    high_concerns.append(part[1].strip())
        elif re.match(r"^\[(高|中|低)\]\s+", line):
            if line.startswith("[高]"):
                high_concerns.append(line[4:].strip())
    return {
        "confidence": confidence or "?",
        "unfinished": unfinished or "無",
        "high_concerns": high_concerns[:3],
    }


def _save_code_blocks(
    content: str,
    spec: str,
    root: Optional[Path],
    job_id: str = "",
    backup_done: Optional[set] = None,
) -> tuple[list[str], str, list[dict]]:
    """把回覆中的程式碼區塊依序寫到 spec（逗號分隔的相對路徑）指定的檔案。

    回傳 (已寫入清單, 問題, changes)。寫入前若目標已存在會先備份到
    JOB_DIR/<job_id>/backup/<相對路徑>；同一 job 同一檔只備份第一次。
    """
    files = [s.strip() for s in (spec or "").split(",") if s.strip()]
    if not files:
        return [], "", []
    if root is None:
        return [], "未提供 output_root，未寫檔", []
    blocks = [code for _, code in _extract_code_blocks(content, len(files))]
    saved, problems, changes = [], [], []
    for rel, code in zip(files, blocks):
        target = (root / rel).resolve()
        if root not in target.parents:
            problems.append(f"{rel} 不在 output_root 內，略過")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            old_text = ""
            if existed:
                # errors="replace" 避免非 UTF-8 舊檔讓整批寫檔中斷
                old_text = target.read_text(encoding="utf-8", errors="replace")

            # 首次寫到已存在檔案前先備份（同一 job 同一檔只備份一次）
            if existed and job_id:
                backup_root = JOB_DIR / job_id / "backup"
                if backup_done is None or rel not in backup_done:
                    backup_target = backup_root / rel
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_target)
                    if backup_done is not None:
                        backup_done.add(rel)

            # 原子寫入：先寫暫存檔再取代，並行任務的測試不會讀到寫到一半的檔案
            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:6]}.tmp")
            try:
                tmp.write_text(code + "\n", encoding="utf-8")
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)  # 取代失敗（例：防毒或編輯器鎖住目標檔）時不留下暫存檔
        except OSError as e:
            problems.append(f"{rel} 寫檔/備份失敗：{type(e).__name__}: {e}")
            continue

        if not existed:
            kind = "added"
            plus = len(code.splitlines())
            minus = 0
        else:
            new_lines = code.splitlines()
            old_lines = old_text.replace("\r\n", "\n").splitlines()
            matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
            plus = minus = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ("replace", "delete"):
                    minus += i2 - i1
                if tag in ("replace", "insert"):
                    plus += j2 - j1
            kind = "modified" if (plus or minus) else "unchanged"

        changes.append({"path": rel, "kind": kind, "plus": plus, "minus": minus})
        saved.append(f"{rel}({code.count(chr(10)) + 1}行)")

    if len(blocks) < len(files):
        problems.append(f"程式碼區塊只有 {len(blocks)} 個，少於指定的 {len(files)} 個檔案")
    return saved, "；".join(problems), changes


# ---------------------------------------------------------------------------
# 輸出資料夾鎖：同一個 output_root 同時只能有一個 job 在寫（跨行程；ds.py 每次是獨立行程）
# 實測事故：多個 Claude 平行派工、任務檔撞名，兩個 job 同時改寫同一個專案，且都回報通過。
# ---------------------------------------------------------------------------
LOCK_NAME = ".ds_swarm.lock"


def _pid_alive(pid: int, since: float = 0.0) -> bool:
    """pid 還在執行。給 since（鎖的建立時間）時，行程若是之後才啟動，代表 PID 被系統重新分配給別的程式，視為已結束。"""
    if pid <= 0:
        return False
    if os.name == "nt":  # Windows 上 os.kill(pid, 0) 會結束行程，不能用
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not (k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259):  # STILL_ACTIVE
                return False
            if since:
                created, _x, _k, _u = (ctypes.c_ulonglong() for _ in range(4))
                if k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(_x),
                                       ctypes.byref(_k), ctypes.byref(_u)):
                    started = created.value / 1e7 - 11644473600  # FILETIME → Unix 秒
                    if started > since + 2:
                        return False
            return True
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_root_lock(root: Path, job_id: str) -> str:
    """取得資料夾鎖；成功回傳空字串，被佔用回傳原因。持有者行程已結束的舊鎖會被接手。"""
    path = root / LOCK_NAME
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "job_id": job_id, "ts": time.time()}).encode())
            os.close(fd)
            return ""
        except FileExistsError:
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                info = {}
            pid, other = int(info.get("pid") or 0), info.get("job_id", "?")
            same_proc_running = pid == os.getpid() and other in JOBS and JOBS[other].get("finished") is None
            if _pid_alive(pid, float(info.get("ts") or 0)) and (pid != os.getpid() or same_proc_running):
                return f"這個資料夾已有另一批任務正在寫入（job {other}），請等它完成或換一個 output_root。"
            path.unlink(missing_ok=True)  # 舊鎖：持有者已結束
    return "無法取得資料夾鎖。"


def _release_root_lock(root: Optional[Path], job_id: str) -> None:
    if root is None:
        return
    path = root / LOCK_NAME
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("job_id") == job_id:
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


def _check_write_conflicts(root: Optional[Path], files: list[str]) -> list[str]:
    """檢查多任務是否寫入同一檔案（不分大小寫）。"""
    seen: dict[str, tuple[int, str]] = {}
    conflicts = []
    base = root if root is not None else Path.cwd()
    for i, spec in enumerate(files):
        for rel in [s.strip() for s in (spec or "").split(",") if s.strip()]:
            norm = str((base / rel).resolve()).casefold()
            if norm in seen:
                j, rel_prev = seen[norm]
                if j != i:
                    conflicts.append(
                        f"#{j + 1} 的 {rel_prev!r} 與 #{i + 1} 的 {rel!r} 都寫入 {norm}"
                    )
            else:
                seen[norm] = (i, rel)
    return conflicts


async def _run_job(job_id: str) -> None:
    job = JOBS[job_id]
    job_dir = JOB_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    async def one(idx: int, task: str) -> None:
        result = None
        pipeline_parts = []
        retried = False
        final_syntax_errors = []
        review_issues_hm = []
        saved = []
        problem = ""
        outcome = "error"
        changes = []
        task_usage = _new_usage_holder()
        task_t0 = time.time()

        # 用量儀表板（即時）：開始就建 run 紀錄，每換一個階段附加一行（寫失敗只印 stderr）
        live_log = ""
        if dashboard_events is not None:
            live_log = dashboard_events.start_live(
                job_id, idx + 1, model=_pick(job["models"][idx], job["pick_texts"][idx]), task=task,
                workspace=str(job["output_root"]) if job["output_root"] is not None else "", log_fn=log)
        live_usage_seen = [""]

        def set_stage(stage: str, model: str = "") -> None:
            job["stage_info"][idx] = {
                "stage": stage,
                "model": model,
                "stage_started": time.time(),
            }
            if live_log:
                snap = json.dumps(task_usage, sort_keys=True)
                if snap != live_usage_seen[0]:
                    live_usage_seen[0] = snap
                    dashboard_events.live_usage(live_log, task_usage, log_fn=log)
                dashboard_events.live_event(live_log, stage, model=model, log_fn=log)

        def remember_usage(call_result: dict) -> None:
            usage = call_result.get("usage")
            _accumulate_usage(task_usage, usage)
            _accumulate_usage(job["usage"], usage)

        # 測試工蜂：與產出同時開跑，只看規格、用另一個模型
        test_rel = (job["test_files"][idx] or "").strip()
        impl_files = [s.strip() for s in (job["output_files"][idx] or "").split(",") if s.strip()]
        test_job = None
        gate = bool(impl_files and job["output_root"] is not None
                    and (test_rel or (job["test_cmds"][idx] or "").strip()))
        writer_alias = TEST_WRITER if TEST_WRITER in ("flash", "pro") else "flash"
        if gate and test_rel:
            producer = _pick(job["models"][idx], job["pick_texts"][idx])
            writer_alias = (TEST_WRITER if TEST_WRITER in ("flash", "pro")
                            else ("pro" if producer == "flash" else "flash"))
            test_job = asyncio.create_task(_hedged_task(
                idx + 1, _build_test_prompt(task, job["shared_context"], test_rel, impl_files),
                writer_alias, _role_effort("test", job["efforts"][idx]), "",
            ))

        try:
            files = impl_files

            # 初版產出
            primary_alias = _pick(job["models"][idx], job["pick_texts"][idx])
            set_stage("產出中", primary_alias)
            r, calls = await _hedged_task(
                idx + 1,
                _build_prompt(task, job["shared_context"], f"子任務 #{idx + 1}"),
                job["models"][idx],
                job["efforts"][idx],
                job["pick_texts"][idx],
                on_hedge=lambda: set_stage("產出中（已送避險備份）", primary_alias),
            )
            for c in calls:
                remember_usage(c)
            if r.get("hedged"):
                pipeline_parts.append(f"產出逾時{HEDGE_SECS_BY_EFFORT.get(job['efforts'][idx], HEDGE_SECS)}s→避險，"
                                      f"採用{'備份' if r['hedge_winner'] == 'backup' else '原請求'}")

            # 截斷：先檢查是否「尾端截斷但程式碼完整」；若指定檔案數已齊全且實際語法檢查全通過才視為 ok
            if r["status"] == "truncated" and files:
                blocks = _extract_code_blocks(r["content"], len(files))
                trunc_syntax_errors, trunc_syntax_notes = await _syntax_check(r["content"], files, job["forbid"][idx])
                closed = len(re.findall(r"^```\s*$", r["content"], re.M)) >= len(files)
                if closed and len(blocks) >= len(files) and not trunc_syntax_errors and not trunc_syntax_notes:
                    r["status"] = "ok"
                    r["content"] = r["content"].replace(TRUNCATION_WARNING, "").strip()
                    pipeline_parts.append(f"{_final_alias(r['model'])}尾端截斷但程式碼完整")
                else:
                    orig_alias = _final_alias(r["model"])
                    other = "pro" if orig_alias == "flash" else "flash"
                    pipeline_parts.append(f"{orig_alias}截斷")
                    retried = True
                    set_stage("重派中", other)
                    r2 = await _execute_single_task(
                        idx + 1,
                        _build_prompt(task, job["shared_context"], f"子任務 #{idx + 1}"),
                        other,
                        "low",
                        job["pick_texts"][idx],
                    )
                    remember_usage(r2)
                    alias2 = _final_alias(r2["model"])
                    if r2["status"] == "ok":
                        pipeline_parts.append(f"重派{other}OK")
                        r = r2
                    else:  # truncated or error
                        if r2["status"] == "truncated":
                            pipeline_parts.append(f"重派{other}仍截斷")
                            r = r2  # 保持截斷狀態
                        else:
                            pipeline_parts.append(f"重派{other}失敗")
                            # 保留原截斷內容，status 設為 truncated
                            r = {"id": idx+1, "status": "truncated",
                                 "model": f"{orig_alias}→{other}",
                                 "content": r["content"],
                                 "usage": r.get("usage", _empty_usage(other))}
            elif r["status"] == "truncated":
                # 沒有指定輸出檔時，無法判斷「尾端截斷但程式碼完整」，維持截斷並準備重派
                orig_alias = _final_alias(r["model"])
                other = "pro" if orig_alias == "flash" else "flash"
                pipeline_parts.append(f"{orig_alias}截斷")
                retried = True
                set_stage("重派中", other)
                r2 = await _execute_single_task(
                    idx + 1,
                    _build_prompt(task, job["shared_context"], f"子任務 #{idx + 1}"),
                    other,
                    "low",
                    job["pick_texts"][idx],
                )
                remember_usage(r2)
                alias2 = _final_alias(r2["model"])
                if r2["status"] == "ok":
                    pipeline_parts.append(f"重派{other}OK")
                    r = r2
                else:
                    if r2["status"] == "truncated":
                        pipeline_parts.append(f"重派{other}仍截斷")
                        r = r2
                    else:
                        pipeline_parts.append(f"重派{other}失敗")
                        r = {"id": idx+1, "status": "truncated",
                             "model": f"{orig_alias}→{other}",
                             "content": r["content"],
                             "usage": r.get("usage", _empty_usage(other))}
            else:
                pipeline_parts.append(_final_alias(r["model"]))
        except Exception as e:  # noqa: BLE001
            log(f"工作 {job_id} 子任務 #{idx + 1} 例外：{type(e).__name__}: {e}")
            r = {"id": idx + 1, "status": "error", "model": "?", "content": f"{type(e).__name__}: {e}",
                 "usage": _empty_usage("?")}

        # 保存初版（v1）
        content_v1 = r["content"]
        (job_dir / f"t{idx+1:02d}.v1.md").write_text(content_v1, encoding="utf-8")

        # 語法檢查
        files = [s.strip() for s in (job["output_files"][idx] or "").split(",") if s.strip()]
        set_stage("語法檢查", "")
        syntax_errors, syntax_notes = await _syntax_check(content_v1, files, job["forbid"][idx])
        pipeline_parts.append("語法OK" if not syntax_errors else f"語法錯{len(syntax_errors)}")
        if syntax_notes:
            problem = "；".join(syntax_notes)

        ok_status = r["status"] == "ok"
        producer_alias = _final_alias(r["model"])
        other_alias = "pro" if producer_alias == "flash" else "flash"
        current_content = content_v1
        final_syntax_errors = syntax_errors
        fixed = False
        unreviewed = False
        unresolved_review = False

        async def fix_loop(content: str, issues: list[str], syn_errs: list[str], label: str):
            """修正最多 2 輪：第 1 輪產出者模型＋該任務的修正強度；第 2 輪換另一個模型並升到 max
            （同模型同強度常卡在同一個思路）。回傳 (內容, 語法錯誤, 是否修好)。
            修不好時：輸入本來語法正確 → 保留輸入版本（不讓修正把好檔改壞）；否則保留最新版。"""
            cur_content, cur_errs = content, syn_errs
            rounds = [(producer_alias, _role_effort("fix", job["efforts"][idx])), (other_alias, "max")]
            for fa, fe in rounds:
                set_stage(f"{label}修正中", fa)
                res = await _execute_single_task(
                    idx + 1, _build_fix_prompt(task, job["shared_context"], cur_content, issues, cur_errs),
                    fa, fe, "")
                remember_usage(res)
                if res["status"] != "ok":
                    pipeline_parts.append(f"{label}修正{fa}失敗/截斷")
                    continue
                set_stage("語法檢查", "")
                new_errs, _ = await _syntax_check(res["content"], files, job["forbid"][idx])
                if not new_errs:
                    pipeline_parts.append(f"{label}修正{fa}({fe})完成，語法OK")
                    return res["content"], [], True
                pipeline_parts.append(f"{label}修正{fa}後仍有語法錯{len(new_errs)}")
                cur_content, cur_errs = res["content"], new_errs
            if not syn_errs:
                pipeline_parts.append(f"{label}修正未成功，保留修正前版本")
                return content, [], False
            return cur_content, cur_errs, False

        # 語法優先：語法有錯先修，不派審查員（連編譯都不過，審查是浪費）
        if ok_status and syntax_errors:
            current_content, final_syntax_errors, fixed = await fix_loop(content_v1, [], syntax_errors, "語法")

        # 審查（語法正確才審，審的是目前版本）：先用另一個模型；截斷/失敗/無 VERDICT 時換模型用 low 再試一次
        review_text = None
        if job["review_enabled"][idx] and ok_status and not final_syntax_errors:
            review_prompt = _build_review_prompt(task, job["shared_context"], current_content, files, [])
            verdict, hm_issues = "UNKNOWN", []
            attempts = [(other_alias, _role_effort("review", job["efforts"][idx])), (producer_alias, "low")]
            for n, (reviewer_alias, review_effort) in enumerate(attempts):
                set_stage("審查中", reviewer_alias)
                review_res = await _execute_single_task(idx+1, review_prompt, reviewer_alias,
                                                        review_effort, "", REVIEW_SYSTEM_PROMPT,
                                                        REVIEW_MAX_TOKENS)
                remember_usage(review_res)
                review_text = review_res["content"]
                suffix = "" if n == 0 else f".r{n + 1}"
                (job_dir / f"t{idx+1:02d}.review{suffix}.md").write_text(review_text, encoding="utf-8")
                if review_res["status"] == "ok":
                    verdict, _, hm_issues = _parse_review(review_text)
                    if verdict != "UNKNOWN":
                        break
                pipeline_parts.append(f"審查{reviewer_alias}失敗")
            if verdict != "UNKNOWN":
                high_count = sum(1 for i in hm_issues if i.startswith("[高]"))
                mid_count = len(hm_issues) - high_count
                pipeline_parts.append(f"審查{reviewer_alias}:{verdict}(高{high_count}中{mid_count})")
                review_issues_hm = hm_issues[:6]
                if hm_issues:
                    current_content, final_syntax_errors, review_fixed = await fix_loop(
                        current_content, review_issues_hm, [], "審查")
                    fixed = fixed or review_fixed
                    unresolved_review = not review_fixed  # 審查問題沒修好：不可算通過
            else:
                unreviewed = True
                pipeline_parts.append("未審查")

        final_content = current_content

        # 寫檔前先等專案測試的基準跑完，避免基準量到寫到一半的檔案
        if job.get("baseline_task") is not None:
            set_stage("等專案測試基準", "")
            await asyncio.gather(job["baseline_task"], return_exceptions=True)

        # 寫檔（最終版本）
        set_stage("寫檔", "")
        if r["status"] == "ok":
            saved, save_problem, changes = _save_code_blocks(
                final_content, job["output_files"][idx], job["output_root"],
                job_id, job["backed_up"],
            )
            if save_problem:
                problem = (problem + "；" if problem else "") + save_problem
        else:
            saved, save_problem = [], ""

        async def rewrite_blocked_test(reason: str, old_code: str) -> Optional[str]:
            """生成的測試被安全檢查擋下時，請測試工蜂改用允許的寫法重寫一次；成功回傳新測試碼並已寫檔。"""
            set_stage("改寫被擋的測試", writer_alias)
            prompt = (_build_test_prompt(task, job["shared_context"], test_rel, impl_files)
                      + f"\n\n【上一版被擋下】上一版測試用了禁止的操作：{reason}。請改寫整份測試：CLI 一律直接呼叫 "
                        "main(argv)，用 redirect_stdout／redirect_stderr 擷取輸出、捕捉 SystemExit；"
                        "其他測試內容與斷言保持不變。\n【上一版】\n```\n" + old_code + "\n```")
            res, calls = await _hedged_task(idx + 1, prompt, writer_alias,
                                            _role_effort("test", job["efforts"][idx]), "")
            for c in calls:
                remember_usage(c)
            blocks = _extract_code_blocks(res["content"], 1) if res["status"] == "ok" else []
            if not blocks:
                return None
            _save_code_blocks(f"```\n{blocks[0][1]}\n```", test_rel, job["output_root"], job_id, job["backed_up"])
            if _unsafe_test_reason(job["output_root"] / test_rel):
                return None
            return blocks[0][1]

        # 測試關卡：兩種模式
        #   生成測試：有 test_files → 測試工蜂寫的測試；修正工蜂可判斷實作錯或測試錯，兩邊都能改
        #   既有測試：只有 test_cmd → 跑專案既有測試（例如 bug 的重現測試）；只能改實作，不能改測試
        # 失敗就交給修正工蜂，最多 TEST_FIX_ROUNDS 輪
        tests_state, test_output, test_fixed, dispute_note = "", "", False, ""
        arb = {"first_failures": None, "result": "", "tokens": 0}  # 仲裁觸發率統計（寫進 manifest）
        test_cmd_i = (job["test_cmds"][idx] or "").strip()
        if gate:
            root = job["output_root"]
            can_test = r["status"] == "ok" and saved and not final_syntax_errors
            test_code, test_ready, test_was_added, writer_label = "", True, False, "既有測試"
            if not can_test:
                if test_job is not None:
                    test_job.cancel()
                test_ready = False
            elif test_job is not None:
                set_stage("等測試工蜂", "")
                test_res, test_calls = await test_job
                for c in test_calls:
                    remember_usage(c)
                writer_label = f"{test_res['model']}寫"
                (job_dir / f"t{idx+1:02d}.test.md").write_text(test_res["content"], encoding="utf-8")
                test_blocks = _extract_code_blocks(test_res["content"], 1) if test_res["status"] == "ok" else []
                test_code = test_blocks[0][1] if test_blocks else ""
                test_problem, test_changes = "", []
                if test_code:
                    _, test_problem, test_changes = _save_code_blocks(
                        f"```\n{test_code}\n```", test_rel, root, job_id, job["backed_up"])
                if test_res["status"] != "ok" or not test_code or test_problem:
                    test_ready = False
                    pipeline_parts.append("測試工蜂失敗，略過測試")
                    problem = (problem + "；" if problem else "") + (test_problem or "測試工蜂失敗，未執行測試")
                else:
                    test_was_added = bool(test_changes) and test_changes[0]["kind"] == "added"
            if test_ready and test_rel:
                reason = _unsafe_test_reason(root / test_rel)
                if reason:
                    new_code = await rewrite_blocked_test(reason, test_code)
                    if new_code is None:
                        test_ready = False
                        pipeline_parts.append("生成的測試含高風險操作，改寫後仍不合格，未執行")
                        problem = (problem + "；" if problem else "") + f"生成的測試含高風險操作（{reason}），未執行，請人工確認"
                    else:
                        test_code = new_code
                        pipeline_parts.append(f"測試含高風險操作（{reason[:40]}）→已改寫")
            if test_ready:
                impl_added = {c["path"] for c in changes if c.get("kind") == "added"}
                set_stage("執行測試", "")
                ok, test_output = await _run_tests(root, test_rel, test_cmd_i)
                pipeline_parts.append(f"測試({writer_label}):{'OK' if ok else '失敗'}")
                rounds = 0
                blocked = ""
                disputed = False
                dispute_note = ""
                # B：生成測試失敗 → 另一個模型只看規格寫第二份實作，在同一份測試上跑：
                #   第二份通過 → 原實作錯，直接採用第二份（省掉修正回合）
                #   兩份在同樣的測試失敗 → 判定測試寫錯，不改動實作（避免把正確的程式改壞）
                #   其他情況 → 交給原本的修正流程
                arb["first_failures"] = 0 if ok else len(_failed_tests(test_output)) or 1
                if not ok and ARBITRATE and test_rel:
                    set_stage("仲裁：第二份實作", other_alias)
                    alt, alt_calls = await _hedged_task(
                        idx + 1, _build_prompt(task, job["shared_context"], f"子任務 #{idx + 1}"),
                        other_alias, job["efforts"][idx], "")
                    for c in alt_calls:
                        remember_usage(c)
                        arb["tokens"] += int((c.get("usage") or {}).get("completion_tokens", 0) or 0)
                    alt_blocks = _extract_code_blocks(alt["content"], len(files)) if alt["status"] == "ok" else []
                    alt_text = "\n".join(f"```{lang}\n{code}\n```" for lang, code in alt_blocks[:len(files)])
                    alt_errs = (await _syntax_check(alt_text, files, job["forbid"][idx]))[0] if len(alt_blocks) >= len(files) else ["缺區塊"]
                    if not alt_errs:
                        _save_code_blocks(alt_text, ",".join(files), root, job_id, job["backed_up"])
                        set_stage("仲裁：執行測試", "")
                        alt_ok, alt_out = await _run_tests(root, test_rel, test_cmd_i)
                        orig_fails, alt_fails = _failed_tests(test_output), _failed_tests(alt_out)
                        if alt_ok:
                            final_content, ok, test_output, test_fixed = alt["content"], True, alt_out, True
                            pipeline_parts.append(f"仲裁：{other_alias}獨立實作通過測試→採用")
                            arb["result"] = "adopt_alt"
                        else:
                            _save_code_blocks(final_content, ",".join(files), root, job_id, job["backed_up"])
                            if orig_fails and orig_fails == alt_fails:
                                disputed = True
                                arb["result"] = "test_wrong"
                                pipeline_parts.append(f"仲裁：兩份獨立實作在相同測試失敗→判定測試有誤（{len(orig_fails)} 項）")
                                # 同家族模型的失誤常常相關（研究：failure independence），把爭議斷言放進摘要讓 Claude 順手核對
                                msgs = [ln.strip() for ln in test_output.splitlines()
                                        if re.search(r"AssertionError|assert|Expected|expected|actual|!=", ln)][:2]
                                names = "、".join(sorted(orig_fails))[:120]
                                old_asserts = "｜".join(m[:160] for m in msgs)
                                # C：把判定寫錯的測試修掉（只動這幾條），重跑確認整份測試全綠，摘要才會與實際一致
                                set_stage("修正爭議測試", writer_alias)
                                dfix_prompt = (
                                    _context_prefix(job["shared_context"])
                                    + "你是測試修正工蜂。下列測試在兩份獨立撰寫的實作上都以相同方式失敗，已判定是測試誤讀規格。"
                                      f"只修正或刪除這些測試：{names}；其他測試一字不改。"
                                      "規格有明確規定該行為時，改成規格要求的預期；規格沒有規定（未定義的行為）時，"
                                      "直接刪除那條斷言，不要改成另一個寫死的預期。\n"
                                    + "\n【規格（原任務）】\n" + task.strip() + "\n"
                                    + f"\n【目前測試 {test_rel}】\n```\n{test_code}\n```\n"
                                    + "\n【測試執行輸出（節錄）】\n```\n" + test_output[-2000:] + "\n```\n"
                                    + "\n【輸出】單一程式碼區塊，內容是完整測試檔。")
                                dres, dcalls = await _hedged_task(idx + 1, dfix_prompt, writer_alias,
                                                                  _role_effort("fix", job["efforts"][idx]), "")
                                for c in dcalls:
                                    remember_usage(c)
                                    arb["tokens"] += int((c.get("usage") or {}).get("completion_tokens", 0) or 0)
                                dblocks = _extract_code_blocks(dres["content"], 1) if dres["status"] == "ok" else []
                                if dblocks:
                                    _save_code_blocks(f"```\n{dblocks[0][1]}\n```", test_rel, root, job_id, job["backed_up"])
                                if dblocks and not _unsafe_test_reason(root / test_rel):
                                    test_code = dblocks[0][1]
                                    ok, test_output = await _run_tests(root, test_rel, test_cmd_i)
                                if ok:
                                    dispute_note = (f"已修正爭議測試 {names}" + (f"｜原斷言：{old_asserts}" if old_asserts else ""))
                                    pipeline_parts.append("爭議測試已修正→整份測試通過")
                                else:
                                    dispute_note = f"爭議測試 {names} 修正後整份測試仍未通過" + (f"｜{old_asserts}" if old_asserts else "")
                                    pipeline_parts.append("爭議測試修正後仍失敗")
                                problem = (problem + "；" if problem else "") + dispute_note
                            else:
                                pipeline_parts.append("仲裁：無定論，交給修正")
                                arb["result"] = "inconclusive"
                    else:
                        pipeline_parts.append("仲裁：第二份實作失敗，交給修正")
                        arb["result"] = "alt_failed"
                while not ok and not disputed and rounds < TEST_FIX_ROUNDS:
                    rounds += 1
                    # 第 1 輪產出者模型＋修正強度；第 2 輪換另一個模型並升到 max
                    alias, fix_effort = ((producer_alias, _role_effort("fix", job["efforts"][idx])) if rounds == 1
                                         else (other_alias, "max"))
                    set_stage("依測試修正", alias)
                    tf_res = await _execute_single_task(
                        idx + 1,
                        _build_test_fix_prompt(task, job["shared_context"], final_content,
                                               test_rel, test_code, test_output,
                                               test_cmd_i if not test_rel else ""),
                        alias, fix_effort, "",
                    )
                    remember_usage(tf_res)
                    # 本輪失敗不中止：continue 讓下一輪（換模型、max）再試，失敗的版本不寫檔
                    if tf_res["status"] != "ok":
                        pipeline_parts.append(f"依測試修正{alias}失敗")
                        continue
                    blocks = _extract_code_blocks(tf_res["content"])
                    need = len(files) + (1 if test_rel else 0)
                    if len(blocks) < need:
                        pipeline_parts.append(f"依測試修正{alias}：程式碼區塊數不足")
                        continue
                    impl_text = "\n".join(f"```{lang}\n{code}\n```" for lang, code in blocks[:len(files)])
                    errs, _ = await _syntax_check(impl_text, files, job["forbid"][idx])
                    if errs:
                        pipeline_parts.append(f"依測試修正{alias}後語法錯{len(errs)}，未寫入")
                        continue
                    _save_code_blocks(impl_text, ",".join(files), root, job_id, job["backed_up"])
                    if test_rel:
                        test_code = blocks[len(files)][1]
                        _save_code_blocks(f"```\n{test_code}\n```", test_rel, root, job_id, job["backed_up"])
                        reason = _unsafe_test_reason(root / test_rel)
                        if reason:
                            new_code = await rewrite_blocked_test(reason, test_code)
                            if new_code is None:
                                blocked = reason
                                pipeline_parts.append("修正後的測試含高風險操作，改寫後仍不合格，停止執行")
                                break
                            test_code = new_code
                            pipeline_parts.append("修正後的測試含高風險操作→已改寫")
                    final_content = tf_res["content"]
                    set_stage("執行測試", "")
                    ok, test_output = await _run_tests(root, test_rel, test_cmd_i)
                    pipeline_parts.append(f"依測試修正{alias}→測試{'OK' if ok else '失敗'}")
                    test_fixed = test_fixed or ok
                # 爭議測試若沒修綠就是 fail（不再有「✔ 但整份測試是紅的」）
                tests_state = "skipped" if blocked else ("pass" if ok else "fail")
                if blocked:
                    problem = (problem + "；" if problem else "") + f"修正後的測試含高風險操作（{blocked}），未執行"
                # 多次寫入同一檔後，依磁碟最終內容重算變更
                changes = [_final_change(root, f, job_id, f in impl_added) for f in files]
                if test_rel:
                    changes.append(_final_change(root, test_rel, job_id, test_was_added))
                saved = [f"{c['path']}" for c in changes]
                if not ok and not blocked and not disputed:
                    last = test_output.strip().splitlines()[-1] if test_output.strip() else ""
                    problem = (problem + "；" if problem else "") + f"測試仍失敗：{last[:150]}"
            else:
                tests_state = "skipped"  # 有指定測試卻沒跑成：絕不能算通過

        # 保存最終版本
        (job_dir / f"t{idx+1:02d}.md").write_text(final_content, encoding="utf-8")

        # 決定 outcome
        if r["status"] == "error":
            outcome = "error"
        elif r["status"] == "truncated":
            outcome = "truncated"
        elif final_syntax_errors or tests_state == "fail" or (files and not saved) or unresolved_review:
            outcome = "issues"
        elif tests_state == "skipped":
            outcome = "untested"
        elif fixed or test_fixed:
            outcome = "fixed"
        elif unreviewed and tests_state != "pass":  # 測試通過本身就是驗證
            outcome = "unreviewed"
        else:
            outcome = "pass"

        pipeline_str = " → ".join(pipeline_parts)

        result = {
            "id": idx + 1,
            "status": r["status"] if r["status"] != "error" else "error",
            "model": r["model"],
            "content": final_content,
            "saved": saved,
            "problem": problem,
            "pipeline": pipeline_str,
            "review_issues": review_issues_hm,
            "syntax_errors": final_syntax_errors,
            "tests": tests_state,
            "dispute": dispute_note,
            "arbitration": arb,
            "test_output": test_output[-600:] if tests_state == "fail" else "",
            "retried": retried,
            "outcome": outcome,
            "usage": task_usage,
            "changes": changes,
        }
        job["results"][idx] = result
        set_stage("完成", "")

        # 用量儀表板：寫結束事件（寫失敗只印 stderr，絕不影響工蜂）
        if live_log:
            dashboard_events.live_end(
                live_log,
                ok=result.get("outcome") in ("pass", "fixed", "untested", "unreviewed"),
                status=str(result.get("outcome") or ""),
                usage=task_usage,
                cost_usd=_estimate_cost(task_usage),
                elapsed_sec=time.time() - task_t0,
                log_fn=log,
            )

    # 專案既有測試（verify_cmd）：先跑一次記下原本結果（與產出並行；寫檔前會等它跑完），
    # 全部任務寫完後再跑一次，兩次比較寫進摘要。原本就失敗的測試不算這批改壞的。
    verify_cmd = job.get("verify_cmd", "")
    baseline_task = None
    if verify_cmd and job["output_root"] is not None:
        async def baseline() -> None:
            job["verify"]["before"] = await _run_tests(job["output_root"], "", verify_cmd)
        baseline_task = asyncio.create_task(baseline())
    job["baseline_task"] = baseline_task

    outcomes = await asyncio.gather(*(one(i, t) for i, t in enumerate(job["tasks"])),
                                    return_exceptions=True)
    if baseline_task is not None:
        await asyncio.gather(baseline_task, return_exceptions=True)
        job["stage_note"] = "執行專案測試（寫檔後）"
        job["verify"]["after"] = await _run_tests(job["output_root"], "", verify_cmd)
    for i, exc in enumerate(outcomes):
        if isinstance(exc, BaseException) and job["results"][i] is None:
            log(f"工作 {job_id} 子任務 #{i + 1} 未預期例外：{type(exc).__name__}: {exc}")
            job["results"][i] = {"id": i + 1, "status": "error", "model": "?", "outcome": "error",
                                 "content": f"{type(exc).__name__}: {exc}", "changes": []}

    # 最終一致性檢查：全部寫完後，把每個「測試通過」的任務測試再跑一次（後面的任務可能改到前面的依賴），
    # 讓摘要的「✔」與使用者實際執行的結果一致。
    final = []
    for i, r in enumerate(job["results"]):
        test_rel = (job["test_files"][i] or "").strip()
        cmd = (job["test_cmds"][i] or "").strip()
        if not r or r.get("tests") != "pass" or job["output_root"] is None or not (test_rel or cmd):
            continue
        job["stage_note"] = "最終重跑全部測試"
        ok, out = await _run_tests(job["output_root"], test_rel, cmd)
        final.append(ok)
        if not ok:
            r["tests"] = "fail"
            r["outcome"] = "issues"
            r["test_output"] = out[-600:]
            r["problem"] = ((r.get("problem") + "；") if r.get("problem") else "") + "整批完成後重跑測試失敗（可能被其他任務的變更影響）"
    if final:
        job["final_check"] = f"最終重跑測試：{sum(final)}/{len(final)} 通過"
    job["finished"] = time.time()
    _release_root_lock(job["output_root"], job_id)

    # 寫 manifest，供伺服器重啟後 restore_swarm_job 讀取
    try:
        manifest = {
            "job_id": job_id,
            "output_root": str(job["output_root"]) if job["output_root"] is not None else "",
            "finished": job["finished"],
            "tasks": [
                {
                    "id": r.get("id"),
                    "changes": r.get("changes", []),
                    "arbitration": r.get("arbitration", {}),
                    "outcome": r.get("outcome"),
                }
                for r in job["results"]
                if r is not None
            ],
        }
        (job_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        log(f"工作 {job_id} 寫 manifest 失敗：{type(e).__name__}: {e}")

    # 最後寫摘要（先寫暫存再改名），wait_job.py 看到 summary.txt 即代表整批完成
    try:
        tmp = job_dir / "summary.txt.tmp"
        tmp.write_text(_render_job(job_id, job), encoding="utf-8")
        os.replace(tmp, job_dir / "summary.txt")
    except Exception as e:  # noqa: BLE001
        log(f"工作 {job_id} 寫 summary 失敗：{type(e).__name__}: {e}")


@mcp.tool()
async def submit_swarm_job(
    task_list: Optional[list[str]] = None,
    shared_context: str = "",
    models: Optional[list[ModelChoice]] = None,
    effort: str = "",
    output_root: str = "",
    output_files: Optional[list[str]] = None,
    job_file: str = "",
    shared_attach: Optional[list[str]] = None,
    task_attach: Optional[list[str]] = None,
    read_root: str = "",
    review: str = "",
    test_files: Optional[list[str]] = None,
    test_cmd: Optional[list[str]] = None,
    efforts: Optional[list[str]] = None,
    verify_cmd: str = "",
    forbid_patterns: Optional[list[str]] = None,
) -> str:
    """【背景批次】長任務專用：立即回傳 job_id，工蜂在背景並行執行，之後用 get_swarm_job 取結果。

    task_list / shared_context / models：同 batch_parallel_swarm；有 output_files 的任務 auto 一律用 flash。
    effort: "" | max | high | low，套用到整批。空白=自動：有審查流水線的任務用 high（審查員會補抓錯），其餘用 max。
    efforts: 選填，與 task_list 一一對應的逐任務強度（"" | low | high | max），優先於 effort；空字串=沿用 effort／自動。
    output_root: 絕對路徑資料夾；搭配 output_files 讓伺服器直接寫檔（路徑不可跳出此資料夾）。
    output_files: 與 task_list 一一對應；每項為逗號分隔的相對路徑，依序對應該任務回覆中的程式碼區塊；空字串=不寫檔。
    job_file: 選填，JSON 檔絕對路徑，內容可含 task_list、shared_context、models、output_files、output_root、
              review（"auto"|"on"|"off"）；呼叫參數有值時優先於檔案內容。可省去重複貼上長指令。
    shared_attach: 選填，所有任務共用的唯讀附檔（read_root 內相對路徑或 glob）。
    task_attach: 選填，與 task_list 一一對應，每項為逗號分隔的相對路徑或 glob，附給該任務。
    read_root: 附檔根目錄（預設同 output_root）。附檔在送出當下讀取（快照）；敏感檔自動略過。
    review: "" | "auto" | "on" | "off"；空白時依 job_file 的 review，再無則 "auto"。
            auto = 該任務有 output_files 時啟用審查，否則關閉。
            啟用時會多派審查工蜂與可能的修正工蜂，耗時較長。
    test_files: 選填，與 task_list 一一對應的測試檔相對路徑（例 "tests/test_inventory.py"、"tests/bytes.test.mjs"），
                空字串=不測。有值時同時派「測試工蜂」（預設 flash、看不到實作、只看規格）寫測試，實作寫檔後伺服器實際執行；
                失敗就把輸出交給修正工蜂判斷實作錯或測試錯並修正，最多 2 輪。.py 用 unittest，.js/.mjs 用 node --test。
                注意：測試碼由模型撰寫並在本機執行（cwd=output_root，逾時 120 秒，不帶 API 金鑰）。
    test_cmd: 選填，與 task_list 對應的測試指令（在 output_root 執行）。
              搭配 test_files：用這個指令跑生成的測試（空字串=依副檔名自動）。
              只給 test_cmd、不給 test_files：跑「既有測試」當關卡（例如 bug 的重現測試），不派測試工蜂，
              修正工蜂只能改實作、不能改測試。
    forbid_patterns: 選填，正規表示式清單（套用到所有任務的輸出檔）。規格禁止的函式／模組
                     （例 "(?<![.\\w])(eval|exec|compile)\\s*\\(", "import ast"）寫在這裡：每個版本都會掃描原始碼全文
                     （含註解、docstring、字串），命中就當成錯誤交給修正工蜂，修不掉標「仍有問題」。
    verify_cmd: 選填，專案既有的整體測試指令（例 "python -m pytest -q"）。送出時先跑一次記下原本結果，
                整批寫完後再跑一次，摘要顯示「原本通過 → 現在失敗」等比較（只回報，不自動修）。
    自動強度：有測試關卡（test_files 或 test_cmd）的任務預設 low，測試沒過時修正工蜂自動升到 high。
    每個任務完整回覆另存於 ~/.deepseek_swarm_jobs/<job_id>/tNN.md（另有 v1、review 版本）。
    整批完成時寫 summary.txt（內容同 get_swarm_job 摘要）；用 shell 背景執行
    `python <本程式所在資料夾>\\wait_job.py <job_id>` 等待（送出後的回傳訊息會給完整指令），完成即印出摘要，不必輪詢。
    """
    spec: dict = {}
    if job_file:
        try:
            spec = json.loads(Path(job_file).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return f"[ERROR] 無法讀取 job_file：{type(e).__name__}: {e}"

    tasks = [t for t in (task_list or spec.get("task_list") or []) if t and t.strip()]
    if not tasks:
        return "[ERROR] task_list 為空。"
    effort = effort or spec.get("effort", "")
    if effort and effort not in VALID_EFFORTS:
        return f"[ERROR] effort 只能是空白（自動）或 {VALID_EFFORTS}。"
    model_list = list(models or spec.get("models") or [])
    bad = [m for m in model_list if m not in VALID_MODELS]
    if bad:
        return f"[ERROR] models 只能包含 {VALID_MODELS}，收到 {bad}。"
    model_list += ["auto"] * (len(tasks) - len(model_list))
    files = list(output_files or spec.get("output_files") or [])
    files += [""] * (len(tasks) - len(files))
    # 寫檔的程式任務不走關鍵字判斷（避免提到 history 等字就被派給較慢的 pro）
    model_list = ["flash" if m == "auto" and files[i].strip() else m
                  for i, m in enumerate(model_list[: len(tasks)])]
    root_str = output_root or spec.get("output_root") or ""
    root = Path(root_str).resolve() if root_str else None
    if root is not None and not root.is_absolute():
        return "[ERROR] output_root 必須是絕對路徑。"

    tests = list(test_files or spec.get("test_files") or [])
    tests += [""] * (len(tasks) - len(tests))
    tests = [(t or "").strip() for t in tests[: len(tasks)]]
    cmds = list(test_cmd or spec.get("test_cmd") or [])
    cmds += [""] * (len(tasks) - len(cmds))
    for i, t in enumerate(tests):
        if (t or (cmds[i] or "").strip()) and (root is None or not files[i].strip()):
            return (f"[ERROR] #{i + 1} 指定了 test_files/test_cmd，但沒有 output_root 或 output_files"
                    "（測試需要先寫出實作檔）。")
    verify_cmd = (verify_cmd or spec.get("verify_cmd") or "").strip()
    if verify_cmd and root is None:
        return "[ERROR] verify_cmd 需要 output_root（在該資料夾執行）。"

    # 寫入衝突檢查：同一檔案不可由兩個任務寫入（測試檔也算）
    conflicts = _check_write_conflicts(
        root, [",".join(x for x in (files[i], tests[i]) if x.strip()) for i in range(len(tasks))])
    if conflicts:
        return "[ERROR] 寫入衝突：\n" + "\n".join(conflicts)

    # 解析 review 參數：呼叫參數非空時優先；否則 job_file 的 review；再無則 auto
    review_setting = review if review else spec.get("review", "auto")
    if review_setting not in ("auto", "on", "off"):
        return f"[ERROR] review 只能是 'auto'、'on' 或 'off'，收到 {review_setting!r}。"
    review_enabled = []
    for i in range(len(tasks)):
        has_output = bool(files[i].strip())
        if review_setting == "on":
            review_enabled.append(True)
        elif review_setting == "off":
            review_enabled.append(False)
        else:  # auto
            review_enabled.append(has_output)
    per_effort = [(e or "").strip() for e in (efforts or spec.get("efforts") or [])]
    bad_e = [e for e in per_effort if e and e not in VALID_EFFORTS]
    if bad_e:
        return f"[ERROR] efforts 只能包含空字串或 {VALID_EFFORTS}，收到 {bad_e}。"
    per_effort += [""] * (len(tasks) - len(per_effort))
    # 自動強度（便宜先試、關卡把關、失敗才升級）：
    #   有測試關卡 → low（測試沒過時修正工蜂自動升到 high）；有審查無測試 → high；其餘（推理題）→ max
    has_gate = [bool(files[i].strip() and (tests[i] or (cmds[i] or "").strip())) for i in range(len(tasks))]
    efforts = [per_effort[i] or effort or ("low" if has_gate[i] else "high" if review_enabled[i] else "max")
               for i in range(len(tasks))]
    # H：有測試關卡的任務，high 一律改回 low（測試沒過時修正會自動升到 high）。
    # 實測：主代理自行設 high 的 4 個子任務有 3 個觸發逾時避險，DeepSeek 費用翻倍，正確率沒有提升。
    # max 視為使用者／主代理明確標示的高風險，保留。
    effort_notes = []
    for i in range(len(tasks)):
        if has_gate[i] and efforts[i] == "high":
            efforts[i] = "low"
            effort_notes.append(f"#{i + 1}")
    # forbid_patterns 接受兩種格式：字串清單＝套用到全部任務；清單的清單＝與 task_list 一一對應
    # （主代理常照其他欄位的習慣寫成巢狀，實測直接當掉、多花一輪）
    raw_forbid = forbid_patterns or spec.get("forbid_patterns") or []
    if not isinstance(raw_forbid, list):
        return '[ERROR] forbid_patterns 要是字串清單（全部任務共用），例 ["import ast"]，或與 task_list 對應的清單的清單。'
    if raw_forbid and all(isinstance(x, list) for x in raw_forbid):
        per_forbid = [[p for p in x if isinstance(p, str) and p] for x in raw_forbid]
        per_forbid += [[]] * (len(tasks) - len(per_forbid))
    elif all(isinstance(x, str) for x in raw_forbid):
        per_forbid = [[p for p in raw_forbid if p]] * len(tasks)
    else:
        return '[ERROR] forbid_patterns 不能混用字串和清單：全部任務共用寫 ["import ast"]；逐任務寫 [[], ["import ast"], []]。'
    bad_rx = []
    for p in {p for x in per_forbid for p in x}:
        try:
            re.compile(p)
        except re.error as e:
            bad_rx.append(f"{p!r}：{e}")
    if bad_rx:
        return "[ERROR] forbid_patterns 有不合法的正規表示式：" + "；".join(bad_rx)
    forbid = per_forbid[: len(tasks)]
    # C：review=auto 時，有生成測試把關且非 max 的任務不審查（測試是更可靠的關卡）；max（高風險）兩者都要
    if review_setting == "auto" and not REVIEW_WITH_TESTS:
        review_enabled = [review_enabled[i] and not (tests[i] and efforts[i] != "max") for i in range(len(tasks))]

    rr = read_root or spec.get("read_root") or root_str
    rroot = Path(rr).resolve() if rr else None
    shared_text, attach_notes = _read_attachments(rroot, _split_patterns(shared_attach or spec.get("shared_attach")))
    per_task = list(task_attach or spec.get("task_attach") or [])
    per_task += [""] * (len(tasks) - len(per_task))
    new_tasks = []
    for i, t in enumerate(tasks):
        txt, n = _read_attachments(rroot, _split_patterns(per_task[i]))
        attach_notes += [f"#{i + 1} {x}" for x in n]
        new_tasks.append(t + txt)
    # 附檔是任務的一部分：缺檔就整批不送出（實測缺規格時工蜂只能自己猜 API，白跑一整輪 $0.26）
    missing = [n.replace(MISSING_MARK, "") for n in attach_notes if MISSING_MARK in n]
    if missing:
        return ("[ERROR] 附檔有問題，未送出任何任務：" + "；".join(missing)
                + f"\n相對路徑以 read_root 為根（目前：{rroot}）；規格在別的資料夾時改用絕對路徑。")

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    if root is not None and any(f.strip() for f in files[: len(tasks)]):
        lock_error = _acquire_root_lock(root, job_id)
        if lock_error:
            return f"[ERROR] {lock_error}"
    JOBS[job_id] = {
        "tasks": new_tasks,
        "pick_texts": tasks,
        "shared_context": (shared_context or spec.get("shared_context", "")) + shared_text,
        "models": model_list[: len(tasks)],
        "efforts": efforts,
        "output_root": root,
        "output_files": files[: len(tasks)],
        "test_files": tests,
        "test_cmds": [(c or "") for c in cmds[: len(tasks)]],
        "review_enabled": review_enabled,
        "results": [None] * len(tasks),
        "started": time.time(),
        "finished": None,
        "usage": _new_usage_holder(),
        "backed_up": set(),
        "stage_info": [None] * len(tasks),
        "verify_cmd": verify_cmd,
        "verify": {},
        "forbid": forbid,
    }
    JOBS[job_id]["runner"] = asyncio.create_task(_run_job(job_id))
    # 不論 job 正常結束或中途例外，都釋放資料夾鎖（同一行程內的鎖不會因為行程還活著而卡死）
    JOBS[job_id]["runner"].add_done_callback(lambda _t, r=root, j=job_id: _release_root_lock(r, j))
    picked = ", ".join(f"#{i + 1}={_pick(m, t)}" for i, (m, t) in enumerate(zip(model_list, tasks)))
    note = f"\n附檔備註：{'；'.join(attach_notes)}" if attach_notes else ""
    review_note = f" review={review_setting} effort={'/'.join(sorted(set(efforts)))}"
    if any(tests):
        review_note += f" 測試={sum(1 for t in tests if t)}項"
    if effort_notes:
        review_note += f"\n注意：{'、'.join(effort_notes)} 有測試關卡，high 已改為 low（測試沒過時會自動升級）"
    JOBS[job_id]["effort_notes"] = effort_notes
    return (f"[SUBMITTED] job_id={job_id} 任務數={len(tasks)} 模型：{picked}{review_note}{note}\n"
            f"等待：shell 背景執行 python {WAIT_JOB_SCRIPT} {job_id}（完成自動印摘要）")


@mcp.tool()
async def get_swarm_job(job_id: str, wait_seconds: int = MAX_WAIT, full: bool = False, brief: bool = True) -> str:
    """【取背景批次結果】最多等待 wait_seconds（上限 40 秒）後回報進度。

    未完成時回 [RUNNING] 與已完成數，再呼叫一次即可繼續等。
    brief=True（預設）時每個任務只回摘要：狀態、pipeline、已寫入檔案、問題、
    FLAGS 中的「信心」「未完成」兩行與疑點中標 [高] 的行（最多 3 條）、未解決的審查問題（最多 3 條）。
    full=True 時回完整回覆內容。
    若 full=False 且 brief=False，則回舊版簡介（非 ok 顯示末 800 字，ok 顯示 FLAGS）。
    header 會加上總計：通過/修正後通過/仍有問題/截斷/失敗。
    """
    job = JOBS.get(job_id)
    if job is None:
        return f"[ERROR] 找不到 job_id={job_id}（伺服器可能已重啟；完整回覆仍在 {JOB_DIR / job_id}）。"
    deadline = time.time() + max(0, min(int(wait_seconds), MAX_WAIT))
    while job["finished"] is None and time.time() < deadline:
        await asyncio.sleep(1)
    return _render_job(job_id, job, full, brief)


def _render_job(job_id: str, job: dict, full: bool = False, brief: bool = True) -> str:
    results = job["results"]
    done = [r for r in results if r is not None]
    elapsed = int((job["finished"] or time.time()) - job["started"])
    state = "DONE" if job["finished"] is not None else "RUNNING"

    # 統計 outcome
    counts = {"pass": 0, "fixed": 0, "unreviewed": 0, "untested": 0, "issues": 0, "truncated": 0, "error": 0}
    for r in done:
        outcome = r.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    total_line = (f"通過 {counts['pass']}｜修正後通過 {counts['fixed']}｜未審查 {counts['unreviewed']}｜"
                  f"未測試 {counts['untested']}｜仍有問題 {counts['issues']}｜截斷 {counts['truncated']}｜"
                  f"失敗 {counts['error']}")

    lines = [f"[{state}] job_id={job_id} 完成 {len(done)}/{len(results)}｜經過 {elapsed}s｜{total_line}｜回覆存於 {JOB_DIR / job_id}"]
    lines.append(_usage_header(job.get("usage")))
    if job.get("final_check"):
        lines.append(job["final_check"])
    verify = job.get("verify") or {}
    if job.get("verify_cmd"):
        before, after = verify.get("before"), verify.get("after")
        word = lambda r: "?" if r is None else ("通過" if r[0] else "失敗")
        line = f"專案測試（{job['verify_cmd']}）：原本{word(before)} → 現在{word(after)}"
        if after is not None and not after[0]:
            line += "（原本就失敗，不一定是這批造成）" if before is not None and not before[0] else " ⚠ 這批改動造成失敗"
            line += "\n專案測試輸出末段:\n" + after[1][-800:]
        lines.append(line)

    for idx, r in enumerate(results):
        if r is None:
            stage_info = job["stage_info"][idx]
            if stage_info:
                stage = stage_info.get("stage", "產出中")
                model = stage_info.get("model", "")
                started = stage_info.get("stage_started", time.time())
                secs = int(time.time() - started)
                text = f"#{idx + 1} {stage}"
                if model:
                    text += f"（{model}）"
                text += f" 已 {secs}s"
                if secs > TIMEOUT + 60:
                    text += " ⚠ 可能卡住"
                lines.append(f"--- {text}")
            else:
                lines.append(f"--- #{idx + 1} 執行中（{_pick(job['models'][idx], job['pick_texts'][idx])}）")
            continue
        head = f"--- #{r['id']} [{r['status'].upper()}] model={r['model']}"
        if full:
            # 照舊完整內容
            if r.get("saved"):
                head += " 已寫入：" + " ".join(r["saved"])
            if r.get("problem"):
                head += f"｜注意：{r['problem']}"
            lines.append(head)
            lines.append(r["content"])
        elif brief:
            # 摘要模式
            parts = [head]
            if r.get("pipeline"):
                parts.append(f"pipeline: {r['pipeline']}")
            if r.get("saved"):
                parts.append("已寫入：" + " ".join(r["saved"]))
            if r.get("problem"):
                parts.append("問題：" + r["problem"])
            parts.append(_render_changes(r.get("changes", [])))
            parts.append(f"用量：輸出 {_total_output_tokens(r.get('usage'))} tokens")
            flags_summary = _extract_flags_summary(r["content"])
            parts.append(f"信心: {flags_summary['confidence']}｜未完成: {flags_summary['unfinished']}")
            if flags_summary["high_concerns"]:
                parts.append("高疑點: " + "；".join(flags_summary["high_concerns"]))
            if r.get("review_issues"):
                parts.append("審查問題: " + "；".join(r["review_issues"][:3]))
            if r.get("tests"):
                parts.append("測試: " + {"pass": "通過", "fail": "失敗", "skipped": "未執行 ⚠",
                                         "disputed": "通過（爭議測試判定為測試錯）"}.get(r["tests"], r["tests"]))
            if r.get("test_output"):
                parts.append("測試輸出末段:\n" + r["test_output"])
            lines.append(" ".join(parts))
        else:
            # 舊版簡介模式
            if r.get("saved"):
                head += " 已寫入：" + " ".join(r["saved"])
            if r.get("problem"):
                head += f"｜注意：{r['problem']}"
            lines.append(head)
            if r["status"] != "ok":
                lines.append(r["content"][-800:])
            else:
                lines.append(_flags_of(r["content"]))
    return "\n".join(lines)


@mcp.tool()
async def restore_swarm_job(job_id: str) -> str:
    """【還原背景批次寫入】把該 job 的 backup 檔全部還原到原位置，並刪除該 job 新增的檔案（僅限 output_root 內）。

    job 不在記憶體時，會嘗試從 JOB_DIR/<job_id>/manifest.json 讀取 output_root 與 changes。
    """
    job = JOBS.get(job_id)
    backup_root = JOB_DIR / job_id / "backup"

    if job is not None:
        output_root = job.get("output_root")
        changes = []
        for r in job.get("results", []):
            if r:
                changes.extend(r.get("changes", []))
    else:
        manifest_path = JOB_DIR / job_id / "manifest.json"
        if not manifest_path.is_file():
            return f"[ERROR] 找不到 job_id={job_id}，也沒有 manifest.json。"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return f"[ERROR] 無法讀取 manifest.json：{type(e).__name__}: {e}"
        root_str = manifest.get("output_root", "")
        output_root = Path(root_str).resolve() if root_str else None
        changes = []
        for task in manifest.get("tasks", []):
            changes.extend(task.get("changes", []))

    if output_root is None:
        return "[ERROR] 該 job 沒有 output_root，無法還原。"

    restored = []
    deleted = []
    problems = []

    # 還原所有 backup 檔；沒有 backup 資料夾不代表沒有 added 檔要刪除
    if backup_root.is_dir():
        for backup_file in sorted(backup_root.rglob("*")):
            if not backup_file.is_file():
                continue
            rel = backup_file.relative_to(backup_root).as_posix()
            target = (output_root / rel).resolve()
            if output_root not in target.parents:
                problems.append(f"{rel} 不在 output_root 內，略過還原")
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, target)
                restored.append(rel)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{rel} 還原失敗：{type(e).__name__}: {e}")
    else:
        problems.append(f"找不到 backup 資料夾（此 job 可能未覆寫既有檔案）：{backup_root}")

    # 刪除 added 檔案（僅限 output_root 內）
    for change in changes:
        if change.get("kind") != "added":
            continue
        rel = change.get("path")
        if not rel:
            continue
        target = (output_root / rel).resolve()
        if output_root not in target.parents:
            continue
        try:
            if target.exists() and target.is_file():
                target.unlink()
                deleted.append(rel)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{rel} 刪除失敗：{type(e).__name__}: {e}")

    lines = [f"[RESTORED] job_id={job_id}"]
    lines.append("還原：" + (", ".join(restored) if restored else "無"))
    lines.append("刪除：" + (", ".join(deleted) if deleted else "無"))
    if problems:
        lines.append("問題：" + "；".join(problems))
    return "\n".join(lines)


if __name__ == "__main__":
    log(
        f"啟動：flash={MODEL_MAP['flash']} pro={MODEL_MAP['pro']} auto={AUTO_MODEL} "
        f"base_url={BASE_URL} 並發={CONCURRENCY} 逾時={TIMEOUT}s 輸出上限={MAX_TOKENS}"
    )
    mcp.run()
