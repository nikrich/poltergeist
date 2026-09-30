var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.js
var main_exports = {};
__export(main_exports, {
  activate: () => activate,
  deactivate: () => deactivate
});
module.exports = __toCommonJS(main_exports);
var import_electron = require("electron");
var import_node_fs3 = require("node:fs");
var import_node_path3 = require("node:path");

// src/main/drafts.js
var import_node_fs = require("node:fs");
var import_node_path = require("node:path");
var KEY = /^[a-z0-9-]{1,120}$/;
function draftFile(dataDir, key) {
  if (!KEY.test(String(key))) throw new Error(`invalid draft key: ${JSON.stringify(key)}`);
  return (0, import_node_path.join)(dataDir, "drafts", `${key}.json`);
}
function writeDraft(dataDir, { key, content, savedAt }) {
  const file = draftFile(dataDir, key);
  if (typeof content !== "string") throw new Error("draft content must be a string");
  (0, import_node_fs.mkdirSync)((0, import_node_path.join)(dataDir, "drafts"), { recursive: true });
  const tmp = `${file}.tmp`;
  (0, import_node_fs.writeFileSync)(tmp, JSON.stringify({ content, savedAt: String(savedAt ?? "") }));
  (0, import_node_fs.renameSync)(tmp, file);
  return true;
}
function readDraft(dataDir, key) {
  const file = draftFile(dataDir, key);
  try {
    return JSON.parse((0, import_node_fs.readFileSync)(file, "utf-8"));
  } catch (e) {
    if (e.code === "ENOENT" || e instanceof SyntaxError) return null;
    throw e;
  }
}
function clearDraft(dataDir, key) {
  (0, import_node_fs.rmSync)(draftFile(dataDir, key), { force: true });
  return true;
}

// src/main/files.js
var import_node_fs2 = require("node:fs");
var import_node_path2 = require("node:path");

// src/fountain/document.js
var DEFAULT_META = Object.freeze({
  title: "Untitled",
  credit: "Written by",
  author: "",
  source: "",
  draft_date: "",
  contact: "",
  scene_numbers: false,
  updated: ""
});
var TITLE_KEYS = [
  ["title", "Title"],
  ["credit", "Credit"],
  ["author", "Author"],
  ["source", "Source"],
  ["draft_date", "Draft date"],
  ["contact", "Contact"]
];
var LABEL_TO_KEY = { ...Object.fromEntries(TITLE_KEYS.map(([k, l]) => [l.toLowerCase(), k])), authors: "author" };

// src/render/pageHtml.js
var FONT_PLACEHOLDER = "__FONT_BASE__";
var FONT_FILES = [
  "courier-prime-latin-400-normal.woff2",
  "courier-prime-latin-400-italic.woff2",
  "courier-prime-latin-700-normal.woff2",
  "courier-prime-latin-700-italic.woff2"
];

// src/main/files.js
var IMPORT_EXTS = ["fountain", "spmd", "txt"];
var EXPORT_EXTS = ["fountain", "txt"];
var MAX_IMPORT_BYTES = 5 * 1024 * 1024;
function exportName(name, ext) {
  const base = String(name ?? "").replace(/[\\/:*?"<>|]+/g, "-").trim() || "screenplay";
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`;
}
function inlineFonts(html, fontDir) {
  const re = new RegExp(`${FONT_PLACEHOLDER}([^"')\\s]+)`, "g");
  return html.replace(re, (_, name) => {
    if (!FONT_FILES.includes(name)) throw new Error(`unknown font: ${name}`);
    return `data:font/woff2;base64,${(0, import_node_fs2.readFileSync)((0, import_node_path2.join)(fontDir, name)).toString("base64")}`;
  });
}

// src/main.js
var ctx = null;
var printWindows = /* @__PURE__ */ new Set();
var withParent = (fn, opts) => {
  const parent = import_electron.BrowserWindow.getFocusedWindow();
  return parent ? fn(parent, opts) : fn(opts);
};
async function exportFile(req) {
  const { defaultName, ext, content } = req ?? {};
  if (!EXPORT_EXTS.includes(ext)) throw new Error(`export-file: unsupported extension ${JSON.stringify(ext)}`);
  if (typeof content !== "string") throw new Error("export-file: content must be a string");
  const r = await withParent(import_electron.dialog.showSaveDialog.bind(import_electron.dialog), {
    defaultPath: exportName(defaultName, ext),
    filters: [{ name: ext === "fountain" ? "Fountain" : "Text", extensions: [ext] }]
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  (0, import_node_fs3.writeFileSync)(r.filePath, content, "utf-8");
  return { path: r.filePath };
}
async function importFile() {
  const r = await withParent(import_electron.dialog.showOpenDialog.bind(import_electron.dialog), {
    properties: ["openFile"],
    filters: [{ name: "Screenplay", extensions: IMPORT_EXTS }]
  });
  if (r.canceled || !r.filePaths?.length) return { canceled: true };
  const file = r.filePaths[0];
  if ((0, import_node_fs3.statSync)(file).size > MAX_IMPORT_BYTES) throw new Error(`${(0, import_node_path3.basename)(file)} is larger than 5 MB`);
  return { name: (0, import_node_path3.basename)(file), content: (0, import_node_fs3.readFileSync)(file, "utf-8") };
}
async function exportPdf(req) {
  const c = ctx;
  if (!c) throw new Error("script-writer is not active");
  const { html, defaultName, paper } = req ?? {};
  if (typeof html !== "string" || !html.startsWith("<!doctype html>")) throw new Error("export-pdf: expected an html document");
  const r = await withParent(import_electron.dialog.showSaveDialog.bind(import_electron.dialog), {
    defaultPath: exportName(defaultName, "pdf"),
    filters: [{ name: "PDF", extensions: ["pdf"] }]
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  if (!ctx) throw new Error("script-writer is not active");
  const tmpDir = (0, import_node_path3.join)(c.dataDir, "tmp");
  (0, import_node_fs3.mkdirSync)(tmpDir, { recursive: true });
  const tmp = (0, import_node_path3.join)(tmpDir, `print-${Date.now()}-${Math.random().toString(36).slice(2)}.html`);
  (0, import_node_fs3.writeFileSync)(tmp, inlineFonts(html, (0, import_node_path3.join)(c.pluginDir, "dist", "fonts")), "utf-8");
  const win = new import_electron.BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  printWindows.add(win);
  try {
    await win.loadFile(tmp);
    await win.webContents.executeJavaScript("document.fonts.ready.then(() => true)");
    const pdf = await win.webContents.printToPDF({
      pageSize: paper === "a4" ? "A4" : "Letter",
      printBackground: true,
      preferCSSPageSize: true,
      margins: { marginType: "none" }
    });
    (0, import_node_fs3.writeFileSync)(r.filePath, pdf);
    return { path: r.filePath };
  } finally {
    printWindows.delete(win);
    if (!win.isDestroyed()) win.destroy();
    (0, import_node_fs3.rmSync)(tmp, { force: true });
  }
}
function activate(context) {
  ctx = context;
  ctx.ipc.handle("draft-write", (req) => writeDraft(ctx.dataDir, req ?? {}));
  ctx.ipc.handle("draft-read", (key) => readDraft(ctx.dataDir, key));
  ctx.ipc.handle("draft-clear", (key) => clearDraft(ctx.dataDir, key));
  ctx.ipc.handle("export-file", exportFile);
  ctx.ipc.handle("import-file", importFile);
  ctx.ipc.handle("export-pdf", exportPdf);
  ctx.log("activated");
}
function deactivate() {
  for (const w of printWindows) if (!w.isDestroyed()) w.destroy();
  printWindows.clear();
  ctx = null;
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  activate,
  deactivate
});
