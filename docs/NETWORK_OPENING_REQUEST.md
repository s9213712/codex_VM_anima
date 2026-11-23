# 給平台管理員的 Cloudflare Tunnel 開通申請

日期：2026-11-23 UTC。
用途：使用者已要求以 Cloudflare Tunnel 公開其 Anima 生圖 API；只允許個人非商業測試，不啟用付費資源。
環境 ID：`ccarenv_b64_Y2NhcmVudl81ZTczNjFhNDNlZTA4MTkxOTU1MzIzMTZlOTJiMGQ4Yg`。

## 最小必要開通項目（HTTP/2 模式）

|方向／類型|目的地|需求|
|---|---|---|
|出站 TCP|`region1.v2.argotunnel.com:7844`|cloudflared HTTP/2 長連線|
|出站 TCP|`region2.v2.argotunnel.com:7844`|Cloudflare 第二個區域端點，避免只允許一區|
|DNS|平台核准的 resolver|允許上述主機 A/AAAA 及 `_v2-origintunneld._tcp.argotunnel.com` SRV 查詢|
|SNI 規則（若有）|`h2.cftunnel.com`、`cftunnel.com`、`_v2-origintunneld._tcp.argotunnel.com`，port 7844|依 Cloudflare 官方文件允許原生 TLS/HTTP2 握手|

我們固定 `--protocol http2`，所以這次**不要求 UDP 7844**；只有之後要改用 QUIC 才需另行開通。
若平台只能用 IP 規則，請使用官方文件當時列出的兩區完整 IP 清單；不要只開一個解析出的 IP，也不要假設 IP 永遠不變。
需支援 cloudflared 原生的 TLS／HTTP2 持續連線。一般「HTTP unrestricted」或允許 HTTPS 443，不等於原生 TCP 7844 可用。
若須經平台 TCP CONNECT／TLS passthrough，請提供正式支援且獲授權的方式；不會關閉 TLS 驗證、修改路由或繞過封鎖。

## 選擇一種佈建方式

### A. Quick Tunnel（免帳號臨時網址）

另需允許 `https://api.trycloudflare.com:443/tunnel` 的 cloudflared API 請求（包含建立 Tunnel 的 POST）。
此環境最近的 HTTPS 檢查回 403，body：`Your request was blocked.`；原生 client 先前直接連線也失敗。
規則來源目前無法從平台診斷工具識別，請管理端確認是平台限制、企業規則或目的服務限制；不能只憑 HTTP policy=unrestricted 判斷已開通。

### B. Named Tunnel（使用既有 Cloudflare 帳號）

執行已建立的 Named Tunnel 不需使用 Quick Tunnel 佈建 API，但**仍需要上面的出站 TCP 7844 與 DNS／TLS 支援**。
使用者需在 Cloudflare 建立 Tunnel 與 Published Application，origin 指向 `http://127.0.0.1:8765`。
固定公開 hostname 需使用者已有可用的 Cloudflare DNS zone／hostname；本任務不購買網域、不啟用付費方案。
Token 以秘密檔案掛載，環境變數 `TUNNEL_TOKEN_FILE` 指向該檔。不要把 Token 貼入對話、命令參數或 Git。
啟動程式使用官方已驗證參數 `cloudflared tunnel --protocol http2 run --token-file <secret-file>`。
Named Token 或 DuckDNS Token 都不能取代網路許可。

## 不需要的設定

- 不需要 VM 公開 IP、入站 22／80／443、NAT port forwarding 或對外開放資料庫。
- 不需要 DuckDNS Token，也不開放全部外部 TCP／UDP。
- 不建立 SSH／其他隧道來繞過平台規則。

## 服務端與驗收

API 僅綁定 `127.0.0.1:8765`。生成／任務／圖片端點需 Bearer 金鑰；健康檢查不暴露金鑰。
Cloudflared 與 API 都有最多 3 小時租期；單張圖最多 600 秒、同時一個 worker、佇列容量 2。
本次重建啟動後的模型與 API 驗證結果另外記錄，不以 11/16 的結果宣稱現在在線。

平台確認生效後：

1. 重新讀取 environment_status 與新設定版本，啟動全新 cloudflared 連線。
2. 確認 Registered tunnel connection，取得並實測公開 hostname；日誌出現 URL 不算驗收成功。
3. 從外部驗證 `/healthz`、無金鑰生成回 401、帶金鑰提交回 202、輪詢完成後圖片回 200。
4. 任何一項失敗均保持 BLOCKED，不宣稱已公開部署。

官方來源（本次已讀取，頁面標示更新日 2026-10-12）：
https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
