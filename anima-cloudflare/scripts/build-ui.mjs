// 把 src/ui.html 內嵌成可被 Worker 直接 import 的 JS 模組（不依賴 Text module rules）
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
// 正規化換行：Windows(CRLF) 與 Linux(LF) 必須產生相同輸出，CI 才能比對漂移
const LF = String.fromCharCode(10);
const CR = String.fromCharCode(13);
const raw = readFileSync(join(root, "src", "ui.html"), "utf8");
const html = raw.split(CR + LF).join(LF).split(CR).join(LF);
const HEADER = "// AUTO-GENERATED from ui.html by scripts/build-ui.mjs - do not edit by hand." + LF;
const out = HEADER + "export default " + JSON.stringify(html) + ";" + LF;
writeFileSync(join(root, "src", "ui.generated.js"), out);
console.log("ui.generated.js written (" + html.length + " chars)");
