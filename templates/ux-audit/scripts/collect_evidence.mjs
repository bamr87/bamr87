#!/usr/bin/env node
/**
 * collect_evidence.mjs — Playwright MVP for the ux-audit kit.
 *
 * Visits surfaces from ux.yml (or --url), writes:
 *   evidence/<slug>/screenshot.png
 *   evidence/<slug>/axe.json
 *   evidence/summary.json
 *
 * Requires: playwright, js-yaml, @axe-core/playwright (peer deps — install in leaf)
 *
 *   node scripts/collect_evidence.mjs
 *   node scripts/collect_evidence.mjs --base-url http://127.0.0.1:4000 --manifest ux.yml
 */
import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

function loadYaml(path) {
  try {
    const yaml = require("js-yaml");
    return yaml.load(readFileSync(path, "utf8"));
  } catch {
    // minimal fallback for the example shape when js-yaml is absent
    const text = readFileSync(path, "utf8");
    const surfaces = [];
    const re = /-\s*url:\s*["']?([^"'\n]+)["']?[\s\S]*?role:\s*["']?([^"'\n]+)/g;
    let m;
    while ((m = re.exec(text))) surfaces.push({ url: m[1], role: m[2] });
    return { surfaces, preview: {} };
  }
}

function parseArgs(argv) {
  const out = { manifest: join(root, "ux.yml"), baseUrl: null, outDir: join(root, "evidence") };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--manifest") out.manifest = resolve(argv[++i]);
    else if (argv[i] === "--base-url") out.baseUrl = argv[++i];
    else if (argv[i] === "--out") out.outDir = resolve(argv[++i]);
  }
  return out;
}

function slugify(url) {
  return url.replace(/^https?:\/\//, "").replace(/[^\w]+/g, "_").replace(/^_|_$/g, "") || "root";
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const manifestPath = existsSync(args.manifest)
    ? args.manifest
    : join(root, "ux.manifest.example.yml");
  const manifest = loadYaml(manifestPath);
  const base =
    args.baseUrl ||
    process.env.UX_BASE_URL ||
    manifest?.preview?.ready_url ||
    "http://127.0.0.1:4173";
  const surfaces = (manifest.surfaces || [{ url: "/", role: "home" }]).map((s) => ({
    ...s,
    abs: s.url.startsWith("http") ? s.url : new URL(s.url, base).toString(),
  }));

  let chromium, AxeBuilder;
  try {
    ({ chromium } = await import("playwright"));
    ({ default: AxeBuilder } = await import("@axe-core/playwright"));
  } catch (err) {
    console.error(
      "collect_evidence: install peer deps in the leaf repo: npm i -D playwright @axe-core/playwright js-yaml && npx playwright install chromium",
    );
    console.error(String(err));
    process.exit(2);
  }

  mkdirSync(args.outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const summary = [];
  const tags = manifest?.audit?.axe_tags || ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

  for (const surface of surfaces) {
    const slug = slugify(surface.url);
    const dir = join(args.outDir, slug);
    mkdirSync(dir, { recursive: true });
    const entry = { url: surface.abs, role: surface.role, slug, ok: false, violations: 0 };
    try {
      await page.goto(surface.abs, { waitUntil: "networkidle", timeout: 30000 });
      await page.screenshot({ path: join(dir, "screenshot.png"), fullPage: true });
      const axe = await new AxeBuilder({ page }).withTags(tags).analyze();
      writeFileSync(join(dir, "axe.json"), JSON.stringify(axe, null, 2));
      entry.ok = true;
      entry.violations = (axe.violations || []).length;
    } catch (err) {
      entry.error = String(err);
      writeFileSync(join(dir, "error.txt"), entry.error);
    }
    summary.push(entry);
    console.log(`${entry.ok ? "ok" : "FAIL"} ${surface.abs} violations=${entry.violations}`);
  }

  await browser.close();
  writeFileSync(join(args.outDir, "summary.json"), JSON.stringify({ base, summary }, null, 2));
  const failed = summary.filter((s) => !s.ok || s.violations > 0);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
