# 進階用法（需要時才讀）

## 對話衛生
- 專案根目錄維持簡短 `CLAUDE.md` 交接檔；一個功能做完就建議開新對話。
- 對話中不切換模型、不增減 MCP 伺服器（快取失效）。

## 修 bug：先重現再修
1. 第一次派工：只寫「重現測試」（`output_files` = 測試檔，task 附 bug 描述，`task_attach` 附相關程式碼），`verify_cmd` 設為執行該測試 → 摘要應顯示「現在失敗」，證明測試真的抓到 bug。顯示通過代表沒重現，改寫測試再派。
2. 第二次派工：修實作（`task_attach` 附程式碼、`output_files` 寫回原檔），`test_cmd` = 重現測試指令（當關卡，工蜂不可改測試），`verify_cmd` = 專案整體測試（防止改壞別處）。
3. 摘要 ✔ 且專案測試沒有 ⚠ 才算修好。

## 測試關卡細節
- `test_files`：測試工蜂（看不到實作）只看規格寫測試；寫檔後伺服器執行；失敗時先仲裁（另一模型寫第二份獨立實作跑同一份測試：通過 → 採用第二份；在相同測試失敗 → 判定測試錯、實作不動，摘要標「爭議測試」），無定論才交修正工蜂。有 test_files 且非 max 的任務預設不另審查（環境變數 DEEPSEEK_REVIEW_WITH_TESTS=1 可改回）。生成的測試若含 subprocess、socket、網路、os.system、shutil.rmtree、eval 等高風險操作，不執行並標「未測試」。
- 只給 `test_cmd`（不給 test_files）：跑既有測試當關卡，修正工蜂只能改實作。
- 同時給兩者：用 test_cmd 執行生成的測試（非 py/js 語言時用）。
- `verify_cmd`：送出時先跑一次、整批寫完再跑一次，只回報不自動修。基準必須在寫檔前跑完，專案測試很慢時任務會等它；大型套件用較快的子集指令。
- 修正自動升級：第 1 輪產出模型＋任務的修正強度；第 2 輪換另一個模型＋max。修不好時保留最後一個語法正確的版本並標「仍有問題」。

## 模型選擇
- `flash`（預設）：較新、推理與程式較強、快、便宜。寫檔任務 auto 一律用它。
- `pro`：參數大，冷門知識（專有名詞、歷史細節、少見函式庫）記得較多；較慢較貴。預設當審查員。
- 投票：3 份 `["flash","flash","pro"]`，5 份 3 flash + 2 pro；可為每份指定不同解法（反證、列舉小案例、從答案反推）。題目放 shared_context，task_list 只寫短標籤。
- 思考模式下 temperature 無效，獨立性靠混用模型與不同解法。

## 高風險任務（錯了會造成實際損失或難以察覺）
| 類型 | 做法 |
|---|---|
| 程式 | 同一批加派 flash、pro 各一份實作（寫到不同檔名），以測試結果擇優 |
| 推理、判斷 | 5 份投票；無明確多數時請兩派各寫精簡論證，Claude 裁決 |
| 長篇文字 | 第二批派審稿工蜂只回問題清單，再派工蜂修正 |

## MCP 工具（ds.py 無法用時的備援）
- ToolSearch 搜尋「deepseek」載入。`submit_swarm_job`（參數同任務檔欄位，需 `output_root` 絕對路徑）→ 立即回傳 job_id → shell 背景執行 `python C:\mcp_tools\wait_job.py <job_id>` 等完成通知。不要反覆呼叫 get_swarm_job。
- `batch_parallel_swarm`：短回答投票（< 150 行、不寫檔；MCP 約 60 秒逾時）。`quick_worker_solve`：單一短問題。
- `get_swarm_job(job_id, full:true)`：看某任務完整內容。`restore_swarm_job(job_id)`：還原該批寫入（覆寫的檔還原、新增的檔刪除；ds.py 送出的 job 也適用）。
- 完整回覆在 `~/.deepseek_swarm_jobs/<job_id>/`（tNN.md 最終版、v1、review、test）。
