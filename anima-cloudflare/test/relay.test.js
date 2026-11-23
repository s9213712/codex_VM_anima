import test from "node:test";
import assert from "node:assert/strict";
import { authenticate, bytes, validJob, safeMetrics, publicJob, agentGate, fallbackDecision, RETENTION_MS, AGENT_SOFT_MS, AGENT_HARD_MS, LEASE_MS, PENDING_MAX_MS } from "../src/logic.js";

const GOOD = { prompt: "a cat", negative_prompt: "blurry", width: 512, height: 512, steps: 8, seed: 42 };
const KEY = "k".repeat(44);

test("logic module loads without the Worker runtime", () => {
  assert.equal(typeof validJob, "function");
  assert.equal(typeof agentGate, "function");
});

test("validJob accepts a complete job", () => {
  assert.deepEqual(validJob(GOOD), GOOD);
});

test("validJob applies documented defaults", () => {
  const job = validJob({ prompt: "a cat" });
  assert.equal(job.negative_prompt, "low quality, blurry");
  assert.equal(job.width, 256);
  assert.equal(job.height, 256);
  assert.equal(job.steps, 8);
  assert.equal(job.seed, 42);
});

test("validJob rejects unknown fields (relay must not become a forwarder)", () => {
  assert.throws(() => validJob({ ...GOOD, url: "http://evil" }), /Unknown job field/);
});

test("validJob rejects malformed values", () => {
  assert.throws(() => validJob([]), /Expected a job object/);
  assert.throws(() => validJob({ ...GOOD, prompt: "" }), /prompt must contain/);
  assert.throws(() => validJob({ ...GOOD, prompt: "x".repeat(1501) }), /prompt must contain/);
  assert.throws(() => validJob({ ...GOOD, width: 130 }), /Dimensions/);
  assert.throws(() => validJob({ ...GOOD, width: 1024 + 32 }), /Dimensions/);
  assert.throws(() => validJob({ ...GOOD, steps: 0 }), /steps must be/);
  assert.throws(() => validJob({ ...GOOD, steps: 21 }), /steps must be/);
  assert.throws(() => validJob({ ...GOOD, seed: -1 }), /Invalid seed/);
  assert.throws(() => validJob({ ...GOOD, negative_prompt: 5 }), /negative_prompt too long/);
});

test("safeMetrics keeps only whitelisted fields", () => {
  const out = safeMetrics({
    sampled_at: 1, evil: "x",
    cpu: { visible_cores: 5, quota_cores: 4, quota_usage_percent: 81, secret: "y" },
    memory: { limit_bytes: 16, used_bytes: 7, quota_headroom_bytes: 9 },
    disk: { total_bytes: 33, used_bytes: 8, free_bytes: 25 },
    model: { state: "READY", rss_bytes: 1, turbo_lora: true, lora_name: "L".repeat(200), guidance_scale: 1, default_steps: 8, secret: "z" },
    api: { uptime_seconds: 10, lease_remaining_seconds: 5 },
  });
  assert.equal(out.evil, undefined);
  assert.equal(out.cpu.secret, undefined);
  assert.equal(out.model.secret, undefined);
  assert.equal(out.model.lora_name.length, 80);
  assert.equal(out.capabilities.vm_create, false);
  assert.equal(out.capabilities.inference_device, "cpu");
});

test("safeMetrics whitelists model state", () => {
  assert.equal(safeMetrics({ model: { state: "WAT" } }).model.state, "UNKNOWN");
  assert.equal(safeMetrics(null), null);
});

test("publicJob only exposes image_url for SUCCEEDED", () => {
  const base = { id: "a", status: "RUNNING", request_json: JSON.stringify(GOOD), created: 1, started: 2, finished: null, error: null, metadata: null };
  assert.equal(publicJob(base).image_url, undefined);
  assert.equal(publicJob({ ...base, status: "SUCCEEDED" }).image_url, "/v1/jobs/a/image");
});

test("authenticate accepts the right key and rejects the wrong one", async () => {
  const good = new Request("https://x/healthz", { headers: { Authorization: `Bearer ${KEY}` } });
  await authenticate(good, KEY);

  const bad = new Request("https://x/healthz", { headers: { Authorization: `Bearer ${"z".repeat(44)}` } });
  await assert.rejects(authenticate(bad, KEY), (e) => e.status === 401);

  const none = new Request("https://x/healthz");
  await assert.rejects(authenticate(none, KEY), (e) => e.status === 401);

  const short = new Request("https://x/healthz", { headers: { Authorization: `Bearer ${KEY}` } });
  await assert.rejects(authenticate(short, "short"), (e) => e.status === 503);
});

test("bytes enforces the declared and streamed limits", async () => {
  const ok = await bytes(new Request("https://x/", { method: "POST", body: "abcd" }), 10);
  assert.equal(ok.length, 4);

  const declared = new Request("https://x/", { method: "POST", body: "abcd", headers: { "Content-Length": "11" } });
  await assert.rejects(bytes(declared, 10), (e) => e.status === 413);

  const streamed = new Request("https://x/", { method: "POST", body: "abcdefgh" });
  await assert.rejects(bytes(streamed, 4), (e) => e.status === 413);
});

test("agentGate implements queue/reject thresholds", () => {
  assert.equal(agentGate(0), "ok");
  assert.equal(agentGate(AGENT_SOFT_MS - 1), "ok");
  assert.equal(agentGate(AGENT_SOFT_MS + 1), "queue");
  assert.equal(agentGate(AGENT_HARD_MS - 1), "queue");
  assert.equal(agentGate(AGENT_HARD_MS + 1), "reject");
  assert.equal(agentGate(null), "reject");
  assert.equal(agentGate(undefined), "reject");
  assert.equal(agentGate(Number.NaN), "reject");
});

test("queue policy constants match the documented values", () => {
  assert.equal(LEASE_MS, 15 * 60 * 1000);
  assert.equal(PENDING_MAX_MS, 10 * 60 * 1000);
  assert.equal(AGENT_SOFT_MS, 90 * 1000);
  assert.equal(AGENT_HARD_MS, 300 * 1000);
});

test("fallbackDecision picks the fallback only when the agent is hard-offline", () => {
  assert.equal(fallbackDecision("ok", true), "primary");
  assert.equal(fallbackDecision("queue", true), "primary");
  assert.equal(fallbackDecision("reject", true), "fallback");
  assert.equal(fallbackDecision("reject", false), "reject");
});

test("publicJob exposes the backend that handled the job", () => {
  const base = { id: "a", status: "SUCCEEDED", request_json: JSON.stringify(GOOD), created: 1, started: 2, finished: 3, error: null, metadata: null };
  assert.equal(publicJob(base).backend, "primary");
  assert.equal(publicJob({ ...base, backend: "fallback" }).backend, "fallback");
});

test("retention window is 7 days", () => {
  assert.equal(RETENTION_MS, 7 * 24 * 60 * 60 * 1000);
});
