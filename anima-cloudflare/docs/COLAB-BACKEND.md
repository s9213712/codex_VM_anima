# Colab 後端建置指南（Anima 生圖節點）

## 概念
Colab 免費 GPU（T4）跑 `agent_diffusers.py`，主動輪詢 Relay 認領任務——
不需要固定網址、不需要隧道。VM／本地 Python／Colab 誰在線誰接單；
UI「後端模式」選「自動」即可讓它們互補。

## 步驟（約 3 分鐘）
1. 開 https://colab.research.google.com → 新增筆記本 →
   編輯 → 筆記本設定 → 硬體加速器選 **T4 GPU**
2. 第一格儲存格貼上 `colab_cell.py` 的內容（本機用
   `scripts/make_colab_cell.py` 產生，金鑰已自動填入，不會經過聊天）
3. 執行 → 等模型首次下載（約 3-5 分鐘）→ log 出現「通用節點啟動」即可
4. 在工作站頁面送出任務；Colab 在線時任務會由它接（可從任務 metadata 確認）

## 注意
- Colab 免費版閒置約 90 分鐘會斷線，斷線後任務自動落回 VM／本地
- 每天有運算時數上限；跑超過會被強制停止
- 金鑰只存在 Colab 儲存格裡；不要把筆記本分享出去（會洩漏金鑰）
