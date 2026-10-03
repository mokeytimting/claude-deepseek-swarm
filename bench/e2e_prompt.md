[BENCH-E2E] 請用 deepseek-orchestrator skill 在目前資料夾完成下列 3 個檔案，做完要自己驗證能執行。規格已完整，不要問我問題，直接做到完成。

## 共通規範
這是一組獨立的小型程式任務。
- Python 任務：Python 3.11+，只用標準庫；整個檔案放在一個 ```python 程式碼區塊。
- JavaScript 任務：Node.js 20+ 的 ES module，只用內建功能；整個檔案放在一個 ```javascript 程式碼區塊。
- 函式名稱、參數、例外類別必須完全照規格，不可更名。
- 不要附測試程式、不要附使用範例在程式碼區塊內。

## 檔案：L1_duration.py
【目的】寫一個時間長度解析函式。
【要求】檔案內定義 `parse_duration(s: str) -> int`，回傳總秒數。
- 格式：由 d、h、m、s 四種單位組成，每個單位前面是非負整數（可有前導零），例如 "1h30m"、"45s"、"2d3h"、"1h2m3s"、"0s"。
- 單位必須依 d → h → m → s 的順序出現，每種最多一次；可省略任何單位，但至少要有一個。
- 不允許空白、小數、負號、大寫單位或其他字元。
- 1d = 86400 秒，1h = 3600，1m = 60。
- 任何不合法輸入（含空字串、順序錯、重複單位、只有單位沒有數字、只有數字沒有單位）一律 raise ValueError。
【輸出】單一 python 程式碼區塊。

## 檔案：inventory.py
【目的】實作一個庫存模組 inventory。
【要求】
- 例外：`class UnknownSKU(KeyError)`、`class InsufficientStock(ValueError)`。
- `class Inventory`，金額一律用整數「分」(cents)：
  - `add_item(sku: str, name: str, qty: int, price_cents: int) -> None`
    sku 為空字串、qty < 0 或 price_cents < 0 → ValueError。
    sku 已存在時：數量累加，name 與 price_cents 更新為新值。
  - `remove(sku: str, qty: int) -> int`：扣庫存並回傳剩餘數量。
    未知 sku → UnknownSKU；qty <= 0 → ValueError；庫存不足 → InsufficientStock 且庫存不變。剩 0 時品項仍保留。
  - `quantity(sku: str) -> int`：未知 sku → UnknownSKU。
  - `total_value() -> int`：所有品項 數量×單價 的總和。
  - `low_stock(threshold: int) -> list[str]`：數量 < threshold 的 sku，依字母遞增排序。
  - `apply_order(lines: list[tuple[str, int]]) -> None`：一次扣多筆，同一 sku 可出現多次（累計扣）。
    全有或全無：任何一筆會失敗（未知 sku、qty <= 0、累計後不足）就拋出對應例外，且庫存完全不變。
  - `to_json() -> str` 與 `@classmethod from_json(cls, s: str) -> "Inventory"`：可完整往返（sku、name、qty、price_cents）。
【輸出】單一 python 程式碼區塊。

## 檔案：bytes.mjs
【目的】寫一個位元組大小格式化 ES module（檔名 bytes.mjs）。
【要求】export 兩個具名函式：
1. `formatBytes(n, decimals = 1)`
   - n 必須是 >= 0 的有限整數，否則 throw RangeError。
   - 單位 B、KB、MB、GB、TB，進位為 1024。選能讓數值 < 1024 的最大單位；超過 TB 時仍用 TB。
   - B 單位不顯示小數：formatBytes(1023) === "1023 B"、formatBytes(0) === "0 B"。
   - 其他單位用 toFixed(decimals)：formatBytes(1536) === "1.5 KB"、formatBytes(1048576, 2) === "1.00 MB"。
   - 數字與單位之間一個空白。
2. `parseBytes(str)`
   - 格式：數字（可有小數）+ 可選空白 + 單位（B/KB/MB/GB/TB，不分大小寫），前後空白忽略。
   - 回傳 Math.round 後的位元組數：parseBytes("1.5 KB") === 1536、parseBytes("2mb") === 2097152、parseBytes(" 10 B ") === 10。
   - 不合法（無單位、未知單位、負數、空字串、非字串）一律 throw Error（可為其子類別）。
【輸出】單一 javascript 程式碼區塊。
