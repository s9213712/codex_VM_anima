#!/usr/bin/env node
// 重建 anima-easy-updater 的 payload 與 manifest（讓更新器永遠跟得上 repo 現況）。
//
//   node anima-easy-updater/rebuild-payload.mjs 2026.11.25-relay3
//
// 重點：文字檔一律存成 LF 再計算 SHA-256，這樣 Windows 與 Linux 的雜湊相同，
// GitHub Actions（Linux checkout）與本機（Windows）才不會互相比對失敗。
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");
const SRC = join(REPO, "anima-cloudflare");
const PAYLOAD = join(HERE, "payload");

const LF = String.fromCharCode(10);
const CR = String.fromCharCode(13);
const TEXT = /\.(js|mjs|cjs|json|jsonc|html|md|py|txt|bat|ya?ml)$/;

// client/* -> anima-client/* ；relay/* -> 專案根目錄
const CLIENT_FILES = [
  "anima_client.py",
  "cloud_task.py",
  "dashboard.html",
  "dashboard.py",
  "github_transport.py",
  "installed-version.json",
  "start-windows.bat",
];

const RELAY_FILES = [
  "src/worker.js",
  "src/logic.js",
  "src/ui.html",
  "src/ui.generated.js",
  "package.json",
  "package-lock.json",
  "wrangler.jsonc",
  "test/relay.test.js",
  "scripts/build-ui.mjs",
  "scripts/health.mjs",
  "README.txt",
  "vm/agent.py",
  "bridge/comfy_bridge.py",
];

const version = process.argv[2];
if (!version) {
  console.error("用法: node anima-easy-updater/rebuild-payload.mjs <version>");
  process.exit(1);
}

const files = {};

function normalize(buf, name) {
  if (!TEXT.test(name)) return buf;
  const text = buf.toString("utf8").split(CR + LF).join(LF).split(CR).join(LF);
  return Buffer.from(text, "utf8");
}

function stage(srcPath, payloadName) {
  const buf = normalize(readFileSync(srcPath), srcPath);
  const dst = join(PAYLOAD, payloadName);
  mkdirSync(dirname(dst), { recursive: true });
  writeFileSync(dst, buf);
  files[payloadName] = createHash("sha256").update(buf).digest("hex");
}

for (const name of CLIENT_FILES) {
  try {
    stage(join(SRC, "anima-client", name), `client/${name}`);
  } catch {
    console.warn(`skip missing client/${name}`);
  }
}

for (const name of RELAY_FILES) {
  try {
    stage(join(SRC, name), `relay/${name}`);
  } catch {
    console.warn(`skip missing relay/${name}`);
  }
}

writeFileSync(
  join(HERE, "manifest.json"),
  JSON.stringify({ version, files }, null, 2) + LF,
  "utf8",
);

// 同步 update.cjs 內的 VERSION 常數
const updater = join(HERE, "update.cjs");
const text = readFileSync(updater, "utf8").replace(/VERSION='[^']*'/, `VERSION='${version}'`);
writeFileSync(updater, text, "utf8");

console.log(`manifest.json 更新完成：${version}，${Object.keys(files).length} 個檔案`);
