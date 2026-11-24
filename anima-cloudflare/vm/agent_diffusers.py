#!/usr/bin/env python3
"""通用 Anima 生圖節點（純 Python + diffusers）。

任何能跑 Python、能連網下載模型的主機（VM／Colab／任何雲）都能當生圖後端：
  AGENT_KEY=... RELAY_URL=https://anima.xxx.workers.dev python3 agent_diffusers.py

協定與 vm/agent.py 相同：輪詢 /agent/claim → /agent/complete，15 分鐘租約。
任務額外欄位：
  model: HF repo id 或本地 safetensors 路徑（預設 JANKU v777 的 HF 對應；無則 SDXL base）
  lora:  HF repo id 或本地 lora 檔（可選）
  turbo: true → 8 步；false → 30 步
首次使用某模型會自動從 HF 下載並快取在 ~/.cache/huggingface。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

RELAY_URL = os.environ.get("RELAY_URL", "https://anima.s92137123.workers.dev").rstrip("/")
AGENT_KEY = os.environ.get("AGENT_KEY", "")
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "900"))
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.expanduser("~/.cache/anima-models"))
TURBO_LORA = os.environ.get("TURBO_LORA", "Magnobber/Anima_Turbo_LoRA_v0.2")  # HF repo 或本地路徑

_pipes: dict[str, object] = {}


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def api(path: str, body=None, method: str = "GET", timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(RELAY_URL + path, data=data, method=method if data else "GET",
                                 headers={"Authorization": "Bearer " + AGENT_KEY,
                                          "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def resolve_source(src: str) -> str:
    """HF repo id 或本地檔案路徑 → diffusers 可用的來源。"""
    if os.path.exists(src):
        return src
    if os.path.isdir(MODELS_DIR):
        local = os.path.join(MODELS_DIR, os.path.basename(src))
        if os.path.exists(local):
            return local
    return src  # HF repo id：diffusers 會自動下載


def get_pipe(model: str):
    key = model or DEFAULT_MODEL
    if key in _pipes:
        return _pipes[key]
    from diffusers import StableDiffusionXLPipeline
    src = resolve_source(key or DEFAULT_MODEL)
    log("載入模型 " + src + "（首次會自動下載）")
    if src.endswith(".safetensors") or src.endswith(".ckpt"):
        pipe = StableDiffusionXLPipeline.from_single_file(
            src, torch_dtype=torch_dtype(), use_safetensors=True)
    else:
        pipe = StableDiffusionXLPipeline.from_pretrained(src, torch_dtype=torch_dtype())
    to_device(pipe)
    _pipes.clear()          # 4GB～16GB 主機一次只留一個模型
    _pipes[key] = pipe
    return pipe


def torch_dtype():
    import torch
    return torch.float16 if torch.cuda.is_available() else torch.float32


def to_device(pipe):
    import torch
    if torch.cuda.is_available():
        pipe.to("cuda")
        pipe.enable_attention_slicing()
    else:
        pipe.enable_attention_slicing()
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pass


def get_lora(pipe, lora: str):
    src = resolve_source(lora)
    log("載入 LoRA " + src)
    if src.endswith(".safetensors") and not os.path.exists(src) and "/" in lora:
        from huggingface_hub import hf_hub_download
        f = hf_hub_download(lora.split("/")[0] + "/" + lora.split("/")[1] if False else lora, None) \
            if False else None
    try:
        pipe.load_lora_weights(src)
    except Exception as exc:
        log("LoRA 載入失敗（忽略）: " + str(exc)[:120])


def render(job: dict) -> bytes:
    import torch
    model = (job.get("model") or DEFAULT_MODEL).strip()
    pipe = get_pipe(model)
    if pipe is None:
        raise RuntimeError("model unavailable")
    turbo = bool(job.get("turbo"))
    lora = (job.get("lora") or "").strip()
    if lora or turbo and TURBO_LORA:
        get_lora(pipe, lora or TURBO_LORA)
    else:
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
    gen = torch.Generator("cpu").manual_seed(int(job.get("seed") or 0))
    image = pipe(
        prompt=job.get("prompt", ""),
        negative_prompt=job.get("negative_prompt", "low quality, blurry"),
        width=int(job.get("width") or 512),
        height=int(job.get("height") or 512),
        num_inference_steps=8 if turbo else int(job.get("steps") or 30),
        generator=gen,
    ).images[0]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    if not AGENT_KEY:
        sys.exit("請設定 AGENT_KEY")
    log(f"通用節點啟動 → {RELAY_URL}（租約 {LEASE_SECONDS}s）")
    while True:
        try:
            job = api(f"/agent/claim?lease={LEASE_SECONDS}", body={"agent": "diffusers-universal"},
                      method="POST")
        except urllib.error.HTTPError as e:
            if e.code == 403:
                log("Agent key 未授權或節點未配對")
            time.sleep(30)
            continue
        except OSError:
            time.sleep(30)
            continue
        if not job.get("job"):
            time.sleep(5)
            continue
        j = job["job"]
        log("接單 " + j["id"][:8] + f" model={j.get('model') or 'default'} turbo={j.get('turbo')}")
        try:
            png = render(j)
            api("/agent/complete", body={"id": j["id"], "image_b64":
                base64.b64encode(png).decode()}, method="POST", timeout=120)
            log("完成 " + j["id"][:8] + f"（{len(png)} bytes）")
        except Exception as exc:
            log("失敗 " + j["id"][:8] + ": " + str(exc)[:160])
            try:
                api("/agent/complete", body={"id": j["id"], "error": str(exc)[:300]}, method="POST")
            except Exception:
                pass


if __name__ == "__main__":
    main()
