# VM 重建包

> 目的：Codex Cloud 的 VM 狀態**最多保留 7 天**（從你最後一次發話算起），而且沒有 uptime 保證。
> 這份文件讓你在 30 分鐘內把同樣的執行環境重建出來 —— 不管是新的 Codex workspace、GCE、Runpod 或你家裡的機器。

---

## 目前這台 VM 的實測規格（2026-11-24 從 `/healthz` 讀取）

| 項目 | 數值 |
|---|---|
| CPU | 4 vCPU 配額（5 核可見） |
| 記憶體 | 17.2 GB |
| 磁碟 | 33.8 GB（已用 7.9） |
| 模型回報 | `Anima Turbo v0.2`（LoRA）、8 步、guidance 1、RSS 4.9 GB |
| 對應方案 | ChatGPT **Pro**（官方規格 4 vCPU / 16 GiB / 32 GiB） |

作業系統為 Linux、ComfyUI 聽 `127.0.0.1:8188`、agent 每 10 秒心跳。

---

## 第一步：從現有 VM 收集（5 分鐘）

在**現在這台** VM 上跑：

```bash
bash collect.sh > vm-manifest.json
cat vm-manifest.json
```

它會輸出（**不含金鑰內容**）：

- 系統規格、GPU 型號
- ComfyUI 的 git 版本、`models/checkpoints` 與 `models/loras` 的檔名清單
- `custom_nodes` 清單、關鍵 pip 套件版本
- `comfyui.service` 與 `anima-agent.service` 的完整 unit
- agent 的實際啟動參數與 workflow 檔名

把這份 JSON 貼給我就好 —— 我可以照著產出精確的重建腳本。

> 沒有 shell 的話：請 Codex 幫你跑 `bash collect.sh` 並把輸出貼回來。

---

## 第二步：在新機器重建（20 分鐘）

### 2.1 準備四個檔案

```
~/anima/agent.py          # repo 的 vm/agent.py
~/anima/workflow.json     # 由 deploy/rebuild/workflow.template.json 修改
~/agent.key               # chmod 600
~/models/<checkpoint>     # 例如 anima-base-v1.0.safetensors
```

`workflow.json` 修改重點：

1. `CheckpointLoaderSimple.ckpt_name` 改成你的檔名
2. 若要掛 Turbo LoRA，在 `5` 前面加一個 `LoraLoader`（`lora_name`: `Anima Turbo v0.2`、`strength_model`/`strength_clip`: 1.0），
   並把 `5.model` 改成指向它
3. 其餘 `{{prompt}}` `{{negative}}` `{{width}}` `{{height}}` `{{steps}}` `{{seed}}` **必須保留**（agent 靠這些字串替換）
4. 要輸出 1080p 就在 `6` 後面加 `ImageScale`（1920×1088）再接 `SaveImage`

### 2.2 執行

```bash
sudo RELAY_URL=https://anima.s92137123.workers.dev \
     AGENT_KEY_FILE=$HOME/agent.key \
     CHECKPOINT_FILE=$HOME/models/anima-base-v1.0.safetensors \
     MODEL_NAME="anima-base-v1.0" \
     bash bootstrap.sh
```

腳本會：裝系統套件 → clone ComfyUI → 建 venv（有 GPU 就裝 cu124，沒有就 CPU 版）
→ 放模型 → 建兩個 systemd unit → 開機自啟 → 等到 `/system_stats` 有回應。

### 2.3 驗收

```bash
systemctl is-active comfyui anima-agent       # 兩個 active
journalctl -u anima-agent -n 10 --no-pager | grep connected
curl -s http://127.0.0.1:8188/system_stats | head -c 80
```

從你的電腦：

```bash
curl -s -H "Authorization: Bearer $CLIENT_KEY" \
  https://anima.s92137123.workers.dev/healthz | python3 -m json.tool
```

`agent_recent: true`、`agent_age_seconds < 10` 就代表接上了。

---

## 第三步：避免下次再來一次

| 做法 | 為什麼 |
|---|---|
| **至少每 5 天在 Codex 那個 task 發一句話** | 官方只保證 7 天內可恢復 |
| **checkpoint 放雲端（HF / R2 / 自家 NAS）** | VM 磁碟只有 32 GB，且會被回收 |
| **workflow 與 unit 進 repo** | 這份重建包已經含 unit 與模板 |
| **設 `FALLBACK_URL`** | VM 一斷，5 分鐘後自動轉備援，你不會斷線 |
| **等價替代：Runpod serverless** | `runpod-workers/worker-comfyui`，不需要常駐 |

---

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `collect.sh` | 在舊 VM 上執行，輸出 `vm-manifest.json`（不含金鑰） |
| `bootstrap.sh` | 在新 Ubuntu 上重建 ComfyUI + agent 兩個 service |
| `workflow.template.json` | ComfyUI API 格式的 txt2img 模板，含 agent 需要的佔位符 |
| `../gpu-vm/install-comfyui.sh` | 只裝 ComfyUI、不裝 agent 的精簡版 |

---

## 已知陷阱

1. **數值以字串送出**：agent 是字串替換，`"{{width}}"` 會變成 `"512"`。
   若 ComfyUI 回 400 `Failed to validate prompt`，把該節點的值改成整數並改用不含該 token 的模板（或請 Codex 改 agent 支援型別轉換）。
2. **磁碟 32 GB**：SDXL checkpoint 約 6.5 GB、SD1.5 約 2 GB，放兩個就快滿，別囤模型。
3. **CPU 出圖很慢**：8 步 Turbo 在 512×512 約 1–2 分鐘；1024 可能超過 15 分鐘租約。
4. **金鑰只在 VM 上**：重建時要重新放 `agent.key`，不要從聊天貼。
