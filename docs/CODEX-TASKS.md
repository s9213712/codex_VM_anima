# 給 Codex 的待辦提示詞（VM 端）

> 這台 VM 是 Codex 建的（`codex_VM_anima`），relay 端（Cloudflare Worker）由 Hermes 維護。
> 下列每一段都可以整段貼給 Codex，等額度回來再執行。**relay 契約不要改**，只改 VM 端。

---

## 1. 輸出 1920×1088（不動 relay 上限）

```
在這個 VM 的 ComfyUI workflow（anima 出圖用）末端加上放大階段，讓最終輸出固定為 1920×1088，
但送給 ComfyUI 的生成尺寸仍維持 relay 傳來的 width/height（≤1024）。

做法：
1. 找到目前 workflow 的 SaveImage 節點。
2. 在它前面插入：
   - "ImageScale"：image 接原本的輸出，upscale_method 用 "lanczos",
     width 1920, height 1088, crop "disabled"
   （若已安裝 RealESRGAN，改成 UpscaleModelLoader(RealESRGAN_x4plus)
     + ImageUpscaleWithModel，再接一個 ImageScale 收斂到 1920×1088）
3. 讓 SaveImage 改接放大後的結果。
4. 不要改動 workflow 的節點編號以外的 relay 介面；agent 仍回傳 PNG。

驗收：
- 送 1024×576 的請求，回傳 PNG 必須是 1920×1088
- 送 512×512，回傳仍是 1920×1088（由放大節點決定）
- 生成時間增加不超過 60 秒
```

---

## 2. 換模型（SDXL / 指定 checkpoint）

```
讓 agent 支援切換 checkpoint，不改 relay 契約。

1. 在 ComfyUI 的 CheckpointLoaderSimple 節點，把 ckpt_name 改成可設定：
   讀環境變數 ANIMA_CKPT（預設 anima-base-v1.0.safetensors）。
2. 若 ANIMA_CKPT 檔名含 "xl"（SDXL），額外處理：
   - 解析度預設改 1024×1024
   - 負面提示詞維持不變
3. 開機時驗證該 checkpoint 存在，不存在就 fallback 回預設並寫入 log。
4. 在 /system_stats 對應的 agent 回報中，把實際載入的 checkpoint 名稱放進 model 欄位。

驗收：
- 設 ANIMA_CKPT=sdxl_base.safetensors 重啟後，/healthz 的 model 顯示該檔名
- 出圖成功且尺寸符合 1024×1024
```

---

## 3. 批次任務（一次多張）

```
讓 VM 端支援一次請求產生多張圖，不改 relay 既有欄位（relay 目前一次送一張）。

1. agent 收到任務後，若任務 JSON 有 "batch"（1–4），就對 ComfyUI 送出 N 次，
   seed 依序 +1（除非使用者指定固定 seed）。
2. 產生 N 張 PNG 後，打包成 zip（無壓縮即可），以 image/zip 回傳。
3. relay 端不需要改動：單張時仍回 PNG；多張時回 zip，副檔名 .zip。

驗收：
- batch=3 的請求回傳含 3 張 PNG 的 zip
- 單張請求行為完全不變
```

---

## 4. agent 自我修復（VM 被收回後）

```
讓 agent 在 VM 重啟後自動恢復，不需要人工介入。

1. 啟動時先讀 relay 的 /healthz，確認 relay 可達；不可達就每 30 秒重試。
2. 心跳失敗連續 5 次 → 重新註冊（重新取得 agent 身分），並記錄原因。
3. 開機時清掉 ComfyUI 的暫存輸出，避免磁碟慢慢滿。
4. 所有錯誤寫入 journald，並在 /healthz 的 last_error 反映最後一次失敗原因。

驗收：
- 重啟 VM 後 60 秒內 /healthz 的 agent_recent 變 true
- 拔掉網路 30 秒再恢復，agent 能自行回到 ready 狀態
```

---

## 注意

- relay 的驗證上限是 **1024 且為 32 的倍數**（1080 不合法，最近值 1088）——VM 端不要試圖放大請求尺寸，改用 workflow 放大。
- 這些改動都不需要動 Cloudflare 端，也不需要更換 Durable Object 實例。
