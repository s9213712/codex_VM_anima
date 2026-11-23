# GitHub私人圖片任務匣

本機client／GitHub Issue Form → 私人repo的anima-job Issue → VM主動輪詢 → 本機Anima API → anima-jobs分支的PNG與任務狀態。
不需要VM公開IP、Cloudflare Token或Github Actions。只對有repo權限的GitHub使用者開放。

Worker只接受OWNER／MEMBER／COLLABORATOR與固定圖片schema，不執行Issue內的程式或URL。
以GitHub Contents SHA做CAS lease，單VM工作鎖900秒；過期的昂貴任務會FAILED要求人工確認／重送，不在新VM偷偷重做。
同時一個worker、單張最多600秒、每日UTC最多20次claim，累積結果檔100MiB上限；單圖2MiB。
圖片存Git歷史，不自動刪除repo／改寫歷史；適合小量測試，不能當無限圖床。

```bash
./scripts/start.sh
.venv/bin/python github_queue/worker.py --repo s9213712/anima-vm-jobs
```

第二條需另一個終端。worker最多3小時。VM暫停時GitHub仍能收件，但要VM真正恢復且worker運作才會生成。
本工具不保證可從外部喚醒這台託管VM；Codex Cloud任務派發需另外設定已發佈環境與本機CLI授權。

任務Issue JSON與手機表單都會做白名單驗證。API key、GitHub token與密碼不可放在prompt。
生成成功後關閉對應Issue、寫入結果連結，客戶端下載時驗證SHA256。原工作分支／main不合併。
GitHub資源快照每1–2分鐘更新，介面附時間；舊快照不能當成仍在線。

來源：GitHub CLI官方登入使用系統憑證儲存，客戶端不索取Token。Repo必須private。
本機用Python與GitHub CLI，沒有Torch／模型依賴。首次在自己的裝置透過gh auth login登入repo所屬帳號。
