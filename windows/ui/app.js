/* PII Vault for Windows: the window. Mirrors the Mac app's SwiftUI views:
   ContentView (sidebar) > NewJobView (StepBar, DropZone, FileReviewCard, ColumnTable, ExtraInfoBox,
   TextTabRow, FindingsList, PromptCard, SentView, RestoreDropZone, PasteAnswerBox, RestoredRow),
   JobsView/JobDetail, Settings (AIToolPicker, FolderStatus, LocalModelCard, UpdateCard),
   WelcomeSheet, OllamaSetupView, MigrationSheet, FolderProblemBanner, Toast, BusyOverlay, InfoPopover.
   Python side: windows/piivault_win/app.py (class Api). */
"use strict";

// ------------------------------------------------------------------ state
const S = {
  boot: null, cfg: {}, page: "new", stage: "add",
  files: [], scan: null, options: {}, plan: {}, reviews: {}, added: {}, pastes: [],
  prompt: "", wantPdf: false, job: null, results: [], restoreResults: [],
  jobs: [], selJob: null, doctor: null, models: null,
  ollama: { state: "checking", started: false, opening: false, skipped: false, pull: null, error: null },
  update: null, updateProg: null, pasteOpen: false, answerOpen: false, welcome: false, ui: {},
};
const TOOL_NAMES = { chatgpt: "ChatGPT", copilot: "Copilot", gemini: "Gemini", claude: "Claude", other: "Other" };
const CAT = { PERSON: "Name", EMAIL: "Email", PHONE: "Phone", SSN: "SSN", ID: "ID number", DOB: "Birth date",
  ADDRESS: "Address", ACCOUNT: "Account #", IP: "IP address", URL: "URL", OTHER: "Identifier" };
const ACTIONS = [["token", "🔒 Tokenize"], ["year", "📅 Year only"], ["scan", "🔍 Scan text"], ["keep", "👁 Keep as is"], ["drop", "✕ Remove"]];
const KIND_LABEL = { table: "XLS", word: "DOC", pdf: "PDF", text: "TXT", unsupported: "?" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel) => document.querySelector(sel);
const toolName = () => { const t = S.cfg.ai_tool; return t && t !== "other" ? TOOL_NAMES[t] : "your AI tool"; };
const base = (p) => String(p || "").split(/[\\/]/).pop();
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// ------------------------------------------------------------------ icons (SF Symbols look-alikes)
const I = {
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/></svg>',
  restore: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v4l3 2"/></svg>',
  jobs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  tray: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="big"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M3 15v3a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
  open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2h8.4A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/><path d="M12 7v8M8.5 11.5L12 15l3.5-3.5" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/></svg>',
  doc: '<svg viewBox="0 0 58 72" class="doc"><defs><linearGradient id="dg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a3f7a"/><stop offset="1" stop-color="#142142"/></linearGradient></defs><path d="M8 0h30l20 20v44a8 8 0 0 1-8 8H8a8 8 0 0 1-8-8V8a8 8 0 0 1 8-8z" fill="url(#dg)"/><path d="M38 0v12a8 8 0 0 0 8 8h12z" fill="#3d5596"/><path d="M29 34v20M20 46l9 9 9-9" stroke="#0e1730" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/></svg>',
  dl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v13M6 11l6 6 6-6M4 21h16"/></svg>',
  dlc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v8M8.5 12.5l3.5 3.5 3.5-3.5"/></svg>',
  history: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 3"/></svg>',
  shieldok: '<svg viewBox="0 0 24 24"><path d="M12 2l8.5 3.2v6.3c0 5-3.6 9.3-8.5 10.5C7.1 20.8 3.5 16.5 3.5 11.5V5.2z" fill="var(--green)"/><path d="M8 12.2l2.8 2.8L16.3 9" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="10.5" width="14" height="10.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" stroke="currentColor" stroke-width="2.2" fill="none"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="5" width="8" height="4" rx="1"/><rect x="13" y="5" width="8" height="4" rx="1"/><rect x="3" y="10.5" width="8" height="4" rx="1"/><rect x="13" y="10.5" width="8" height="4" rx="1"/><rect x="3" y="16" width="8" height="4" rx="1"/><rect x="13" y="16" width="8" height="4" rx="1"/></svg>',
  xcirc: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="var(--faint)"/><path d="M9 9l6 6M15 9l-6 6" stroke="var(--card)" stroke-width="2" stroke-linecap="round"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/></svg>',
};

// ------------------------------------------------------------------ info popovers (InfoTopic)
const INFO = {
  folders: ["Where your files go", [
    "Everything lives in one folder, PII Vault, in your home folder (C: > Users > your name). It's kept out of Documents and Desktop on purpose, so OneDrive never copies your students' data to the cloud.",
    "<b>For AI > Protected</b>: the protected copies. These are the only files you give to an AI tool.",
    "<b>For AI > AI Output</b>: tools that can save on your PC (like Claude's Cowork mode) save here, and PII Vault restores them by itself. If your tool asks for a folder, give it \"For AI\" only.",
    "<b>Restored</b>: your finished files with the real data. Never upload from or share this folder with an AI tool.",
    "Files you download from an AI tool into Downloads are restored by themselves too.",
    "Your original files stay wherever they are and are never changed."]],
  header: ["Which row has the column names", [
    "The row with the column names (Student Name, ID, and so on). PII Vault guesses it. If the columns listed below look wrong, change the number to the row you see in Excel. Rows above it count as extra info. Set it to 0 to treat the tab as text."]],
  extra: ["Extra info above the table", [
    "Many reports put a block of information above the table: course title, term, CRN, enrollment counts. PII Vault finds where the real table starts.",
    "<b>Remove (recommended)</b>: those rows are left out, so the AI gets a clean table that starts with the column names.",
    "<b>Keep</b>: the rows stay exactly where they are, so the protected copy looks like the original. Any names, emails, or IDs in them are swapped for tokens first."]],
  texttab: ["Tabs with no table", [
    "A tab with no table on it, like assignment instructions or notes. If you include it, PII Vault reads it like a Word document and swaps any names, emails, or IDs for tokens. Leave it out if the AI doesn't need it."]],
  kinds: ["What PII Vault found in each column", [
    "<b>Name, Email, ID number and the like</b>: the column holds a direct identifier, so it is protected by default.",
    "<b>Free text</b>: the column holds sentences (comments, notes). Each cell is scanned for names and contact details.",
    "<b>Indirect</b>: not a name or ID, but combined with other columns (ZIP + birth year + major) it can point to one person in a small group. Kept by default; remove it when your group is small.",
    "<b>None</b>: nothing personal was found."]],
  actions: ["What each action does", [
    "<b>Tokenize</b>: swaps each value for a stand-in like PERSON_0001. The same person always gets the same token, so the AI can still count, group, and match rows. The real value goes back in when the AI is done.",
    "<b>Year only</b>: keeps only the year from a date (2005-03-14 becomes 2005) and adds \"(year)\" to the column name. Made for birth dates: the AI can still work out ages, but the exact date never leaves your PC. The full date is not put back afterward.",
    "<b>Scan text</b>: for comment or notes columns. Each cell is read, and only the names, emails, phone numbers, and IDs inside it are swapped for tokens. The rest of the sentence goes to the AI as written.",
    "<b>Keep</b>: sends the column unchanged. Use it for things that aren't personal, like major, term, or GPA.",
    "<b>Remove</b>: deletes the column from the copy the AI gets. Use it for anything the AI doesn't need for this task."]],
  review: ["Review what PII Vault finds", [
    "<b>On</b>: for Word, PDF, and text files, PII Vault lists everything it found before anything is sent. Untick false alarms (like \"Grant\" the scholarship) and add anything it missed.",
    "<b>Off</b>: PII Vault removes everything it finds without asking. Faster for long documents, but you're trusting the detector to catch every name. Spreadsheets always get the column review either way."]],
  pdf: ["\"I need a PDF at the end\"", [
    "An AI tool can't make a PDF that PII Vault is able to fill back in, because the real names can't be written into a finished PDF reliably. Tick this when you want a PDF as the final result: the AI is told to make a Word or HTML file instead, and PII Vault turns it into a PDF on your PC after the real data is back in."]],
  copy: ["Copy Prompt and Copy Files", [
    "<b>Copy Files</b> puts the protected files on your clipboard. Click in your AI tool's message box and press Ctrl+V to attach them. (If your tool won't take pasted files, use its attach button and pick them from Show Protected Files.)",
    "<b>Copy Prompt</b> puts the instructions on your clipboard. Press Ctrl+V again in the same message, then send. The extra lines tell the AI to keep the tokens exactly as written."]],
  restore: ["Restoring a downloaded file", [
    "When the AI gives you a file to download, drop that file here (or choose it). PII Vault puts the real data back and saves the result to your private Restored folder.",
    "If the AI shows its answer as text instead of a file, use Paste the AI's Answer: paste it in and PII Vault saves a restored copy."]],
  updates: ["Updates", [
    "PII Vault checks for a new version when it opens. When there is one, click Install Update: it downloads the new version, checks it, installs it, and reopens. Your folders, settings, and protected jobs stay as they are.",
    "Because PII Vault isn't from the Microsoft Store, Windows may show \"Windows protected your PC\" once after an update. Click More info, then Run anyway."]],
  localmodel: ["Local model", [
    "A small AI model that runs entirely on this PC, through the free Ollama app. PII Vault uses it to spot names that have no label in front of them (\"Met with Jasmine about...\"). Nothing is sent online. Without it, PII Vault still finds labeled names, emails, phones, IDs, and addresses."]],
};
const info = (k) => `<span class="infobtn" data-act="info" data-k="${k}" title="More info">i</span>`;

// ------------------------------------------------------------------ bridge
function api() { return window.pywebview && window.pywebview.api; }
async function call(name, ...args) {
  const r = await api()[name](...args);
  if (r && r.error) { const e = new Error(r.error); e.engine = true; throw e; }
  return r || {};
}
async function tryCall(name, ...args) {
  try { return await call(name, ...args); } catch (e) { toast(e.message, "err"); return null; }
}

// ------------------------------------------------------------------ toast / busy / sheet / popover
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = esc(msg);
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 4200);
}
function busy(msg, sub = "") {
  $("#overlay").innerHTML = msg ? `<div class="overlay"><div class="busy"><div class="spinner"></div>
    <h2>${esc(msg)}</h2>${sub ? `<p class="muted small">${esc(sub)}</p>` : ""}</div></div>` : "";
}
function popover(anchor, key) {
  const [title, paras] = INFO[key];
  const r = anchor.getBoundingClientRect();
  const el = $("#popover");
  el.innerHTML = `<div class="popover" id="pop"><h3>${esc(title)}</h3>${paras.map((p) => `<p>${p}</p>`).join("")}</div>`;
  const pop = $("#pop");
  const w = 400, h = pop.offsetHeight;
  let left = Math.min(Math.max(12, r.left - w / 2), innerWidth - w - 12);
  let top = r.bottom + 8;
  if (top + h > innerHeight - 12) top = Math.max(12, r.top - h - 8);
  pop.style.left = left + "px"; pop.style.top = top + "px";
}
document.addEventListener("mousedown", (e) => { if (!e.target.closest("#pop") && !e.target.closest(".infobtn")) $("#popover").innerHTML = ""; });

// ------------------------------------------------------------------ render
function render() {
  renderNav(); renderBanner();
  const page = { new: renderNew, restore: renderJobs, jobs: renderJobs, settings: renderSettings }[S.page];
  const flush = S.page === "jobs" || S.page === "restore";
  $("#scroll").classList.toggle("flush", flush);
  $("#page").classList.toggle("flush", flush);
  $("#page").innerHTML = page();
  renderSheet();
}
function renderNav() {
  const items = [["new", "New Job", I.plus], ["jobs", "Jobs", I.history], ["settings", "Settings", I.gear]];
  const navPage = S.page === "restore" ? "jobs" : S.page;
  $("#nav").innerHTML = items.map(([k, t, ic]) => `<a class="${navPage === k ? "sel" : ""}" data-act="nav" data-k="${k}">${ic}${t}</a>`).join("");
  const local = localModelOn();
  const ocr = S.doctor ? ({ "windows-ocr": "Windows OCR", tesseract: "Tesseract", none: "not installed" }[S.doctor.ocr_engine] || S.doctor.ocr_engine) : "checking";
  let st = "";
  if (S.update && S.update.state === "available")
    st += `<button class="btn small blue" data-act="nav" data-k="settings" style="margin-bottom:8px">${I.down}Update to ${esc(S.update.version)}</button>`;
  st += `<div class="side-card"><b><span class="gdot ${S.boot ? "" : "off"}"></span>${S.boot ? "Engine ready" : "Engine not set up"}</b>
    <span>Names: ${local ? "local model" : "rules only"}</span><span>OCR: ${esc(ocr)}</span>
    ${S.cfg.watch_downloads !== false ? "<span>Restores AI downloads by itself</span>" : ""}</div>`;
  $("#side-status").innerHTML = st;
}
function localModelOn() {
  if (S.doctor && S.doctor.ner_engine) return S.doctor.ner_engine.startsWith("ollama");
  return !!(S.cfg.use_local_model && S.ollama.state === "running" && hasModel());
}
function renderBanner() {
  const bad = ((S.boot && S.boot.setup && S.boot.setup.folders) || []).filter((f) => !f.ok);
  $("#banner").innerHTML = bad.length ? `<div class="banner">${I.warn.replace("<svg", '<svg style="width:20px;height:20px;flex:none"')}
    <div class="grow"><b>PII Vault can't use its ${esc(bad[0].name)} folder.</b>
    <div class="small">Click Repair. If that doesn't fix it, make sure Windows Security's Controlled folder access isn't blocking PII Vault, then click Repair again.</div></div>
    <button class="btn small" data-act="repair">Repair</button><button class="btn small" data-act="ransomware">Open Settings</button></div>` : "";
}

// ---------------------------------------------------------------- New Job
function stepBar() {
  const at = { add: 0, review: 1, sent: 2 }[S.stage];
  const restored = S.stage === "sent" && S.results.length > 0;
  const cur = S.stage === "sent" ? (restored ? 4 : 3) : at;
  const steps = ["Add files", "Review", "Send to AI", "Restore"];
  return `<div class="msteps">${steps.map((t, i) => {
    const cls = i < cur ? "done" : i === cur ? "on" : "";
    return (i ? `<span class="mline ${i <= cur ? "on" : ""}"></span>` : "") + `<span class="mstep ${cls}"><span class="c"></span>${t}</span>`;
  }).join("")}</div>`;
}
function renderNew() {
  const t = toolName();
  const head = `<div class="page-title"><img src="icon.png" alt=""><div><h1>Protect files for AI</h1>
    <p>Personal information is swapped for tokens on this PC. ${esc(t === "your AI tool" ? "Your AI tool" : t)} works with the tokens, and PII Vault puts the real data back in whatever it makes.</p></div></div>`;
  let body = "";
  if (S.stage === "add") body = addStage();
  else if (S.stage === "review") body = reviewStage();
  else body = sentStage();
  return head + stepBar() + body;
}
function pasteCard() {
  return S.pasteOpen ? `<div class="card"><div class="card-head"><h2>Paste text instead</h2></div>
      <p class="muted small" style="margin-bottom:8px">Notes, an email, a transcript: anything with names in it. It's treated like a text file and deleted from this PC after it's protected.</p>
      <textarea id="paste-text" rows="8" placeholder="Paste here"></textarea>
      <div class="row" style="margin-top:10px"><span class="spacer"></span><button class="btn" data-act="paste-cancel">Cancel</button>
      <button class="btn primary" data-act="paste-go">Continue</button></div></div>` : "";
}
function addStage() {
  return `<div class="drop" data-zone="protect" style="padding:56px 24px">
      ${I.doc}<div class="t" style="margin-top:14px">Drop a spreadsheet, document, PDF, or text file</div>
      <div class="muted">CSV, Excel, Word, PDF (scanned pages are read on this PC), and plain text (.txt, .md, .rtf)</div>
      <div class="links"><a data-act="pick">Choose Files…</a><span class="sep">·</span><a data-act="paste-open">Paste text instead</a></div>
    </div>
    ${pasteCard()}`;
}

// ---- review
function reviewStage() {
  const files = (S.scan && S.scan.files) || [];
  const docs = files.some((f) => ["word", "pdf", "text"].includes(f.kind));
  let out = `<div class="drop" data-zone="protect" style="padding:16px 24px;gap:4px">${I.doc.replace('class="doc"', 'style="width:24px;height:30px"')}
    <div style="font-weight:650;font-size:15px">Drop more files</div>
    <div class="links" style="font-size:15px;margin:0"><a data-act="pick">Choose Files…</a><span class="sep">·</span><a data-act="paste-open">Paste text instead</a></div></div>`;
  out += pasteCard();
  if (docs) {
    out += `<div class="card tight row"><label class="chk grow" style="padding:0"><input type="checkbox" data-act="toggle-review" ${S.scan.review ? "checked" : ""}>
      <span>Review what PII Vault finds in documents before sending</span></label>${info("review")}</div>`;
  }
  out += files.map(fileCard).join("");
  out += promptCard();
  return out;
}
function fileHead(f) {
  return `<div class="file-head"><div class="file-icon ${f.kind}">${f.kind === "table" ? I.grid : KIND_LABEL[f.kind] || "?"}</div>
    <div class="grow"><h3 style="font-size:15px">${esc(f.name)}</h3><div class="muted">${esc(fileSummary(f))}</div></div>
    <button class="xbtn" data-act="remove-file" data-f="${esc(f.file)}" title="Remove">${I.xcirc}</button></div>
    ${f.warning ? `<div class="note small" style="margin-top:10px">${esc(f.warning)}</div>` : ""}
    ${f.error ? `<div class="warn small" style="margin-top:10px">${esc(f.error)}</div>` : ""}`;
}
function fileSummary(f) {
  if (f.kind === "table" && f.sheets) {
    const t = f.sheets.filter((s) => s.kind === "table");
    const prot = t.reduce((n, sh) => n + sh.columns.filter((c) => !["keep", "drop"].includes(colAction(f, sh.name, c))).length, 0);
    const rows = t.reduce((n, sh) => n + sh.rows, 0);
    return `${rows} rows · ${plural(prot, "column")} will be protected${f.sheets.length > 1 ? ` · ${plural(f.sheets.length, "tab")}` : ""}`;
  }
  if (f.kind === "pdf") return `${plural(f.pages || 0, "page")}${f.scanned_pages ? `, ${f.scanned_pages} scanned` : ""}`;
  if (f.kind === "word") return plural(f.paragraphs || 0, "paragraph");
  if (f.kind === "text") return f.name === "Pasted text.txt" ? "Pasted text" : plural(f.paragraphs || 0, "paragraph");
  return "";
}
function fileCard(f) {
  if (f.error || f.kind === "unsupported") return `<div class="card file-card">${fileHead(f)}</div>`;
  if (f.kind === "table") return tableCard(f);
  return docCard(f);
}
function kindPill(c) {
  if (c.category) return `<span class="pill ${c.category === "DOB" ? "amber" : "red"}">🪪 ${CAT[c.category] || c.category}</span>`;
  if (c.free_text) return `<span class="pill blue">☰ Free text</span>`;
  if (c.quasi) return `<span class="pill amber" title="Not a direct identifier, but combined with other columns it can point to one person.">Indirect</span>`;
  return `<span class="pill">None</span>`;
}
function colAction(f, sheet, c) { return ((S.plan[f.file] || {})[sheet] || {})[c.header] ?? c.action; }
function tableCard(f) {
  const opts = S.plan[f.file] || {};
  let h = `<div class="card file-card">${fileHead(f)}`;
  for (const sh of f.sheets) {
    const multi = f.sheets.length > 1;
    if (sh.kind === "text") {
      const inc = ((opts._text_sheets || {})[sh.name]) === true;
      h += `<div class="text-tab"><label class="check grow"><input type="checkbox" data-act="text-tab" data-f="${esc(f.file)}" data-s="${esc(sh.name)}" ${inc ? "checked" : ""}>
        <span><b>${esc(sh.name)}</b> <span class="pill">Text tab</span> ${info("texttab")}<br><span class="muted small">${inc ?
        "Included. Read like a document: any name, email or ID found so far will be swapped for tokens." : "Left out of the protected copy."}</span></span></label>
        ${headerRowControl(f, sh)}</div>`;
      continue;
    }
    h += `<div class="sheet-name">${multi ? `<span>${esc(sh.name)}</span>` : ""}<span class="spacer"></span>${headerRowControl(f, sh)}</div>`;
    h += `<table class="cols"><tr><th>Column</th><th>Detected ${info("kinds")}</th><th>Sample (masked)</th><th>Action ${info("actions")}</th></tr>`;
    for (const c of sh.columns) {
      const a = colAction(f, sh.name, c);
      h += `<tr class="${a === "drop" ? "dropped" : ""}"><td class="h" title="${esc(c.header)}">${esc(c.header || "(no name)")}</td>
        <td>${kindPill(c)}</td><td class="s" title="${esc((c.preview || []).join(", "))}">${esc((c.preview || []).join(", "))}</td>
        <td><select class="act" data-act="col-action" data-f="${esc(f.file)}" data-s="${esc(sh.name)}" data-h="${esc(c.header)}">
        ${ACTIONS.filter(([k]) => k !== "year" || c.category === "DOB" || a === "year").map(([k, t]) => `<option value="${k}" ${a === k ? "selected" : ""}>${t}</option>`).join("")}
        </select></td></tr>`;
    }
    h += `</table>`;
  }
  if (f.has_extra) {
    const mode = opts._extra || f.extra_default || "remove";
    const sh = f.sheets.find((s) => s.extra_rows);
    h += `<div class="extra-box"><div class="row"><h3>Extra info above the table</h3>${info("extra")}<span class="spacer"></span>
      <div class="seg"><button class="${mode === "remove" ? "on" : ""}" data-act="extra" data-f="${esc(f.file)}" data-v="remove">Remove (recommended)</button>
      <button class="${mode === "keep" ? "on" : ""}" data-act="extra" data-f="${esc(f.file)}" data-v="keep">Keep</button></div></div>
      ${sh && sh.extra_preview ? `<div class="mono muted" style="margin-top:8px">${sh.extra_preview.map(esc).join("<br>")}</div>` : ""}
      <p class="muted small" style="margin-top:8px">${mode === "remove" ? "Left out. The AI gets only the table, starting with the column names." :
      "Kept in place, so the protected copy looks like the original. Any names, emails, or IDs in it are swapped for tokens."}</p></div>`;
  }
  return h + `</div>`;
}
function headerRowControl(f, sh) {
  const v = sh.kind === "text" ? 0 : sh.header_row;
  return `<span class="row small muted" style="gap:6px" title="Change this if the columns below look wrong. 0 treats the tab as text.">Column names are on row
    <input type="number" min="0" value="${v}" data-act="header-row" data-f="${esc(f.file)}" data-s="${esc(sh.name)}">${info("header")}</span>`;
}
function docCard(f) {
  let h = `<div class="card file-card">${fileHead(f)}`;
  if (f.kind === "pdf" && f.scanned_pages) h += `<div class="info small" style="margin-top:10px">Personal details are blacked out of the image and replaced with tokens.</div>`;
  if (!S.scan.review) {
    h += `<p class="muted small" style="margin-top:10px">Everything PII Vault finds is removed automatically: every paragraph, table, header, footer, comment, form field, link, and the file's author details.</p>`;
    return h + `</div>`;
  }
  const finds = f.findings || [];
  const rv = S.reviews[f.file] || {};
  const added = S.added[f.file] || [];
  if (!finds.length && !added.length) h += `<div class="ok small" style="margin-top:10px">Nothing personal was found. If you know a name is in there, add it below and every copy of it will be replaced.</div>`;
  else {
    h += `<div class="findings">` + finds.map((g, i) => {
      const off = rv[g.value] === false;
      return `<label class="finding ${off ? "off" : ""}"><input type="checkbox" data-act="finding" data-f="${esc(f.file)}" data-i="${i}" ${off ? "" : "checked"}>
        <div class="grow"><div class="row" style="gap:8px"><span class="v">${esc(g.value)}</span><span class="pill red">${CAT[g.category.replace("~", "")] || g.category}</span>
        ${g.count > 1 ? `<span class="faint small">× ${g.count}</span>` : ""}<span class="spacer"></span><span class="pill small">${esc(g.source)}</span></div>
        <div class="ctx">${esc(g.before)}<mark>${esc(g.value)}</mark>${esc(g.after)}</div></div></label>`;
    }).join("") + added.map((a, i) => `<div class="finding"><input type="checkbox" checked disabled><div class="grow"><div class="row" style="gap:8px">
        <span class="v">${esc(a.value)}</span><span class="pill red">${CAT[a.category]}</span><span class="pill blue small">added by you</span><span class="spacer"></span>
        <button class="btn small link" data-act="unadd" data-f="${esc(f.file)}" data-i="${i}">Remove</button></div></div></div>`).join("") + `</div>`;
  }
  h += `<div class="row" style="margin-top:10px"><input type="text" placeholder="Missed something? Type it exactly as it appears" data-add-input="${esc(f.file)}">
    <select data-add-cat="${esc(f.file)}">${["PERSON", "EMAIL", "PHONE", "ID", "ADDRESS", "OTHER"].map((c) => `<option value="${c}">${CAT[c]}</option>`).join("")}</select>
    <button class="btn" data-act="add-value" data-f="${esc(f.file)}">Add</button></div>`;
  return h + `</div>`;
}
function numHead(n, title, sub, extra = "") {
  return `<div class="numhead"><span class="num">${n}</span><div class="grow"><h2>${title}</h2>${sub ? `<p class="muted">${sub}</p>` : ""}</div>${extra}</div>`;
}
function promptCard() {
  return `<div class="card">${numHead(2, "What should the AI do?", "PII Vault adds instructions so the AI keeps the tokens intact.")}
    <textarea id="prompt" rows="4" placeholder="e.g. Create an HTML dashboard from this spreadsheet">${esc(S.prompt)}</textarea>
    <div class="row" style="margin-top:12px"><label class="chk"><input type="checkbox" data-act="want-pdf" ${S.wantPdf ? "checked" : ""}><span>I need a PDF at the end</span></label>${info("pdf")}</div>
    <div class="row" style="margin-top:8px"><span class="spacer"></span>
    <button class="btn primary big" data-act="protect">${I.shield.replace("<svg", '<svg style="width:18px;height:18px"')}Protect Files</button></div></div>`;
}

// ---- sent
function sentStage() {
  const j = S.job;
  if (!j) return "";
  if (j.status === "blocked") {
    return `<div class="card warn"><h2>Nothing was shared</h2><p style="margin-top:6px">PII Vault stopped before sending: at least one file still contained personal information it could not remove, or failed to process. Nothing was shared.</p>
      <ul>${j.files.map((f) => `<li><b>${esc(base(f.source))}</b>: ${esc(f.error || (f.warnings || []).join(" ") || "OK")}</li>`).join("")}</ul>
      <div class="row"><span class="spacer"></span><button class="btn" data-act="back-review">Back to Review</button><button class="btn primary" data-act="start-over">Start Over</button></div></div>`;
  }
  const t = toolName();
  const files = j.files.filter((f) => !f.error);
  const counts = (f) => Object.values(f.replaced || {}).reduce((a, b) => a + (typeof b === "number" ? b : 0), 0);
  const tool = S.cfg.ai_tool && S.cfg.ai_tool !== "other";
  return `<div class="card"><div class="row" style="gap:16px;align-items:flex-start"><span style="width:44px;height:44px;flex:none">${I.shieldok}</span>
      <div class="grow"><h2>Files protected and ready for ${esc(t)}</h2><p class="muted" style="font-size:15px">${esc(j.id)} · ${S.promptAutoCopied ? "The prompt is already on your clipboard." : "Copy the files and the prompt below."}</p></div></div>
      ${files.map((f) => `<div class="row" style="margin-top:12px"><span style="width:22px;height:22px;color:var(--green)">${f.kind === "table" ? I.grid : I.plus}</span>
        <span class="grow" style="font-weight:600;font-size:15px">${esc(f.sanitized_name)}</span>
        <span class="pill green">${I.lock.replace("<svg", '<svg style="width:12px;height:12px"')} ${counts(f)} values protected</span></div>
        ${(f.warnings || []).length ? `<div class="note small" style="margin-top:6px">${esc(f.warnings.join(" "))}</div>` : ""}`).join("")}
    </div>
    <div class="card">${numHead(3, `Paste into ${esc(t === "your AI tool" ? "your AI tool" : t)}`, "Copy Files and paste into the message box, then Copy Prompt and paste. Send.", info("copy"))}
      <div class="row wrap"><button class="btn primary big" data-act="copy-files">${I.copy}Copy Files</button>
        <button class="btn primary big" data-act="copy-prompt">${I.copy}Copy Prompt</button>
        ${tool ? `<button class="btn big" data-act="open-tool">${I.open}Open ${esc(t)}</button>` : ""}</div>
      ${S.cfg.ai_tool === "claude" ? `<div class="info small" style="margin-top:12px"><b>Skip the download with Claude:</b> in the Claude desktop app, connect the <b>PII Vault › For AI</b> folder to your chat (Cowork mode). Claude reads the protected files from there and saves its answer into For AI › AI Output, and PII Vault restores it by itself. <a data-act="show-folder" data-k="forai">Show the For AI folder</a></div>` : ""}
      <details class="disc"><summary>${I.chev}See the prompt</summary><div class="prompt-box" style="margin-top:8px">${esc(j.cowork_prompt)}</div></details>
      <div class="row" style="margin-top:10px"><a data-act="reveal" data-p="${esc(j.sanitized_dir)}" class="row" style="gap:8px;font-size:15px">${I.folder.replace('fill="currentColor"', 'fill="none" stroke="currentColor" stroke-width="1.6" style="width:22px;height:22px"')}Show Protected Files</a>
        <span class="spacer"></span><button class="btn" data-act="start-over">New Job</button></div></div>
    ${restoreSection(j.id)}`;
}
function restoreSection(jobId) {
  const res = jobId ? S.results : S.restoreResults;
  const t = toolName();
  return `<div class="card">${numHead(4, "Put the real data back", `Drop the file ${esc(t === "your AI tool" ? "your AI tool" : t)} gives you below. The restored copy is saved in PII Vault › Restored.`)}
      ${res.length ? `<div style="margin-bottom:10px">${res.map(resultRow).join("")}</div>` : ""}
      <div class="drop compact row" data-zone="restore" style="flex-direction:row;text-align:left;padding:14px 18px;gap:14px">
        <span style="width:28px;height:28px;color:var(--accent)">${I.dlc}</span>
        <div><div style="font-weight:650;font-size:15px">Drop the AI's file here</div><div class="muted small">Usually in Downloads. Or <a data-act="pick-restore">choose it…</a></div></div>${info("restore")}</div>
      ${S.ui.clipboard_watch !== false ? `<p class="muted small" style="margin-top:8px">No file? Just copy the AI's answer (its copy button) and PII Vault offers to restore it.</p>` : ""}
      ${res.length ? `<p class="muted small" style="margin-top:8px">Follow-ups: ask the AI for a revised file and drop each new version here. Keep the same chat so it keeps the same tokens.</p>` : ""}
      <details class="disc" ${S.answerOpen ? "open" : ""}><summary data-act="answer-toggle">${I.chev}No file? Paste the AI's answer</summary>
        <p class="muted small" style="margin:8px 0">Copy the AI's whole answer (or its HTML code) and paste it here. PII Vault saves a restored copy as HTML, CSV, or Markdown, depending on what you paste.</p>
        <textarea id="answer-text" rows="6"></textarea><div class="row" style="margin-top:8px"><span class="spacer"></span>
        <button class="btn primary" data-act="restore-text" data-j="${esc(jobId || "")}">Restore Pasted Answer</button></div></details>
      <div class="row muted small" style="margin-top:10px"><span class="live-dot"></span>Watching for the AI's file in Downloads and in the AI Output folder (for AI tools that save there directly).</div>
    </div>`;
}
function resultRow(r) {
  const file = r.file || "";
  const unk = r.unknown_tokens || [];
  return `<div class="result"><div class="big-check" style="width:30px;height:30px;${r.error ? "background:var(--red)" : ""}">${r.error ? "!" : I.check}</div>
    <div class="grow"><div class="name">${esc(base(file || r.source))}</div>
    <div class="muted small">${r.error ? esc(r.error) : r.skipped ? esc(r.note || "These were left as is.") :
      `Restored real data in ${plural(r.replaced || 0, "place")}${r.from_downloads ? " · from Downloads" : ""}${r.pdf ? " · PDF made" : ""}`}</div>
    ${unk.length ? `<div class="small" style="color:var(--red)">The AI used tokens that aren't in the vault: ${esc(unk.join(", "))}. These were left as is.</div>` : ""}
    ${r.pdf_note ? `<div class="small" style="color:#a86a08">${esc(r.pdf_note)}</div>` : ""}</div>
    ${!r.error && file ? `<button class="btn small" data-act="open" data-p="${esc(r.pdf || file)}">Open</button>
    <button class="btn small" data-act="reveal" data-p="${esc(r.pdf || file)}">Show in Folder</button>` : ""}</div>`;
}

// ---------------------------------------------------------------- Restore page
function renderRestorePage() {
  return `<div class="page-head"><h1>Put the real data back</h1><p>Put the real data back into a file you downloaded from your AI tool</p></div>
    ${restoreSection(null)}
    <div class="card tight row"><p class="muted small grow">PII Vault already restores new files in Downloads and in For AI > AI Output by itself. To look again right now:</p>
    <button class="btn" data-act="check-output">Check the AI Output folder</button><button class="btn" data-act="show-folder" data-k="restored">Show Restored Folder</button></div>`;
}

// ---------------------------------------------------------------- Jobs
function renderJobs() {
  const jobs = S.jobs || [];
  const label = { sent: ["With AI", "blue"], complete: ["Restored", "green"], blocked: ["Stopped", "red"], ready: ["Ready", ""] };
  const sel = jobs.find((j) => j.id === S.selJob);
  const list = jobs.length ? jobs.map((j) => {
    const [t, c] = label[j.status] || [j.status, ""];
    return `<div class="jrow ${sel && j.id === sel.id ? "sel" : ""}" data-act="sel-job" data-j="${esc(j.id)}"><div class="grow">
      <div class="id">${esc(j.id)}</div><div class="p">${esc(j.prompt || (j.files || []).map((f) => base(f.source)).join(", "))}</div></div>
      <span class="pill ${c}" style="align-self:flex-start">${t}</span></div>`;
  }).join("") : `<div class="empty" style="height:auto;padding-top:80px">${I.history}No jobs yet</div>`;
  return `<div class="split" data-zone="restore"><div class="list">
      <div class="row" style="margin-bottom:6px"><div class="toolbar"><button data-act="pick-restore" title="Restore a file you downloaded from your AI tool">${I.dl}</button>
      <button data-act="refresh-jobs" title="Check for new AI output and refresh">${I.refresh}</button></div></div>${list}</div>
    <div class="detail">${sel ? jobDetail(sel) : `<div class="empty">${I.history}Select a job</div>`}</div></div>`;
}
function fmtDate(s) { try { return new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); } catch { return s; } }
function jobDetail(j) {
  const outs = Object.entries(j.outputs || {});
  return `<div class="col" style="gap:14px"><div class="card"><div class="card-head"><h2 class="mono" style="font-size:15px">${esc(j.id)}</h2><span class="sub">${esc(fmtDate(j.created))}</span></div>
    <div class="kv"><span class="k">What the AI should do</span><span class="selectable">${esc(j.prompt || "(no instructions)")}</span>
    <span class="k">Files</span><span>${(j.files || []).map((f) => `${esc(base(f.source))} → <span class="mono">${esc(f.sanitized_name)}</span>${f.error ? ` <span class="pill red">${esc(f.error)}</span>` : ""}`).join("<br>")}</span>
    <span class="k">PDF at the end</span><span>${j.want_pdf ? "Yes" : "No"}</span></div>
    <div class="row wrap" style="margin-top:14px">
      ${j.sanitized_dir ? `<button class="btn" data-act="job-copy-files" data-p="${esc(j.sanitized_dir)}">${I.copy}Copy Files</button>` : ""}
      ${j.cowork_prompt ? `<button class="btn" data-act="job-copy-prompt" data-j="${esc(j.id)}">${I.copy}Copy Prompt</button>` : ""}
      ${j.sanitized_dir ? `<button class="btn" data-act="reveal" data-p="${esc(j.sanitized_dir)}">Show Protected Files</button>` : ""}
      <span class="spacer"></span><button class="btn primary" data-act="job-open" data-j="${esc(j.id)}">Restore Files for This Job</button></div></div>
    <div class="card"><div class="card-head"><h2>Restored results</h2></div>${outs.length ? outs.map(([, r]) => resultRow(r)).join("") :
      `<p class="muted">Nothing yet. Drop the AI's file below and the restored copy shows up here.</p>`}</div></div>`;
}

// ---------------------------------------------------------------- Settings
function toolPicker() {
  return `<div class="seg">${Object.entries(TOOL_NAMES).map(([k, t]) => `<button class="${S.cfg.ai_tool === k ? "on" : ""}" data-act="tool" data-k="${k}">${t}</button>`).join("")}</div>`;
}
function switchRow(key, title, sub, extra = "") {
  return `<label class="toggle-row" style="cursor:pointer"><span class="switch"><input type="checkbox" data-act="cfg-bool" data-k="${key}" ${S.cfg[key] !== false ? "checked" : ""}><span></span></span>
    <span class="grow"><b>${title}</b>${sub ? `<p>${sub}</p>` : ""}</span>${extra}</label>`;
}
function chk(key, label, extra = "") {
  return `<label class="chk"><input type="checkbox" data-act="cfg-bool" data-k="${key}" ${S.cfg[key] !== false ? "checked" : ""}><span>${label}</span>${extra}</label>`;
}
function renderSettings() {
  const d = S.doctor || {};
  const folders = (S.boot && S.boot.setup && S.boot.setup.folders) || [];
  const fname = { sanitized_dir: "Protected files (what you give the AI)", claude_output_dir: "AI Output (for AI tools that save on your PC)", results_dir: "Restored results (private, never share with an AI tool)" };
  const ocr = { "windows-ocr": "Windows OCR", tesseract: "Tesseract", "apple-vision": "Apple Vision OCR", none: "No OCR engine found" }[d.ocr_engine] || "Checking";
  const names = d.ner_engine ? (d.ner_engine.startsWith("ollama") ? `Local model (${d.ner_engine.slice(7)})` : "Rules only") : "Checking";
  return `<h1 class="plain">Settings</h1>
    <div class="card"><div class="mcard-title"><h2>Your AI tool</h2></div>${toolPicker()}</div>

    <div class="card">${localModelCard()}</div>

    <div class="card"><div class="mcard-title"><h2>Detection</h2></div>
      <div class="mrow"><span class="k">Names in free text</span><span class="v">${esc(names)}</span></div>
      <div class="mrow"><span class="k">Scanned PDFs</span><span class="v">${esc(ocr)}</span></div>
      ${chk("use_local_model", "Use the local model for names")}
      ${chk("review_unstructured", "Review what PII Vault finds in Word, PDF, and text files", " " + info("review"))}</div>

    <div class="card"><div class="mcard-title"><h2>Folders</h2>${info("folders")}<span class="spacer"></span>
      <button class="btn" data-act="show-folder" data-k="home">Show PII Vault Folder</button><button class="btn" data-act="repair">Repair</button></div>
      ${folders.map((f) => `<div class="folder-row"><span class="okcirc ${f.ok ? "" : "bad"}">${f.ok ? I.check : "!"}</span><div class="grow"><div style="font-weight:600">${esc(fname[f.key] || f.name)}</div>
        <div class="mono muted selectable" style="font-size:12px">${esc(f.path)}</div>${f.ok ? "" : `<div class="small" style="color:var(--red)">${esc(f.error || "Can't be used.")}</div>`}</div>
        <button class="iconbtn" data-act="reveal" data-p="${esc(f.path)}" title="Show in File Explorer">${I.folder.replace('fill="currentColor"', 'fill="none" stroke="currentColor" stroke-width="1.6"')}</button></div>`).join("")}
      ${chk("watch_downloads", "Restore files I download from my AI tool automatically (Downloads folder)")}
      <label class="chk"><input type="checkbox" data-act="ui-bool" data-k="clipboard_watch" ${S.ui.clipboard_watch !== false ? "checked" : ""}><span>Offer to restore AI answers I copy (clipboard)</span></label>
      <p class="faint small" style="margin-top:6px">Tip: in File Explorer, right-click the PII Vault folder and choose Pin to Quick access so it's always one click away.</p></div>

    <div class="card">${updateCard()}</div>

    <div class="card"><div class="mcard-title"><h2>About</h2></div>
      <div class="mrow"><span class="k">Engine version</span><span class="v">${esc(d.version || (S.boot && S.boot.version) || "")}</span></div>
      <div class="mrow"><span class="k">Python</span><span class="v">${d.python ? esc(d.python) + " (built in)" : ""}</span></div>
      <div class="mrow"><span class="k">Vault encryption</span><span class="v">AES (Fernet), key in Windows Credential Manager</span></div>
      <div class="mrow"><span class="k">Vault location</span><span class="v selectable">${esc(S.boot && S.boot.app_data || "")}</span></div>
      ${(d.warnings || []).map((w) => `<div class="note small" style="margin-top:10px">${esc(w)}</div>`).join("")}</div>
    <div class="row"><button class="btn" data-act="recheck">Re-check</button><button class="btn" data-act="welcome-again">Show Welcome Again</button></div>`;
}
function updateCard() {
  const u = S.update || {};
  const cur = S.boot ? S.boot.version : "";
  let body;
  if (S.updateProg) {
    const p = S.updateProg;
    body = p.error ? `<div class="warn small">${esc(p.error)}</div>` : p.installing ? `<div class="row"><div class="spinner" style="width:18px;height:18px;border-width:2px"></div><b>Installing. PII Vault will reopen by itself.</b></div>` :
      `<div class="col"><b>Downloading the update</b><div class="progress"><div style="width:${Math.round((p.fraction || 0) * 100)}%"></div></div></div>`;
  } else if (u.state === "available") {
    body = `<div class="row"><span style="color:var(--accent);width:20px;height:20px">${I.down}</span><b style="color:var(--accent)" class="grow">Version ${esc(u.version)} is ready to install.</b>
      <button class="btn primary" data-act="update-install">Install Update</button></div>`;
  } else if (u.state === "error") {
    body = `<div class="row"><span class="grow muted">${esc(u.message)}</span><button class="btn" data-act="update-check">Check Again</button></div>`;
  } else {
    body = `<div class="row"><span class="okcirc">${I.check}</span><span class="grow" style="color:var(--green);font-size:15px">You have the latest version.</span>
      <button class="btn" data-act="update-check">Check Again</button></div>`;
  }
  return `<div class="mcard-title"><h2>Updates</h2>${info("updates")}<span class="spacer"></span><span class="muted small">This PC has version ${esc(cur)}</span></div>${body}`;
}

// ---- local model card (Settings) and Ollama setup (Welcome + Settings)
function localModelCard() {
  const m = S.models || {};
  const running = S.ollama.state === "running";
  let h = `<div class="mcard-title"><h2>Local model</h2>${info("localmodel")}<span class="spacer"></span>
    <span class="pill ${running ? "green" : "amber"}">${running ? "✓ Ollama running" : "Ollama not running"}</span></div>`;
  if (!running) return h + `<p class="muted" style="margin-bottom:10px">Once Ollama is running, choose a model here.</p>` + ollamaSetup(true);
  const cat = m.catalog || [];
  h += `<p class="muted" style="margin-bottom:6px">Choose a model. Only these are offered, to keep downloads small.</p>`;
  for (const c of cat) {
    const on = S.cfg.local_model === c.name;
    const pulling = S.ollama.pull && S.ollama.pull.model === c.name;
    h += `<div class="model ${on && c.installed ? "on" : ""}" ${c.installed ? `data-act="model" data-k="${esc(c.name)}"` : ""}>
      <span style="color:var(--accent);opacity:${c.installed ? 1 : .45}">${on && c.installed ? I.check.replace("<svg", '<svg style="width:18px;height:18px"') : '<svg viewBox="0 0 24 24" style="width:18px;height:18px" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/></svg>'}</span>
      <div class="grow"><div class="row" style="gap:8px"><b>${esc(c.title)}</b>${c.recommended ? `<span class="pill blue">Recommended</span>` : ""}</div>
      <div class="muted small">${esc(c.blurb.replace("Macs", "PCs"))}</div><div class="faint small">${c.size_gb.toFixed(1)} GB download · ${c.ram_gb} GB+ memory</div>
      ${pulling ? `<div class="progress" style="margin-top:6px"><div style="width:${Math.round(S.ollama.pull.fraction * 100)}%"></div></div>` : ""}</div>
      ${c.installed ? (on ? `<span class="pill green">In use</span>` : `<button class="btn small" data-act="model" data-k="${esc(c.name)}">Use</button>`) :
        `<button class="btn dlbtn" data-act="pull" data-k="${esc(c.name)}" ${S.ollama.pull ? "disabled" : ""}>${I.dlc}${pulling ? Math.round(S.ollama.pull.fraction * 100) + "%" : "Download " + c.size_gb.toFixed(1) + " GB"}</button>`}</div>`;
  }
  const others = (m.installed || []).filter((n) => !cat.some((c) => c.name === n || c.name + ":latest" === n));
  if (others.length) h += `<div class="row" style="margin-top:10px"><span>Or use a model you already have</span>
    <select data-act="model-select" style="min-width:240px"><option value="">Choose</option>${others.map((n) => `<option ${S.cfg.local_model === n ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>`;
  if (S.ollama.error) h += `<div class="warn small" style="margin-top:10px">${esc(S.ollama.error)}</div>`;
  return h;
}
function recommended() { return ((S.models && S.models.catalog) || []).find((c) => c.recommended) || { name: "qwen3:4b", title: "Qwen 3 (4B)", size_gb: 2.5 }; }
function hasModel() {
  const inst = (S.models && S.models.installed) || [];
  return inst.some((n) => n === S.cfg.local_model || n === S.cfg.local_model + ":latest") ||
    ((S.models && S.models.catalog) || []).some((c) => c.installed);
}
function ollamaSetup(inSettings = false) {
  const o = S.ollama;
  if (o.skipped && !inSettings) return `<p class="muted">Skipped. You can set it up any time in Settings.</p>`;
  if (o.state === "checking") return `<div class="row muted"><div class="spinner" style="width:16px;height:16px;border-width:2px"></div>Looking for Ollama on this PC</div>`;
  if (o.state === "not_installed") {
    if (o.started) return `<b>Your download has started. Then:</b><ol class="numbered" style="margin-top:8px">
        <li>Open the Ollama download (OllamaSetup.exe, usually in Downloads).</li>
        <li>Click Install. If Windows asks whether to allow it, click Yes.</li>
        <li>Ollama opens by itself when it's done. Its llama icon shows up next to the clock.</li></ol>
        <p class="small"><a data-act="ollama-page">Download didn't start? Go to the download page</a></p>
        <div class="row muted small" style="margin-top:6px"><div class="spinner" style="width:14px;height:14px;border-width:2px"></div>Waiting for Ollama. This screen moves on by itself.</div>`;
    return `<b>Ollama isn't on this PC yet.</b><p class="muted small" style="margin:4px 0 10px">Ollama is a free app that runs a small AI model privately on this PC. PII Vault uses it to catch names that have no label in front of them, like a name in the middle of a sentence. Setup takes about 5 minutes. PII Vault still works without it.</p>
      <div class="row"><button class="btn primary" data-act="ollama-download">Download Ollama</button>${inSettings ? "" : `<button class="btn link" data-act="ollama-skip">Skip for now</button>`}</div>`;
  }
  if (o.state === "installed") {
    return `<b>Ollama is installed but not open.</b><div class="row" style="margin-top:8px"><button class="btn primary" data-act="ollama-open" ${o.opening ? "disabled" : ""}>Open Ollama</button>
      ${o.opening ? `<span class="muted small">Opening. This can take a few seconds the first time.</span>` : ""}</div>
      <p class="faint small" style="margin-top:8px">Tip: Ollama starts by itself when you sign in to Windows, so you only do this once.</p>`;
  }
  if (inSettings) return "";
  if (o.pull) {
    return `<b>Downloading ${esc(recommended().title)}</b><div class="progress" style="margin:8px 0"><div style="width:${Math.round(o.pull.fraction * 100)}%"></div></div>
      <p class="muted small">${Math.round(o.pull.fraction * 100)}%. You can keep going while it downloads.</p>`;
  }
  if (!hasModel()) {
    const r = recommended();
    return `<b>Ollama is running. Last step: download the model.</b><div class="row" style="margin-top:8px"><div class="grow"><b>${esc(r.title)}</b>
      <div class="muted small">${(r.size_gb || 2.5).toFixed(1)} GB download. Runs only on this PC.</div></div>
      <button class="btn primary" data-act="pull" data-k="${esc(r.name)}">Download Model</button></div>
      <p class="faint small" style="margin-top:6px">Other models are in Settings › Names in free text.</p>
      ${o.error ? `<div class="warn small" style="margin-top:8px">${esc(o.error)}</div>` : ""}`;
  }
  const t = ((S.models.catalog || []).find((c) => c.name === S.cfg.local_model) || {}).title || S.cfg.local_model;
  return `<div class="ok">All set. Names are found with ${esc(t || "your local model")}.</div>`;
}

// ---------------------------------------------------------------- sheets (Welcome, Migration)
function renderSheet() {
  const mig = S.boot && S.boot.setup && S.boot.setup.migration;
  if (S.welcome) {
    $("#sheet").innerHTML = `<div class="sheet-bg"><div class="sheet">
      <div class="hero"><img src="icon.png" alt=""><div><h1>Welcome to PII Vault</h1>
      <p class="muted" style="margin-top:4px">Use ChatGPT, Copilot, Gemini, Claude, or any AI tool on files with student or personal data, without the AI ever seeing the real names.</p></div></div>
      <div class="card"><h3>Which AI tool do you use?</h3><div style="margin:8px 0">${toolPicker()}</div>
        <p class="muted small">This only sets the Open button. Protecting and restoring work the same with any tool.</p></div>
      <div class="card"><div class="row"><span style="color:#4a90e2;width:26px">${I.folder}</span><h3 class="grow">Everything is saved in one place: your home folder › PII Vault</h3>
        <button class="btn small" data-act="show-folder" data-k="home">Show</button></div>
        <p class="muted small" style="margin-top:6px">PII Vault made this folder for you. Protected copies go in For AI, restored files in Restored. If your AI tool can work with folders on your PC (like Claude's Cowork mode), give it the For AI folder only and its work is restored automatically. Files you download from it are restored automatically too.</p>
        <p class="small" style="margin-top:6px;color:var(--red)">Your original files are never moved or changed. Never upload anything from the Restored folder to an AI tool.</p></div>
      <div class="card"><div class="row" style="margin-bottom:6px"><h3 class="grow">Recommended: better name finding</h3>${info("localmodel")}</div>
        <p class="muted small" style="margin-bottom:10px">PII Vault checks this PC for Ollama, the free app that runs a private name-finding model.</p>${ollamaSetup(false)}</div>
      <div class="row"><span class="faint small grow">Everything runs on this PC.</span><button class="btn primary big" data-act="welcome-done">Get Started</button></div>
    </div></div>`;
  } else if (mig && (mig.from || []).length && !S.migShown) {
    $("#sheet").innerHTML = `<div class="sheet-bg"><div class="sheet"><h1>Your PII Vault folder moved</h1>
      <p>Everything now lives in one place: your home folder > PII Vault.</p>
      <p class="muted">PII Vault moved ${plural(mig.moved || 0, "item")}. Your jobs still restore as before.</p>
      <p class="muted small">If you gave your AI tool the old For AI folder (for example in Claude's Cowork mode), connect the new one instead: PII Vault > For AI.</p>
      ${(mig.left_behind || []).length ? `<div class="note small"><b>These couldn't be moved and are still in their old place:</b><br>${mig.left_behind.map(esc).join("<br>")}</div>` : ""}
      <div class="row"><button class="btn" data-act="show-folder" data-k="home">Show PII Vault Folder</button><span class="spacer"></span><button class="btn primary" data-act="mig-ok">OK</button></div></div></div>`;
  } else $("#sheet").innerHTML = "";
}

// ------------------------------------------------------------------ actions
const A = {
  nav(el) { S.page = el.dataset.k; if (S.page === "jobs") loadJobs(); if (S.page === "settings") { loadDoctor(); loadModels(); } render(); $("#scroll").scrollTop = 0; },
  info(el) { popover(el, el.dataset.k); },
  async pick() {
    const r = await tryCall("choose_files", "protect");
    if (r && r.files.length) addFiles(r.files);
  },
  "paste-open"() { S.pasteOpen = true; render(); setTimeout(() => $("#paste-text") && $("#paste-text").focus(), 30); },
  "paste-cancel"() { S.pasteOpen = false; render(); },
  async "paste-go"() {
    const t = ($("#paste-text").value || "").trim();
    if (!t) return;
    const r = await tryCall("paste_to_file", t);
    if (r) { S.pastes.push(r.file); S.pasteOpen = false; addFiles([r.file]); }
  },
  "remove-file"(el) {
    const f = el.dataset.f;
    S.files = S.files.filter((x) => x !== f);
    if (S.scan) S.scan.files = S.scan.files.filter((x) => x.file !== f);
    delete S.plan[f]; delete S.reviews[f]; delete S.added[f];
    if (S.pastes.includes(f)) { call("forget_paste", f); S.pastes = S.pastes.filter((x) => x !== f); }
    if (!S.files.length) S.stage = "add";
    render();
  },
  "col-action"(el) {
    const { f, s, h } = el.dataset;
    S.plan[f] = S.plan[f] || {}; S.plan[f][s] = S.plan[f][s] || {};
    S.plan[f][s][h] = el.value; render();
  },
  extra(el) { S.plan[el.dataset.f] = S.plan[el.dataset.f] || {}; S.plan[el.dataset.f]._extra = el.dataset.v; render(); },
  "text-tab"(el) {
    const p = (S.plan[el.dataset.f] = S.plan[el.dataset.f] || {});
    p._text_sheets = p._text_sheets || {}; p._text_sheets[el.dataset.s] = el.checked; render();
  },
  async "header-row"(el) {
    const { f, s } = el.dataset;
    const n = Math.max(0, parseInt(el.value || "0", 10));
    S.options[f] = S.options[f] || { _header_rows: {} };
    S.options[f]._header_rows[s] = n;
    const p = (S.plan[f] = S.plan[f] || {}); p._header_rows = { ...(p._header_rows || {}), [s]: n }; delete p[s];
    busy("Looking for personal information");
    try {
      const r = await call("scan", [f], { [f]: S.options[f] });
      S.scan.files = S.scan.files.map((x) => (x.file === f ? r.files[0] : x));
    } catch (e) { toast(e.message, "err"); }
    busy(""); render();
  },
  finding(el) {
    const { f, i } = el.dataset;
    const g = S.scan.files.find((x) => x.file === f).findings[+i];
    S.reviews[f] = S.reviews[f] || {}; S.reviews[f][g.value] = el.checked; render();
  },
  "add-value"(el) {
    const f = el.dataset.f;
    const inp = document.querySelector(`[data-add-input="${CSS.escape(f)}"]`);
    const cat = document.querySelector(`[data-add-cat="${CSS.escape(f)}"]`).value;
    const v = (inp.value || "").trim();
    if (v.length < 2) return;
    S.added[f] = S.added[f] || []; S.added[f].push({ value: v, category: cat }); render();
  },
  unadd(el) { S.added[el.dataset.f].splice(+el.dataset.i, 1); render(); },
  async "toggle-review"(el) {
    await tryCall("config_set", "review_unstructured", el.checked);
    S.cfg.review_unstructured = el.checked;
    await rescanAll();
  },
  "want-pdf"(el) { S.wantPdf = el.checked; },
  "start-over"() { resetJob(); render(); },
  "back-review"() { S.stage = "review"; render(); },
  async protect() {
    S.prompt = ($("#prompt") || {}).value ?? S.prompt;
    const plan = buildPlan();
    const docs = S.scan.files.some((f) => ["word", "pdf", "text"].includes(f.kind));
    busy("Removing personal information", docs ? "Reading every paragraph, table, header, footer and comment" : "");
    try {
      const job = await call("sanitize", S.files, S.prompt, plan, S.wantPdf, false);
      S.job = job; S.results = []; S.stage = "sent";
      S.promptAutoCopied = job.status !== "blocked" && !!(await api().copy_text(job.cowork_prompt)).ok;
      for (const p of S.pastes) call("forget_paste", p);
      S.pastes = [];
      loadJobs();
    } catch (e) { toast(e.message, "err"); }
    busy(""); render(); $("#scroll").scrollTop = 0;
  },
  async "copy-files"(el) {
    const r = await tryCall("copy_files", S.job.sanitized_dir);
    if (r) { flash(el, "Files Copied"); toast(`${plural(r.count, "file")} copied. Click in ${toolName()}'s message box and press Ctrl+V.`); }
  },
  async "copy-prompt"(el) {
    const r = await tryCall("copy_text", S.job.cowork_prompt);
    if (r) { flash(el, "Prompt Copied"); toast(`Prompt copied. Paste it into ${toolName()} with Ctrl+V, then send.`); }
  },
  async "open-tool"() { await tryCall("open_tool", S.cfg.ai_tool); },
  async reveal(el) { await tryCall("reveal", el.dataset.p); },
  async open(el) { await tryCall("open_path", el.dataset.p); },
  async "show-folder"(el) { await tryCall("show_folder", el.dataset.k); },
  async "pick-restore"() {
    const r = await tryCall("choose_files", "restore");
    if (r && r.files.length) restoreFiles(r.files, S.page === "jobs" ? (S.selJob || null) : undefined);
  },
  "answer-toggle"() { S.answerOpen = !S.answerOpen; },
  async "restore-text"(el) {
    const t = ($("#answer-text").value || "").trim();
    if (!t) return;
    busy("Putting the real data back");
    try {
      const r = await call("restore_text", t, el.dataset.j || null);
      addResults(r.processed || [], el.dataset.j || null);
      S.answerOpen = false;
    } catch (e) { toast(e.message, "err"); }
    busy(""); render();
  },
  async "check-output"() {
    busy("Putting the real data back");
    const r = await tryCall("process_outputs");
    busy("");
    if (r) {
      const items = r.processed || [];
      if (!items.length) toast("Nothing new to restore.");
      else App.onProcessed(items);
    }
    render();
  },
  "sel-job"(el) { S.selJob = el.dataset.j; render(); },
  async "refresh-jobs"() {
    const r = await tryCall("process_outputs");
    if (r && (r.processed || []).length) App.onProcessed(r.processed);
    await loadJobs(); render();
  },
  async recheck() { busy("Setting up"); const r = await tryCall("repair"); if (r) S.boot.setup = r; await loadDoctor(); await loadModels(); busy(""); render(); },
  async "job-copy-files"(el) {
    const r = await tryCall("copy_files", el.dataset.p);
    if (r) toast(`${plural(r.count, "file")} copied. Click in ${toolName()}'s message box and press Ctrl+V.`);
  },
  async "job-copy-prompt"(el) {
    const j = S.jobs.find((x) => x.id === el.dataset.j);
    if (j && await tryCall("copy_text", j.cowork_prompt)) toast(`Prompt copied. Paste it into ${toolName()}.`);
  },
  "job-open"(el) {
    const j = S.jobs.find((x) => x.id === el.dataset.j);
    if (!j) return;
    resetJob(); S.job = j; S.stage = "sent"; S.page = "new";
    S.results = Object.values(j.outputs || {});
    render();
  },
  async tool(el) {
    S.cfg.ai_tool = el.dataset.k; render();
    await tryCall("config_set", "ai_tool", el.dataset.k);
  },
  async "ui-bool"(el) {
    S.ui[el.dataset.k] = el.checked; render();
    await tryCall("ui_set", el.dataset.k, el.checked);
  },
  async "clip-restore"() {
    const job = (S.page === "new" && S.stage === "sent" && S.job) ? S.job.id :
      ((S.jobs || []).find((j) => ["sent", "complete"].includes(j.status)) || {}).id || null;
    $("#clipcard").innerHTML = "";
    busy("Putting the real data back");
    try {
      const r = await call("restore_clipboard", job);
      addResults(r.processed || [], job);
      const ok = (r.processed || []).find((x) => !x.error);
      if (ok && !(S.page === "new" && S.stage === "sent")) toast(`Restored ${base(ok.file)}. Saved in PII Vault > Restored.`, "good");
    } catch (e) { toast(e.message, "err"); }
    busy(""); render();
  },
  async "clip-dismiss"() { $("#clipcard").innerHTML = ""; await tryCall("dismiss_clipboard"); },
  async "cfg-bool"(el) {
    S.cfg[el.dataset.k] = el.checked; render();
    await tryCall("config_set", el.dataset.k, el.checked);
    if (el.dataset.k === "use_local_model") loadDoctor();
  },
  async model(el) {
    S.cfg.local_model = el.dataset.k; render();
    await tryCall("config_set", "local_model", el.dataset.k); loadDoctor();
  },
  async "model-select"(el) {
    if (!el.value) return;
    S.cfg.local_model = el.value; render();
    await tryCall("config_set", "local_model", el.value); loadDoctor();
  },
  async pull(el) {
    S.ollama.error = null;
    S.ollama.pull = { model: el.dataset.k, fraction: 0 }; render();
    await tryCall("pull_model", el.dataset.k);
  },
  async "ollama-download"() { S.ollama.started = true; render(); await tryCall("ollama_download"); },
  async "ollama-page"() { await tryCall("ollama_download_page"); },
  async "ollama-open"() {
    S.ollama.opening = true; render();
    const r = await tryCall("ollama_open");
    if (r && !r.ok) { S.ollama.opening = false; toast("Make sure the Ollama app is installed, then try again.", "err"); render(); }
  },
  "ollama-skip"() { S.ollama.skipped = true; render(); },
  async "welcome-done"() {
    S.welcome = false; render();
    await tryCall("ui_set", "welcome_done", true);
  },
  "welcome-again"() { S.welcome = true; S.ollama.skipped = false; render(); },
  async "mig-ok"() { S.migShown = true; render(); await tryCall("ack_migration"); },
  async repair() {
    busy("Setting up");
    const r = await tryCall("repair");
    busy("");
    if (r) {
      S.boot.setup = r;
      toast(r.folders_ok ? "Folders are set up." : "Some folders still can't be used.", r.folders_ok ? "good" : "err");
    }
    render();
  },
  async ransomware() { await tryCall("open_ransomware_settings"); },
  async "update-check"() {
    const r = await tryCall("update_check", true);
    if (r) { S.update = r; if (r.state === "latest") toast("You have the latest version."); }
    render();
  },
  async "update-install"() { S.updateProg = { fraction: 0 }; render(); const r = await tryCall("update_install"); if (!r) { S.updateProg = null; render(); } },
};
function flash(el, text) {
  const old = el.innerHTML;
  el.classList.add("done"); el.innerHTML = I.check + text;
  setTimeout(() => { el.classList.remove("done"); el.innerHTML = old; }, 1800);
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.tagName === "SELECT" || (el.tagName === "INPUT" && el.type !== "button")) return;
  const fn = A[el.dataset.act];
  if (fn) { if (el.tagName !== "SUMMARY") e.preventDefault(); fn(el); }
});
document.addEventListener("change", (e) => {
  const el = e.target.closest("[data-act]");
  if (el && (el.tagName === "SELECT" || el.tagName === "INPUT") && A[el.dataset.act]) A[el.dataset.act](el);
});
document.addEventListener("input", (e) => { if (e.target.id === "prompt") S.prompt = e.target.value; });
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.dataset && e.target.dataset.addInput) {
    A["add-value"]({ dataset: { f: e.target.dataset.addInput } });
  }
  if (e.key === "Escape") $("#popover").innerHTML = "";
});

// ---- drag and drop: the page highlights the zone; Python reads the real file paths (App.onDrop)
let hotZone = null;
document.addEventListener("dragover", (e) => {
  e.preventDefault();
  const z = e.target.closest && e.target.closest("[data-zone]");
  document.querySelectorAll("[data-zone]").forEach((d) => d.classList.toggle("hot", d === z));
  hotZone = z ? z.dataset.zone : null;
});
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.querySelectorAll(".drop.hot").forEach((d) => d.classList.remove("hot")); });
document.addEventListener("drop", (e) => {
  e.preventDefault();
  document.querySelectorAll(".drop.hot").forEach((d) => d.classList.remove("hot"));
  setTimeout(() => { hotZone = hotZone; }, 0);
});

// ------------------------------------------------------------------ flows
function resetJob() {
  for (const p of S.pastes) call("forget_paste", p);
  Object.assign(S, { stage: "add", files: [], scan: null, options: {}, plan: {}, reviews: {}, added: {}, pastes: [],
    prompt: "", wantPdf: false, job: null, results: [], pasteOpen: false, answerOpen: false });
}
async function addFiles(paths) {
  if (S.stage === "sent") resetJob();
  const fresh = paths.filter((p) => !S.files.includes(p));
  if (!fresh.length) return;
  S.page = "new";
  const docs = fresh.some((p) => /\.(docx|pdf|txt|md|markdown|rtf|text)$/i.test(p));
  busy(docs && S.cfg.review_unstructured !== false ? "Reading your documents for personal information" : "Looking for personal information",
    docs && S.cfg.use_local_model ? "The local model reads every sentence, so long documents take a minute." : "");
  try {
    const r = await call("scan", fresh, S.options);
    S.files.push(...fresh);
    S.scan = S.scan ? { ...r, files: [...S.scan.files, ...r.files] } : r;
    for (const f of r.files) if (f.kind === "table" && f.has_text_sheets) {
      S.plan[f.file] = S.plan[f.file] || {}; S.plan[f.file]._text_sheets = S.plan[f.file]._text_sheets || {};
    }
    S.stage = "review";
  } catch (e) { toast(e.message, "err"); }
  busy(""); render();
}
async function rescanAll() {
  if (!S.files.length) { render(); return; }
  busy("Looking for personal information");
  try { S.scan = await call("scan", S.files, S.options); } catch (e) { toast(e.message, "err"); }
  busy(""); render();
}
function buildPlan() {
  const plan = {};
  for (const f of S.scan.files) {
    const p = JSON.parse(JSON.stringify(S.plan[f.file] || {}));
    if (S.options[f.file] && S.options[f.file]._header_rows) p._header_rows = { ...S.options[f.file]._header_rows, ...(p._header_rows || {}) };
    if (["word", "pdf", "text"].includes(f.kind) && S.scan.review) {
      const rv = S.reviews[f.file] || {};
      const values = {}, ignore = [];
      for (const g of f.findings || []) (rv[g.value] === false ? ignore.push(g.value) : (values[g.value] = g.category.replace("~", "")));
      for (const a of S.added[f.file] || []) values[a.value] = a.category;
      p._review = { values, ignore };
    }
    plan[f.file] = p;
  }
  return plan;
}
async function restoreFiles(paths, jobOverride) {
  const job = jobOverride !== undefined ? jobOverride : (S.page === "new" && S.stage === "sent" && S.job ? S.job.id : null);
  busy("Putting the real data back");
  try {
    const r = await call("restore", paths, job);
    addResults(r.processed || [], job);
  } catch (e) { toast(e.message, "err"); }
  busy(""); render();
}
function addResults(items, job) {
  const target = job && S.job && job === S.job.id ? S.results : S.restoreResults;
  for (const it of items) {
    const i = target.findIndex((x) => x.file && x.file === it.file);
    if (i >= 0) target[i] = it; else target.unshift(it);
  }
  const ok = items.filter((x) => !x.error);
  if (ok.length) toast(`Restored ${ok.length === 1 ? base(ok[0].file) : plural(ok.length, "file")}. Saved in PII Vault > Restored.`, "good");
  for (const x of items.filter((x) => x.error)) toast(`${base(x.source)}: ${x.error}`, "err");
  loadJobs();
}
async function loadJobs() { const r = await tryCall("jobs"); if (r) { S.jobs = r.jobs || []; if (S.page === "jobs") render(); } }
async function loadDoctor() { const r = await tryCall("doctor"); if (r) { S.doctor = r; if (r.config) S.cfg = r.config; render(); } }
async function loadModels() {
  try { const r = await call("models"); S.models = r; S.ollama.state = r.ollama_state; if (r.selected) S.cfg.local_model = r.selected; }
  catch { /* Ollama status stays as it was */ }
  render();
}
let ollamaTimer = null;
function watchOllama() {
  clearInterval(ollamaTimer);
  ollamaTimer = setInterval(async () => {
    if (!(S.welcome || S.page === "settings")) return;
    const before = S.ollama.state;
    const r = await api().ollama_state();
    if (r && r.state && r.state !== before) { S.ollama.state = r.state; if (r.state === "running") { S.ollama.opening = false; await loadModels(); } else render(); }
  }, 3000);
}

// ------------------------------------------------------------------ pushed from Python
window.App = {
  onDrop(paths) {
    const zone = hotZone || (S.page === "restore" || S.page === "jobs" || (S.page === "new" && S.stage === "sent") ? "restore" : "protect");
    hotZone = null;
    if (S.welcome) return;
    if (zone === "restore") restoreFiles(paths);
    else addFiles(paths);
  },
  onProcessed(items) {
    for (const it of items) {
      if (S.job && it.job === S.job.id) addResults([it], S.job.id);
      else addResults([it], null);
    }
    render();
  },
  onClipboardAnswer(c) {
    if (S.welcome) return;
    $("#clipcard").innerHTML = `<div class="clipcard"><div class="row" style="align-items:flex-start;gap:12px">
      <span style="width:26px;height:26px;color:var(--accent);flex:none">${I.restore}</span>
      <div class="grow"><b>Restore the AI answer you copied?</b>
      <div class="muted small">${plural(c.tokens, "token")} found · ${c.chars.toLocaleString()} characters</div>
      <div class="small clip-preview">${esc(c.preview)}</div></div></div>
      <div class="row" style="margin-top:12px"><span class="spacer"></span><button class="btn" data-act="clip-dismiss">Not Now</button>
      <button class="btn primary" data-act="clip-restore">Restore</button></div></div>`;
  },
  onPullProgress(p) { S.ollama.pull = { model: p.model, fraction: p.fraction || 0 }; render(); },
  async onPullDone(p) {
    S.ollama.pull = null;
    if (p.error) S.ollama.error = p.error;
    else { S.cfg.local_model = p.model; S.cfg.use_local_model = true; toast("Model downloaded. Names are found with your local model.", "good"); }
    await loadModels(); loadDoctor();
  },
  onUpdateProgress(p) {
    if (p.error) { S.updateProg = null; S.update = { state: "error", message: p.error }; toast(p.error, "err"); }
    else S.updateProg = p;
    render();
  },
};

// ------------------------------------------------------------------ start
async function start() {
  busy("Setting up");
  try {
    S.boot = await call("boot");
    S.cfg = S.boot.config || {};
    S.ui = S.boot.ui || {};
    S.welcome = !(S.boot.ui && S.boot.ui.welcome_done);
  } catch (e) {
    busy(""); $("#page").innerHTML = `<div class="card warn"><h2>Engine not set up</h2><p>${esc(e.message)}</p></div>`; return;
  }
  busy(""); render();
  loadJobs(); loadModels(); watchOllama();
  tryCall("update_check", false).then((r) => { if (r) { S.update = r; render(); if (r.state === "available") toast(`A new version of PII Vault is ready. Open Settings to install it.`); } });
  setTimeout(loadDoctor, 1500);
}
if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start);
