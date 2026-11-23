# 用 Codex / Claude / Jules 的雲端 VM 建置本專案

> 結論先講：**這三家的雲端 VM 都適合「改程式、跑測試、開 PR」，都不適合當 Anima 的出圖後端**
> （沒有 GPU、VM 生命週期是分鐘到小時、會被回收）。
> 要真正出圖，仍然需要你自己的機器或長期租用的 GPU VM（見 `docs/VM-SETUP.md`）。

---

## 1. 三邊 VM 的實際差異

| | **Codex Cloud**（OpenAI） | **Claude Code cloud**（Anthropic） | **Jules**（Google） |
|---|---|---|---|
| 入口 | 網頁 / 桌面 / 手機，`Work in > Cloud` | claude.ai/code、桌面、手機、`claude --cloud` | jules.google.com |
| VM 形態 | 每個 task 一個 workspace | 每個 session 一台 VM | 每個 task 一台**短命 VM** |
| 生命週期 | task 期間；published environment 保存「已裝好的檔案系統」快照 | 閒置幾分鐘後**暫停並保留檔案**；被回收則下次重建新 VM | task 結束即釋放；setup 後可存 snapshot |
| 系統 | 容器化 Linux workspace | Anthropic 管理的 Linux VM | Ubuntu 24.04 |
| 預裝 | 依環境自動偵測 | 常見工具鏈（可自訂 setup） | Node 22 / Python 3.12 / Go / Java / Rust / Docker / gcc / cmake |
| 網路 | 預設受限；可開 `public internet`、`package manager domains`、自訂網域 | 分級（預設只允許套件來源與 allowlist，可放寬） | 安裝依賴時可連網 |
| 密鑰 | Environment variables（直接注入）或 **HTTP secrets**（代理替換，程式只看到佔位符） | Environment variables（.env 格式）＋ network secrets | Configuration 內設定環境變數 |
| 客製安裝 | `Install script` + `Start skill`，由 Codex 幫你寫並測試 | `Setup script`（新 session 開頭執行） | `Initial Setup` 腳本，按 **Run and Snapshot** 驗證並快照 |
| 專案指示檔 | `AGENTS.md` | `CLAUDE.md`（不讀 AGENTS.md） | `AGENTS.md` / `README.md` |
| GPU | **無** | **無** | **無** |
| 能否常駐 daemon | 不行（task 結束就沒了） | 不行（閒置會暫停、可能被回收） | 不行（短命 VM） |
| 最適合 | 有規模的 repo 改造、跑測試、發 PR | 同上，且能接 GitHub 開 PR | 同上，環境預裝最齊 |

> 規格數字（vCPU/記憶體）三家都沒有寫進公開文件；社群回報 Codex Pro 約 4 vCPU / 16 GiB / 32 GiB 磁碟。
> 這是**社群數據，非官方保證**，實際以你帳號看到的為準。

---

## 2. 為什麼不能拿來跑 Anima 後端

`vm/agent.py` 的運作方式：

1. 常駐，每 **10 秒**送一次心跳
2. 每 2 秒 poll 一次 `POST /agent/claim`
3. 領到任務後執行 ComfyUI，回報進度，15 分鐘租約內交件

三個平台都會在這之前把 VM 停掉或回收：

- **Codex**：task 結束 workspace 就結束
- **Claude**：閒置幾分鐘 VM 暫停；被回收就重建（重建後 `/home/user/anima` 的安裝與暫存都沒了，除非寫進 setup script）
- **Jules**：官方明寫「short-lived VM」

再加上**沒有 GPU**：SD 1.5 在 CPU 上 512×512 約 1–2 分鐘，放大到 1024 更久，而租約是 15 分鐘 —— 等於送出去也來不及。

**所以正確用法是**：用它們維護 relay 與工具鏈，用你自己的機器出圖。

---

## 3. 三個平台各自的建置步驟

三個平台的 setup script 可以共用同一段（下面以 Codex 為例，其餘相同）：

```bash
set -e
cd anima-cloudflare
npm ci
npm run build:ui
npm test
node ../scripts/check-secrets.mjs
node --check src/worker.js
```

### 3.1 Codex Cloud

1. 開新 task → `Work in` 選 **Cloud** → `Select environment` → **Create environment**
2. 選 repository `s9213712/codex_VM_anima`
3. 讓 Codex 自己探測，然後在 **Install script** 貼上上面那段
4. **Network**：加 `anima.s92137123.workers.dev`（若要在 VM 內打 relay 做 smoke test）
5. **Environment variables**：`CLIENT_KEY`、`AGENT_KEY`（**只在需要實測時加**，測試本身不需要）
6. `Publish` → 之後每個 task 都從這個快照開始

> 想讓 Codex 少走冤枉路：repo 根目錄的 `AGENTS.md` 已經寫好專案結構與禁區（見第 4 節）。

### 3.2 Claude Code cloud

1. claude.ai/code → 訊息框下方第一個控制項 → **New environment**
2. **Setup script** 貼上面那段
3. **Network access** 選放寬，並加入 `anima.s92137123.workers.dev`
4. **Environment variables** 用 `.env` 格式填（測試用不到，實測才需要）
5. 之後 `claude --cloud` 或網頁開 session 都會用這個環境

⚠️ Claude Code 讀的是 **`CLAUDE.md`**，不是 `AGENTS.md`。要它遵守同樣規則，
請在 repo 建 `CLAUDE.md`（內容可直接複製 `AGENTS.md`）—— 這個檔案我沒有代你建立，
需要的話說一聲，或自己加。

### 3.3 Jules

1. 左側 codebases 選這個 repo → 上方 **Configuration**
2. **Initial Setup** 貼同一段腳本
3. 按 **Run and Snapshot** —— 成功後會存成快照，之後每個 task 直接從快照起
4. Jules 會讀 `AGENTS.md` 與 `README.md` 來補環境細節

---

## 4. 三邊都能用的驗收清單

在任何一個雲端 VM 貼上這段，應該全部通過（不需要金鑰）：

```bash
cd anima-cloudflare
npm ci                                   # 依賴
npm run build:ui                         # 產生 ui.generated.js
npm test                                 # 15 項單元測試
node ../scripts/check-secrets.mjs        # 確認沒有金鑰被追蹤
node --check src/worker.js src/logic.js  # 語法
node -e "require('../anima-easy-updater/update.cjs').payload()"   # 更新器完整性
```

全部通過代表這個 VM 具備「可以改 relay、可以開 PR」的條件。

---

## 5. 想在這類 VM 上短暫實測（不建議常態）

可以，但只能當一次性 demo：

```bash
pip install --quiet requests  # agent.py 只用標準庫，其實不用
python3 vm/agent.py --relay https://anima.s92137123.workers.dev \
  --key-file ./agent.key --backend command \
  --command 'python3 -c "from PIL import Image; Image.new(\"RGB\",(512,512),(20,30,60)).save(\"$ANIMA_OUT\")"' \
  --once
```

`--once` 只領一張就退出，用來驗證金鑰與 relay 連線。
**不要**在雲端 VM 開常駐模式，VM 隨時會被收掉，任務會卡到租約逾時。

---

## 6. 三個平台怎麼選

| 你的目的 | 建議 |
|---|---|
| 大改 relay、需要長時間迭代與多檔案重構 | **Codex Cloud**（環境快照 + 權限控制最完整） |
| 已經在用 Claude、想直接開 PR | **Claude Code cloud** |
| 需要很多預裝工具鏈（C/C++、Docker、多語言） | **Jules**（預裝最齊，snapshot 免重裝） |
| 需要 GPU 出圖 | **都不行** → 自有機器或 Runpod（見 `docs/VM-SETUP.md`、`docs/CODEX-TASKS.md`） |
