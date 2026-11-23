#!/usr/bin/env node
// Anima relay health check — prints status only, never the key.
// Usage: node scripts/health.mjs [--json]
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const priv = join(root, ".private");
const asJson = process.argv.includes("--json");

function readText(p) {
  return readFileSync(p, "utf8").trim();
}

let url, key;
try {
  url = readText(join(priv, "relay-url.txt")).replace(/\/+$/, "");
  key = readText(join(priv, "client.key"));
} catch (e) {
  console.error(`FAIL cannot read .private/*: ${e.message}`);
  process.exit(2);
}

if (!/^https:\/\//.test(url)) {
  console.error(`FAIL relay URL must be HTTPS (got ${url.replace(/\/\/.*/, "//…")})`);
  process.exit(2);
}

const started = Date.now();
let body, status;
try {
  const res = await fetch(`${url}/healthz`, {
    headers: { Authorization: `Bearer ${key}`, "User-Agent": "anima-health/1.0" },
    signal: AbortSignal.timeout(15000),
  });
  status = res.status;
  body = await res.json();
} catch (e) {
  console.error(`FAIL request error: ${e.message}`);
  process.exit(3);
}

const latency = Date.now() - started;
const agentAge = body?.agent?.observed_at ? Math.round((Date.now() - body.agent.observed_at) / 1000) : null;
const model = body?.agent?.system?.model?.state ?? "UNKNOWN";
const cpu = body?.agent?.system?.cpu;
const mem = body?.agent?.system?.memory;

const ok = status === 200 && body?.relay === "READY" && body?.agent_recent === true;

if (asJson) {
  console.log(JSON.stringify({ ok, status, latency_ms: latency, relay: body?.relay ?? null, agent_recent: body?.agent_recent ?? null, agent_age_s: agentAge, ready: body?.agent?.ready ?? null, busy: body?.agent?.busy ?? null, model_state: model, cpu_usage_percent: cpu?.quota_usage_percent ?? null, mem_used_gb: mem?.used_bytes ? +(mem.used_bytes / 1e9).toFixed(2) : null }, null, 1));
} else {
  console.log(`${ok ? "PASS" : "FAIL"} relay=${body?.relay ?? "?"} http=${status} latency=${latency}ms`);
  console.log(`     agent_recent=${body?.agent_recent} age=${agentAge ?? "?"}s ready=${body?.agent?.ready} busy=${body?.agent?.busy} model=${model}`);
  if (cpu) console.log(`     cpu=${cpu.quota_usage_percent ?? "?"}%  mem=${mem?.used_bytes ? (mem.used_bytes / 1e9).toFixed(1) + "/" + (mem.limit_bytes / 1e9).toFixed(0) + " GB" : "?"}`);
}

process.exit(ok ? 0 : 1);
