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

此選項待使用者確認是否建立私人repo，及主要送單裝置。它不需要公開VM埠、Cloudflare Token或Actions；
任務由本機／GitHub UI送出，VM背景worker從合法GitHub API讀取，結果保存在私人結果分支。
在repo、信任驗證及worker完成實測前，不宣稱此模式已啟用。

## 目前限制

VM內127.0.0.1只對VM本身有效，本機填這個位址會連到自己的電腦。
選HTTP模式仍需完成Cloudflare部署授權；改成本機程式本身不會產生外網入口。
