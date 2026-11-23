# 本次恢復實測（2026-11-23）

- 模型權重：5個safetensors檔，均與官方LFS SHA256一致。
- 模型：circlestone-labs/Anima-Base-v1.0-Diffusers，revision `073c3a9db359c31ad0e8aa268d15775473c2176c`。
- 執行：CPU BF16，256×256，8steps，seed42。
- 本次生成耗時：161.68秒；完成時RSS 5.55 GiB（不是peak）。
- PNG已透過真實API下載，HTTP200、PIL驗證與SHA256比對通過。
- 真實驗證：未授權401、steps超限422；5項測試通過。
- 目前CPU為Intel Xeon Platinum 8573C；上次11/16約40秒的歷史結果不能當成本次效能。
- 防止重複啟動：第二次start被flock擋下，exit1，未另啟大型模型。
- Cloudflare公開連線：BLOCKED。使用者已回覆尚未開通網路，沒有Token或公開URL。

平台開通清單：NETWORK_OPENING_REQUEST.md。Secret只應放環境秘密儲存，不可貼入對話。
本地服務不等於已公開；請先確認Cloudflare所需出站路由，再作Named Tunnel設定。
