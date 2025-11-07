# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

這是一個圖像題目提取系統，使用 OpenRouter 的 Qwen3 VL 視覺模型從圖片中識別題目和選項，並提供 tkinter GUI 進行題目管理。

**重要**: 所有程式碼、註釋、UI文字、訊息都必須使用**繁體中文**。

## 快速開始

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動應用程式
python main.py
```

## 依賴庫

- `requests`: OpenRouter API 通訊
- `Pillow`: 圖片處理和縮放（自動縮放、格式轉換）
- `tkinter`: GUI 界面（Python 內建）

## 核心架構

### 三層架構設計

1. **API 層** (`api_client.py`)
   - `OpenRouterClient`: 處理與 OpenRouter API 的所有通訊
   - 負責圖片 base64 編碼和視覺模型調用
   - 使用結構化 prompt 確保 AI 輸出 JSON 格式

2. **資料層** (`question_database.py`)
   - `QuestionDatabase`: 管理題目的 CRUD 操作
   - 使用 JSON 檔案持久化儲存
   - 處理題庫匯入時的 ID 重新分配邏輯
   - **Hash 去重系統**: 自動識別並防止重複題目（忽略選項順序）
   - **近似比對系統**: 使用 difflib 計算相似度，可配置閾值和權重
   - **標點符號正規化**: 智慧偵測中文語境，自動統一標點符號格式
   - **圖片管理**: 自動儲存和管理題目相關圖片

3. **UI 層** (`main.py`)
   - `QuestionExtractorApp`: tkinter GUI 應用程式
   - 使用背景執行緒處理圖片，避免 UI 凍結
   - 控制面板分為三區：檔案操作、圖片處理、題庫管理
   - **批量答題功能**: `BatchAnswerDialog` 批量調用 AI 生成答案
   - **批量解題功能**: `BatchGenerateNoteDialog` 批量生成題目解析
   - **全局設定**: `GlobalSettingsDialog` 統一管理應用程式設定
   - **圖片關鍵字偵測**: 自動識別題目中的圖片相關關鍵字

### 資料結構

題目資料格式（JSON）:
```json
{
  "id": 0,
  "question": "題目內容",
  "question_hash": "題目內容的 MD5 hash",
  "options": {
    "A": "選項A",
    "B": "選項B",
    "C": "選項C",
    "D": "選項D"
  },
  "options_hash": "選項內容的 MD5 hash（忽略順序）",
  "combined_hash": "題目+選項的組合 hash（用於去重）",
  "correct_answer": "A",  // 可為 "A", "AB", "ABC" 等多選
  "source": "原始圖片路徑",
  "image_path": "儲存的圖片路徑（images/hash.jpg）",
  "created_at": "ISO 時間戳"
}
```

## 關鍵實作細節

### AI Prompt 設計
- 位於 `api_client.py` 的 `extract_questions_from_image()`
- Prompt 要求 AI 輸出嚴格的 JSON 格式
- 包含對螢幕雜訊的過濾指令
- 處理 markdown 程式碼區塊標記的清理邏輯

### 題庫合併邏輯
- `import_from_file()` 會重新分配所有匯入題目的 ID
- 使用 `len(self.questions)` 作為起始 ID
- 匯入的題目 source 會加上 " (已匯入)" 標記

### UI 複選框狀態管理
- 每個選項 (A-D) 有對應的 `tk.BooleanVar()`
- 儲存時收集所有勾選的選項組成字串 (如 "AB")
- 載入時將字串拆解設定各複選框狀態

### 背景執行緒圖片處理
- 使用 `threading.Thread` 處理批量圖片
- 透過 `root.after(0, callback)` 更新 UI
- 避免在背景執行緒直接操作 tkinter 元件

### Hash 去重機制
- **題目 hash**: 對題目文字進行 MD5 hash
- **選項 hash**: 對所有選項值排序後進行 hash（忽略 A/B/C/D 鍵順序）
- **組合 hash**: 題目 hash + 選項 hash 的組合，作為唯一識別
- 添加題目時自動檢查 `combined_hash` 是否已存在
- 重複題目返回已存在的 ID，不重複添加
- 批量添加會統計新增和重複數量

### 圖片管理系統

**基本功能**:
- 圖片儲存在 `images/` 目錄
- 使用 `combined_hash` 作為圖片檔名（統一為 .jpg 格式）
- 重複題目不會重複儲存圖片
- UI 中顯示圖片連結，點擊可用系統預設程式開啟
- 支援 Windows、macOS、Linux 跨平台開啟圖片

**自動縮放機制** (`save_image()` 和 `encode_image_to_base64()` 方法):
1. **尺寸檢測**: 計算圖片短邊（`min(width, height)`）
2. **條件縮放**:
   - 短邊 > 1200px → 等比縮小至短邊 1200px
   - 短邊 ≤ 1200px → 保持原尺寸
3. **演算法**: 使用 `Image.Resampling.LANCZOS`
   - 最適合文字內容的重採樣演算法
   - 保持邊緣銳利，不會模糊
   - 品質優於 BILINEAR 和 BICUBIC
4. **雙重縮放優化**:
   - **儲存時**: `save_image()` 縮放後儲存至 `images/` 資料夾
   - **上傳時**: `encode_image_to_base64()` 在記憶體中縮放後上傳至 API
   - 目的: 節省 API 上傳時間和成本，同時保持本地儲存效率

**格式轉換**:
- 自動將 PNG/RGBA/LA/P 模式轉換為 RGB
- 透明背景替換為白色背景
- 統一儲存為 JPEG 格式（節省空間）
- 儲存參數: `quality=95, optimize=True`

**實際效果**:
- 4K 螢幕截圖 (3840x2160) → 縮放至 2133x1200
- 檔案大小從 2-3 MB → 200-400 KB（節省 80-90%）
- API 上傳流量同樣減少 80-90%
- 文字依然清晰可讀

### 近似比對系統

**相似度計算**:
- 使用 `difflib.SequenceMatcher` 計算題目和選項的相似度
- **權重配置**: 題目和選項分別有權重（預設 0.6 和 0.4），可在 config.json 調整
- **閾值控制**: 相似度超過閾值（預設 0.75）但不完全相同時觸發比對

**三種狀態**:
- `new`: 新題目，直接添加
- `duplicate`: 完全重複，自動跳過
- `similar`: 近似題目，加入待處理清單

**非阻塞處理機制**:
1. **待處理清單**: 使用 `queue.Queue` 儲存需要使用者決定的近似題目
2. **背景執行緒**: 持續 AI 判讀，發現近似題目時放入 queue
3. **主執行緒**: 每 500ms 檢查 queue（`check_pending_queue()`）
4. **彈出對話框**: 非阻塞，使用者處理時背景繼續工作

**比對對話框** (`ComparisonDialog` 類別):
- **顯示內容**:
  - 新舊題目完整內容對比
  - 相似度百分比（紅色 >90%，橙色 <90%）
  - 正確答案（如果已存在題目有設定）
  - 📷 查看圖片連結（每個題目卡片）

- **三種選擇**:
  - **確認選擇**: 單選按鈕選擇保留哪個版本
  - **全部保留（新增）**: 強制添加新題目（`force_add_question()`）
  - **跳過**: 放棄添加新題目

- **圖片連結實作**:
  - 新題目: 使用 `self.image_path`（剛上傳的圖片）
  - 已存在題目: 使用 `question_data.get('image_path', '')`
  - 點擊後使用系統預設程式開啟（跨平台支援）
  - 方便使用者直接比對原圖判斷哪個正確

### 標點符號正規化系統

**核心功能** (`normalize_punctuation()` 靜態方法):
- 自動統一題目和選項中的標點符號格式
- 在 hash 計算**之前**執行，確保相同內容不因標點差異而被判定為不同題目

**三種模式**:
1. `disabled`: 停用（預設）
2. `to_fullwidth`: 轉換為全形標點（`,` → `，`、`?` → `？`）
3. `to_halfwidth`: 轉換為半形標點（`，` → `,`、`？` → `?`）

**智慧中文語境偵測** (`is_chinese_context()` 內部方法):
- 檢查標點符號前後 2 個字元的上下文
- 偵測條件:
  - 包含中日韓統一表意文字 (U+4E00-U+9FFF, U+3400-U+4DBF)
  - 包含中文標點符號（，。！？；：「」『』等）
- 只在中文語境下轉換標點，保留其他語言原樣

**特殊處理**:
- **小數點保護**: 不轉換數字中的小數點（如 `3.14`）
- **URL 保護**: 不轉換網址中的符號
- 使用正則表達式 `\d+\.\d+` 偵測數字格式

**執行時機**:
- `add_question()` 方法開頭立即執行
- 在 hash 計算之前完成正規化
- 確保重複偵測的準確性

**範例**:
```python
# 輸入（混合標點）
question = "這是一個測試,對嗎?"
# 輸出（to_fullwidth 模式）
question = "這是一個測試，對嗎？"

# 輸入（保留小數點）
question = "圓周率約為3.14,對嗎?"
# 輸出
question = "圓周率約為3.14，對嗎？"

# 輸入（英文語境保留）
question = "This is a test, right?"
# 輸出（不變）
question = "This is a test, right?"
```

### 批量答題與解題系統

**批量答題** (`BatchAnswerDialog` 類別):
- 批量調用 `AnswerClient` 為題目生成答案和解析
- 可選項:
  - **跳過已答**: 跳過已有答案的題目
  - **生成解析**: 同時生成題目解析（note）
  - **包含圖片**: 將題目圖片一併發送給 AI
  - **批次大小**: 控制每批處理的題目數量（預設 10）
- 進度顯示:
  - 即時日誌輸出處理狀態
  - 顯示答案和解析內容
  - 統計處理成功/失敗數量
- 背景執行緒處理，不阻塞 UI

**批量解題** (`BatchGenerateNoteDialog` 類別):
- 專門用於批量生成題目解析（note）
- 可選項:
  - **跳過已有解析**: 跳過已有 note 的題目
  - **跳過無答案**: 跳過未設定答案的題目
  - **包含圖片**: 將題目圖片一併發送給 AI
  - **批次大小**: 控制每批處理的題目數量（預設 10）
- 同樣使用背景執行緒和即時日誌

**圖片關鍵字自動偵測** (`contains_image_keywords()` 靜態方法):
- 自動偵測題目中是否包含圖片相關關鍵字
- 關鍵字列表（不區分大小寫）:
  - 繁體中文: 圖、圖片、圖像、圖表、照片、截圖
  - 簡體中文: 图、图片、图像、图表、照片、截图
  - 英文: image, images, picture, pictures, photo, photos, figure, figures, screenshot, pic, pics
- 當偵測到關鍵字時，自動強制包含圖片發送至 AI
- 可在全局設定中開啟/關閉（預設關閉）
- 日誌輸出: "偵測到圖片關鍵字，自動包含圖片"

**非阻塞處理流程**:
1. 使用者點擊按鈕開啟對話框
2. 設定選項後點擊「開始處理」
3. 背景執行緒開始批量處理
4. 主視窗可繼續操作
5. 日誌即時更新處理狀態
6. 完成後顯示統計資訊

### 全局設定系統

**全局設定對話框** (`GlobalSettingsDialog` 類別):
- 統一管理應用程式全局設定
- 設定內容儲存至 `config.json`
- 修改後立即生效（部分需重啟程式）

**當前設定項目**:

1. **標點符號自動整理**:
   - 三選一: 停用 / 轉全形 / 轉半形
   - 影響範圍: 所有新增題目
   - 執行時機: hash 計算之前
   - 重啟後生效（資料庫初始化時讀取）

2. **圖片自動偵測**:
   - 核取方塊: 自動偵測題目中的圖片關鍵字
   - 影響範圍: 批量答題和批量解題
   - 立即生效（不需重啟）

**UI 設計**:
- 使用 `ttk.LabelFrame` 分組顯示不同類別設定
- 單選按鈕 (`ttk.Radiobutton`) 用於互斥選項
- 核取方塊 (`ttk.Checkbutton`) 用於開關選項
- 視窗尺寸: 500x500（確保所有內容可見）
- 模態視窗: 使用 `grab_set()` 確保使用者完成設定

## 配置檔案

### config.json
```json
{
  "openrouter_api_key": "sk-or-v1-...",
  "model": "qwen/qwen3-vl-235b-a22b-instruct",
  "site_url": "http://localhost",
  "site_name": "Question Extractor",
  "similarity_threshold": 0.75,
  "question_weight": 0.6,
  "options_weight": 0.4,
  "punctuation_mode": "disabled",
  "auto_detect_image_keywords": false
}
```

- API 金鑰不應提交到版本控制
- 提供 `config.example.json` 作為模板

**參數說明**:

- **相似度參數**:
  - `similarity_threshold`: 0.0-1.0，越高越嚴格（預設 0.75）
  - `question_weight`: 題目相似度權重（預設 0.6）
  - `options_weight`: 選項相似度權重（預設 0.4）
  - `question_weight` + `options_weight` 應等於 1.0
  - 這些參數在資料庫初始化時讀取，重啟程式後生效

- **標點符號正規化**:
  - `punctuation_mode`: "disabled", "to_fullwidth", "to_halfwidth"
  - 預設: "disabled"（停用）
  - 影響新增題目時的標點符號處理
  - 修改後需重啟程式生效

- **圖片關鍵字偵測**:
  - `auto_detect_image_keywords`: true / false
  - 預設: false（停用）
  - 影響批量答題和批量解題時的圖片發送邏輯
  - 修改後立即生效

## 匯出格式

文字檔匯出格式 (`export_to_text()`):
```
1.(A)題目內容
A.選項A B.選項B C.選項C D.選項D

2.無正確答案的題目
A.選項A B.選項B C.選項C D.選項D
```

## 修改指南

### 修改 AI Prompt
編輯 `api_client.py` 第 68-91 行的 `prompt` 變數

### 新增題目屬性
1. 更新 `QuestionDatabase.add_question()` 參數
2. 修改資料結構 (第 65-72 行)
3. 更新 UI 輸入元件 (`main.py`)
4. 調整匯出邏輯

### 支援新的圖片格式
修改 `api_client.py` 第 44-50 行的 `mime_type` 字典

### 調整圖片縮放參數
在 `question_database.py` 的 `save_image()` 方法中：
- **修改短邊限制**: 調整 `max_short_side` 參數（預設 1200）
- **修改品質**: 調整 `quality` 參數（預設 95，範圍 1-100）
- **修改演算法**: 更換 `Image.Resampling` 演算法
  - `LANCZOS`: 最高品質（預設，適合文字）
  - `BICUBIC`: 高品質
  - `BILINEAR`: 中等品質
  - `NEAREST`: 最快但品質差

範例：
```python
# 更嚴格的尺寸限制
img.resize((new_width, new_height), Image.Resampling.LANCZOS)

# 更高的壓縮品質
img.save(dest_path, 'JPEG', quality=98, optimize=True)
```

## 語言要求

- **所有新增程式碼、註釋、文件必須使用繁體中文**
- UI 文字、錯誤訊息、日誌輸出均為繁體中文
- 變數名稱使用英文，但 docstring 和註釋用繁體中文
- AI prompt 使用繁體中文以確保正確識別繁體題目

## 常見陷阱

1. **ID 衝突**: 匯入題庫時必須重新分配 ID，不能直接使用原 ID
2. **執行緒安全**: 圖片處理在背景執行緒，UI 更新必須透過 `root.after()`
3. **JSON 解析**: AI 回應可能包含 markdown 標記，需清理後再解析
4. **檔案編碼**: 所有檔案操作必須指定 `encoding='utf-8'`
5. **複選框狀態**: 使用 `key in correct_answer` 而非 `== correct_answer`
6. **Hash 計算順序**: 選項 hash 必須對值排序後計算，以忽略選項順序
7. **圖片路徑**: 圖片儲存使用相對路徑（`images/xxx.jpg`），確保跨平台兼容
8. **去重返回值**: `add_question()` 現在返回 `(id, status, similar_list)` 三元組
   - `status`: "new", "duplicate", "similar"
   - `similar_list`: 近似題目列表 `[(題目, 相似度), ...]`
9. **權重總和**: `question_weight` + `options_weight` 必須等於 1.0
10. **閾值範圍**: `similarity_threshold` 必須在 0.0-1.0 之間
11. **佇列阻塞**: 使用 `queue.get_nowait()` 而非 `queue.get()` 避免阻塞主執行緒
12. **對話框模態**: `ComparisonDialog` 使用 `grab_set()` 確保使用者必須處理後才能繼續
13. **圖片格式**: 所有圖片統一儲存為 .jpg，即使原始是 .png
14. **圖片縮放**: 使用 LANCZOS 演算法，不要使用 NEAREST 或 BILINEAR（文字會模糊）
15. **透明背景**: PNG 透明背景會自動轉為白色，確保 JPEG 相容
16. **Pillow 依賴**: 必須安裝 Pillow >= 10.0.0，舊版本 `Image.Resampling.LANCZOS` API 不同
17. **圖片鎖定**: Windows 上圖片開啟後可能被鎖定，清理測試檔案時需處理 PermissionError
18. **標點符號正規化時機**: `normalize_punctuation()` 必須在 `calculate_*_hash()` 之前執行，否則去重會失效
19. **中文語境偵測**: 檢查前後 2 字元而非 1 字元，提高偵測準確度
20. **圖片關鍵字大小寫**: 使用 `text.lower()` 和 `keyword.lower()` 確保不區分大小寫比對
21. **全局設定模態**: `GlobalSettingsDialog` 必須使用 `grab_set()` 避免使用者在設定未完成時操作主視窗
22. **批量處理記憶體**: 批次大小預設 10，避免大量 API 請求造成記憶體溢出
23. **背景執行緒 UI 更新**: 批量處理的日誌必須透過 `root.after()` 更新，直接呼叫會導致執行緒錯誤
24. **config.json 預設值**: 新增配置項目時必須在程式碼中提供 `config.get('key', default)` 預設值，避免舊版 config 造成 KeyError
25. **圖片上傳優化**: `encode_image_to_base64()` 在記憶體中縮放，不影響原始檔案，節省 API 成本
