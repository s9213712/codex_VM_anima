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

    def generate(self, job: dict) -> bytes:
        graph = self._fill(self.workflow, job)
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
        if self.path == "/healthz":
            return self._json(200, {"ok": True, "comfy": "up" if COMFY and COMFY.up() else "down"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
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
