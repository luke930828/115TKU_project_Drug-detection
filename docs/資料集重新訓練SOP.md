# 匯入新標註資料 → 重新訓練 → 交付模型 SOP

適用情境：在 Roboflow 標了新圖 / 補了樣本 / 調整了類別，要重跑一版 YOLO 模型。
所有指令都從**專案根目錄**執行，Python 一律用 `venv/Scripts/python.exe`。

---

## 0. 名詞與路徑對照

| 東西 | 路徑 | 進 git？ |
|---|---|---|
| Roboflow 剛解壓縮的原始匯出 | `data/raw/`（`train/ valid/ test/ data.yaml`） | ❌ `data/raw/*` 被 ignore |
| `import_roboflow.py` 處理後的訓練資料 | `data/processed/` | ❌ `data/processed/*` 被 ignore |
| 類別權重表（唯一標準來源） | `modules/yolo/app/ai_model/scoring.py` 的 `CLASS_WEIGHTS` | ✅ |
| 訓練腳本設定 | `src/ai_model/train.py` 的 `TrainConfig` | ✅ |
| 訓練產出紀錄與圖表 | `runs/detect/<name>/` | ❌ `runs/` 被 ignore |
| **服務實際載入的模型** | `modules/yolo/app/models/best.pt` | ❌ `modules/*/app/models/*.pt` 被 ignore |

> ⚠️ 模型權重**永遠不會經過 git**，這是刻意的。訓練完要另外把 `best.pt` 交給打包 Docker 的組員（雲端硬碟 / LINE / GitHub Release）。

---

## 1. Roboflow 匯出設定

1. 標註完 → **Generate** 一個新 Version
2. **Preprocessing**：
   - `Auto-Orient` = 開
   - `Resize` = `640 x 640`，模式選 `Fit (white edges)`
3. **Augmentation**：**全部關掉**。
   旋轉、翻轉、模糊、亮度、雜訊這些一律不要在 Roboflow 做——YOLO 訓練時會即時做等效的增強（mosaic / HSV / scale / translate / flip / cutout），Roboflow 那種是「烘死在硬碟上的固定變體」，兩邊疊加反而有害，還會讓圖片數字灌水。
4. **Export** → 格式選 `YOLOv8`（或 `YOLOv11`，結構一樣）→ 下載 zip

---

## 2. 解壓縮到乾淨的地方

把 zip 解壓縮到一個**暫存資料夾**（例如 `D:\Downloads\roboflow_v4\`）。
不要直接解到 `D:\` 根目錄，也不要直接解到專案的 `data/`。

解出來會有：`train/ valid/ test/ data.yaml README.dataset.txt README.roboflow.txt`

---

## 3. 備份舊資料集（重要，不能跳過）

`import_roboflow.py` **不會清空** `data/raw` 和 `data/processed`，它是用「複製 + 同名覆蓋」的方式匯入。
如果直接把新資料倒進去，舊那批**檔名不同**的圖片和標籤會留著，兩套不同的類別 ID 對照表混在同一個 `data.yaml` 底下 → 訓練資料整個對不上、靜默錯標。

所以每次匯入新版之前，先把現有的搬走：

```bash
# <描述> 用能看懂的字，例如 15class_v3 / 761img_noaug
mv data/raw       data/raw_<描述>_legacy
mv data/processed data/processed_<描述>_legacy
```

舊的 `data/*_legacy` 資料夾都被 gitignore，只佔本機硬碟。留最近 1~2 版就好，太舊的（例如 `*_v1_legacy`）確定用不到再刪。

---

## 4. 把新資料放進 data/raw/

```bash
mkdir -p data/raw
# 從暫存資料夾把這四個整包搬進去（Windows 檔案總管拖曳也可以）
mv /d/Downloads/roboflow_v4/{train,valid,test,data.yaml} data/raw/
```

放完後 `data/raw/` 底下應該長這樣：
```
data/raw/
├── data.yaml
├── train/   ├── images/  └── labels/
├── valid/   ├── images/  └── labels/
└── test/    ├── images/  └── labels/
```

---

## 5. 對類別（只有動過類別時才要處理）

打開 `data/raw/data.yaml`，看 `nc:` 和 `names:`。

- **只是補圖、沒動類別** → 跳過這步，直接下一步。
- **改了類別**（加 / 刪 / 改名）→ `names:` 裡每一個名字都必須跟
  `modules/yolo/app/ai_model/scoring.py` 的 `CLASS_WEIGHTS` 的 key **一字不差**
  （snake_case、大小寫、底線都要對）。
  - 新增類別：先在 `CLASS_WEIGHTS` 加一行（給它一個權重），再往下做。
  - 刪除類別：從 `CLASS_WEIGHTS` 移掉，並檢查 `src/防毒後端/main.py` 的
    `VISUAL_CARRIER_ONLY_CLASSES` 有沒有引用到它。
  - 刪類別一定要在 Roboflow 用 **Modify Classes → Remove** 產生新版本，
    **不要**自己手動改 zip——手動刪會讓後面所有類別的數字 ID 錯位、靜默錯標。

---

## 6. 執行匯入

```bash
venv/Scripts/python.exe -m src.ai_model.import_roboflow
```

這支會：
- 讀 `data/raw/data.yaml` 的 `names`，逐一比對 `CLASS_WEIGHTS`，名字對不上直接報錯停下
- 通過後把 images/labels 複製到 `data/processed/`
- **原封不動**沿用 Roboflow 的 `names` 順序寫出 `data/processed/data.yaml`
- 某類別這批完全沒樣本 → 只印警告，不擋匯入

看到 `🚀 匯入完成！` 就成功了。

---

## 7. 調 train.py 的 TrainConfig

打開 `src/ai_model/train.py`，看 `TrainConfig`：

| 欄位 | 什麼時候要改 |
|---|---|
| `data_yaml` | 不用動，固定 `data/processed/data.yaml` |
| `name` | **改了類別數 / 類別清單 → 一定要換新名字**（例如 `drug_prevention_v4_xxx`），否則會跟舊 run 撞、也可能不小心 `--resume` 到類別數不合的舊 checkpoint。只是補圖、類別沒變 → 可以沿用同名（會覆蓋舊 run 目錄），但建議還是換名字，方便留舊的曲線圖做對照。 |
| `epochs` / `patience` | 一般不用動（150 / 30） |
| `batch` | 一般不用動（`0.3` = AutoBatch 目標 30% 顯存，4GB 卡的安全值） |
| `deploy_dir` | 不用動，已固定 `modules/yolo/app/models`（= 服務真正讀的路徑） |

> 舊權重**不用手動改名**。`train.py` 的 `backup_existing_weights()` 會在部署新模型前，
> 自動把現有的 `modules/yolo/app/models/best.pt` 改名成 `best_backup_<時間戳>.pt`。

---

## 8. 開始訓練

```bash
venv/Scripts/python.exe -m src.ai_model.train
```

RTX 3050 上大約 1.5~2 小時（150 epoch 跑滿，或提前被 patience=30 早停）。

- 開訓前會印「資料健檢」，列出樣本數 < 100 的類別——這些之後 AP 通常偏低，優先補標的名單。
- 中途按 Ctrl+C 也會嘗試把「最後一個完整 epoch」的權重部署出去。
- 跑完會自動把 `best.pt` 複製到 `modules/yolo/app/models/best.pt`。

---

## 9. 看結果

- 主控台最後會印 `mAP50` / `mAP50-95` 總分
- `runs/detect/<name>/` 底下：
  - `results.png` — loss / mAP 隨 epoch 的曲線
  - `confusion_matrix.png` — 哪些類別互相搞混
  - 主控台的 per-class 表 — 各類別 P / R / mAP50 / mAP50-95
- 弱類別（mAP 低 + Recall 低）→ 通常是樣本太少，回 Roboflow 補標那個類別，下一輪再訓

---

## 10. 交付與提交

**模型檔（給 Docker 組員）**
- `modules/yolo/app/models/best.pt` 上傳雲端 / GitHub Release，通知組員換檔後重新 `docker build`
- git 不會帶這個檔，別指望 pull 就有

**程式碼（推 git）**
只推 code：
```bash
git add src/ai_model/train.py modules/yolo/app/ai_model/scoring.py src/防毒後端/main.py
git commit -m "..."
git push origin feature/v2-scoring
```
`data/`、`runs/`、`*.pt` 都在 `.gitignore` 裡，不會也不該被推上去。

---

## 快速版（類別沒變、只補圖）

```bash
# 1. 備份舊資料
mv data/raw data/raw_$(date +%Y%m%d)_legacy
mv data/processed data/processed_$(date +%Y%m%d)_legacy

# 2. 放新資料
mkdir -p data/raw
mv /d/Downloads/roboflow_vN/{train,valid,test,data.yaml} data/raw/

# 3. 匯入
venv/Scripts/python.exe -m src.ai_model.import_roboflow

# 4. （可選）改 train.py 的 name 換個新實驗名

# 5. 訓練（自動備份舊 best.pt、自動部署新的）
venv/Scripts/python.exe -m src.ai_model.train

# 6. 把 modules/yolo/app/models/best.pt 傳給 Docker 組員
```
