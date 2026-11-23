// 把 src/ui.html 內嵌成可被 Worker 直接 import 的 JS 模組（不依賴 Text module rules）
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const html = readFileSync(join(root, "src", "ui.html"), "utf8");
const out = `// AUTO-GENERATED from ui.html by scripts/build-ui.mjs — do not edit by hand.\nexport default ${JSON.stringify(html)};\n`;
writeFileSync(join(root, "src", "ui.generated.js"), out);
console.log(`ui.generated.js written (${html.length} chars)`);
