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
    if "circlestone" in low and "diffusers" in low:
        return "anima-official"
    if "qwen-image" in low:
        return "qwen-image"
    if "krea" in low:
        return "krea-single"
    if "moss-image" in low or "moss" in low:
        return "moss"
    if "circlestone" in low or "anima-compile" in low or "anima-" in low:
        return "anima"
    if low.endswith(".safetensors") or low.endswith(".ckpt"):
        return "sdxl-single"
    return "generic"


_PIPE_CACHE = {}

ANIMA_OFFICIAL_REPO = "circlestone-labs/Anima-Base-v1.0-Diffusers"


def _load_anima_official(src: str, dtype):
    """Anima 官方（circlestone-labs/Anima，Cosmos-Predict2-2B finetune）。
    split_files/ 的 safetensors 是 ComfyUI 鍵名（net.* / 無前綴 VAE），不能直接餵
    diffusers；改用官方同步發布的 diffusers 格式 repo（ModularPipeline，
    diffusers >= 0.43 原生支援），內含已轉換的 transformer/VAE/Qwen3-0.6B/
    AnimaTextConditioner/scheduler/t5_tokenizer。"""
    from diffusers import ModularPipeline
    import torch
    # split_files 原始 repo（circlestone-labs/Anima）沒有 modular_model_index.json，
    # 一律導向官方同步發布的 diffusers 格式 repo
    repo = src if "diffusers" in src.lower() else ANIMA_OFFICIAL_REPO
    if dtype == torch.float16 and torch.cuda.is_available() and torch.cuda.is_bf16_supported():
        dtype = torch.bfloat16   # fp16 會溢位輸出全黑（實測），Anima 官方建議 bf16
    pipe = ModularPipeline.from_pretrained(repo)
    pipe.load_components(dtype=dtype)
    return pipe


def _load_qwen_image(src: str, dtype):
    """Qwen-Image-2.1（20B）：bitsandbytes NF4 量化，T4 16GB / 本機 4GB 才放得下。"""
    import torch
    from diffusers import DiffusionPipeline
    kwargs = {"torch_dtype": dtype}
    try:
        from diffusers import PipelineQuantizationConfig
        kwargs["quantization_config"] = PipelineQuantizationConfig(
            quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4",
                          "bnb_4bit_compute_dtype": torch.float16})
    except Exception:
        from diffusers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16)
    return DiffusionPipeline.from_pretrained(src, **kwargs)


def _load_moss(src: str, dtype):
    """MOSS-Image：pipeline 類別不在 diffusers 套件內，從 repo 根目錄的
    pipeline_moss_image.py 動態載入 MOSSImagePipeline。權重 fp16 約 35GB，
    Colab T4（15GB VRAM/12GB RAM）必須 NF4 量化；小 VRAM 主機用 fp16+offload。"""
    import importlib.util, pathlib
    import torch
    from diffusers import BitsAndBytesConfig
    from huggingface_hub import hf_hub_download
    p = pathlib.Path(hf_hub_download(src, "pipeline_moss_image.py"))
    spec = importlib.util.spec_from_file_location("moss_image_repo_code", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kwargs = {"torch_dtype": dtype, "trust_remote_code": True}
    if torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory > 14e9:
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    return mod.MOSSImagePipeline.from_pretrained(src, **kwargs)


def _load_krea_single(src: str, dtype):
    """Krea 2（FLUX.2 系社群 finetune，ComfyUI 單檔）。優先 Flux2Pipeline.
    from_single_file，失敗退 FluxPipeline.from_single_file，兩者錯誤都保留。"""
    from diffusers import Flux2Pipeline, FluxPipeline
    errs = []
    for cls in (Flux2Pipeline, FluxPipeline):
        try:
            return cls.from_single_file(src, torch_dtype=dtype)
        except Exception as exc:
            errs.append(f"{cls.__name__}: {str(exc)[:220]}")
    raise RuntimeError("Krea 單檔載入失敗（依序嘗試 Flux2/Flux from_single_file）→ " + " | ".join(errs))


def _sdxl_single_source(src: str) -> str:
    """sdxl-single 來源：repo id → hf_hub_download 出本地檔。"""
    if src.startswith("http") or os.path.exists(src):
        return src
    from huggingface_hub import hf_hub_download, list_repo_files
    if src.endswith(".safetensors"):
        repo_id, fname = src.rsplit("/", 1)[0], src.rsplit("/", 1)[1]
    else:
        files = [f for f in list_repo_files(src) if f.endswith(".safetensors")]
        if not files:
            raise RuntimeError(f"repo {src} 內沒有 .safetensors")
        repo_id, fname = src, sorted(files, key=len)[0]
    return hf_hub_download(repo_id, fname)


def _anima_compat(pipe) -> None:
    for name, fn in (("enable_model_cpu_offload", lambda: pipe.enable_model_cpu_offload()),
                     ("enable_attention_slicing", lambda: pipe.enable_attention_slicing())):
        try:
            getattr(pipe, name, None)()
        except Exception as exc:
            log(f"{name} 跳過: {str(exc)[:80]}")


def load_pipe(model: str, family_override: str = ""):
    import torch
    from diffusers import DiffusionPipeline, StableDiffusionXLPipeline
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    src, family = resolve_source(model, "checkpoint")
    if family == "auto":
        family = guess_family(src)
    if family_override:
        family = family_override
    key = (str(src), family, str(dtype))
    if key in _PIPE_CACHE:
        log("快取命中 " + str(src))
        return _PIPE_CACHE[key]
    log(f"載入 {src}（family={family}）")
    try:
        if family == "sdxl-single":
            pipe = StableDiffusionXLPipeline.from_single_file(_sdxl_single_source(src), torch_dtype=dtype)
        elif family == "anima":
            pipe = DiffusionPipeline.from_pretrained(src, torch_dtype=dtype, trust_remote_code=True)
        elif family == "anima-official":
            pipe = _load_anima_official(src, dtype)
        elif family == "qwen-image":
            pipe = _load_qwen_image(src, dtype)
        elif family == "krea-single":
            pipe = _load_krea_single(src, dtype)
        elif family == "moss":
            pipe = _load_moss(src, dtype)
        else:
            pipe = DiffusionPipeline.from_pretrained(src, torch_dtype=dtype)
    except Exception as exc:
        msg = str(exc)
        if "404" in msg:
            raise RuntimeError(f"模型載入失敗：HF 上找不到此 repo 或其結構不支援 diffusers 標準載入（404）：{src}")
        if "401" in msg or "403" in msg:
            raise RuntimeError(f"模型載入失敗：此 repo 需要在 HuggingFace 網頁登入並同意授權條款後才能下載（401/403）：{src}")
        raise
    if family == "anima-official":
        pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    elif family == "qwen-image" and torch.cuda.is_available():
        pipe.enable_sequential_cpu_offload()   # NF4 20B：逐層搬運，慢但放得下
    elif torch.cuda.is_available():
        try:
            pipe.to("cuda")
        except torch.cuda.OutOfMemoryError:
            try:
                pipe.enable_model_cpu_offload()   # VRAM 放不下才分層搬運
            except Exception:
                pipe.enable_sequential_cpu_offload()
    else:
        pipe.enable_attention_slicing()
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
            import psutil
            vm = psutil.virtual_memory()
            return {"used": round(vm.used / 1e9, 1), "total": round(vm.total / 1e9, 1),
                    "percent": vm.percent}
        except Exception:
            pass
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

    def _gpu(self):
        try:
            import pynvml
            if not getattr(self.server, "_nvml", None):
                pynvml.nvmlInit()
                self.server._nvml = pynvml.nvmlDeviceGetHandleByIndex(0)
            h = self.server._nvml
            u = pynvml.nvmlDeviceGetUtilizationRates(h)
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            return {"util_percent": u.gpu, "vram_used": round(m.used / 1e9, 1),
                    "vram_total": round(m.total / 1e9, 1)}
        except Exception:
            return None

    def _hist(self, cpu, memp, gpu=None, vram=None):
        try:
            import time as _t
            if not hasattr(self.server, "_hist"):
                self.server._hist = []
            h = self.server._hist
            if cpu is not None or memp is not None:
                h.append({"t": int(_t.time()), "cpu": cpu, "mem": memp,
                          "gpu": gpu, "vram": vram})
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
            gpu = self._gpu()
            return self._json(200, {"ok": True, "engine": "diffusers-universal",
                                    "system": {"memory": mem, "gpu": gpu,
                                               "cpu": {"usage_percent": cpu},
                                               "history": self._hist(cpu, mem["percent"] if mem else None,
                                                                     gpu["util_percent"] if gpu else None,
                                                                     gpu["vram_used"] if gpu else None)}})
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
    (MODELS_DIR / "checkpoints").mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / "loras").mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        save_registry({})
    log(f"diffusers-universal backend :{port}，模型目錄 {MODELS_DIR}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
