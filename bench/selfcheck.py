"""評分自我檢查：用標準答案跑一遍，確認每關評分程式本身正確。改了 levels.py 後執行 python bench/selfcheck.py"""
import sys, shutil
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels import LEVELS
from grading import grade_level

REF = {
"L1_duration.py": r'''
import re
_R = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
def parse_duration(s):
    if not isinstance(s, str) or not s: raise ValueError(s)
    m = _R.fullmatch(s)
    if not m or not any(m.groups()): raise ValueError(s)
    d, h, mi, se = (int(g) if g else 0 for g in m.groups())
    return d*86400 + h*3600 + mi*60 + se
''',
"L2_tools.py": r'''
from collections import OrderedDict
def merge_intervals(iv):
    for a, b in iv:
        if a > b: raise ValueError
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out
class LRUCache:
    def __init__(self, capacity):
        if capacity <= 0: raise ValueError
        self.c, self.d = capacity, OrderedDict()
    def get(self, k, default=None):
        if k not in self.d: return default
        self.d.move_to_end(k); return self.d[k]
    def put(self, k, v):
        self.d[k] = v; self.d.move_to_end(k)
        if len(self.d) > self.c: self.d.popitem(last=False)
    def __len__(self): return len(self.d)
''',
"stats.py": r'''
import math
from collections import Counter
def _ne(xs):
    xs = list(xs)
    if not xs: raise ValueError("empty")
    return xs
def mean(xs): xs = _ne(xs); return sum(xs)/len(xs)
def median(xs):
    s = sorted(_ne(xs)); n = len(s)
    return s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2
def mode(xs):
    c = Counter(_ne(xs)); m = max(c.values())
    return min(k for k, v in c.items() if v == m)
def percentile(xs, p):
    s = sorted(_ne(xs))
    if not 0 <= p <= 100: raise ValueError
    k = (len(s)-1)*p/100; f = math.floor(k); c = math.ceil(k)
    return s[f] + (s[c]-s[f])*(k-f)
''',
"inventory.py": r'''
import json
class UnknownSKU(KeyError): pass
class InsufficientStock(ValueError): pass
class Inventory:
    def __init__(self): self.items = {}
    def add_item(self, sku, name, qty, price_cents):
        if not sku or qty < 0 or price_cents < 0: raise ValueError
        old = self.items.get(sku, {"qty": 0})
        self.items[sku] = {"name": name, "qty": old["qty"] + qty, "price": price_cents}
    def _get(self, sku):
        if sku not in self.items: raise UnknownSKU(sku)
        return self.items[sku]
    def remove(self, sku, qty):
        it = self._get(sku)
        if qty <= 0: raise ValueError
        if qty > it["qty"]: raise InsufficientStock(sku)
        it["qty"] -= qty; return it["qty"]
    def quantity(self, sku): return self._get(sku)["qty"]
    def total_value(self): return sum(i["qty"]*i["price"] for i in self.items.values())
    def low_stock(self, t): return sorted(k for k, i in self.items.items() if i["qty"] < t)
    def apply_order(self, lines):
        need = {}
        for sku, q in lines:
            self._get(sku)
            if q <= 0: raise ValueError
            need[sku] = need.get(sku, 0) + q
        for sku, q in need.items():
            if q > self.items[sku]["qty"]: raise InsufficientStock(sku)
        for sku, q in need.items(): self.items[sku]["qty"] -= q
    def to_json(self): return json.dumps(self.items)
    @classmethod
    def from_json(cls, s):
        inv = cls(); inv.items = json.loads(s); return inv
''',
"bytes.mjs": r'''
const U = ["B","KB","MB","GB","TB"];
export function formatBytes(n, decimals = 1) {
  if (!Number.isInteger(n) || n < 0) throw new RangeError("bad");
  let i = 0, v = n;
  while (v >= 1024 && i < U.length - 1) { v /= 1024; i++; }
  return i === 0 ? `${n} B` : `${v.toFixed(decimals)} ${U[i]}`;
}
export function parseBytes(str) {
  if (typeof str !== "string") throw new Error("bad");
  const m = /^\s*(\d+(?:\.\d+)?)\s*([a-z]+)\s*$/i.exec(str);
  if (!m) throw new Error("bad");
  const i = U.indexOf(m[2].toUpperCase());
  if (i < 0) throw new Error("bad");
  return Math.round(parseFloat(m[1]) * 1024 ** i);
}
''',
"expr_eval.py": r'''
import re
from fractions import Fraction
def evaluate(expr):
    if not isinstance(expr, str): raise ValueError
    toks = []
    for m in re.finditer(r"\s+|\d+|[-+*/^()]|.", expr):
        s = m.group()
        if s.isspace(): continue
        if s.isdigit(): toks.append(("n", int(s)))
        elif s in "+-*/^()": toks.append(("o", s))
        else: raise ValueError(s)
    pos = 0
    def peek(): return toks[pos] if pos < len(toks) else (None, None)
    def take(v=None):
        nonlocal pos
        t = peek()
        if t[0] is None or (v is not None and t != ("o", v)): raise ValueError
        pos += 1; return t
    def expr_():
        v = term()
        while peek() in (("o", "+"), ("o", "-")):
            op = take()[1]; r = term(); v = v + r if op == "+" else v - r
        return v
    def term():
        v = unary()
        while peek() in (("o", "*"), ("o", "/")):
            op = take()[1]; r = unary(); v = v * r if op == "*" else v / r
        return v
    def unary():
        if peek() == ("o", "-"): take(); return -unary()
        return power()
    def power():
        b = primary()
        if peek() == ("o", "^"):
            take(); e = unary()
            if e.denominator != 1 or abs(e) > 1000: raise ValueError
            return b ** int(e)
        return b
    def primary():
        t = peek()
        if t[0] == "n": take(); return Fraction(t[1])
        if t == ("o", "("): take(); v = expr_(); take(")"); return v
        raise ValueError
    v = expr_()
    if pos != len(toks): raise ValueError
    return v
''',
"semver_tools.py": r'''
import re
_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?")
def _parse(s):
    m = _RE.fullmatch(s) if isinstance(s, str) else None
    if not m: raise ValueError(s)
    return (int(m[1]), int(m[2]), int(m[3])), (m[4].split(".") if m[4] else [])
def is_valid(s):
    try: _parse(s); return True
    except ValueError: return False
def _cid(a, b):
    ad, bd = a.isdigit(), b.isdigit()
    if ad and bd: a, b = int(a), int(b)
    elif ad: return -1
    elif bd: return 1
    return (a > b) - (a < b)
def compare(a, b):
    (ca, pa), (cb, pb) = _parse(a), _parse(b)
    if ca != cb: return -1 if ca < cb else 1
    if not pa and not pb: return 0
    if not pa: return 1
    if not pb: return -1
    for x, y in zip(pa, pb):
        r = _cid(x, y)
        if r: return r
    return (len(pa) > len(pb)) - (len(pa) < len(pb))
def max_satisfying(versions, rng):
    if not isinstance(rng, str) or not rng.startswith("^") or "+" in rng: raise ValueError
    (M, m, p), pre = _parse(rng[1:])
    if pre: raise ValueError
    lo = (M, m, p); hi = (M + 1, 0, 0) if M else ((0, m + 1, 0) if m else (0, 0, p + 1))
    best = None
    for v in versions:
        try: core, vp = _parse(v)
        except ValueError: continue
        if vp or not (lo <= core < hi): continue
        if best is None or compare(v, best) > 0: best = v
    return best
''',
"csv.mjs": r'''
export function parseCSV(text) {
  if (typeof text !== "string") throw new TypeError("text");
  const rows = []; if (text === "") return rows;
  let row = [], i = 0; const n = text.length;
  while (true) {
    let field = "";
    if (text[i] === '"') {
      i++;
      while (true) {
        if (i >= n) throw new Error("unterminated");
        const ch = text[i];
        if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } i++; break; }
        field += ch; i++;
      }
      if (i < n && text[i] !== "," && text[i] !== "\n" && !(text[i] === "\r" && text[i + 1] === "\n")) throw new Error("after quote");
    } else {
      while (i < n && text[i] !== "," && text[i] !== "\n") {
        const ch = text[i];
        if (ch === '"') throw new Error("quote");
        if (ch === "\r") { if (text[i + 1] === "\n") break; throw new Error("lone CR"); }
        field += ch; i++;
      }
    }
    row.push(field);
    if (i >= n) { rows.push(row); return rows; }
    if (text[i] === ",") { i++; continue; }
    i += text[i] === "\r" ? 2 : 1;
    rows.push(row); row = [];
    if (i >= n) return rows;
  }
}
export function toCSV(rows) {
  if (!Array.isArray(rows)) throw new TypeError("rows");
  return rows.map(r => {
    if (!Array.isArray(r) || r.length === 0) throw new Error("row");
    if (r.length === 1 && r[0] === "") return '""';
    return r.map(f => {
      if (typeof f !== "string") throw new TypeError("field");
      return /[",\r\n]/.test(f) ? '"' + f.replace(/"/g, '""') + '"' : f;
    }).join(",");
  }).join("\n");
}
''',
}
# 常見錯誤版本：評分程式必須讓它們掉分（證明測試有鑑別力）
BAD = {
"expr_eval.py": REF["expr_eval.py"].replace(
    "def unary():\n        if peek() == (\"o\", \"-\"): take(); return -unary()\n        return power()",
    "def unary():\n        return power()").replace(
    "def primary():\n        t = peek()",
    "def primary():\n        t = peek()\n        if t == (\"o\", \"-\"): take(); return -primary()"),  # 一元負號綁在數字上：-2^2 = 4
"semver_tools.py": REF["semver_tools.py"].replace("if ad and bd: a, b = int(a), int(b)", "if ad and bd: pass"),  # 識別碼一律字串比較
"csv.mjs": REF["csv.mjs"].replace('if (r.length === 1 && r[0] === "") return \'""\';', ""),  # 單一空欄位沒處理
}
ws = Path(__file__).resolve().parent / "runs" / "_selfcheck"; shutil.rmtree(ws, ignore_errors=True); ws.mkdir(parents=True)
bad_ws = ws / "bad"; bad_ws.mkdir()
for n, t in REF.items(): (ws / n).write_text(t.strip() + "\n", encoding="utf-8")
for n, t in BAD.items(): (bad_ws / n).write_text(t.strip() + "\n", encoding="utf-8")
from levels import L3_SEED
(bad_ws / "stats.py").write_text(L3_SEED, encoding="utf-8")
by_id = {lv["id"]: lv for lv in LEVELS}
for lv in LEVELS:
    content = f"推導...\nFINAL: {lv['answer']()}" if lv["kind"] == "final" else ""
    print(lv["id"], grade_level(lv, ws, content))
print("--- 錯誤版本（應該掉分）")
print("seed(未修) L3:", grade_level(by_id["L3"], bad_ws))
for lid in ("H1", "H2", "H3"):
    print(f"錯誤版 {lid}:", grade_level(by_id[lid], bad_ws))
print("錯答 L6a:", grade_level(by_id["L6a"], ws, "FINAL: 1"))
