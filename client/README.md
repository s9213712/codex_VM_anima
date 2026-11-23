# 不經聊天的本機生圖送單器

這個目錄只需要Python標準函式庫，**本機不需要安裝Torch、Diffusers或下載模型**。
真正推理仍在VM；本機關掉視窗不會取消已送出的任務，但VM暫停、到期或中斷會影響生成，不能由此客戶端自動喚醒託管VM。

## HTTP中繼／API模式

公開API部署並取得自己的client key後：

```bash
python anima_client.py --api https://你的已驗證API網址 --key-file client.key submit --prompt "anime mountain lake at sunrise" --wait --output lake.png
```

這條命令完全不需要ChatGPT。若不加--wait，會回傳task ID，可稍後查詢或下載：

```bash
python anima_client.py --api https://你的已驗證API網址 --key-file client.key status TASK_UUID
python anima_client.py --api https://你的已驗證API網址 --key-file client.key download TASK_UUID --output lake.png
```

檔案中可放多行中文提示詞，使用--prompt-file prompt.txt。預設256×256、8steps、seed42；--size與--steps可調。
金鑰只讀本機檔案，不放URL、不印出、不提交Git；請在自己的裝置保護key檔。
外部URL只接受HTTPS且拒絕重新導向，避免Authorization被轉送至別的主機。程式不覆蓋既有輸出檔。

## GitHub收件匣

客戶端與worker已實作，本機測試通過；遠端尚未啟用。現有GitHub連線建立私人repo回傳403，需帳號持有人先建立私人anima-vm-jobs儲存庫。它不需要公開VM埠、Cloudflare Token或Actions；
任務由本機／GitHub UI送出，VM背景worker從合法GitHub API讀取，結果保存在私人結果分支。
在repo、信任驗證及worker完成實測前，不宣稱此模式已啟用。

## 目前限制

VM內127.0.0.1只對VM本身有效，本機填這個位址會連到自己的電腦。
選HTTP模式仍需完成Cloudflare部署授權；改成本機程式本身不會產生外網入口。

## 自動下載的條件

使用submit --wait會保持客戶端運作、輪詢狀態，完成後檢查PNG與SHA256並存到--output檔案。
不加--wait只回傳任務ID。關閉客戶端不會取消後端已受理的任務；但本機關機／休眠時不能繼續下載，需之後用status和download取回。
請保存任務ID；結果能保留多久取決於已配置的收件匣與VM生命週期。

## VM資源概況

```bash
python anima_client.py --api https://你的已驗證API網址 --key-file client.key resources
python anima_client.py --api https://你的已驗證API網址 --key-file client.key resources --watch 10 --duration 600
```

可看CPU配額與使用率、cgroup記憶體用量／上限、磁碟空間、模型狀態／RSS、API運作時間及租期。
記憶體cgroup用量包含可回收快取；quota_headroom是配額減用量，不等同Linux MemAvailable。
CPU第一次取樣為null，下一次取得後才有使用率，不假造0%。HTTP中繼回傳VM主動上送的快照，含時間與延遲，並非直接讀取另一台機器。
這個API需Bearer金鑰，不回傳環境變數、Secret、密碼或雲端帳號額度。watch最多3小時，Ctrl+C可停止。

## 可提交雲端任務，但沒有VM電源API

可選用官方Codex CLI（本機須另安裝並用ChatGPT帳號執行codex login）：

```bash
python cloud_task.py probe
python cloud_task.py submit-task --env 已發佈的CodexCloud環境ID --branch 目標工作分支 --task-file task.txt
python cloud_task.py status TASK_ID
```

官方CLI有實驗性codex cloud exec命令。本工具先驗證登入模式與實際唯讀雲端存取，再提交一次任務，失敗不重試、不切換付費API key。
本次VM的login status雖報ChatGPT，實際cloud list卻401；因此**目前未完成派發驗收，也未提交任何新Cloud Task**。
需在你自己的裝置完成登入，並提供已配置／發佈的CodexCloud環境ID；不能把目前ccarenv開頭的託管電腦ID當成該ID。
它只派發新Cloud Task與查狀態，不是一般VPS建立／開關機API，不保證喚醒或重用同一台VM，也還沒有自動取得Cloud Task圖片產物的整合。
Cloud Task會使用你的原生Codex額度，剩餘額度未知；不自動購買額度或啟用付費API。提交回應若逾時，先list/status確認是否已建立，不自動重送。
Windows的可選派發工具要求官方原生codex.exe；沒有在Windows上實測，不宣稱跨平台完整驗收。

完整「建立環境／啟動 → 送單 → 取圖」一鍵流程尚未完成。送單、下載、資源查詢均需先接上已授權的外部收件方式。

## 完整本機送單介面（GitHub模式）

需要Python 3.10以上與官方GitHub CLI（https://cli.github.com/），本機不裝模型。
Windows雙擊start-windows.bat；macOS／Linux在終端執行 ./start-mac-linux.sh。
首次GitHub登入在你自己的裝置及瀏覽器完成，不在聊天貼Token。請登入可存取connection.json所列私人repo的帳號。
啟動後會打開本機瀏覽器介面：送單、查詢、圖片預覽、自動下載、VM資源快照。
瀏覽器若阻擋自動下載，使用頁面的下載按鈕。關掉介面之後請保留任務編號，可稍後查詢。

命令列也可以不帶--api：

```bash
python anima_client.py submit --prompt "sunrise over a mountain lake" --wait --output lake.png
python anima_client.py status ISSUE_NUMBER
python anima_client.py download ISSUE_NUMBER --output lake.png
python anima_client.py resources --watch 30 --duration 600
```

connection.json預設私人任務匣；不包含任何Token。GitHub模式的任務編號是Issue number，不是HTTP API的UUID。
手機可直接用私人repo的Generate an image Issue Form送單，結果連結在完成的Issue內；不需要聊天，也不需要在手機跑Python。

雲端啟動按鈕只在connection.json填入codex_environment_id後啟用，還會檢查本機Codex CLI實際授權；
它提交新Cloud Task，不是一般VM建立／喚醒API。沒有完成此設定時，介面明確顯示未設定，不會謊報VM已建立。
本次沒有在Windows或macOS上執行測試；核心Python與本機HTTP介面在雲端Linux驗證；GitHub鎖定／任務格式有本機測試，真實遠端送單仍待私人repo建立後驗收。
