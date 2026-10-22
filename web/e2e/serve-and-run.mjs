// web/e2e/serve-and-run.mjs — start a static server for web/, run run.mjs, then stop.
// OWNER: web tab. Keeps the e2e self-contained (no external server needed).
// Playwright is expected on NODE_PATH (installed ad hoc; not vendored into the repo).

import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const PORT = Number(process.env.PORT || 8099);
const BASE = `http://localhost:${PORT}`;

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
  ".ico": "image/x-icon", ".map": "application/json",
};

const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, BASE).pathname);
    if (p === "/" || p.endsWith("/")) p += "index.html";
    const full = normalize(join(webRoot, p));
    if (!full.startsWith(webRoot)) { res.writeHead(403).end("no"); return; }
    const body = await readFile(full);
    res.writeHead(200, { "content-type": MIME[extname(full)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404, { "content-type": "text/plain" }).end("404");
  }
});

await new Promise((r) => server.listen(PORT, r));
console.log(`[e2e] serving ${webRoot} at ${BASE}`);

const child = spawn(process.execPath, [join(webRoot, "e2e", "run.mjs")], {
  stdio: "inherit",
  env: { ...process.env, BASE },
});

child.on("exit", (code) => {
  server.close();
  process.exit(code ?? 1);
});
