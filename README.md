# DeepSeek 工蜂（deepseek-swarm）

讓 Claude 當指揮、DeepSeek 當工人：Claude 只負責釐清需求、拆任務、看摘要；程式碼的產出、審查、寫測試、跑測試、修正都交給 DeepSeek 在背景完成。

> English summary: an MCP server + Claude skill that lets Claude delegate code-generation tasks to DeepSeek workers, with automatic syntax checks, server-side test writing/running, and arbitration between independent implementations. Windows-only installer. Includes an optional Cloudflare image-generation MCP server and a benchmark suite.

## 它做什麼

- **MCP 伺服器 `deepseek_swarm`**：`submit_swarm_job`、`get_swarm_job`、`quick_worker_solve` 等工具，任務在背景執行。
- **Skill `deepseek-orchestrator`**：教 Claude 怎麼拆任務、一個指令派工、怎麼讀摘要，把 Claude 的對話輪數壓到最少。
- **`ds.py`**：一個指令派工並等待結果的命令列工具（Skill 預設用它，不用載入 MCP 工具）。
- **自動品質關卡**：產出 → 語法檢查 → 寫檔（先備份）→ 另一個工蜂只看規格寫測試並實際執行 → 測試失敗時由另一模型寫第二份獨立實作仲裁。
- **選用：`cloudflare_image`**：把需要圖片的任務交給 Cloudflare 生圖。
- **選用：即時儀表板**（`files/dashboard/`）。
- **`bench/`**：固定題庫與隱藏測試的評測腳本，改完程式後可以量有沒有真的變好。

## 需求

- Windows（安裝程式與 skill 範例用的是 Windows 路徑與 PowerShell）
- Python 3.10 以上
- Node.js 20 以上（建議；只影響 JavaScript 任務的測試）
- [DeepSeek API 金鑰](https://platform.deepseek.com)（用 Cloudflare 生圖才需要另外的 Cloudflare 帳號與 token）
- Claude 桌面 App 或 Claude Code

## 安裝

```powershell
copy secrets.env.example secrets.env
# 用編輯器打開 secrets.env，填入自己的金鑰
python setup.py
```

`setup.py` 會：安裝 Python 套件、把程式複製到 `C:\mcp_tools`（同名檔先備份）、把金鑰寫進使用者環境變數、安裝 skill 到 `~/.claude/skills/deepseek-orchestrator`、把兩個 MCP server 加進 Claude 設定（原設定先備份）、最後自我檢查。只想檢查不改東西：`python setup.py --check`。

裝完請**完全結束** Claude App（含系統匣圖示）再重開，新對話說「用 deepseek 工蜂幫我寫 …」即可。

也可以直接把這個資料夾交給 Claude Code，並請它照 [SETUP_FOR_CLAUDE.md](SETUP_FOR_CLAUDE.md) 安裝。

> **金鑰安全**：`secrets.env` 已列在 `.gitignore`，不要把它提交或貼到對話。安裝完成後金鑰已寫進環境變數與 Claude 設定檔，可以刪掉 `secrets.env`。

## 適合與不適合

- **適合**：一次要寫大量程式碼、多個可獨立驗證的小模組、批次重複性任務。Claude 輸出的字最貴（輸出單價約為輸入的 5 倍），這類任務把「寫」外包最有感。
- **不適合**：幾行的小修改、一兩句就答完的問題。每次對話本身有固定開銷，小任務外包不一定比 Claude 自己做划算。

## 評測結果與限制

`bench/` 是作者自己設計的題庫（小函式到多元件模組、JS、推理題，用工蜂看不到的隱藏測試評分）。在作者的最新設定下，11 題的 3 次執行正確率都是 100%，每輪約 100 秒、DeepSeek 端費用約 0.16 美元。請把這些數字當參考，不是保證：

- 題庫是作者自己出、也針對它調過參數，有過擬合的可能；每組設定只跑 1～3 次。
- 推理題偶爾失分，部分設定下正確率會掉。
- **沒有對照組**：目前沒有量化「相較於 Claude 自己做」或「用 Haiku 子代理做」到底省多少 Claude 用量，這是尚未驗證的部分。歡迎用 `bench/claude_usage.py` 自己量，有結果也歡迎回報。

評測用法見 [bench/README.md](bench/README.md)。

## 已知限制

- 目前只支援 Windows，安裝位置固定為 `C:\mcp_tools`，skill 內的指令也寫死這個路徑。
- 文件與提示詞以繁體中文為主。
- 這是個人專案，沒有穩定性承諾。

## 授權

MIT，見 [LICENSE](LICENSE)。
