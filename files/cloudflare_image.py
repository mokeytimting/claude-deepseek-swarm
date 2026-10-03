"""Cloudflare Workers AI 生圖 MCP 伺服器（stdio）。

注意：這是 stdio MCP 伺服器，stdout 專供協定通訊。
任何除錯訊息一律用 log() 印到 stderr，絕對不要在這裡 print()。

用途：
  Claude 拆任務 → DeepSeek 寫詳細 prompt → 本工具呼叫 Workers AI 生圖、
  存檔、回傳本機路徑 → Claude 直接讀圖審核，不合格就改 prompt 或帶參考圖重跑。

模型（model 參數）：
  klein  （預設）FLUX.2 [klein] 4B：快、省額度，可指定尺寸與 seed，支援 0–4 張參考圖改圖。
  fast   FLUX.1 [schnell]：最省額度，但尺寸固定、不能指定 seed、不能放參考圖。
  text   Leonardo Lucid Origin：圖中英文字較準，但很耗額度（免費額度每天約只夠 3–4 張）。
  ※ 以上模型的中文字都偏弱。需要中文字時，先生無字底圖，再用程式或設計軟體加字。

費用：
  免費方案每天 10,000 Neurons（UTC 0 點重置，台灣早上 8 點），用完 API 直接回錯誤，不會扣款。
  另有每日張數上限（CF_IMAGE_DAILY_LIMIT），超過就不送出請求。
  指定 seed 時啟用快取：參數完全相同就回傳舊檔，不重複消耗額度。
  同一時間只跑一個生圖請求，確保每日上限不會被並發呼叫繞過。

環境變數：
  CF_ACCOUNT_ID         必填，Cloudflare Account ID
  CF_API_TOKEN          必填，Workers AI API Token
  CF_IMAGE_OUTPUT_DIR   選填，存檔資料夾，預設 ~/Pictures/ai_images
  CF_IMAGE_DAILY_LIMIT  選填，每日最多生成張數，預設 50
  CF_IMAGE_TIMEOUT      選填，單次請求逾時秒數，預設 300
"""

import asyncio
import base64
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from PIL import Image


def log(msg: str) -> None:
    print(f"[cf-image] {msg}", file=sys.stderr, flush=True)


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
    """先讀行程環境變數；讀不到時（Windows 上 app 常沿用舊環境）改讀使用者環境變數的登錄檔。
    每次呼叫都重讀，換 Token 不必重開 app。"""
    value = os.environ.get(name, "").strip()
    if value or sys.platform != "win32":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ""


OUTPUT_DIR = Path(
    os.environ.get("CF_IMAGE_OUTPUT_DIR", "").strip() or Path.home() / "Pictures" / "ai_images"
).expanduser()
DAILY_LIMIT = _env_int("CF_IMAGE_DAILY_LIMIT", 50)
TIMEOUT = _env_int("CF_IMAGE_TIMEOUT", 300)
RUN_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/"

USAGE_FILE = OUTPUT_DIR / "usage.json"
CACHE_FILE = OUTPUT_DIR / "cache.json"
MAX_N = 4
REF_MAX_SIDE = 511  # klein 規定參考圖必須小於 512x512
SIZE_RE = re.compile(r"^(\d{3,4})\s*[*xX×]\s*(\d{3,4})$")

# size: (最小邊, 最大邊)；None 表示不能指定尺寸
MODELS = {
    "klein": {"id": "@cf/black-forest-labs/flux-2-klein-4b", "multipart": True,
              "size": (256, 1920), "seed": True, "max_refs": 4},
    "fast": {"id": "@cf/black-forest-labs/flux-1-schnell", "multipart": False,
             "size": None, "seed": False, "max_refs": 0},
    "text": {"id": "@cf/leonardo/lucid-origin", "multipart": False,
             "size": (256, 2500), "seed": True, "max_refs": 0},
}
ModelChoice = Literal["klein", "fast", "text"]

if not _get_secret("CF_ACCOUNT_ID") or not _get_secret("CF_API_TOKEN"):
    log("警告：未設定 CF_ACCOUNT_ID 或 CF_API_TOKEN，所有工具呼叫都會回傳錯誤。")

mcp = FastMCP("Cloudflare-Image")
lock = asyncio.Lock()

# 常見錯誤的白話說明（比對錯誤碼或訊息關鍵字）
ERROR_HINTS = {
    "4006": "今天的免費額度（10,000 Neurons）用完了，台灣時間早上 8 點重置。",
    "neurons": "今天的免費額度（10,000 Neurons）用完了，台灣時間早上 8 點重置。",
    "10000": "Token 無效或權限不足，請確認 CF_API_TOKEN 並重開 Claude app。",
    "Authentication": "Token 無效或權限不足，請確認 CF_API_TOKEN 並重開 Claude app。",
    "3030": "prompt 被判定為不適當內容，請調整描述。",
}


# ---------- 用量與快取（JSON 檔） ----------

def _load_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log(f"讀取 {path.name} 失敗，視為空白：{e}")
        return default


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _today() -> str:
    return dt.date.today().isoformat()


def _used_today() -> int:
    return int(_load_json(USAGE_FILE, {}).get(_today(), 0))


def _add_usage(count: int) -> int:
    usage = _load_json(USAGE_FILE, {})
    today = _today()
    usage[today] = int(usage.get(today, 0)) + count
    recent = sorted(usage)[-31:]  # 只保留最近 31 天
    _save_json(USAGE_FILE, {k: usage[k] for k in recent})
    return usage[today]


# ---------- 參數處理 ----------

def _parse_size(size: str, limits: Optional[tuple[int, int]]) -> tuple[Optional[tuple[int, int]], Optional[str]]:
    """回傳 ((寬, 高) 或 None 表示用模型預設, 錯誤訊息)。寬高會向下取到 16 的倍數。"""
    size = (size or "").strip()
    if not size:
        return None, None
    if limits is None:
        return None, "這個模型不能指定尺寸，請把 size 留空或改用 klein。"
    m = SIZE_RE.match(size)
    if not m:
        return None, f"size 格式錯誤：{size!r}，要像 1024x768 或 1024*1024。"
    lo, hi = limits
    w, h = int(m[1]) // 16 * 16, int(m[2]) // 16 * 16
    if not (lo <= w <= hi and lo <= h <= hi):
        return None, f"寬高都要介於 {lo} 與 {hi} 之間。"
    return (w, h), None


def _load_reference(ref: str) -> tuple[Optional[bytes], Optional[str]]:
    """讀取本機參考圖，縮到小於 512x512 並轉成 PNG bytes。回傳 (bytes, 錯誤訊息)。"""
    path = Path((ref or "").strip()).expanduser()
    if not path.is_file():
        return None, f"找不到參考圖：{ref}（只支援本機檔案路徑）"
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            img.thumbnail((REF_MAX_SIDE, REF_MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
    except OSError as e:
        return None, f"無法讀取參考圖 {ref}：{e}"


def _error_text(errors: list, fallback: str) -> str:
    parts = [f"{e.get('code')}: {e.get('message')}" for e in errors if isinstance(e, dict)]
    text = "；".join(parts) or fallback
    hint = next((h for key, h in ERROR_HINTS.items() if key.lower() in text.lower()), "")
    return text + (f"\n提示：{hint}" if hint else "")


def _image_suffix(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


# ---------- API 呼叫 ----------

async def _run_model(client: httpx.AsyncClient, creds: tuple[str, str], spec: dict,
                     fields: dict, refs: list[bytes]) -> bytes:
    account_id, api_token = creds
    url = RUN_URL.format(account_id=account_id) + spec["id"]
    headers = {"Authorization": f"Bearer {api_token}"}
    if spec["multipart"]:
        # 全部欄位都走 files，httpx 才會送 multipart（只有 data 時會變成 urlencoded）
        files = {k: (None, str(v)) for k, v in fields.items()}
        for i, data in enumerate(refs):
            files[f"input_image_{i}"] = (f"ref{i}.png", data, "image/png")
        resp = await client.post(url, headers=headers, files=files)
    else:
        resp = await client.post(url, headers=headers, json=fields)

    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code != 200 or not body.get("success", False):
        raise RuntimeError(_error_text(body.get("errors") or [], f"HTTP {resp.status_code}: {resp.text[:300]}"))

    b64 = (body.get("result") or {}).get("image")
    if not b64:
        raise RuntimeError("API 沒有回傳圖片。")
    return base64.b64decode(b64)


# ---------- MCP 工具 ----------

@mcp.tool()
async def generate_image(
    prompt: str,
    reference_images: Optional[list[str]] = None,
    model: ModelChoice = "klein",
    size: str = "",
    n: int = 1,
    seed: Optional[int] = None,
) -> str:
    """【Cloudflare 生圖／改圖】用 Workers AI 生成圖片，存到本機並回傳檔案路徑。免費額度內不收費。

    prompt: 圖片描述，用英文效果最好。模型中文字都偏弱：需要中文字時請生無字底圖，之後再加字。
    reference_images: 0–4 張本機參考圖路徑（只有 klein 支援），會自動縮到 512 以下。
                      prompt 可用 image 0、image 1 指代，例如 "keep image 0, change background to night"。
    model: klein（預設，快、省、可改圖）| fast（最省，但尺寸固定、無 seed）|
           text（英文字較準，但很耗額度，每天約 3–4 張）。
    size: 例如 1024x768、1024x1024、768x1024；留空用模型預設。klein 範圍 256–1920，text 範圍 256–2500。
          尺寸越大越耗額度，草稿建議 1024 以內。
    n: 張數 1–4，逐張生成；有指定 seed 時第 i 張用 seed+i。
    seed: 指定後結果可重現，且參數完全相同時直接回傳快取、不重複消耗額度（fast 不支援）。
    回傳第一行為狀態，例如：[OK] model=klein 張數=1 今日已用 3/50；
    之後每行一個本機圖片路徑，可直接用 Read 看圖審核。狀態有 OK / CACHED / PARTIAL / ERROR。
    """
    creds = (_get_secret("CF_ACCOUNT_ID"), _get_secret("CF_API_TOKEN"))
    if not all(creds):
        return "[ERROR] 未設定 CF_ACCOUNT_ID 或 CF_API_TOKEN 使用者環境變數。"
    if not prompt or not prompt.strip():
        return "[ERROR] prompt 不可為空。"
    if model not in MODELS:
        return f"[ERROR] model 只能是 {tuple(MODELS)}。"
    spec = MODELS[model]
    if not isinstance(n, int) or not 1 <= n <= MAX_N:
        return f"[ERROR] n 必須是 1–{MAX_N} 的整數。"
    if seed is not None:
        if not spec["seed"]:
            return "[ERROR] fast 模型不支援 seed，請拿掉 seed 或改用 klein。"
        if not 0 <= seed <= 2147483647 - MAX_N:
            return "[ERROR] seed 必須介於 0 與 2147483643 之間。"

    wh, err = _parse_size(size, spec["size"])
    if err:
        return f"[ERROR] {err}"

    ref_paths = [r for r in (reference_images or []) if r and r.strip()]
    if len(ref_paths) > spec["max_refs"]:
        if spec["max_refs"] == 0:
            return f"[ERROR] {model} 模型不支援參考圖，改圖請用 klein。"
        return f"[ERROR] 參考圖最多 {spec['max_refs']} 張，收到 {len(ref_paths)} 張。"
    refs: list[bytes] = []
    for ref in ref_paths:
        data, err = _load_reference(ref)
        if err:
            return f"[ERROR] {err}"
        refs.append(data)

    base_fields: dict = {"prompt": prompt.strip()}
    if wh:
        base_fields["width"], base_fields["height"] = wh

    async with lock:
        cache_key = None
        if seed is not None:
            digest = hashlib.sha256()
            digest.update(json.dumps([spec["id"], base_fields, seed, n], ensure_ascii=False).encode("utf-8"))
            for data in refs:
                digest.update(hashlib.sha256(data).digest())
            cache_key = digest.hexdigest()
            cached = _load_json(CACHE_FILE, {}).get(cache_key)
            if cached and all(Path(p).is_file() for p in cached):
                return f"[CACHED] model={model} 參數相同，未消耗額度\n" + "\n".join(cached)

        used = _used_today()
        if used + n > DAILY_LIMIT:
            return (
                f"[ERROR] 今日已生成 {used} 張，再生 {n} 張會超過每日上限 {DAILY_LIMIT}。"
                "明天再試，或調高環境變數 CF_IMAGE_DAILY_LIMIT。"
            )

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: list[str] = []
        error = ""
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for i in range(n):
                fields = dict(base_fields)
                if seed is not None:
                    fields["seed"] = seed + i
                try:
                    data = await _run_model(client, creds, spec, fields, refs)
                except Exception as e:  # noqa: BLE001 — 任何失敗都要回報給呼叫端
                    log(f"第 {i + 1} 張生成失敗：{type(e).__name__}: {e}")
                    error = str(e)
                    break
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                path = OUTPUT_DIR / f"{stamp}_{model}_{i + 1}{_image_suffix(data)}"
                path.write_bytes(data)
                paths.append(str(path))

        used_now = _add_usage(len(paths)) if paths else used
        if cache_key and len(paths) == n:
            cache = _load_json(CACHE_FILE, {})
            cache[cache_key] = paths
            _save_json(CACHE_FILE, cache)

    if not paths:
        return f"[ERROR] model={model}\n{error}"
    status = "OK" if len(paths) == n else "PARTIAL"
    lines = [f"[{status}] model={model} 張數={len(paths)}/{n} 今日已用 {used_now}/{DAILY_LIMIT}"]
    lines += paths
    if error:
        lines.append(f"其餘失敗原因：{error}")
    return "\n".join(lines)


@mcp.tool()
async def image_usage() -> str:
    """查詢今天已生成幾張圖、每日上限、可用模型與存檔資料夾。不會消耗額度。"""
    models = "、".join(f"{k}={v['id']}" for k, v in MODELS.items())
    return (
        f"今日已用 {_used_today()}/{DAILY_LIMIT} 張（Cloudflare 免費額度另計，台灣早上 8 點重置）\n"
        f"模型：{models}\n"
        f"存檔資料夾：{OUTPUT_DIR}"
    )


if __name__ == "__main__":
    log(f"啟動：每日上限={DAILY_LIMIT} 存檔={OUTPUT_DIR} 模型={', '.join(MODELS)}")
    mcp.run()
