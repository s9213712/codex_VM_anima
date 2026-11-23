#!/usr/bin/env python3
"""Anima VM agent — reference implementation of the relay agent protocol.

Runs inside the Codex VM (or any Linux box) and connects outbound to the
Cloudflare relay. No inbound ports are required.

    python3 agent.py --relay https://anima.example.workers.dev \
                     --key-file /path/to/agent.key \
                     --backend comfy --comfy-url http://127.0.0.1:8188 \
                     --workflow /path/to/workflow.json

Backends
    comfy    drive a local ComfyUI (default)
    command  run any command that writes a PNG (ANIMA_OUT env var = target path)

Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HEARTBEAT_SECONDS = 10
CLAIM_BACKOFF = 2.0
HTTP_TIMEOUT = 30


# --------------------------------------------------------------------------- relay client
class Relay:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def _request(self, path: str, data=None, raw: bytes | None = None, headers=None, timeout=HTTP_TIMEOUT):
        hdrs = {"Authorization": "Bearer " + self.key, "User-Agent": "anima-agent/1.0"}
        body = None
        if raw is not None:
            body = raw
            hdrs["Content-Type"] = "application/octet-stream"
        elif data is not None:
            body = json.dumps(data).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = urllib.request.Request(self.url + path, data=body, headers=hdrs, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                payload = res.read()
                if not payload:
                    return None
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    return payload
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "ignore")
            raise RuntimeError(f"{path} -> HTTP {exc.code}: {detail}") from None

    def heartbeat(self, ready, busy, system):
        return self._request("/agent/heartbeat", {"ready": ready, "busy": busy, "system": system})

    def claim(self, ready, busy, system):
        return self._request("/agent/claim", {"ready": ready, "busy": busy, "system": system})

    def progress(self, job_id, lease, stage, step, total, elapsed, log_tail=""):
        return self._request(
            f"/agent/jobs/{job_id}/progress",
            {"stage": stage, "step": step, "elapsed_seconds": elapsed, "log_tail": log_tail},
            headers={"X-Lease-Token": lease},
        )

    def complete(self, job_id, lease, png: bytes, metadata: dict):
        return self._request(
            f"/agent/jobs/{job_id}/complete",
            raw=png,
            headers={"X-Lease-Token": lease, "X-Generation-Metadata": json.dumps(metadata)[:2000]},
        )

    def fail(self, job_id, lease, message: str):
        return self._request(f"/agent/jobs/{job_id}/fail", {"error": message[:1900]}, headers={"X-Lease-Token": lease})


# --------------------------------------------------------------------------- system metrics
def read_meminfo():
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0]) * 1024
    except Exception:
        pass
    return info


def system_snapshot(model_state="READY", lora_name=None, rss_bytes=0):
    mem = read_meminfo()
    try:
        total = shutil.disk_usage("/")
        disk = {"total_bytes": total.total, "used_bytes": total.used, "free_bytes": total.free}
    except Exception:
        disk = {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0}
    try:
        load1 = os.getloadavg()[0]
    except Exception:
        load1 = 0.0
    cores = os.cpu_count() or 1
    return {
        "sampled_at": time.time(),
        "cpu": {"visible_cores": cores, "quota_cores": cores, "quota_usage_percent": round(min(100.0, load1 / cores * 100), 2)},
        "memory": {
            "limit_bytes": mem.get("MemTotal", 0),
            "used_bytes": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
            "quota_headroom_bytes": mem.get("MemAvailable", 0),
        },
        "disk": disk,
        "model": {"state": model_state, "rss_bytes": rss_bytes, "turbo_lora": bool(lora_name), "lora_name": lora_name,
                  "guidance_scale": None, "default_steps": None},
        "api": {"uptime_seconds": int(time.time() - START_TIME), "lease_remaining_seconds": None},
    }


# --------------------------------------------------------------------------- backends
class ComfyBackend:
    """Drives a local ComfyUI instance.

    The workflow JSON is a normal ComfyUI API prompt graph; the strings
    {{prompt}}, {{negative}}, {{width}}, {{height}}, {{steps}}, {{seed}}
    are substituted wherever they appear.
    """

    def __init__(self, base_url: str, workflow_path: str, poll_seconds: float = 1.0, client_id: str | None = None):
        self.base = base_url.rstrip("/")
        self.workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
        self.poll = poll_seconds
        self.client_id = client_id or str(uuid.uuid4())

    def _subst(self, value, job):
        if isinstance(value, str):
            for token, key in (("{{prompt}}", "prompt"), ("{{negative}}", "negative_prompt"),
                               ("{{width}}", "width"), ("{{height}}", "height"),
                               ("{{steps}}", "steps"), ("{{seed}}", "seed")):
                if token in value:
                    value = value.replace(token, str(job[key]))
            return value
        if isinstance(value, list):
            return [self._subst(v, job) for v in value]
        if isinstance(value, dict):
            return {k: self._subst(v, job) for k, v in value.items()}
        return value

    def _post(self, path, payload):
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as res:
            return json.loads(res.read() or b"{}")

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=HTTP_TIMEOUT) as res:
            return json.loads(res.read() or b"{}")

    def generate(self, job, on_progress) -> bytes:
        graph = self._subst(self.workflow, job)
        started = time.time()
        on_progress("ENCODING", 0, job["steps"], time.time() - started)
        prompt_id = self._post("/prompt", {"prompt": graph, "client_id": self.client_id})["prompt_id"]

        last_step, last_report = 0, 0.0
        while True:
            hist = self._get(f"/history/{prompt_id}")
            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("completed") or entry.get("outputs"):
                    on_progress("DECODING", job["steps"], job["steps"], time.time() - started)
                    images = []
                    for node in entry.get("outputs", {}).values():
                        images.extend(node.get("images", []))
                    if not images:
                        raise RuntimeError("ComfyUI finished without an image output")
                    img = images[0]
                    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
                    with urllib.request.urlopen(self.base + "/view?" + q, timeout=HTTP_TIMEOUT) as res:
                        return res.read()
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI reported an error: " + json.dumps(status)[:400])

            try:
                q = self._get("/queue")
                running = [item for item in q.get("queue_running", []) if item and item[1] == prompt_id]
                if running and time.time() - last_report > 1.0:
                    last_step = min(job["steps"] - 1, max(last_step, 0))
                    on_progress("DENOISING", last_step, job["steps"], time.time() - started)
                    last_report = time.time()
            except Exception:
                pass

            if time.time() - started > 1800:
                raise TimeoutError("ComfyUI job exceeded 30 minutes")
            time.sleep(self.poll)


class CommandBackend:
    """Runs an arbitrary command; it must write a PNG to $ANIMA_OUT."""

    def __init__(self, template: str):
        self.template = template

    def generate(self, job, on_progress) -> bytes:
        out = Path("/tmp/anima-out-%s.png" % uuid.uuid4().hex[:8])
        env = dict(os.environ, ANIMA_PROMPT=job["prompt"], ANIMA_NEGATIVE=job["negative_prompt"],
                   ANIMA_WIDTH=str(job["width"]), ANIMA_HEIGHT=str(job["height"]),
                   ANIMA_STEPS=str(job["steps"]), ANIMA_SEED=str(job["seed"]), ANIMA_OUT=str(out))
        started = time.time()
        on_progress("ENCODING", 0, job["steps"], 0.0)
        proc = subprocess.run(self.template, shell=True, env=env, capture_output=True, text=True, timeout=1800)
        on_progress("SAVING", job["steps"], job["steps"], time.time() - started)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "command failed")[-1500:])
        if not out.exists():
            raise RuntimeError("command did not create $ANIMA_OUT")
        return out.read_bytes()


# --------------------------------------------------------------------------- worker loop
START_TIME = time.time()


def main():
    ap = argparse.ArgumentParser(description="Anima VM agent (reference implementation)")
    ap.add_argument("--relay", required=True, help="https://<worker>.workers.dev")
    ap.add_argument("--key-file", required=True, help="path to agent.key")
    ap.add_argument("--backend", choices=["comfy", "command"], default="comfy")
    ap.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    ap.add_argument("--workflow", help="ComfyUI API workflow JSON (required for --backend comfy)")
    ap.add_argument("--command", help="shell command writing $ANIMA_OUT (required for --backend command)")
    ap.add_argument("--model-name", default="Anima")
    ap.add_argument("--lora", default=None, help="lora name reported to the UI (optional)")
    ap.add_argument("--once", action="store_true", help="claim at most one job then exit (debug)")
    args = ap.parse_args()

    key = Path(args.key_file).read_text(encoding="utf-8").strip()
    if len(key) < 32:
        raise SystemExit("agent.key looks invalid")
    relay = Relay(args.relay, key)

    if args.backend == "comfy":
        if not args.workflow:
            raise SystemExit("--workflow is required for the comfy backend")
        backend = ComfyBackend(args.comfy_url, args.workflow)
    else:
        if not args.command:
            raise SystemExit("--command is required for the command backend")
        backend = CommandBackend(args.command)

    state = {"ready": True, "busy": False, "model": "READY"}

    def hb_loop():
        while True:
            try:
                relay.heartbeat(state["ready"], state["busy"], system_snapshot(state["model"], args.lora))
            except Exception as exc:
                print(f"[heartbeat] {exc}", flush=True)
            time.sleep(HEARTBEAT_SECONDS)

    threading.Thread(target=hb_loop, daemon=True).start()
    print(f"[agent] connected to {args.relay} backend={args.backend} host={socket.gethostname()} {platform.platform()}", flush=True)

    while True:
        try:
            claim = relay.claim(state["ready"], state["busy"], system_snapshot(state["model"], args.lora))
        except Exception as exc:
            print(f"[claim] {exc}", flush=True)
            time.sleep(CLAIM_BACKOFF)
            continue

        job = (claim or {}).get("job")
        if not job:
            time.sleep(CLAIM_BACKOFF)
            continue

        job_id, lease, request = job["id"], job["lease"], job["request"]
        print(f"[job] {job_id} {request['width']}x{request['height']} steps={request['steps']}", flush=True)
        state.update(busy=True, model="RUNNING")

        def on_progress(stage, step, total, elapsed, log_tail=""):
            try:
                relay.progress(job_id, lease, stage, step, total, elapsed, log_tail)
            except Exception as exc:
                print(f"[progress] {exc}", flush=True)

        job_started = time.time()
        try:
            png = backend.generate(request, on_progress)
            meta = {"engine": args.backend, "model": args.model_name,
                    "host": socket.gethostname(), "duration_seconds": round(time.time() - job_started, 3)}
            relay.complete(job_id, lease, png, meta)
            print(f"[job] {job_id} done ({len(png)} bytes)", flush=True)
        except Exception as exc:
            print(f"[job] {job_id} failed: {exc}", flush=True)
            try:
                relay.fail(job_id, lease, str(exc))
            except Exception as inner:
                print(f"[fail] {inner}", flush=True)
        finally:
            state.update(busy=False, model="READY")
            if args.once:
                return


if __name__ == "__main__":
    main()
