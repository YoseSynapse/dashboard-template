/* V.R World Media posting dashboard — shared helpers (vanilla JS, no deps). */
"use strict";

/* ---------- fetch wrapper ---------- */
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined && body !== null && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body; // fetch sets multipart boundary itself
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("Cannot reach the dashboard server. Is it running on port 8077? (" + e.message + ")");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON body */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.error || data.message)) || ("HTTP " + res.status);
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}
const get = (p) => api("GET", p);
const post = (p, b) => api("POST", p, b);
const del = (p) => api("DELETE", p);

/* ---------- labels ---------- */
const BRANDS = {
  quiet_position: { name: "Faceless Wicks (Quiet Position)", handle: "@facelesswicksofficial" },
  the_odds_board: { name: "The Odds Board", handle: "@hqtheoddsboardofficial" },
  heist:          { name: "heistHQ365", handle: "@Heisthq365official" },
  jose_personal:  { name: "Jose (personal)", handle: "@yos_ego" }
};
const PLATFORMS = {
  tiktok: "TikTok", x: "X", instagram: "Instagram", youtube: "YouTube"
};
const STATUSES = ["draft", "pending_approval", "approved", "scheduled", "published", "failed"];

const BRAND_HINTS = {
  quiet_position: "No broker affiliate links. Educational coverage only. Never promise profits or guaranteed outcomes. Binary-options coverage: honest explainers only, no funnels.",
  the_odds_board: "Zero outbound gambling-operator links. No bonuses, promos, or deposit CTAs. Free community only — no hype, no guarantees. Compliance cornerstone: Jose's own voice-over on faceless content.",
  heist: "Label ALL concept/fan art explicitly ([CONCEPT], [RUMOR]). Everything depicted in the thumbnail must appear in the video. Compliance cornerstone: Jose's own voice-over on faceless content.",
  jose_personal: "Personal brand — same company compliance rules apply. Affiliate links need clear FTC disclosure."
};

/* Title formulas are stored flat in composer_data.json, in brand order:
   0-14 = quiet_position, 15-29 = the_odds_board, 30-44 = heist */
const FORMULA_BRAND_RANGES = { quiet_position: [0, 14], the_odds_board: [15, 29], heist: [30, 44] };
function formulasFor(brand, all) {
  const r = FORMULA_BRAND_RANGES[brand];
  return r ? all.slice(r[0], r[1] + 1) : all;
}

/* ---------- formatting ---------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function brandLabel(b) { return BRANDS[b] ? BRANDS[b].name : b; }
function platformLabel(p) { return PLATFORMS[p] || p; }
function statusPill(s) { return '<span class="pill ' + esc(s) + '">' + esc(String(s).replace(/_/g, " ")) + "</span>"; }
function postBrand(p) { return p.brand || (p.account && p.account.brand) || ""; }
function postPlatforms(p) {
  if (p.platforms && p.platforms.length) return p.platforms;
  const accs = p.accounts || (p.account ? [p.account] : []);
  return accs.map(a => a.platform).filter(Boolean);
}

/* ---------- media preview ---------- */
function isVideoFilename(name) {
  return /\.(mp4|mov|m4v|webm)$/i.test(name || "");
}
function mediaPreviewHTML(filename, cls) {
  if (!filename) return '<p class="small">No media attached.</p>';
  const url = "/media/" + encodeURIComponent(filename);
  const c = cls ? "preview " + cls : "preview";
  if (isVideoFilename(filename)) {
    return '<video class="' + c + '" controls preload="metadata"><source src="' + esc(url) + '"></video>';
  }
  return '<img class="' + c + '" src="' + esc(url) + '" alt="media preview" loading="lazy">';
}

/* ---------- nav ---------- */
function renderNav(active) {
  const links = [
    ["index.html", "Home"], ["upload.html", "Upload"], ["compose.html", "Compose"],
    ["approve.html", "Approve"], ["audit.html", "Audit"]
  ];
  const nav = document.getElementById("nav");
  if (!nav) return;
  let html = '<span class="brand">V.R World Media</span>';
  links.forEach(([href, label]) => {
    html += '<a href="' + href + '"' + (href === active ? ' class="active"' : "") + ">" + label + "</a>";
  });
  nav.innerHTML = html;
}

/* ---------- composer data (cached) ---------- */
let _composerData = null;
async function getComposerData() {
  if (_composerData) return _composerData;
  try {
    _composerData = await get("/api/composer-data");
  } catch (e) {
    _composerData = { title_formulas: [], thumbnail_checklist: [], hook_templates: [], platform_limits: {} };
  }
  return _composerData;
}

/* ---------- accounts (cached) ---------- */
let _accounts = null;
async function getAccounts(refresh) {
  if (_accounts && !refresh) return _accounts;
  try { _accounts = await get("/api/accounts"); }
  catch (e) { _accounts = []; }
  return _accounts;
}

function showError(el, err) {
  if (typeof el === "string") el = document.getElementById(el);
  if (el) el.innerHTML = '<div class="banner red">⚠️ ' + esc(err && err.message ? err.message : err) + "</div>";
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
