#!/usr/bin/env node
// 阻擋金鑰進 Git：檢查已追蹤檔案與工作區中未被忽略的敏感檔。
// 用法：node scripts/check-secrets.mjs
import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { chdir } from "node:process";

// 不論從哪個子目錄執行，都切到 repo 根目錄再檢查
const root = execSync("git rev-parse --show-toplevel", { encoding: "utf8" }).trim();
chdir(root);

const FORBIDDEN_TRACKED = [
  /(^|\/)\.private\//,
  /\.key$/,
  /relay-keys\.json$/,
  /vm-pairing\.encrypted\.json$/,
  /(^|\/)\.wrangler\//,
];

const SENSITIVE_PATHS = [
  "anima-cloudflare/.private/client.key",
  "anima-cloudflare/.private/agent.key",
  "anima-cloudflare/.private/relay-keys.json",
  "anima-cloudflare/vm-pairing/vm-pairing.encrypted.json",
];

let failed = false;

const tracked = execSync("git ls-files", { encoding: "utf8" }).split("\n").filter(Boolean);
for (const file of tracked) {
  if (FORBIDDEN_TRACKED.some((re) => re.test(file))) {
    console.error(`FAIL tracked secret: ${file}`);
    failed = true;
  }
}

for (const path of SENSITIVE_PATHS) {
  if (!existsSync(path)) continue;
  try {
    execSync(`git check-ignore -q "${path}"`);
  } catch {
    console.error(`FAIL not ignored: ${path}`);
    failed = true;
  }
}

if (failed) {
  console.error("\n失敗：請把上述檔案加入 .gitignore 並 git rm --cached");
  process.exit(1);
}
console.log(`PASS 沒有敏感檔被追蹤（檢查 ${tracked.length} 個檔案）`);
