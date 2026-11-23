# 用 Claude 建／接管這台 VM

> 你已經用 Codex 證實「雲端 agent + 一台 VM + 這個 repo」可行。
> Claude 也能做同一件事，但**入口不同**：關鍵在「Claude 跑在哪台機器上」。
>
> 官方依據：<https://code.claude.com/docs/en/self-hosted-environments>（自架環境）
> 與 <https://code.claude.com/docs/en/cloud-environments>（雲端環境設定）

---

## 1. 四條路，先選對

| 路線 | Claude 跑在哪 | 你的 VM 能不能用 | 方案需求 | 適合 |
|---|---|---|---|---|
| **A. Claude Code CLI 裝在 VM 上** | 你的 VM | ✅ 直接改檔案、跑 systemd | Pro/Max 或 API key | **最接近 Codex 的做法，推薦** |
| **B. CLI 在本機，SSH 進 VM** | 你的電腦 | ✅ 間接（透過 ssh 指令） | 同上 | 不想在 VM 裝東西 |
| **C. Remote Control** | 你的常開機器 | ✅ 就是你的機器 | Pro / Max / Ultra | 想用手機／網頁操作你家的機器 |
| **D. Claude Code cloud（Anthropic VM）** | Anthropic 的 VM | ❌ 不是你的機器、無 GPU、會被回收 | Pro/Max/Ultra/Team | 只能改 code、跑測試、開 PR |

另外 **self-hosted environment + runner**（Team/Enterprise、公開 beta、預設關閉）可以讓「雲端 session」跑在你自己的網路裡 —— 但那是給企業用的，個人沒必要折騰，選 A 就好。

---

## 2. 路線 A：把 Claude Code 裝在 VM 上（推薦）

### 一次性設定

```bash
# 在 VM 內
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g @anthropic-ai/claude-code

# 登入（headless 會給一組 URL + code，用瀏覽器完成）
claude
```

登入後 `cd ~/anima` 或 repo 目錄，直接 `claude` 開互動 session。

### 第一個 prompt（照貼）

```
這是 Anima 出圖服務的 VM 端。先讀 AGENTS.md（若存在）與 docs/VM-SETUP.md。

現況：
- ComfyUI 應在 127.0.0.1:8188（用 curl -s http://127.0.0.1:8188/system_stats 確認）
- agent.py 在 ~/anima/agent.py，金鑰在 ~/anima/agent.key
- relay 是 https://anima.s92137123.workers.dev

請依序：
1. 檢查 ComfyUI 是否活著、agent 是否已註冊（curl relay /healthz 看 agent_recent）
2. 若沒註冊，建立 systemd unit 並 enable --now，參數照 docs/VM-SETUP.md
3. 送一張 128x128 steps=1 的測試，確認 /v1/jobs/<id>/image 回合法 PNG
4. 回報：兩個 service 狀態、healthz 摘要、測試 PNG 的位元組數
不要改 relay 端、不要動 .private 以外的金鑰、不要開任何 inbound port。
```

### 之後的日常用法

```bash
cd ~/anima && claude -p "檢查 agent log，若有重複錯誤就修並重啟"
```

---

## 3. 路線 B：CLI 在本機，讓它 SSH 進去

如果你的 VM 有 SSH key（Codex 用的那組就行），本機裝好 Claude Code 後：

```
你有 ssh 權限進入 <user>@<vm-host>。請透過 ssh 完成以下工作，不要假設本機有 ComfyUI：
1. ssh 進去檢查 systemctl status comfyui anima-agent
2. 檢查 curl -s http://127.0.0.1:8188/system_stats
3. 若 agent 沒在跑，依 docs/VM-SETUP.md 建 systemd unit 並啟動
4. 把 journalctl -u anima-agent -n 30 的結果貼回來
```

優點：VM 不用裝 Node/Claude；缺點：每次都要繞一層，檔案編輯不直覺。

---

## 4. 路線 C：Remote Control（手機／網頁操作你自己的機器）

適合「我不想在 VM 裡開終端機，但想用手機叫它做事」。

- 需求：Pro / Max / Ultra
- 做法：在你那台常開的機器跑 `claude`，啟用 Remote Control，之後從 claude.ai 或手機接手同一個 session
- 這條路的 session **跑在你自己的機器上**，用你家的網路與檔案，不是 Anthropic 的 VM

---

## 5. 路線 D：Claude Code cloud（Anthropic VM）——只拿來改 code

跟 Jules 一樣：每 session 一台 Anthropic 管理的 VM，閒置會暫停、可能被回收，**沒有 GPU**。

設定方式：
1. claude.ai/code → 訊息框下方環境選擇器 → **New environment**
2. **Setup script**：

```bash
set -e
cd anima-cloudflare
npm ci
npm run build:ui
npm test
node ../scripts/check-secrets.mjs
```

3. **Network access**：放寬並加入 `anima.s92137123.workers.dev`（僅在需要實測時）
4. **Environment variables**：`CLIENT_KEY` / `AGENT_KEY`（測試用不到）

⚠️ **Claude Code 讀 `CLAUDE.md`，不讀 `AGENTS.md`。**
本 repo 目前只有 `AGENTS.md`（給 Codex/Jules）。要讓 Claude 遵守同樣規則，
在 repo 根目錄新增 `CLAUDE.md`，內容可直接用下面這段：

```markdown
# CLAUDE.md

## 專案
Anima 出圖 relay：Cloudflare Worker + Durable Object，外部 GPU 機器跑 agent.py 驅動 ComfyUI。
詳細結構與指令見 AGENTS.md（本檔为 Claude 版摘要）。

## 指令
cd anima-cloudflare && npm ci && npm run build:ui && npm test
node ../scripts/check-secrets.mjs

## 禁區
- 不動 anima-cloudflare/.private/；不把金鑰寫進任何檔案
- export default 必須留在 src/worker.js
- 改 src/ui.html 後一定要 npm run build:ui 並一起 commit
- 不自行 bump Durable Object 的 instance 版本（會清空任務紀錄）
- relay 契約不改；尺寸 128–1024 且為 32 的倍數
- 不要在雲端 VM 執行 wrangler deploy
```

> 這個檔案我沒有代你建立（需要你明確同意）。要我加就說一聲。

---

## 6. 跟 Codex 的差異（實際體感）

| | Codex Cloud | Claude Code CLI（在 VM 上） | Claude Code cloud |
|---|---|---|---|
| 誰的機器 | OpenAI 的 task workspace | **你自己的 VM** | Anthropic 的 VM |
| 能不能裝 ComfyUI 常駐 | ❌ | ✅ | ❌ |
| 能不能跑 systemd | ❌ | ✅ | ❌ |
| 壽命 | task 期間 | 你關掉為止 | session 空閒即暫停、可能回收 |
| 適合本專案 | 改 repo / 開 PR | **接管 VM、修 agent、裝模型** | 改 repo |

**結論**：Codex 幫你「生」了 VM；Claude 要「接管」那台 VM，請用**路線 A**（把 CLI 裝在 VM 上）。
兩者可以並存：Codex 改 repo、Claude 顧機器。

---

## 7. 驗收（不管走哪條路）

```bash
systemctl is-active comfyui anima-agent          # 都要 active
curl -s http://127.0.0.1:8188/system_stats | head -c 80
journalctl -u anima-agent -n 5 --no-pager | grep connected
```

然後在你電腦上：

```bash
curl -s -H "Authorization: Bearer $CLIENT_KEY" \
  https://anima.s92137123.workers.dev/healthz | python3 -m json.tool
```

`agent_recent: true` 且 `agent_age_seconds < 10` 就代表 Claude 顧的機器已經接上 relay。
