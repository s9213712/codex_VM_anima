#!/usr/bin/env python3
"""ComfyUI fallback bridge — exposes the relay's fallback contract.

    POST /generate   Authorization: Bearer <BRIDGE_TOKEN>
    {"prompt":..., "negative_prompt":..., "width":..., "height":..., "steps":..., "seed":...}
    -> image/png

    GET /healthz     {"ok":true,"comfy":"up|down"}

Runs next to a ComfyUI instance (default http://127.0.0.1:8188) and is meant to be
published through a tunnel (Cloudflare Tunnel / ngrok) so the Worker can reach it.

    BRIDGE_TOKEN=... COMFY_URL=http://127.0.0.1:8188 \
    WORKFLOW=/opt/anima/workflow.json python3 comfy_bridge.py --port 8899

Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 32 * 1024
MAX_IMAGE = 2 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class Comfy:
    def __init__(self, base: str, workflow_path: str):
        self.base = base.rstrip("/")
        self.workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
        self.client_id = str(uuid.uuid4())

    def _fill(self, node, job):
        if isinstance(node, str):
            for token, key in (("{{prompt}}", "prompt"), ("{{negative}}", "negative_prompt"),
                               ("{{width}}", "width"), ("{{height}}", "height"),
                               ("{{steps}}", "steps"), ("{{seed}}", "seed")):
                if token in node:
                    node = node.replace(token, str(job[key]))
            return node
        if isinstance(node, list):
            return [self._fill(v, job) for v in node]
        if isinstance(node, dict):
            return {k: self._fill(v, job) for k, v in node.items()}
        return node

    def _json(self, path, payload=None):
        if payload is None:
            with urllib.request.urlopen(self.base + path, timeout=30) as res:
                return json.loads(res.read() or b"{}")
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read() or b"{}")

    def up(self) -> bool:
        try:
            self._json("/system_stats")
            return True
        except Exception:
            return False

    @staticmethod
    def _two_pass(graph: dict, width: int, height: int) -> dict:
        # 生成小圖後 lanczos 放大到目標（3050 4GB 友善）
        small_w, small_h = max(320, width // 2), max(320, height // 2)
        for node in graph.values():
            if node.get("class_type") == "EmptyLatentImage":
                node["inputs"]["width"], node["inputs"]["height"] = small_w, small_h
        decode = next((nid for nid, n in graph.items() if n.get("class_type") == "VAEDecode"), None)
        save = next((nid for nid, n in graph.items() if n.get("class_type") == "SaveImage"), None)
        if not (decode and save):
            return graph
        graph["scale_up"] = {"class_type": "ImageScale",
                             "inputs": {"upscale_method": "lanczos", "width": width, "height": height,
                                        "crop": "disabled", "image": [decode, 0]}}
        graph[save]["inputs"]["images"] = ["scale_up", 0]
        return graph

    def generate(self, job: dict) -> bytes:
        graph = self._fill(self.workflow, job)
        # 模型選擇：主模型 JANKU v777 為預設，可用 model 覆蓋
        model = (job.get("model") or "").strip()
        if model:
            for node in graph.values():
                if node.get("class_type") == "CheckpointLoaderSimple":
                    node["inputs"]["ckpt_name"] = model
        # LoRA：turbo 走 anima-turbo-lora-v0.2；也可指定其他 lora 名稱
        turbo = bool(job.get("turbo"))
        lora = (job.get("lora") or "").strip() or ("anima-turbo-lora-v0.2.safetensors" if turbo else "")
        if lora:
            clip_skip = {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": -2}}
            loader = {"class_type": "LoraLoader",
                      "inputs": {"lora_name": lora, "strength_model": 1.0, "strength_clip": 1.0}}
            for nid, node in list(graph.items()):
                inp = node.get("inputs", {})
                if node.get("class_type") == "KSampler":
                    if "model" in inp and isinstance(inp["model"], list):
                        loader["inputs"]["model"] = inp["model"]
                        inp["model"] = ["lora_dyn", 0]
                    if "positive" in inp and isinstance(inp["positive"], list):
                        clip_skip["inputs"]["clip"] = ["lora_dyn", 1]
                        inp["positive"] = ["clip_skip_dyn", 0]
                    if "negative" in inp and isinstance(inp["negative"], list):
                        inp["negative"] = ["clip_skip_dyn", 1]
            graph["lora_dyn"] = loader
            graph["clip_skip_dyn"] = clip_skip
        # 步數：turbo 8 步，非 turbo 30 步
        for node in graph.values():
            if node.get("class_type") == "KSampler":
                node["inputs"]["steps"] = 8 if turbo else 30
        try:
            graph = self._two_pass(graph, int(job.get("width") or 512), int(job.get("height") or 512))
        except Exception:
            pass
        prompt_id = self._json("/prompt", {"prompt": graph, "client_id": self.client_id})["prompt_id"]
        deadline = time.time() + 900
        while time.time() < deadline:
            hist = self._json(f"/history/{prompt_id}")
            entry = hist.get(prompt_id)
            if entry:
                images = []
                for out in entry.get("outputs", {}).values():
                    images.extend(out.get("images", []))
                if not images:
                    raise RuntimeError("ComfyUI returned no image")
                img = images[0]
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                with urllib.request.urlopen(self.base + "/view?" + q, timeout=60) as res:
                    return res.read()
            time.sleep(1.0)
        raise TimeoutError("ComfyUI job exceeded 15 minutes")



DOWNLOADS: dict[str, dict] = {}   # name -> {status, kind, got, total, error}


def _models_root(kind: str) -> pathlib.Path:
    """ComfyUI models 對應資料夾（找得到就回實際路徑）。"""
    env = os.environ.get("COMFY_MODELS_ROOT")
    cands = []
    if env:
        cands.append(pathlib.Path(env))
    cands += [pathlib.Path("D:/ComfyUI_windows_portable/ComfyUI/models"),
              pathlib.Path.home() / "ComfyUI/ComfyUI/models"]
    root = next((c for c in cands if c.is_dir()), None)
    if root is None:
        raise RuntimeError("找不到 ComfyUI models 資料夾，請設 COMFY_MODELS_ROOT")
    sub = {"checkpoint": "checkpoints", "lora": "loras", "diffusion": "diffusion_models/community"}[kind]
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download(url: str, kind: str, name: str) -> None:
    import time as _t
    entry = DOWNLOADS.setdefault(name, {"status": "downloading", "kind": kind, "got": 0, "total": 0})
    try:
        if "civitai.com" in url and "token=" not in url:
            tok = os.environ.get("CIVITAI_TOKEN", "")
            if tok:
                url += ("&" if "?" in url else "?") + "token=" + tok
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as res:
            total = int(res.headers.get("Content-Length") or 0)
            entry["total"] = total
            dest = _models_root(kind) / name
            got = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = res.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    entry["got"] = got
        entry["status"] = "done"
        log(f"模型下載完成 {name}（{got/1e6:.0f} MB）")
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)[:200]
        log("模型下載失敗 " + name + ": " + str(exc)[:120])


def start_download(url: str, kind: str, name: str) -> dict:
    import threading
    if not re.match(r"^https://(huggingface\.co|hf-mirror\.com|civitai\.com)/", url):
        return {"ok": False, "error": "只接受 huggingface.co 或 civitai.com 網址"}
    if name in DOWNLOADS and DOWNLOADS[name]["status"] == "downloading":
        return {"ok": False, "error": "同名模型下載中"}
    if not name.endswith(".safetensors"):
        name += ".safetensors"
    DOWNLOADS[name] = {"status": "downloading", "kind": kind, "got": 0, "total": 0}
    threading.Thread(target=_download, args=(url, kind, name), daemon=True).start()
    return {"ok": True, "name": name}


def download_status() -> list:
    return [{"name": k, **v} for k, v in DOWNLOADS.items()]


COMFY: Comfy | None = None
TOKEN = os.environ.get("BRIDGE_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    server_version = "anima-bridge/1.0"

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if self.path.startswith("/models/download") and "name=" in self.path:
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            name = q.get("name", [""])[0]
            return self._json(200, {"status": DOWNLOADS.get(name, {"status": "unknown"})})
        if self.path == "/models":
            models = loras = []
            try:
                info = COMFY._json("/object_info", None) if COMFY else {}
                models = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})\
                    .get("ckpt_name", [[], {}])[0]
                loras = info.get("LoraLoader", {}).get("input", {}).get("required", {})\
                    .get("lora_name", [[], {}])[0]
            except Exception:
                pass
            dm = []
            try:
                info2 = COMFY._json("/object_info", None) if COMFY else {}
                dm = info2.get("UNETLoader", {}).get("input", {}).get("required", {})\
                    .get("unet_name", [[], {}])[0]
            except Exception:
                pass
            return self._json(200, {"checkpoints": models, "loras": loras,
                                    "diffusion_models": dm, "downloads": download_status()})
        if self.path == "/healthz":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            mem = None
            try:
                st = _MS(ctypes.sizeof(_MS))
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
                mem = {"used": round((st.ullTotalPhys - st.ullAvailPhys) / 1e9, 1),
                       "total": round(st.ullTotalPhys / 1e9, 1), "percent": st.dwMemoryLoad}
            except Exception:
                pass
            return self._json(200, {"ok": True, "comfy": "up" if COMFY and COMFY.up() else "down",
                                    "system": {"memory": mem,
                                               "gpu": "RTX 3050 Laptop (fallback host)"}})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/models/download":
            import json as _json
            from urllib.parse import parse_qs, urlparse
            ln = int(self.headers.get("Content-Length") or 0)
            body = _json.loads(self.rfile.read(ln) or b"{}")
            url = (body.get("url") or "").split("?download=true")[0]
            kind = body.get("kind") or ("lora" if "/lora" in url else "checkpoint")
            name = body.get("name") or url.rstrip("/").split("/")[-1].split("?")[0]
            if "civitai.com/api/download" in url:
                name = (body.get("name") or "civitai_" + url.rstrip("/").split("/")[-1]) + ".safetensors"
            return self._json(200, start_download(url, kind, name))
        if self.path != "/generate":
            return self._json(404, {"error": "not found"})
        if not TOKEN or self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self._json(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._json(413, {"error": "body size"})
            job = json.loads(self.rfile.read(length))
            png = COMFY.generate(job)
            if not png.startswith(PNG_MAGIC):
                return self._json(502, {"error": "upstream did not return PNG"})
            if len(png) > MAX_IMAGE:
                return self._json(502, {"error": "image exceeds 2 MB limit"})
            return self._send(200, png, "image/png")
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": str(exc)[:500]})

    def log_message(self, fmt, *args):
        print("[bridge] " + fmt % args, flush=True)


def main():
    global COMFY
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    ap.add_argument("--workflow", default=os.environ.get("WORKFLOW"))
    args = ap.parse_args()

    if not TOKEN:
        raise SystemExit("set BRIDGE_TOKEN (long random string) before starting")
    if not args.workflow:
        raise SystemExit("set WORKFLOW to a ComfyUI API workflow JSON")

    COMFY = Comfy(args.comfy_url, args.workflow)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[bridge] listening on {args.host}:{args.port} -> {args.comfy_url}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
