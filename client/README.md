# Anima Studio 客戶端

Windows 完整安裝與 Git 更新請看 [教程](../docs/WINDOWS_GUIDE.md)。一般使用請開啟**應用程式安裝位置**的 `anima-client/start-windows.bat`，不要直接在 Git 原始碼內建立金鑰或快取。

只需 Python3.10+，本機不下載 Anima 或安裝 Torch。介面顯示中文狀態、真實進度/日誌、資源圖表及歷史縮圖，不顯示原始 API JSON。參數匯出為一般文字。

正常模式走已部署的 Cloudflare HTTPS 中繼，使用安裝位置 `.private/client.key`；認證不放網址、不印出、不提交 Git。`connection.json` 是無金鑰來源範例，更新器保留每台電腦既有實際設定。

命令列診斷（會輸出開發資料，一般使用者不需要執行）：

```powershell
python anima_client.py --api https://你的實際Worker.workers.dev --key-file ..\.private\client.key submit --prompt "anime mountain lake" --width 768 --height 512 --steps 8 --wait --output lake.png
```

此客戶端不能建立或喚醒 VM。已送出的任務須 VM 真正運作才會生成；本機關機時不會自動下載。已快取歷史在 history-data，詳細上限見 [歷史說明](../docs/HISTORY_PREVIEWS.md)。

可選 GitHub 私人收件匣與 Codex Cloud Task CLI 是另外模式，不是預設 HTTP 路徑，也不是已驗證的 VM 電源 API。
