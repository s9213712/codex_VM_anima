#!/usr/bin/env python3
"""通用 diffusers 生圖後端 v2（不依賴 ComfyUI）。

任何「能跑 Python、能下載模型」的主機都能當 Anima 生圖節點。

端點：
  GET  /healthz
  GET  /models                → 主模型/LoRA/下載狀態
  POST /models/download       {url, name?, kind?, family?}   HF／civitai 直鏈現場下載
  POST /generate              六欄位 + model/lora/turbo → PNG bytes

模型解析（registry.json 可擴充新家族，不用改程式）：
  1. registry.json 有該名稱 → 照登錄的 family 走
  2. .safetensors 單檔 → sdxl-single（from_single_file）
  3. HF repo id → DiffusionPipeline.from_pretrained（自動偵測架構；
     Anima 系（circlestone）用 anima family：modular 新格式 + trust_remote_code）
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("FALLBACK_TOKEN", "")
MODELS_DIR = pathlib.Path(os.environ.get("MODELS_DIR", os.path.expanduser("~/anima-models")))
TURBO_LORA = os.environ.get("TURBO_LORA", "Anima/turbo-v0.2")
REGISTRY = MODELS_DIR / "registry.json"
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "JANKUTrainedChenkinNoobai_v777.safetensors")

DOWNLOADS: dict[str, dict] = {}
_pipes: dict[str, object] = {}
_lock = threading.Lock()


def log(m: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + m, flush=True)


def registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_registry(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def local_models(kind: str) -> list[str]:
    d = MODELS_DIR / ("checkpoints" if kind == "checkpoint" else "loras")
    return sorted(f.name for f in d.glob("*.safetensors")) if d.is_dir() else []


def resolve_source(model: str, kind: str) -> tuple[str, str]:
    """回 (source, family)。registry 優先，否則啟發式。"""
    reg = registry().get(model)
    if reg:
        return reg.get("source", model), reg.get("family", "auto")
    local = MODELS_DIR / ("checkpoints" if kind == "checkpoint" else "loras") / model
    if local.exists():
        return str(local), "auto"
    return model, "auto"


def guess_family(source: str) -> str:
    low = source.lower()
    if "circlestone" in low or "anima-" in low:
        return "anima"
    if low.endswith(".safetensors") or low.endswith(".ckpt"):
        return "sdxl-single"
    return "generic"


_PIPE_CACHE = {}


def load_pipe(model: str, family_override: str = ""):
    import torch
    from diffusers import DiffusionPipeline, StableDiffusionXLPipeline
    src, family = resolve_source(model, "checkpoint")
    if family == "auto":
        family = guess_family(src)
    if family_override:
        family = family_override
    key = (str(src), family)
    if key in _PIPE_CACHE:
        log("快取命中 " + str(src))
        return _PIPE_CACHE[key]
    log(f"載入 {src}（family={family}）")
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    if family == "sdxl-single":
        pipe = StableDiffusionXLPipeline.from_single_file(src, torch_dtype=dtype)
    elif family == "anima":
        pipe = DiffusionPipeline.from_pretrained(src, torch_dtype=dtype, trust_remote_code=True)
    else:
        pipe = DiffusionPipeline.from_pretrained(src, torch_dtype=dtype)
    if torch.cuda.is_available():
        try:
            pipe.enable_model_cpu_offload()   # 4GB 卡放不下整支 SDXL，讓 diffusers 分層搬運
        except Exception:
            pipe.to("cuda")
        pipe.enable_attention_slicing()
    else:
        pipe.enable_attention_slicing()
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pass
    with _lock:
        _pipes.clear()
        _PIPE_CACHE.clear()
        _PIPE_CACHE[key] = pipe
        _pipes[model] = pipe
    return pipe


def render(job: dict) -> bytes:
    import torch
    model = (job.get("model") or DEFAULT_MODEL).strip()
    pipe = load_pipe(model, (job.get("base_family") or "").strip())
    turbo = bool(job.get("turbo"))
    lora = (job.get("lora") or "").strip() or (TURBO_LORA if turbo else "")
    if lora:
        lsrc, _ = resolve_source(lora, "lora")
        log("載入 LoRA " + lsrc)
        try:
            pipe.load_lora_weights(lsrc)
        except Exception as exc:
            log("LoRA 失敗（忽略）: " + str(exc)[:140])
    else:
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
    gen = torch.Generator("cpu").manual_seed(int(job.get("seed") or 0))
    img = pipe(prompt=job.get("prompt", ""),
               negative_prompt=job.get("negative_prompt", "low quality, blurry"),
               width=int(job.get("width") or 512), height=int(job.get("height") or 512),
               num_inference_steps=8 if turbo else int(job.get("steps") or 30),
               generator=gen).images[0]
    try:
        pipe.unload_lora_weights()
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _download(url: str, kind: str, name: str) -> None:
    entry = DOWNLOADS.setdefault(name, {"status": "downloading", "kind": kind, "got": 0, "total": 0})
    try:
        if "civitai.com" in url and "token=" not in url:
            tok = os.environ.get("CIVITAI_TOKEN", "")
            if tok:
                url += ("&" if "?" in url else "?") + "token=" + tok
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        dest = MODELS_DIR / ("checkpoints" if kind == "checkpoint" else "loras") / name
        got = 0
        with urllib.request.urlopen(req, timeout=60) as res, open(dest, "wb") as f:
            entry["total"] = int(res.headers.get("Content-Length") or 0)
            while True:
                chunk = res.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                entry["got"] = got
        entry["status"] = "done"
        log(f"下載完成 {name}（{got/1e6:.0f} MB）")
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)[:200]
        log("下載失敗 " + name + ": " + str(exc)[:120])


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _mem(self):
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong)] + \
                           [("p%d" % i, ctypes.c_ulonglong) for i in range(5)]
            st = MS()
            st.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return {"used": round((st.tp - st.ap) / 1e9, 1), "total": round(st.tp / 1e9, 1),
                    "percent": st.load}
        except Exception:
            return None

    def _cpu(self):
        try:
            import psutil
            return psutil.cpu_percent(interval=0.15)
        except Exception:
            return None

    def _hist(self, cpu, memp):
        try:
            import time as _t
            if not hasattr(self.server, "_hist"):
                self.server._hist = []
            h = self.server._hist
            if cpu is not None or memp is not None:
                h.append({"t": int(_t.time()), "cpu": cpu, "mem": memp})
                del h[:-60]
            return h
        except Exception:
            return []

    def do_GET(self):
        if self.path.startswith("/preload"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            model = (q.get("model") or [DEFAULT_MODEL])[0]
            fam = (q.get("family") or [""])[0]
            try:
                load_pipe(model, fam)
                return self._json(200, {"ok": True, "model": model})
            except Exception as exc:
                return self._json(500, {"ok": False, "error": str(exc)[:200]})
        if self.path == "/healthz":
            cpu = self._cpu()
            mem = self._mem()
            return self._json(200, {"ok": True, "engine": "diffusers-universal",
                                    "system": {"memory": mem,
                                               "cpu": {"usage_percent": cpu},
                                               "history": self._hist(cpu, mem["percent"] if mem else None)}})
        if self.path == "/models":
            return self._json(200, {
                "checkpoints": sorted(set(local_models("checkpoint")) | set(registry().keys())),
                "loras": local_models("lora"),
                "registry": registry(),
                "downloads": list(DOWNLOADS.values())})
        if self.path.startswith("/models/download"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            name = q.get("name", [""])[0]
            return self._json(200, {"status": DOWNLOADS.get(name, {"status": "unknown"})})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln) or b"{}")
        if self.path == "/models/download":
            url = (body.get("url") or "").strip()
            if not re.match(r"^https://(huggingface\.co|hf-mirror\.com|civitai\.com)/", url):
                return self._json(400, {"ok": False, "error": "只接受 HF 或 civitai 網址"})
            name = (body.get("name") or url.rstrip("/").split("/")[-1].split("?")[0])
            kind = body.get("kind") or ("lora" if "lora" in url.lower() else "checkpoint")
            family = body.get("family") or "auto"
            if not name.endswith(".safetensors"):
                name += ".safetensors"
            if DOWNLOADS.get(name, {}).get("status") == "downloading":
                return self._json(409, {"ok": False, "error": "下載中"})
            reg = registry()
            reg[name] = {"source": name, "family": family}
            save_registry(reg)
            threading.Thread(target=_download, args=(url, kind, name), daemon=True).start()
            return self._json(200, {"ok": True, "name": name})
        if self.path == "/generate":
            if TOKEN and self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self._json(401, {"error": "Bearer key required"})
            try:
                png = render(body)
            except Exception as exc:
                log("generate 失敗: " + str(exc)[:200])
                return self._json(500, {"error": str(exc)[:300]})
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return
        self._json(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8899"))
    log(f"diffusers-universal backend :{port}，模型目錄 {MODELS_DIR}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
