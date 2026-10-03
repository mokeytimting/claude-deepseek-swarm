# 圖片流程（需要點陣圖時才讀）

生圖工具（Cloudflare Workers AI，免費額度內不收費）：
- `…generate_image`(prompt, reference_images, model, size, n, seed)：生圖／改圖，回傳本機圖片路徑
- `…image_usage`()：查今日已生成張數，不消耗額度

工具清單沒有時用 ToolSearch 搜尋「generate_image」載入；找不到就告訴使用者生圖工具沒有接上，不要改用其他付費服務。

## 1. 寫 prompt
- 1–2 張：Claude 直接寫（prompt 很短，派工反而更貴）。
- 3 張以上或要統一風格：派 DeepSeek 一次寫完。shared_context 放專案背景與共用風格（畫風、色調、光線），每張圖一個 task；要求每張輸出三行：`PROMPT: <英文>`、`SIZE: <寬>x<高>`、`MODEL: klein|fast|text`。
- 規則：英文；寫清楚主體、構圖、畫風、色彩、光線、用途；沒有 negative_prompt，不想要的改用正面描述（例：plain background）。
- 圖中**不要放文字**，除非必要且為短英文（用 text 模型）。**中文字一律不靠模型**：先生無字底圖，再用程式加字（HTML/CSS 疊字，或派 DeepSeek 寫 Pillow 腳本）。

## 2. 生圖

| 情境 | model |
|---|---|
| 預設、改圖、要風格一致 | klein（可放 0–4 張參考圖，用 image 0、image 1 指代） |
| 大量草稿、不要求尺寸 | fast（尺寸固定、無 seed、無參考圖） |
| 圖中需要英文字 | text（很耗額度，每天約 3–4 張，非必要不用） |

- size 依用途：橫幅 1920x640、文章配圖 1024x768、方形 1024x1024；klein 上限 1920。
- 先生 1 張；使用者要多個選項才用 n>1。要能重現或之後微調時給 seed。
- 同系列風格一致：先定稿第一張，之後用 klein 把它放進 reference_images。

## 3. 審核
Claude 用 Read 看圖，檢查主體、構圖、風格，以及變形（手、臉、肢體）、亂碼文字、多餘元素。
- 不合格 → 改 prompt 重生；局部修改用 klein 帶原圖當參考圖並描述要改的地方。
- 同一張最多重生 3 次，第 2 次起換說法或換模型；仍不合格就附上最好的一張，說明問題請使用者決定。

## 4. 整合
圖片預設存在 `~/Pictures/ai_images`。放進專案時複製到素材資料夾並改成有意義的檔名（例：`assets/hero-banner.jpg`）。

## 錯誤處理
`[ERROR]` 提到額度用完或每日上限 → 停止生圖並告訴使用者（台灣時間早上 8 點重置），不要改用付費服務；`[PARTIAL]` → 只補生失敗的張數。

## 回報
加一行：生了幾張、重生幾次、最終檔案位置、今日用量。
