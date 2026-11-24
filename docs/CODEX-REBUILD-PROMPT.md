# 開一個新的 Codex Cloud session 後，怎麼叫它幫你建置

> 前提：新 session 是**全新 workspace**（4 vCPU / 16 GiB / 32 GiB、無 GPU）。
> 舊 session 的檔案不會帶過來 —— 除非你在舊 session 發佈過 environment 快照。

---

## 開 session 前的三件準備

### 1. 先確認能不能重用舊環境（最省事）

舊 task 還開著的話，直接在那個 task 裡開新 turn，環境是延續的。
只有在舊 task 已被歸檔／超過 7 天時，才需要下面這套重建。

若你要長期重複用，在舊環境設定頁按 **Publish**，之後新 task 可選它當起始快照。

### 2. 在 Codex 的 environment 設定加一個 secret

`Settings > Codex Cloud > Environments > 你的環境 > Environment variables`

```
ANIMA_AGENT_KEY = <anima-cloudflare/.private/agent.key 的內容>
```

- 加在環境設定，**不要貼進對話**
- 這台機器因此能領任務；不用的話之後刪掉

### 3. 準備 checkpoint 的下載網址

新 workspace 沒有你的模型。先決定：

- 有公開／可簽章 URL → 填進提示詞的 `<CHECKPOINT_URL>`
- 放在私有位置 → 先上傳到 HuggingFace 私有 repo 或 R2，給 Codex 一把唯讀 token
- 都沒有 → 先跳過模型，環境建好後你自己放（提示詞已含「跳過並回報」的分支）

另外，**Network** 若要在 workspace 內直接打 relay，把 `anima.s92137123.workers.dev` 加入允許網域。
（只做 agent 心跳的話不用，agent 是事後在你 VM 上跑；但這台本身就是 VM，所以建議加。）

---

## 主提示詞（整段貼給新的 Codex session）

```
你在一個全新的 Codex Cloud workspace（Ubuntu、4 vCPU、16 GiB RAM、32 GiB 磁碟、沒有 GPU）。
目標：把 Anima 出圖環境建起來、接上既有的 Cloudflare relay，並證明它能出圖。
不要修改 relay 端的程式，也不要動任何金鑰內容的輸出。

先讀這三個檔案再動手：
- AGENTS.md
- docs/VM-SETUP.md
- deploy/rebuild/README.md

已知事實：
- relay：https://anima.s92137123.workers.dev
- agent 金鑰在環境變數 ANIMA_AGENT_KEY（已設為 secret；不要 echo、不要寫進 repo、不要放進指令字串）
- 沒有 GPU，ComfyUI 只能 CPU；磁碟 32 GB，只裝必要模型
- 這台機器要能長期跑，行程掛掉要自動重啟

執行步驟：

1. 系統套件
   sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv git ffmpeg libgl1 curl jq procps

2. ComfyUI
   git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ~/ComfyUI

3. Python 環境
   python3 -m venv ~/venvs/comfy
   ~/venvs/comfy/bin/pip install -q --upgrade pip wheel
   ~/venvs/comfy/bin/pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
   ~/venvs/comfy/bin/pip install -q -r ~/ComfyUI/requirements.txt

4. 模型
   mkdir -p ~/ComfyUI/models/checkpoints
   把 <CHECKPOINT_URL> 下載到 ~/ComfyUI/models/checkpoints/（若沒有提供 URL，跳過這步並在回報中明確說明）

5. agent 與 workflow
   mkdir -p ~/anima
   複製 repo 的 vm/agent.py 到 ~/anima/agent.py
   複製 deploy/rebuild/workflow.template.json 到 ~/anima/workflow.json
   把 workflow.json 的 CheckpointLoaderSimple.ckpt_name 改成第 4 步實際下載的檔名
   （沒有模型就保留原檔名）

6. 金鑰（不要印出內容）
   printf '%s' "$ANIMA_AGENT_KEY" > ~/anima/agent.key && chmod 600 ~/anima/agent.key

7. 啟動方式（先判斷 systemd 是否可用）
   若 `ps -p 1 -o comm=` 回 systemd：
     建立 /etc/systemd/system/comfyui.service 與 anima-agent.service（內容照 deploy/rebuild/bootstrap.sh），
     systemctl daemon-reload && systemctl enable --now comfyui anima-agent
   否則（雲端 workspace 常見）：
     用 setsid nohup 啟動兩個行程，並寫 ~/anima/keepalive.sh：
       - 每 60 秒檢查 `pgrep -f "main.py --listen"` 與 `pgrep -f agent.py`
       - 掛掉就重啟，輸出寫到 ~/comfy.log 與 ~/anima/agent.log
     再 `setsid nohup bash ~/anima/keepalive.sh > ~/anima/keepalive.log 2>&1 &`

8. 驗收（每一項都要貼出實際輸出）
   a) curl -s http://127.0.0.1:8188/system_stats | head -c 200
   b) 用 workflow.json 直接對 ComfyUI 送一張 128x128、steps=1 的圖
      （把 {{prompt}} 換成 "test"、{{negative}} 換成 ""、{{width}}/{{height}} 換成 128、{{steps}} 換成 1、{{seed}} 換成 1），
      等到完成後把 PNG 存成 ~/anima/test.png，回報檔案大小
   c) tail -n 20 ~/anima/agent.log，確認出現 "[agent] connected"
   d) 回報：兩個行程的 PID、ComfyUI 版本、checkpoint 檔名、test.png 位元組數

限制：
- 不要執行 wrangler deploy
- 不要修改 repo 內的任何檔案（除非我明確要求）
- 不要開任何 inbound port
- 不要在同一行指令裡展開金鑰
```

---

## 我這邊要怎麼確認成功

你在 Codex 貼完、它回報後，跟我說一聲，我會從 relay 端驗：

```bash
curl -s -H "Authorization: Bearer $CLIENT_KEY" \
  https://anima.s92137123.workers.dev/healthz
```

要看到 `agent_recent: true`、`agent_age_seconds < 10`、`model.state: READY`。
然後我會實際送一張圖確認整條鏈路。

---

## 若它卡住，貼這段除錯提示詞

```
agent 沒有出現在 relay 的 healthz（外面看到 agent_recent=false）。
請依序檢查並貼出實際輸出，不要修改 relay：
1. pgrep -af "agent.py|main.py --listen"
2. tail -n 40 ~/anima/agent.log
3. ls -l ~/anima/agent.key（只看權限與大小，不要 cat）
4. curl -s -o /dev/null -w "%{http_code}" https://anima.s92137123.workers.dev/healthz
5. curl -s http://127.0.0.1:8188/system_stats | head -c 120
```

---

## 三個常見失敗點

| 症狀 | 原因 | 解法 |
|---|---|---|
| `[agent] connected` 有出現但 healthz 沒反應 | 金鑰是 client.key 不是 agent.key | 換成 `agent.key` |
| ComfyUI 起來但送單 400 | workflow 的數值被替換成字串 | 把該節點改成整數，或請 Codex 改 agent 支援型別 |
| 過一陣子就斷 | workspace 沒有 systemd、nohup 被清掉 | 用 keepalive.sh + 每 5 天回來發一句話 |
