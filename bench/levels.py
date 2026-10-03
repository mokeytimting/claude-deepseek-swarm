"""測試關卡定義。

每一關 = 給工蜂的題目 + 工蜂看不到的評分程式。
題目固定不變，才能比較不同版本的伺服器 / skill。
要新增關卡：在 LEVELS 加一筆；改了既有關卡的題目或評分，請把 SUITE_VERSION 加 1（舊紀錄不再和新紀錄比）。
"""
from __future__ import annotations

SUITE_VERSION = 2  # v2：加入困難關卡 H1–H3

SHARED_CONTEXT = """這是一組獨立的小型程式任務。
- Python 任務：Python 3.11+，只用標準庫；整個檔案放在一個 ```python 程式碼區塊。
- JavaScript 任務：Node.js 20+ 的 ES module，只用內建功能；整個檔案放在一個 ```javascript 程式碼區塊。
- 函式名稱、參數、例外類別必須完全照規格，不可更名。
- 不要附測試程式、不要附使用範例在程式碼區塊內。"""

# ---------------------------------------------------------------- L1
L1_TASK = """【目的】寫一個時間長度解析函式。
【要求】檔案內定義 `parse_duration(s: str) -> int`，回傳總秒數。
- 格式：由 d、h、m、s 四種單位組成，每個單位前面是非負整數（可有前導零），例如 "1h30m"、"45s"、"2d3h"、"1h2m3s"、"0s"。
- 單位必須依 d → h → m → s 的順序出現，每種最多一次；可省略任何單位，但至少要有一個。
- 不允許空白、小數、負號、大寫單位或其他字元。
- 1d = 86400 秒，1h = 3600，1m = 60。
- 任何不合法輸入（含空字串、順序錯、重複單位、只有單位沒有數字、只有數字沒有單位）一律 raise ValueError。
【輸出】單一 python 程式碼區塊。"""

L1_TEST = r'''
import pytest_like as t
from L1_duration import parse_duration as p
t.eq(p("1h30m"), 5400); t.eq(p("45s"), 45); t.eq(p("2h"), 7200)
t.eq(p("1h2m3s"), 3723); t.eq(p("2d3h"), 183600); t.eq(p("0s"), 0)
t.eq(p("007m"), 420); t.eq(p("1d1s"), 86401)
for bad in ["", "1m1h", "1h1h", "h", "10", "1.5h", "-1s", "1H", "1h 30m", " 1h", "1x", "1hm"]:
    t.raises(ValueError, p, bad)
'''

# ---------------------------------------------------------------- L2
L2_TASK = """【目的】實作兩個常用工具。
【要求】
1. `merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]`
   - 合併重疊或相接的區間（(1,2) 與 (2,5) 視為相接，合併為 (1,5)）。
   - 輸入可能未排序；輸出依起點遞增排序，元素為 tuple。
   - 任一區間 start > end 時 raise ValueError。空清單回傳空清單。不可修改輸入。
2. `class LRUCache`
   - `__init__(self, capacity: int)`：capacity <= 0 時 raise ValueError。
   - `get(self, key, default=None)`：找不到回傳 default；找到時該 key 成為最近使用。
   - `put(self, key, value)`：新增或更新（更新也算最近使用）；超過容量時淘汰最久未使用者。
   - `__len__(self)`：目前項目數。
【輸出】單一 python 程式碼區塊。"""

L2_TEST = r'''
import pytest_like as t
from L2_tools import merge_intervals as m, LRUCache
t.eq(m([]), [])
t.eq(m([(1, 3), (2, 6), (8, 10), (15, 18)]), [(1, 6), (8, 10), (15, 18)])
t.eq(m([(5, 7), (1, 2), (2, 4)]), [(1, 4), (5, 7)])
t.eq(m([(1, 10), (2, 3), (4, 5)]), [(1, 10)])
t.eq(m([(3, 3)]), [(3, 3)])
src = [(4, 5), (1, 2)]; m(src); t.eq(src, [(4, 5), (1, 2)])
t.raises(ValueError, m, [(1, 2), (5, 4)])
t.raises(ValueError, LRUCache, 0)
c = LRUCache(2); c.put("a", 1); c.put("b", 2); t.eq(c.get("a"), 1)
c.put("c", 3); t.eq(c.get("b"), None); t.eq(c.get("b", -1), -1); t.eq(c.get("a"), 1); t.eq(c.get("c"), 3)
c.put("a", 10); c.put("d", 4); t.eq(c.get("c"), None); t.eq(c.get("a"), 10); t.eq(len(c), 2)
'''

# ---------------------------------------------------------------- L3（修改既有檔案）
L3_SEED = '''def mean(xs):
    return sum(xs) / len(xs)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2]


def mode(xs):
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    return max(counts, key=counts.get)


def percentile(xs, p):
    s = sorted(xs)
    k = len(s) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)
'''

L3_TASK = """【目的】修正附檔 stats.py 裡的錯誤，讓它符合下列規格。
【要求】
- 四個函式 mean、median、mode、percentile 的名稱與參數不變。
- 所有函式遇到空序列都 raise ValueError。
- median：偶數個元素時回傳中間兩數的平均。
- mode：回傳出現次數最多的值；平手時回傳其中最小的值。
- percentile(xs, p)：p 必須在 0～100（含），否則 raise ValueError；
  採線性內插：先排序 s，位置 k = (len(s) - 1) * p / 100，取 s[floor(k)] 與 s[ceil(k)] 依小數部分內插（等同 numpy 預設）。
- 不可修改傳入的序列。
【輸出】修正後完整的 stats.py，單一 python 程式碼區塊。"""

L3_TEST = r'''
import pytest_like as t
from stats import mean, median, mode, percentile
t.close(mean([1, 2, 3]), 2); t.close(mean([1, 2]), 1.5)
t.close(median([3, 1, 2]), 2); t.close(median([4, 1, 3, 2]), 2.5); t.close(median([7]), 7)
t.eq(mode([1, 2, 2, 3, 3]), 2); t.eq(mode([5]), 5); t.eq(mode([9, 9, 1]), 9)
t.close(percentile([1, 2, 3, 4], 0), 1); t.close(percentile([1, 2, 3, 4], 100), 4)
t.close(percentile([1, 2, 3, 4], 50), 2.5); t.close(percentile([10, 20, 30, 40, 50], 25), 20)
t.close(percentile([4, 1, 3, 2], 75), 3.25); t.close(percentile([5], 30), 5)
for f in (mean, median, mode):
    t.raises(ValueError, f, [])
t.raises(ValueError, percentile, [], 50)
t.raises(ValueError, percentile, [1, 2], -1)
t.raises(ValueError, percentile, [1, 2], 100.5)
xs = [3, 1, 2]; median(xs); percentile(xs, 50); t.eq(xs, [3, 1, 2])
'''

# ---------------------------------------------------------------- L4（較大、有交易語意）
L4_TASK = """【目的】實作一個庫存模組 inventory。
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
【輸出】單一 python 程式碼區塊。"""

L4_TEST = r'''
import pytest_like as t
from inventory import Inventory, UnknownSKU, InsufficientStock
t.ok(issubclass(UnknownSKU, KeyError)); t.ok(issubclass(InsufficientStock, ValueError))
inv = Inventory()
inv.add_item("B", "bolt", 10, 25); inv.add_item("A", "anchor", 3, 1000); inv.add_item("B", "bolt2", 5, 30)
t.eq(inv.quantity("B"), 15); t.eq(inv.total_value(), 15 * 30 + 3 * 1000)
t.raises(ValueError, inv.add_item, "", "x", 1, 1); t.raises(ValueError, inv.add_item, "C", "x", -1, 1)
t.raises(ValueError, inv.add_item, "C", "x", 1, -1)
t.eq(inv.remove("A", 3), 0); t.eq(inv.quantity("A"), 0)
t.raises(UnknownSKU, inv.remove, "Z", 1); t.raises(ValueError, inv.remove, "B", 0)
t.raises(InsufficientStock, inv.remove, "B", 16); t.eq(inv.quantity("B"), 15)
t.raises(UnknownSKU, inv.quantity, "Z")
t.eq(inv.low_stock(5), ["A"]); t.eq(inv.low_stock(100), ["A", "B"])
inv.add_item("C", "cap", 4, 5)
t.raises(InsufficientStock, inv.apply_order, [("B", 10), ("C", 1), ("B", 6)])
t.eq(inv.quantity("B"), 15); t.eq(inv.quantity("C"), 4)
t.raises(UnknownSKU, inv.apply_order, [("C", 1), ("Q", 1)]); t.eq(inv.quantity("C"), 4)
t.raises(ValueError, inv.apply_order, [("C", 1), ("B", 0)]); t.eq(inv.quantity("C"), 4)
inv.apply_order([("B", 10), ("C", 1), ("B", 5)]); t.eq(inv.quantity("B"), 0); t.eq(inv.quantity("C"), 3)
inv2 = Inventory.from_json(inv.to_json())
t.eq(inv2.quantity("C"), 3); t.eq(inv2.total_value(), inv.total_value()); t.eq(inv2.low_stock(1), ["A", "B"])
'''

# ---------------------------------------------------------------- L5（JavaScript）
L5_TASK = """【目的】寫一個位元組大小格式化 ES module（檔名 bytes.mjs）。
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
【輸出】單一 javascript 程式碼區塊。"""

L5_TEST = r'''
import assert from "node:assert/strict";
import { formatBytes as f, parseBytes as p } from "./bytes.mjs";
assert.equal(f(0), "0 B"); assert.equal(f(1023), "1023 B"); assert.equal(f(1024), "1.0 KB");
assert.equal(f(1536), "1.5 KB"); assert.equal(f(1048576, 2), "1.00 MB"); assert.equal(f(5 * 1024 ** 3), "5.0 GB");
assert.equal(f(1024 ** 5), "1024.0 TB"); assert.equal(f(1536, 0), "2 KB");
for (const bad of [-1, 1.5, NaN, Infinity]) assert.throws(() => f(bad), RangeError);
assert.equal(p("1.5 KB"), 1536); assert.equal(p("2mb"), 2097152); assert.equal(p(" 10 B "), 10);
assert.equal(p("1TB"), 1024 ** 4); assert.equal(p("0.5 kb"), 512);
for (const bad of ["", "10", "5 XB", "-1 KB", "KB", null, 42]) assert.throws(() => p(bad), Error);
console.log("ALL_OK");
'''

# ---------------------------------------------------------------- H1–H3（困難：細節多、模型常錯，逐條計分以拉開差距）
H1_TASK = """【目的】寫一個有理數算式求值器（檔名 expr_eval.py）。
【要求】檔案內定義 `evaluate(expr: str) -> Fraction`（fractions.Fraction），精確計算，不可使用 eval／exec。
- 語法：非負整數字面值（十進位數字，沒有小數點）、二元運算 + - * / ^、一元負號 -、小括號。空白可出現在任何記號之間，一律忽略。
- 優先順序（高到低）：^ ＞ 一元負號 ＞ * / ＞ + -。
- ^ 為右結合（2^3^2 = 2^9 = 512）；其餘二元運算左結合（8/4/2 = 1）。
- 一元負號可連用（--3 = 3），可出現在算式開頭、左括號之後、任何二元運算子之後，包括 ^ 的右邊（2^-1 = 1/2）。
  因為 ^ 高於一元負號：-2^2 = -4、2*-3^2 = -18；(-2)^2 = 4。
- 沒有一元正號（"+3" 不合法）。
- ^ 的指數必須是整數值（例如 4^(2/2) 合法），且絕對值 <= 1000；否則 raise ValueError。
- 除以零、0 的負整數次方 → raise ZeroDivisionError。
- 其他任何不合法輸入（空字串、括號不配對、空括號、缺運算元、多餘記號、非法字元、小數、兩個數字之間只有空白）→ raise ValueError。
- 回傳值一律是 Fraction（整數結果也是 Fraction）。
【輸出】單一 python 程式碼區塊。"""

H1_TEST = r'''
import pytest_like as t
from fractions import Fraction as F
from expr_eval import evaluate as e
t.eq(e("1+2*3"), 7)
t.eq(e("(1+2)*3"), 9)
t.eq(e("2^3^2"), 512)
t.eq(e("-2^2"), -4)
t.eq(e("(-2)^2"), 4)
t.eq(e("2^-2"), F(1, 4))
t.eq(e("7/2"), F(7, 2))
t.eq(e("1-2-3"), -4)
t.eq(e("8/4/2"), 1)
t.eq(e("2--3"), 5)
t.eq(e("--3"), 3)
t.eq(e(" 2 * ( 3 + 4 ) "), 14)
t.eq(e("4^(2/2)"), 4)
t.eq(e("-3*-2"), 6)
t.eq(e("2*-3^2"), -18)
t.eq(e("(1/3)*3"), 1)
t.ok(isinstance(e("1+1"), F))
t.raises(ValueError, e, "")
t.raises(ValueError, e, "1+")
t.raises(ValueError, e, "(1+2")
t.raises(ValueError, e, "1+2)")
t.raises(ValueError, e, "1 2")
t.raises(ValueError, e, "2^(1/2)")
t.raises(ValueError, e, "+3")
t.raises(ValueError, e, "1.5")
t.raises(ValueError, e, "2^1001")
t.raises(ValueError, e, "a")
t.raises(ValueError, e, "()")
t.raises(ZeroDivisionError, e, "1/0")
t.raises(ZeroDivisionError, e, "0^-1")
t.raises(ZeroDivisionError, e, "1/(2-2)")
'''

H2_TASK = """【目的】實作 SemVer 2.0.0 版本工具（檔名 semver_tools.py）。
【要求】
- `is_valid(s: str) -> bool`：完全符合 SemVer 2.0.0 語法（MAJOR.MINOR.PATCH，可選 -prerelease 與 +build）。
  MAJOR、MINOR、PATCH 與純數字的 prerelease 識別碼不可有前導零；識別碼只含 [0-9A-Za-z-] 且不可為空；
  不接受前綴 v、前後空白或結尾換行。
- `compare(a: str, b: str) -> int`：依 SemVer 2.0.0 第 11 節的優先順序回傳 -1、0、1；build metadata 不影響比較。
  任一參數不合法 → raise ValueError。
  （有 prerelease 的版本小於同核心的正式版；prerelease 逐個識別碼比較：純數字識別碼以數值比較、其餘以 ASCII 字典序、
  純數字 < 非純數字；前面都相同時識別碼較多者較大。）
- `max_satisfying(versions: list[str], rng: str) -> str | None`：rng 為插入號範圍 "^X.Y.Z"
  （X.Y.Z 必須是合法、且不含 prerelease 與 build 的版本，否則 raise ValueError）。
  範圍：X>0 時 >=X.Y.Z 且 <(X+1).0.0；X=0 且 Y>0 時 >=0.Y.Z 且 <0.(Y+1).0；X=0 且 Y=0 時 >=0.0.Z 且 <0.0.(Z+1)。
  versions 中不合法的字串略過；含 prerelease 的版本一律不符合。回傳符合者中優先順序最高的那個原字串，沒有則回傳 None。
【輸出】單一 python 程式碼區塊。"""

H2_TEST = r'''
import pytest_like as t
from semver_tools import is_valid as v, compare as c, max_satisfying as ms
t.ok(v("1.0.0"))
t.ok(v("1.0.0-alpha.1+build.5"))
t.ok(v("1.0.0-0a"))
t.ok(not v("1.0"))
t.ok(not v("01.0.0"))
t.ok(not v("1.0.0-01"))
t.ok(not v("1.0.0-"))
t.ok(not v("1.0.0+"))
t.ok(not v("v1.0.0"))
t.ok(not v("1.0.0-a..b"))
t.ok(not v("1.0.0\n"))
t.eq(c("1.0.0-alpha", "1.0.0-alpha.1"), -1)
t.eq(c("1.0.0-alpha.1", "1.0.0-alpha.beta"), -1)
t.eq(c("1.0.0-alpha.beta", "1.0.0-beta"), -1)
t.eq(c("1.0.0-beta", "1.0.0-beta.2"), -1)
t.eq(c("1.0.0-beta.2", "1.0.0-beta.11"), -1)
t.eq(c("1.0.0-beta.11", "1.0.0-rc.1"), -1)
t.eq(c("1.0.0-rc.1", "1.0.0"), -1)
t.eq(c("1.0.0", "1.0.0-rc.1"), 1)
t.eq(c("1.0.0+a", "1.0.0+b"), 0)
t.eq(c("2.0.0", "10.0.0"), -1)
t.eq(c("1.10.0", "1.9.0"), 1)
t.eq(c("1.0.0-2", "1.0.0-10"), -1)
t.eq(c("1.0.0-a", "1.0.0-1"), 1)
t.eq(c("1.0.0-Z", "1.0.0-a"), -1)
t.raises(ValueError, c, "1.0", "1.0.0")
VS = ["1.2.3", "1.2.10", "1.3.0-beta", "1.9.9", "2.0.0", "0.2.5", "0.2.9", "0.3.0", "0.0.3", "0.0.4", "bad", "1.10.0"]
t.eq(ms(VS, "^1.2.3"), "1.10.0")
t.eq(ms(VS, "^0.2.3"), "0.2.9")
t.eq(ms(VS, "^0.0.3"), "0.0.3")
t.eq(ms(VS, "^3.0.0"), None)
t.eq(ms(VS, "^1.9.10"), "1.10.0")
t.eq(ms([], "^1.0.0"), None)
t.eq(ms(["1.5.0-rc.1"], "^1.0.0"), None)
t.raises(ValueError, ms, VS, "1.2.3")
t.raises(ValueError, ms, VS, "^1.2")
t.raises(ValueError, ms, VS, "^1.2.3-beta")
'''

H3_TASK = """【目的】寫一個 CSV 解析與輸出 ES module（檔名 csv.mjs）。
【要求】export 兩個具名函式：
1. `parseCSV(text)` → 字串陣列的陣列（每筆紀錄一個陣列）
   - text 不是字串 → throw TypeError。空字串 → 回傳 []。
   - 欄位以逗號分隔；紀錄以 "\\n" 或 "\\r\\n" 分隔；最後一筆紀錄後面的換行可有可無（不產生額外紀錄）。
   - 中間的空行是一筆只有一個空字串欄位的紀錄："a\\n\\nb" → [["a"], [""], ["b"]]；",," → [["", "", ""]]。
   - 欄位第一個字元是雙引號時為「引號欄位」：內容可包含逗號、\\r、\\n，兩個連續雙引號代表一個雙引號；
     結束引號之後只能緊接逗號、換行（\\n 或 \\r\\n）或文字結尾，否則 throw Error；引號沒有結束 → throw Error。
   - 非引號欄位中出現雙引號、或出現後面不是 \\n 的 \\r → throw Error。
   - 空白是內容的一部分，不修剪：" a ,b" → [[" a ", "b"]]（因此 ' "a"' 的引號不在欄位開頭，屬於非引號欄位中的雙引號 → throw Error）。
2. `toCSV(rows)` → 字串
   - rows 必須是陣列、每筆紀錄是至少含一個欄位的陣列，否則 throw Error（可為其子類別）；欄位不是字串 → throw TypeError。
   - 欄位含逗號、雙引號、\\r 或 \\n 時用雙引號包起來，內部雙引號寫成兩個；其他欄位原樣輸出。
   - 只含一個空字串欄位的紀錄輸出為 '""'（讓它能被解析回 [""]）。
   - 紀錄之間用 "\\n" 連接，結尾不加換行；rows 為 [] 時回傳 ""。
   - 對任何合法 rows：parseCSV(toCSV(rows)) 必須與 rows 完全相同。
【輸出】單一 javascript 程式碼區塊。"""

H3_TEST = r'''
import { parseCSV as p, toCSV as t } from "./csv.mjs";
let ok = 0, n = 0; const fails = [];
function check(name, fn) { n++; try { fn(); ok++; } catch (e) { fails.push(name + ": " + String(e && e.message).slice(0, 100)); } }
const deq = (a, b) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`預期 ${JSON.stringify(b)} 得到 ${JSON.stringify(a)}`); };
const thr = (fn, T = Error) => { try { fn(); } catch (e) { if (!(e instanceof T)) throw new Error("例外類別不對：" + (e && e.name)); return; } throw new Error("沒有丟出例外"); };
check("empty", () => deq(p(""), []));
check("simple", () => deq(p("a,b,c"), [["a", "b", "c"]]));
check("trailing LF", () => deq(p("a,b\n1,2\n"), [["a", "b"], ["1", "2"]]));
check("CRLF", () => deq(p("a\r\nb\r\n"), [["a"], ["b"]]));
check("quoted comma", () => deq(p('"x,y",z'), [["x,y", "z"]]));
check("escaped quote", () => deq(p('"he said ""hi"""'), [['he said "hi"']]));
check("quoted LF", () => deq(p('"line1\nline2",b'), [["line1\nline2", "b"]]));
check("quoted CRLF", () => deq(p('"a\r\nb"'), [["a\r\nb"]]));
check("blank line", () => deq(p("a\n\nb"), [["a"], [""], ["b"]]));
check("empty fields", () => deq(p(",,"), [["", "", ""]]));
check("spaces kept", () => deq(p(" a ,b"), [[" a ", "b"]]));
check("empty quoted", () => deq(p('""'), [[""]]));
check("quote in field", () => thr(() => p('a"b')));
check("unterminated", () => thr(() => p('"abc')));
check("text after quote", () => thr(() => p('"a"b')));
check("space before quote", () => thr(() => p(' "a"')));
check("lone CR", () => thr(() => p("a\rb")));
check("non-string", () => thr(() => p(42), TypeError));
check("toCSV simple", () => deq(t([["a", "b"], ["1", "2"]]), "a,b\n1,2"));
check("toCSV quote", () => deq(t([["x,y", 'q"z']]), '"x,y","q""z"'));
check("toCSV single empty", () => deq(t([[""]]), '""'));
check("toCSV empty first", () => deq(t([["", "a"]]), ",a"));
check("toCSV none", () => deq(t([]), ""));
check("toCSV non-string", () => thr(() => t([[1]]), TypeError));
check("toCSV empty row", () => thr(() => t([[]])));
const rows = [["a", "b,c", 'd"e', "f\ng", ""], ["", ""], [" x "], ["\r\n"], [""], ["z"]];
check("round trip", () => deq(p(t(rows)), rows));
for (const f of fails.slice(0, 4)) console.log("FAIL", f);
console.log(`SCORE ${ok}/${n}`);
'''

# ---------------------------------------------------------------- L6（推理，看 FINAL）
def _digit_sum_20() -> int:
    return sum(1 for n in range(1, 10001) if sum(map(int, str(n))) == 20)


def _coin_ways() -> int:
    ways = [1] + [0] * 100
    for c in (1, 2, 5, 10):
        for v in range(c, 101):
            ways[v] += ways[v - c]
    return ways[100]


def _catalan8() -> int:
    from math import comb
    return comb(16, 8) // 9


REASONING = [
    ("L6a", "1 到 10000（含）之間，各位數字和恰為 20 的整數有幾個？", _digit_sum_20),
    ("L6b", "用 1 元、2 元、5 元、10 元硬幣（每種數量不限、不計順序）湊出剛好 100 元，共有幾種組合？", _coin_ways),
    ("L6c", "在方格上從 (0,0) 走到 (8,8)，每步只能向右 (x+1) 或向上 (y+1)，且任何時刻都必須滿足 y <= x。共有幾條路徑？", _catalan8),
]
REASONING_SUFFIX = "\n【輸出】簡短推導後，最後單獨一行寫 `FINAL: <整數>`。"

# ---------------------------------------------------------------- 彙總
# kind: py = 跑 python 評分；js = 跑 node 評分；final = 比對 FINAL 行
LEVELS = [
    {"id": "L1", "name": "時間解析（易）", "kind": "py", "task": L1_TASK, "out": "L1_duration.py", "test": L1_TEST},
    {"id": "L2", "name": "區間合併+LRU（中）", "kind": "py", "task": L2_TASK, "out": "L2_tools.py", "test": L2_TEST},
    {"id": "L3", "name": "修改既有檔案（中）", "kind": "py", "task": L3_TASK, "out": "stats.py", "test": L3_TEST,
     "seed": {"stats.py": L3_SEED}, "attach": "stats.py"},
    {"id": "L4", "name": "庫存交易模組（難）", "kind": "py", "task": L4_TASK, "out": "inventory.py", "test": L4_TEST},
    {"id": "L5", "name": "JS 位元組格式（中）", "kind": "js", "task": L5_TASK, "out": "bytes.mjs", "test": L5_TEST},
    {"id": "H1", "name": "算式求值（難）", "kind": "py", "task": H1_TASK, "out": "expr_eval.py", "test": H1_TEST},
    {"id": "H2", "name": "SemVer 工具（難）", "kind": "py", "task": H2_TASK, "out": "semver_tools.py", "test": H2_TEST},
    {"id": "H3", "name": "CSV 解析輸出 JS（難）", "kind": "jsscore", "task": H3_TASK, "out": "csv.mjs", "test": H3_TEST},
] + [
    {"id": lid, "name": f"推理 {lid[-1]}", "kind": "final", "task": q + REASONING_SUFFIX, "out": "", "answer": fn}
    for lid, q, fn in REASONING
]
