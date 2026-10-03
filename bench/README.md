# DeepSeek 工蜂測試關卡

每次改完 `deepseek_swarm.py` 或 `deepseek-orchestrator` skill，跑一次，看有沒有真的變好。
判斷順序照 skill 的原則：**先看正確率，正確率持平才比時間與費用**。

## 第一關：伺服器（不花 Claude，約 3–8 分鐘）
直接呼叫伺服器程式跑 8 個固定題目，用工蜂看不到的隱藏測試評分。

```
cd C:\mcp_tools
python bench\run_bench.py --label "這次改了什麼"
```

| 關卡 | 測什麼 |
|---|---|
| L1 時間解析 | 簡單函式、邊界輸入 |
| L2 區間合併+LRU | 兩個元件、狀態 |
| L3 修改既有檔案 | 附檔 `task_attach`、寫回原檔、備份 |
| L4 庫存模組 | 較長檔案、「全有或全無」交易 |
| L5 JS 位元組格式 | JavaScript 語法檢查與寫檔 |
| L6a–c 推理 | `FINAL:` 格式與答案正確 |

常用選項：
- `--server deepseek_swarm.pre-extras.backup.py --label 舊版`：測舊版本（舊版沒有 submit_swarm_job 時自動改用 quick_worker_solve）
- `--repeat 2`：同一版跑兩次取平均，AI 每次結果不同，差距小時用這個確認
- `--levels L3,L4`：只跑部分關卡（只和關卡數相同的紀錄比較）
- `--effort auto`：讓伺服器自動選強度（寫檔任務 high、其餘 max）
- `--tests`：啟用伺服器端測試（test_files，測試檔寫到 gen_tests/）；可用環境變數 `DEEPSEEK_TEST_WRITER=flash|pro|other` 換測試工蜂模型
- `--history`：只看歷史

結果記在 `bench/history.jsonl`，工蜂產出的檔案留在 `bench/runs/<時間>/` 可以打開看。

## 第二關：Claude 用量（量 skill 的效果）
skill 的目標是省 Claude，這只能在真的對話裡量。

1. `python bench\claude_usage.py --prompt` → 產生 `bench\e2e_prompt.md`
2. Claude 桌面 App 開**新對話**、選一個**空資料夾**，貼上 e2e_prompt.md 全文送出，等它做完（中途不要插話）
3. `python bench\claude_usage.py --label "這次改了什麼"`

它會自動找最近一次開頭是 `[BENCH-E2E]` 的對話，統計 Claude 的「等效輸入 tokens」
（輸出 ×5、快取讀 ×0.1、快取寫 ×1.25/×2，對應實際計價比例），並評分那個資料夾裡做出來的檔案。
紀錄在 `bench/history_claude.jsonl`。

也可以請 Claude 用子代理代跑（不用自己開新對話）：成品放 `bench/e2e_runs/<時間>/`，再用
`python bench\claude_usage.py --session <子代理 .jsonl 路徑> --workdir <成品資料夾> --label ...` 評分。
限制：子代理的對話紀錄不記最終輸出 token（只記串流開頭的值），所以「輸出」會偏低，輸入/快取數字是準的。
子代理的紀錄只和子代理的紀錄比，不要和真實對話的紀錄混著比。

## 改題目
改 `levels.py` 後先跑 `python bench\selfcheck.py`（用標準答案確認評分程式沒寫錯），
然後把 `SUITE_VERSION` 加 1，舊紀錄就不會和新題目混在一起比。
