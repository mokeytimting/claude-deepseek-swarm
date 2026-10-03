# 給 Claude Code：請把這台電腦設定成可以用 DeepSeek 工蜂

使用者把這個資料夾交給你，要你直接裝好到能用。請照順序做，遇到問題自己排除，最後回報結果。

1. 確認 Python 3.10 以上：`python --version`。
   - 沒有或太舊：`winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements`，
     裝完後用完整路徑（通常是 `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`）執行後面的指令，因為目前終端機的 PATH 還沒更新。
   - 注意：Windows 內建的 `python` 可能只是 Microsoft Store 的捷徑（執行會跳商店），要當成沒裝。
2. （建議）確認 Node.js 20 以上：`node --version`。沒有就 `winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements`。沒有 Node 只影響 JavaScript 任務的測試。
3. 在 `setup.py` 所在的資料夾執行：`python setup.py`（解壓縮後若多了一層同名資料夾，先 `cd` 進去）
   - 它會安裝套件、把程式放到 `C:\mcp_tools`、設定金鑰環境變數、安裝 skill、把 MCP server 寫進 Claude 設定（原設定會先備份）。
   - 最後會自我檢查；有 ✘ 就依訊息修正，再跑 `python setup.py --check` 直到全部 ✔。
4. 全部 ✔ 後告訴使用者：
   - 請**完全結束** Claude App（包含右下角系統匣圖示）再重開。
   - 重開後開新對話，說「用 deepseek 工蜂幫我寫 …」就能用。
   - 建議刪掉這個資料夾和 zip 檔，因為 `secrets.env` 裡有金鑰（已經寫進環境變數和設定檔，不再需要）。

不要把 `secrets.env` 的內容印出來或貼到對話裡。
