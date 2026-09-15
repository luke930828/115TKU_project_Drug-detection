# 多模態毒品交易防制系統

淡江大學專題。系統自動爬取網頁，同時用**文字模型**與**影像模型**判讀是不是毒品販售網站，
依風險分級後交給承辦人員覆核。

## 系統架構

六個服務以 Docker Compose 編排，彼此透過內部網路溝通：

| 服務 | 功能 |
|---|---|
| `crawler` | 搜尋並爬取網頁，取得純文字與商品圖，關鍵字初篩 |
| `backend` | FastAPI。派發任務給兩個 AI 引擎、統整結果、名單與權限管理 |
| `nlp` | XLM-RoBERTa 文字分類，輸出校準後的毒品機率與關鍵字 |
| `yolo` | YOLO 物件偵測（15 類），附 EasyOCR 讀取圖片文字 |
| `frontend` | React 操作介面，nginx 提供 HTTPS 與 API 反向代理 |
| `mysql` | 分析結果、網頁快照、黑白名單、使用者、稽核日誌 |

```
爬蟲抓網頁 → 後端（白名單比對）→ NLP 判文字、YOLO 判圖片 → 後端分級 → 前端清單 → 人工覆核
```

## 判定規則

文字分數決定「要不要人工看」，影像分數決定「進哪一個清單」：

| 條件 | 風險等級 | 去向 |
|---|---|---|
| 文字 ≥ 85 且 影像 ≥ 30 | 極高風險 | 黑名單清單 |
| 文字 ≥ 85 | 高風險 | 待確認清單（優先覆核） |
| 文字 ≥ 30 | 中風險 | 待確認清單（建議覆核） |
| 其餘 | 低風險 | 不進清單 |

文字分數是經 Platt 校準的機率（0～100）；影像分數是「類別權重 × 信心度」的合成指標，不是機率。

## 目錄結構

```
modules/     五個服務的原始碼（backend、crawler、frontend、nlp、yolo）
deploy/      docker-compose 設定與 HTTPS 憑證相關
tests/       整合測試與資安測試
models/      影像模型權重（不進 git，說明見 models/MODELS.txt）
data/        評估資料與圖表
Makefile     常用指令
```

## 部署

系統目前只部署在專題主機上。

## 常用指令

```bash
make full           # 六個服務啟動
make help           # 列出所有指令
make ps             # 各服務健康狀態
make logs           # 即時紀錄
make verify         # 檢查服務是不是正常啟動（掛載、模型、憑證）
make recreate       # Docker Desktop 或 WSL 重開過就跑這個（重建容器，讓掛載重新解析）
make rebuild M=nlp  # 改完某個模組後重建（正式 compose 沒掛載原始碼）
make stop           # 停止，資料保留
make backup         # 備份資料庫到 data/backups/
make test           # 跑測試（stub 取代 AI 服務，不需要 GPU）
make check          # 部署前確認沒有把秘密或大檔加進 git
```

> `make clean` 會刪掉資料庫資料，不要隨便執行。備份時資料庫與圖片 volume 要一起備份。

## 模型

| 模型 | 版本 | 上線日期 |
|---|---|---|
| 文字 | [`matt0513/drug-detection-xlm-roberta-v3`](https://huggingface.co/matt0513/drug-detection-xlm-roberta-v3)（Platt 校準 a=0.513、b=0.659） | 2026-09-09 |
| 影像 | YOLO v3，15 類 | 2026-09-10 |

在 48 筆與訓練資料零重疊的完整網頁上：文字模型 ROC-AUC 0.938，
送覆核的 precision 0.893、recall 0.926。
