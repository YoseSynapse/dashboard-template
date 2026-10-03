
/* =====================================================================
   app.js — V.R World Media Posting Dashboard (demo / Phase 1)
   ---------------------------------------------------------------------
   Plain vanilla JavaScript, no frameworks, no build step. The file is
   organized into numbered sections with big banner comments:

     1. THE API LAYER ......... every data operation goes through API
     2. COMPLIANCE ENGINE ..... brand safety rules (Tripwire Bible)
     3. UI HELPERS ............ small shared functions
     4. APP STATE ............. in-memory state (not persisted)
     5. VIEW: UPLOAD
     6. VIEW: COMPOSE
     7. VIEW: QUEUE
     8. VIEW: APPROVALS
     9. VIEW: AUDIT LOG
    10. NAVIGATION + INIT

   HOW THE VIEWS WORK:
   index.html has five <section> elements, one per view. Each render
   function below rebuilds its section's inner HTML from scratch.
   showView() switches which section is visible and re-renders it, so
   the screen is always fresh. Buttons use inline onclick="..." handlers
   that call the global functions defined here — the simplest pattern
   to read while learning.
   ===================================================================== */


/* =====================================================================
   1. THE API LAYER
   ---------------------------------------------------------------------
   EVERY read/write of posts, audit entries, and accounts goes through
   this object. The rest of the app never touches localStorage directly.

   RIGHT NOW: everything is stored in the browser's localStorage, so the
   page works from file:// with no server at all.

   *** PHASE 2: replace the body of each function below with fetch()
   calls to the Python backend (e.g. fetch('/api/posts')), keeping the
   SAME function names and return shapes. The rest of the app won't
   change — that is the whole point of this layer. ***

   localStorage keys:
     vrwm_posts     -> array of post objects
     vrwm_audit     -> array of audit entries
     vrwm_accounts  -> array of account objects (seeded on first run)

   A post looks like:
     { id, brand, platforms[], title, caption, hashtags, thumbnailNotes,
       scheduledAt (ISO string or null), publishNow (bool),
       labelsConceptArt (bool), mediaName, mediaSize,
       status, rejectionNote, createdAt, updatedAt }

   Post lifecycle:
     draft -> pending_approval -> approved / scheduled
                                     |
                                     +--> (Phase 2: published)
     rejected -> back to draft
   ===================================================================== */
const API = {
  // --- internal helpers (not part of the public API) ---
  _read(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      console.warn('Could not read ' + key + ':', e);
      return fallback;
    }
  },

  _write(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      console.warn('Could not save ' + key + ':', e);
    }
  },

  _newId() {
    // Simple unique id: timestamp + random bit, safe for HTML attributes.
    return 'p' + Date.now().toString(36) + Math.floor(Math.random() *
1e6).toString(36);
  },

  // --- posts ---
  listPosts() {
    return this._read('vrwm_posts', []);
  },

  getPost(id) {
    return this.listPosts().find(function (p) { return p.id === id; });
  },

  savePost(post) {
    // Creates a NEW post. Returns the saved post (with id + timestamps).
    const posts = this.listPosts();
    const now = new Date().toISOString();
    post.id = post.id || this._newId();
    post.createdAt = post.createdAt || now;
    post.updatedAt = now;
    posts.push(post);
    this._write('vrwm_posts', posts);
    return post;
  },

  updatePost(id, patch) {
    // Merges `patch` into the existing post. Returns the updated post.
    const posts = this.listPosts();
    const post = posts.find(function (p) { return p.id === id; });
    if (!post) return null;
    Object.assign(post, patch, { updatedAt: new Date().toISOString() });
    this._write('vrwm_posts', posts);
    return post;
  },

  deletePost(id) {
    const posts = this.listPosts().filter(function (p) { return p.id !== id; });
    this._write('vrwm_posts', posts);
  },

  // --- audit log ---
  listAudit() {
    return this._read('vrwm_audit', []);
  },

  logAudit(entry) {
    // entry: { brand, action, detail, postId }
    const log = this.listAudit();
    log.push({
      id: this._newId(),
      ts: new Date().toISOString(),
      brand: entry.brand || '',
      action: entry.action || '',
      detail: entry.detail || '',
      postId: entry.postId || ''
    });
    this._write('vrwm_audit', log);
  },

  // --- accounts ---
  getAccounts() {
    let accounts = this._read('vrwm_accounts', null);
    if (!accounts) {
      accounts = this._seedAccounts();
      this._write('vrwm_accounts', accounts);
    }
    return accounts;
  },

  _seedAccounts() {
    // Demo account list: 4 brands x 4 platforms = 16 accounts.
    // Handles come from the build plan. Real OAuth token wiring
    // (per-account encrypted token store) arrives in Phase 2.
    const brands = [
      { brand: 'quiet_position', handle: '@facelesswicks' },
      { brand: 'the_odds_board', handle: '@theoddsboardhq' },
      { brand: 'heist',          handle: '@heisthq365' },
      { brand: 'jose_personal',  handle: '@jose' }
    ];
    const platforms = ['tiktok', 'instagram', 'x', 'youtube'];
    const out = [];
    brands.forEach(function (b) {
      platforms.forEach(function (pl) {
        out.push({
          id: b.brand + '__' + pl,   // e.g. "heist__tiktok"
          brand: b.brand,
          platform: pl,
          handle: b.handle
        });
      });
    });
    return out;
  }
};


/* =====================================================================
   2. COMPLIANCE ENGINE
   ---------------------------------------------------------------------
   check(brand, title, caption, hashtags) -> { blocks: [], warnings: [] }

   These rules mirror the Tripwire Bible + this week's media research
   (SEO dossier, Ads dossier). Matching is a case-insensitive SUBSTRING
   search — simple and strict on purpose for a demo.

   - blocks:   the post CANNOT be submitted until fixed (red, submit
               button is disabled).
   - warnings: allowed through, but Jose should read them (amber).

   NOTE: the Heist concept-art rule is enforced in the Compose view
   (renderCompose) because it depends on a checkbox, not on text.
   ===================================================================== */
const Compliance = {
  check(brand, title, caption, hashtags) {
    const blocks = [];
    const warnings = [];

    // Combine all text fields into one lowercase blob to search.
    const text = (title + ' ' + caption + ' ' + hashtags).toLowerCase();

    // Helper: does the text contain this phrase (case-insensitive)?
    function has(phrase) {
      return text.indexOf(phrase.toLowerCase()) !== -1;
    }

    /* ---- QUIET POSITION (forex education — highest-risk brand) ----
       Educational coverage ONLY. No binary/broker funnels, no affiliate
       links. One slip here is the highest-risk item in the company. */
    if (brand === 'quiet_position') {
      const qpBlocks = [
        'pocket option', 'quotex', 'iq option', 'binomo',
        'olymptrade', 'olymp trade', 'exnova', 'deriv',
        'deposit bonus', 'affiliate link', 'sign up with my link', 'broker'
      ];
      qpBlocks.forEach(function (term) {
        if (has(term)) {
          blocks.push({
            rule: 'quiet_position / no-broker-funnels',
            message: 'Blocked term "' + term + '" — Quiet Position is educational coverage only. No binary/broker funnels or affiliate links.'
          });
        }
      });

      const qpWarns = ['guaranteed', 'get rich', '100% win',
'risk-free', "can't lose"];
      qpWarns.forEach(function (term) {
        if (has(term)) {
          warnings.push({
            rule: 'quiet_position / no-hype',
            message: 'Hype phrase "' + term + '" — income claims and"guaranteed" language attract regulator attention. Reword.'
          });
        }
      });
    }

    /* ---- THE ODDS BOARD (sports — free community positioning) ----
       Zero outbound gambling-operator links (YouTube Mar-2025 rule),
       no bonuses / promos / deposit CTAs. "No hype, no guarantees." */
    if (brand === 'the_odds_board') {
      const obBlocks = [
        'draftkings', 'fanduel', 'bet365', 'caesars', 'betmgm',
        'pointsbet', 'unibet', 'william hill', 'ladbrokes', 'paddy power',
        'promo code', 'free bet', 'deposit bonus'
      ];
      obBlocks.forEach(function (term) {
        if (has(term)) {
          blocks.push({
            rule: 'the_odds_board / no-operator-links',
            message: 'Blocked term "' + term + '" — zero gambling-operator links, bonuses, or promos on The Odds Board.'
          });
        }
      });

      const obWarns = ['lock of the', 'guaranteed', "can't lose"];
      obWarns.forEach(function (term) {
        if (has(term)) {
          warnings.push({
            rule: 'the_odds_board / no-hype',
            message: 'Hype phrase "' + term + '" — the brand positionis "no hype, no guarantees." Reword.'
          });
        }
      });
    }

    /* ---- ALL BRANDS ---- */
    if (has('financial advice')) {
      warnings.push({
        rule: 'all / financial-advice',
        message: '"financial advice" — add an educational/entertainment disclaimer; never present content as personal financial advice.'
      });
    }

    // TikTok allows max 100 hashtags. Count #tokens in the hashtags field.
    const tagCount = hashtags.split(/[\s,]+/).filter(function (t) {
      return t.charAt(0) === '#';
    }).length;
    if (tagCount > 100) {
      blocks.push({
        rule: 'tiktok / hashtag-limit',
        message: 'TikTok allows max 100 hashtags — you have ' +
tagCount + '. Trim the list.'
      });
    }

    return { blocks: blocks, warnings: warnings };
  }
};


/* =====================================================================
   3. UI HELPERS
   Small shared functions used by several views.
   ===================================================================== */

// Brand key -> pretty display name.
const BRAND_NAMES = {
  quiet_position: 'Quiet Position',
  the_odds_board: 'The Odds Board',
  heist: 'Heist',
  jose_personal: 'Jose Personal'
};

// Platform key -> pretty display name.
const PLATFORM_NAMES = {
  tiktok: 'TikTok',
  instagram: 'Instagram',
  x: 'X',
  youtube: 'YouTube'
};

// Per-brand hint shown at the top of the Compose view.
const BRAND_HINTS = {
  quiet_position: 'Educational coverage only — no binary/Pocket Option funnels, no broker affiliate links. Highest-risk item in the company.', 
  the_odds_board: 'Zero gambling-operator links. No bonuses, promos, or deposit CTAs. Free community — "no hype, no guarantees."',
  heist: 'Label ALL concept / fan art as [CONCEPT] or [RUMOR] on every upload.',
  jose_personal: 'Personal brand — standard tripwire rules apply to every post.'
};

// Escape user text before putting it into HTML. Prevents a caption
// containing < or > from breaking the page layout.
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// "2026-09-26T14:30" -> "Sat, Sep 26, 2026, 2:30 PM"
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    year: 'numeric', hour: 'numeric', minute: '2-digit'
  });
}

// "in 2h 15m" / "in 3d 4h" / "overdue by 20m" — countdown-ish label.
function timeUntil(iso) {
  if (!iso) return 'ready to publish now';
  const diff = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(diff);
  const mins = Math.floor(abs / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  let label;
  if (days >= 1) label = 'in ' + days + 'd ' + (hrs % 24) + 'h';
  else if (hrs >= 1) label = 'in ' + hrs + 'h ' + (mins % 60) + 'm';
  else label = 'in ' + mins + 'm';
  if (diff < 0) label = 'overdue by ' + label.slice(3);
  return label;
}

// Status key -> pill CSS class.
function pillClass(status) {
  return {
    draft: 'pill-draft',
    pending_approval: 'pill-pending',
    approved: 'pill-approved',
    scheduled: 'pill-scheduled',
    rejected: 'pill-rejected',
    published: 'pill-published'
  }[status] || 'pill-draft';
}

// Status key -> pretty label.
function statusLabel(status) {
  return {
    draft: 'Draft',
    pending_approval: 'Pending approval',
    approved: 'Approved',
    scheduled: 'Scheduled',
    rejected: 'Rejected',
    published: 'Published'
  }[status] || status;
}

// Read the current value of a form field by id (empty string if missing).
function val(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}

// Which platform checkboxes are ticked in the Compose view?
function selectedPlatforms() {
  return Array.prototype.slice
    .call(document.querySelectorAll('input[name="c-platform"]:checked'))
    .map(function (cb) { return cb.value; });
}


/* =====================================================================
   4. APP STATE
   In-memory only — nothing here is saved to localStorage. Anything that
   must survive a refresh lives in API instead.
   ===================================================================== */
let pendingMedia = null;   // { name, size } from the Upload view (file info only)
let editingDraftId = null; // when set, Compose is editing this draft
let auditBrandFilter = ''; // brand filter on the Audit Log view


/* =====================================================================
   5. VIEW: UPLOAD
   Pick a video/image file. We keep ONLY the name + size in memory —
   blobs (the actual file bytes) CANNOT be persisted to localStorage,
   so the file itself lives only for this page session. Phase 2's
   backend will accept the real file upload.
   ===================================================================== */
function renderUpload() {
  const root = document.getElementById('upload-root');

  const mediaLine = pendingMedia
    ? '<div class="banner">Selected: <strong>' +
esc(pendingMedia.name) + '</strong> ' +
      '(' + (pendingMedia.size / 1048576).toFixed(1) + ' MB) — file info held in memory only; ' +
      'the actual file is uploaded by the Phase-2 backend.</div>'
    : '';

  root.innerHTML =
    '<div class="panel">' +
      '<h2>Upload media</h2>' +
      '<p class="hint">Choose the finished video (with your voice-over baked in) or an image. ' +
      'One upload can be posted to all four brands / platforms from the Compose view.</p>' +
      '<label for="upload-file">Video or image file</label>' +
      '<input type="file" id="upload-file" accept="video/*,image/*" onchange="onFilePicked()">' +
      mediaLine +
      '<div class="button-row">' +
        '<button class="btn btn-primary" onclick="continueToCompose()" ' +
          (pendingMedia ? '' : 'disabled') + '>Continue to Compose</button>' +
      '</div>' +
      (pendingMedia ? '' : '<p class="hint">Pick a file first — the button unlocks once a file is selected.</p>') +
    '</div>';
}

// Runs when the user picks a file. Stores name + size in memory.
function onFilePicked() {
  const input = document.getElementById('upload-file');
  const file = input && input.files && input.files[0];
  if (file) {
    pendingMedia = { name: file.name, size: file.size };
  } else {
    pendingMedia = null;
  }
  renderUpload(); // re-render so the button unlocks
}

// Carry the file info into the Compose view.
function continueToCompose() {
  if (!pendingMedia) return;
  editingDraftId = null;
  showView('compose');
}


/* =====================================================================
   6. VIEW: COMPOSE
   The packaging + compliance workstation: brand, accounts, title,
   caption, hashtags, thumbnail notes, schedule, the 45 title formulas
   (click to insert), 20 hook templates (click to insert), the 15-item
   thumbnail checklist, and the LIVE compliance readout.

   FORMULA GROUPING (indices into COMPOSER_DATA.title_formulas):
     0–14  -> Quiet Position (forex / risk education)
     15–29 -> The Odds Board (odds / sportsbook education)
     30–44 -> Heist (GTA 6)
   This grouping matches the actual content of the formulas array.
   ===================================================================== */
function renderCompose() {
  const root = document.getElementById('compose-root');
  const accounts = API.getAccounts();
  const editing = editingDraftId ? API.getPost(editingDraftId) : null;

  // Current field values: from the draft being edited, or blank.
  const brand = editing ? editing.brand : 'quiet_position';
  const plats = editing ? editing.platforms : ['tiktok'];

  // --- brand select ---
  const brandOptions = Object.keys(BRAND_NAMES).map(function (key) {
    return '<option value="' + key + '"' + (key === brand ? 'selected' : '') + '>' +
      esc(BRAND_NAMES[key]) + '</option>';
  }).join('');

  // --- platform checkboxes for the chosen brand, labeled with handle ---
  const platformBoxes = accounts
    .filter(function (a) { return a.brand === brand; })
    .map(function (a) {
      const checked = plats.indexOf(a.platform) !== -1 ? ' checked' : '';
      return '<label class="check-row"><input type="checkbox"name="c-platform" value="' +   a.platform + '"' + checked + 'onchange="updateCompliance()"> ' + esc(PLATFORM_NAMES[a.platform]) + ' <small>' + esc(a.handle) +
'</small></label>';
    }).join('');

  // --- 45 title formulas, grouped by brand ---
  // Group boundaries (see banner comment above):
  const formulaGroups = [
    { name: 'Quiet Position', from: 0, to: 14 },
    { name: 'The Odds Board', from: 15, to: 29 },
    { name: 'Heist', from: 30, to: 44 }
  ];
  let formulaHtml = '';
  formulaGroups.forEach(function (g) {
    formulaHtml += '<li class="helper-group-title">' + g.name + '(formulas ' + (g.from + 1) + '–' + (g.to + 1) + ')</li>';
    for (let i = g.from; i <= g.to; i++) {
      formulaHtml += '<li onclick="insertFormula(' + i + ')"title="Click to insert into title">' +
        esc(COMPOSER_DATA.title_formulas[i]) + '</li>';
    }
  });

  // --- 20 hook templates (click to append to caption) ---
  const hookHtml = COMPOSER_DATA.hook_templates.map(function (hook, i) {
    return '<li onclick="insertHook(' + i + ')" title="Click to append to caption">' + esc(hook) + '</li>';
  }).join('');

  // --- 15 thumbnail checklist items ---
  const thumbHtml = COMPOSER_DATA.thumbnail_checklist.map(function (item, i) {
    return '<label class="check-row"><input type="checkbox"data-thumb="' + i + '" onchange="toggleThumbNote(this)"> ' +
      '<span>' + esc(item) + '</span></label>';
  }).join('');

  // --- pre-fill notes checkboxes when editing a draft ---
  const draftNotes = editing ? editing.thumbnailNotes : '';

  root.innerHTML =
    '<div class="banner">' + esc(BRAND_HINTS[brand]) + '</div>' +

    (pendingMedia
      ? '<div class="banner">Media attached: <strong>' +
esc(pendingMedia.name) + '</strong> ' +
        '(' + (pendingMedia.size / 1048576).toFixed(1) + ' MB)</div>'
      : '<div class="banner warn">No media attached — you can still draft the copy, ' +
        'or go back to Upload to pick a file first.</div>') +

    '<div class="panel">' +
      '<h2>' + (editing ? 'Edit draft' : 'Compose post') + '</h2>' +

      '<label for="c-brand">Brand</label>' +
      '<select id="c-brand" onchange="onBrandChange()">' +
brandOptions + '</select>' +

      '<label>Accounts (platforms)</label>' +
      '<div id="c-platforms">' + platformBoxes + '</div>' +

      '<label for="c-title">Title</label>' +
      '<input type="text" id="c-title" placeholder="Video title"value="' + esc(editing ? editing.title : '') + '"oninput="updateCompliance()">' +

      '<label for="c-caption">Caption / description</label>' +
      '<textarea id="c-caption" oninput="updateCompliance()">' +
esc(editing ? editing.caption : '') + '</textarea>' +
      '<p class="hint" id="c-capcount"></p>' +

      '<label for="c-hashtags">Hashtags</label>' +
      '<input type="text" id="c-hashtags" placeholder="#forex #riskmanagement …" value="' + esc(editing ? editing.hashtags : '') +
'" oninput="updateCompliance()">' +

      '<label for="c-thumbnotes">Thumbnail notes</label>' +
      '<textarea id="c-thumbnotes" placeholder="Notes for the thumbnail designer…">' + esc(draftNotes) + '</textarea>' +

      // Heist-only concept-art checkbox (shown/hidden by onBrandChange).
      '<div id="c-concept-wrap">' +
        '<label class="check-row"><input type="checkbox" id="c-concept" onchange="updateCompliance()"> ' +
        'This upload labels its concept / fan art as [CONCEPT] or [RUMOR] (required for Heist)</label>' +
      '</div>' +

      '<label for="c-schedule">Schedule</label>' +
      '<input type="datetime-local" id="c-schedule" value="' +
esc(editing && editing.scheduledAt ? editing.scheduledAt.slice(0, 16)
: '') + '">' +
      '<label class="check-row"><input type="checkbox" id="c-publishnow"' +
        (editing && editing.publishNow ? ' checked' : '') + '> Publish now (no scheduled time)</label>' +

      '<div class="compliance-box" id="compliance-box"></div>' +

      '<div class="button-row">' +
        '<button class="btn btn-secondary" onclick="saveDraft()">Save draft</button>' +
        '<button class="btn btn-primary" id="btn-submit" onclick="submitForApproval()">Submit for approval</button>' +
        (editing ? '<button class="btn btn-danger"onclick="deleteDraft()">Delete draft</button>' : '') +
      '</div>' +
    '</div>' +

    '<div class="compose-grid">' +
      '<div class="panel"><h3>Title formulas (click to insert)</h3>' +
        '<ul class="helper-list">' + formulaHtml + '</ul></div>' +
      '<div class="panel"><h3>Hook templates (click to append to caption)</h3>' +
        '<ul class="helper-list">' + hookHtml + '</ul></div>' +
    '</div>' +

    '<div class="panel"><h3>Thumbnail checklist</h3>' +
      '<p class="hint">Ticking an item appends it to your thumbnail notes above.</p>' +
      thumbHtml +
    '</div>' +

    (editing ? '' : renderDraftList());

  onBrandChange();      // show/hide the Heist checkbox + refresh hint banner
  updateCompliance();   // run the compliance check once on load
  markThumbChecks();    // re-tick checklist boxes that match existing notes
}

// Show the Heist concept-art checkbox only for the Heist brand,
// rebuild the platform checkboxes for the new brand, refresh the hint.
function onBrandChange() {
  const brand = val('c-brand');
  const wrap = document.getElementById('c-concept-wrap');
  if (wrap) wrap.style.display = brand === 'heist' ? 'block' : 'none';

  const accounts = API.getAccounts();
  const boxes = accounts
    .filter(function (a) { return a.brand === brand; })
    .map(function (a) {
      return '<label class="check-row"><input type="checkbox"name="c-platform" value="' +
        a.platform + '" checked onchange="updateCompliance()"> ' +
        esc(PLATFORM_NAMES[a.platform]) + ' <small>' + esc(a.handle) +
'</small></label>';
    }).join('');
  const holder = document.getElementById('c-platforms');
  if (holder) holder.innerHTML = boxes;

  // Refresh the rule-hint banner at the top (first .banner in this view).
  const banner = document.querySelector('#compose-root .banner');
  if (banner) banner.textContent = BRAND_HINTS[brand];

  updateCompliance();
}

// Click a title formula -> insert it into the title field.
function insertFormula(i) {
  const el = document.getElementById('c-title');
  const formula = COMPOSER_DATA.title_formulas[i];
  el.value = el.value.trim() ? el.value.trim() + ' | ' + formula : formula;
  updateCompliance();
  el.focus();
}

// Click a hook template -> append it to the caption.
function insertHook(i) {
  const el = document.getElementById('c-caption');
  const hook = COMPOSER_DATA.hook_templates[i];
  el.value = el.value.trim() ? el.value.trim() + '\n' + hook : hook;
  updateCompliance();
  el.focus();
}

// Ticking a thumbnail checklist item appends it to the notes;
// unticking removes that line again.
function toggleThumbNote(checkbox) {
  const notesEl = document.getElementById('c-thumbnotes');
  const item = COMPOSER_DATA.thumbnail_checklist[Number(checkbox.getAttribute('data-thumb'))];
  const lines = notesEl.value.split('\n').map(function (l) { return
l.trim(); });
  if (checkbox.checked) {
    if (lines.indexOf(item) === -1) lines.push(item);
  } else {
    const at = lines.indexOf(item);
    if (at !== -1) lines.splice(at, 1);
  }
  notesEl.value = lines.filter(Boolean).join('\n');
}

// When editing a draft, re-tick checklist boxes whose text is in the notes.
function markThumbChecks() {
  const notes = val('c-thumbnotes');
  document.querySelectorAll('#compose-root[data-thumb]').forEach(function (cb) {const item =COMPOSER_DATA.thumbnail_checklist[Number(cb.getAttribute('data-thumb'))]; cb.checked = notes.indexOf(item) !== -1;
  });
}

// The LIVE compliance readout. Runs on every keystroke in title/caption/
// hashtags and whenever brand/platforms change. Blocks (red) disable the
// Submit button; warnings (amber) are allowed through.
function updateCompliance()
{
    const box = document.getElementById('compliance-box');
  if (!box) return;

  const brand = val('c-brand');
  const title = val('c-title');
  const caption = val('c-caption');
  const hashtags = val('c-hashtags');
  const platforms = selectedPlatforms();

  const result = Compliance.check(brand, title, caption, hashtags);
  const blocks = result.blocks.slice();   // copy — we may add more below
  const warnings = result.warnings.slice();

  // Heist concept-art rule (checkbox lives in the view, not in text):
  // warn — not block — unless the box is ticked.
  const conceptBox = document.getElementById('c-concept');
  if (brand === 'heist' && conceptBox && !conceptBox.checked) {
    warnings.push({
      rule: 'heist / label-concept-art',
      message: 'Concept / fan art must be labeled [CONCEPT] or[RUMOR]. Tick the checkbox above once the upload is labeled.'
    });
  }

  // Platform limits, enforced per the research content pack:
  // TikTok/IG caption max 2200, X max 280, YouTube description max 5000.
  const limits = COMPOSER_DATA.platform_limits;
  const capMax = { tiktok: 'caption_max', instagram: 'caption_max', x:
'caption_max', youtube: 'description_max' };
  platforms.forEach(function (pl) {
    const max = limits[pl] && limits[pl][capMax[pl]];
    if (max && caption.length > max) {
      blocks.push({
        rule: pl + ' / caption-limit',
        message: PLATFORM_NAMES[pl]+ ' allows max ' + max + 'characters — caption is ' + caption.length + '. Shorten it.'
      });
    }
  });
  // X hashtag guidance: more than ~4 looks spammy.
  if (platforms.indexOf('x') !== -1) {
    const xTags = hashtags.split(/[\s,]+/).filter(function (t) {
return t.charAt(0) === '#'; }).length;
    if (xTags > 4) {
      warnings.push({
        rule: 'x / hashtag-guidance',
        message: 'X guidance is ~4 hashtags max — you have ' + xTags +
'. Trim for reach.'
      });
    }
  }

  // Caption character counter with the strictest selected limit.
  const countEl = document.getElementById('c-capcount');
  if (countEl) {
    const strictest = Math.min.apply(null, platforms.map(function (pl) {
      return (limits[pl] && limits[pl][capMax[pl]]) || Infinity;
    }));
    countEl.textContent = 'Caption: ' + caption.length + ' chars' +
      (strictest !== Infinity ? ' (strictest selected platform limit:'+ strictest + ')' : '');
  }

  // Render the readout.
  let html = '';
  blocks.forEach(function (b) {
    html += '<div class="compliance-item block"><span class="compliance-rule">BLOCK</span> ' +
      esc(b.message) + ' <small>(' + esc(b.rule) + ')</small></div>';
  });
  warnings.forEach(function (w) {
    html += '<div class="compliance-item warn"><span class="compliance-rule">WARNING</span> ' +
      esc(w.message) + ' <small>(' + esc(w.rule) + ')</small></div>';
  });
  if (!blocks.length && !warnings.length) {
    html = '<div class="compliance-item ok">Compliance clear — no blocks or warnings.</div>';
  }
  box.innerHTML = html;

  // Blocks disable submission; warnings do not.
  const submit = document.getElementById('btn-submit');
  if (submit) submit.disabled = blocks.length > 0;
}

// Gather the Compose form into a post-shaped object.
function collectCompose() {
  return {
    brand: val('c-brand'),
    platforms: selectedPlatforms(),
    title: val('c-title').trim(),
    caption: val('c-caption').trim(),
    hashtags: val('c-hashtags').trim(),
    thumbnailNotes: val('c-thumbnotes').trim(),
    labelsConceptArt: !!(document.getElementById('c-concept') &&
document.getElementById('c-concept').checked),
    scheduledAt: (function () {
      if (document.getElementById('c-publishnow').checked) return null;
      const raw = val('c-schedule');
      return raw ? new Date(raw).toISOString() : null;
    })(),
    publishNow: document.getElementById('c-publishnow').checked,
    mediaName: pendingMedia ? pendingMedia.name : (editingDraftId &&
API.getPost(editingDraftId).mediaName) || '',
    mediaSize: pendingMedia ? pendingMedia.size : (editingDraftId &&
API.getPost(editingDraftId).mediaSize) || 0,
    rejectionNote: ''
  };
}

// Basic form validation before any save.
function validateCompose(data) {
  if (!data.title) return 'Give the post a title.';
  if (!data.platforms.length) return 'Tick at least one platform/account.';
  return null;
}

// Save as draft (stays editable, never goes near the approval queue).
function saveDraft() {
  const data = collectCompose();
  const err = validateCompose(data);
  if (err) { alert(err); return; }

  if (editingDraftId) {
    API.updatePost(editingDraftId, Object.assign(data, { status: 'draft' }));
    API.logAudit({ brand: data.brand, action: 'updated', detail:
'Draft updated: ' + data.title, postId: editingDraftId });
  } else {
    const post = API.savePost(Object.assign(data, { status: 'draft' }));
    API.logAudit({ brand: data.brand, action: 'created', detail:
'Draft created: ' + data.title, postId: post.id });
    editingDraftId = post.id;
  }
  alert('Draft saved.');
  renderCompose();
}

// Submit for approval. Blocked while any BLOCK is active
// (the button is disabled, this is a second safety net).
function submitForApproval() {
  const data = collectCompose();
  const err = validateCompose(data);
  if (err) { alert(err); return; }

  const result = Compliance.check(data.brand, data.title,
data.caption, data.hashtags);
  if (result.blocks.length) {
    alert('Cannot submit — resolve the BLOCK items first.');
    return;
  }

  let postId;
  if (editingDraftId) {
    API.updatePost(editingDraftId, Object.assign(data, { status:
'pending_approval' }));
    postId = editingDraftId;
  } else {
    const post = API.savePost(Object.assign(data, { status:
'pending_approval' }));
    postId = post.id;
  }
  API.logAudit({ brand: data.brand, action: 'submitted', detail:
'Submitted for approval: ' + data.title, postId: postId });

  editingDraftId = null;
  pendingMedia = null;
  alert('Submitted for approval. Jose reviews it in the Approvals tab.');
  showView('approvals');
}

// Load a draft back into the form for editing.
function loadDraft(id) {
  const post = API.getPost(id);
  if (!post) return;
  editingDraftId = id;
  pendingMedia = post.mediaName ? { name: post.mediaName, size:
post.mediaSize || 0 } : null;
  showView('compose');
}

// Delete the draft currently being edited.
function deleteDraft() {
  if (!editingDraftId) return;
  if (!confirm('Delete this draft?')) return;
  const post = API.getPost(editingDraftId);
  API.deletePost(editingDraftId);
  API.logAudit({ brand: post.brand, action: 'deleted', detail: 'Draft deleted: ' + post.title, postId: editingDraftId });
  editingDraftId = null;
  renderCompose();
}

// Draft list shown under the composer (so drafts are findable).
function renderDraftList() {
  const drafts = API.listPosts().filter(function (p) {
    return p.status === 'draft' || p.status === 'rejected';
  });
  if (!drafts.length) return '';

  const cards = drafts.map(function (p) {
    return '<div class="card">' +
      '<span class="pill ' + pillClass(p.status) + '">' +
statusLabel(p.status) + '</span> ' +
      '<strong>' + esc(p.title) + '</strong>' +
      '<div class="card-meta">' + esc(BRAND_NAMES[p.brand]) + ' · ' +
        p.platforms.map(function (pl) { return
esc(PLATFORM_NAMES[pl]); }).join(', ') +
        (p.rejectionNote ? ' · Rejection note: ' +
esc(p.rejectionNote) : '') + '</div>' +
      '<div class="card-actions"><button class="btn btn-secondary"onclick="loadDraft(\'' + p.id + '\')">Edit</button></div>' +
    '</div>';
  }).join('');

  return '<div class="panel"><h3>Drafts</h3>' + cards + '</div>';
}


/* =====================================================================
   7. VIEW: QUEUE
   Posts with status `scheduled` (approved with a future time) plus
   `approved` posts set to publish-now. Each card shows a countdown-ish
   "scheduled for" label and a Cancel button (sends it back to draft).

   HONEST NOTE: GitHub Pages is  static hosting — it cannot run a timer
   that fires posts at the right time. The Phase-2 Python backend owns
   the scheduler; this view is the human-readable face of that queue.
   ===================================================================== */
function renderQueue() {
  const root = document.getElementById('queue-root');

  const queued = API.listPosts().filter(function (p) {
    return p.status === 'scheduled' || p.status === 'approved';
  });

  // Soonest first.
  queued.sort(function (a, b) {
    const at = a.scheduledAt ? new Date(a.scheduledAt).getTime() : 0;
    const bt = b.scheduledAt ? new Date(b.scheduledAt).getTime() : 0;
    return at - bt;
  });

  let html =
    '<div class="banner warn">GitHub Pages can\'t auto-post — it\'s static hosting with no ' +
    'always-on process. The Phase-2 backend fires these at the right time; this queue is its waiting room.</div>';

  if (!queued.length) {
    html += '<div class="panel"><div class="empty-state">Queue is empty. Approved posts with a ' +
      'scheduled time (or "publish now") land here.</div></div>';
  } else {
    html += queued.map(function (p) {
      const when = p.scheduledAt
        ? fmtDate(p.scheduledAt) + ' (' + timeUntil(p.scheduledAt) + ')'
        : 'Approved — publish now';
      return '<div class="card">' +
        '<span class="pill ' + pillClass(p.status) + '">' +
statusLabel(p.status) + '</span> ' +
        '<strong>' + esc(p.title) + '</strong>' +
        '<div class="card-meta">' + esc(BRAND_NAMES[p.brand]) + ' · ' +
          p.platforms.map(function (pl) { return
esc(PLATFORM_NAMES[pl]); }).join(', ') + '</div>' +
        '<div>Scheduled for: <strong>' + esc(when) + '</strong></div>' +
        (p.mediaName ? '<div class="card-meta">Media: ' +
esc(p.mediaName) + '</div>' : '') +
        '<div class="card-actions">' +
          '<button class="btn btn-danger" onclick="cancelQueued(\'' +
p.id + '\')">Cancel (back to draft)</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  root.innerHTML = html;
}

// Cancel a queued post -> back to draft. Logged in the audit trail.
function cancelQueued(id) {
  const post = API.getPost(id);
  if (!post || !confirm('Cancel this queued post? It goes back todraft.')) return;
  API.updatePost(id, { status: 'draft', scheduledAt: null, publishNow: false });
  API.logAudit({ brand: post.brand, action: 'cancelled', detail:
'Queue slot cancelled: ' + post.title, postId: id });
  renderQueue();
}


/* =====================================================================
   8. VIEW: APPROVALS
   Every post with status `pending_approval`, shown with full detail.
   Jose taps Approve (moves to scheduled/approved) or Reject-with-note
   (sends it back to draft with the note attached). Nothing posts
   without his approval — that is the standing rule.
   ===================================================================== */
function renderApprovals() {
  const root = document.getElementById('approvals-root');

  const pending = API.listPosts().filter(function (p) {
    return p.status === 'pending_approval';
  });

  if (!pending.length) {
    root.innerHTML = '<div class="panel"><div class="empty-state">' +
      'Nothing waiting for approval. Compose something and hit "Submit for approval".</div></div>';
    return;
  }

  root.innerHTML = pending.map(function (p) {
    return '<div class="card">' +
      '<span class="pill ' + pillClass(p.status) + '">' +
statusLabel(p.status) + '</span> ' +
      '<strong>' + esc(BRAND_NAMES[p.brand]) + '</strong>' +
      '<h3 style="margin-top:0.5rem">' + esc(p.title) + '</h3>' +
      '<div class="card-meta">Platforms: ' +
        p.platforms.map(function (pl) { return
esc(PLATFORM_NAMES[pl]); }).join(', ') + ' · ' +
        'Created ' + fmtDate(p.createdAt) + '</div>' +
      '<p style="white-space:pre-wrap;margin:0.5rem 0">' +
esc(p.caption) + '</p>' +
      (p.hashtags ? '<div class="card-meta">Hashtags: ' +
esc(p.hashtags) + '</div>' : '') +
      (p.thumbnailNotes ? '<div class="card-meta">Thumbnail notes: ' +
esc(p.thumbnailNotes) + '</div>' : '') +
      '<div class="card-meta">Timing: ' +
        (p.scheduledAt ? fmtDate(p.scheduledAt) + ' (' +
timeUntil(p.scheduledAt) + ')' : 'Publish now') + '</div>' +
      (p.mediaName ? '<div class="card-meta">Media: ' +
esc(p.mediaName) + '</div>' : '') +
      (p.labelsConceptArt ? '<div class="card-meta">Concept art labeled: yes</div>' : '') +
      '<div class="card-actions">' +
        '<button class="btn btn-success" onclick="approvePost(\'' +
p.id + '\')">Approve</button>' +
        '<button class="btn btn-danger" onclick="rejectPost(\'' + p.id
+ '\')">Reject with note</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

// Approve -> scheduled (has a future time) or approved (publish now).
function approvePost(id) {
  const post = API.getPost(id);
  if (!post) return;
  const next = post.scheduledAt ? 'scheduled' : 'approved';
  API.updatePost(id, { status: next, rejectionNote: '' });
  API.logAudit({ brand: post.brand, action: 'approved', detail:
'Approved: ' + post.title, postId: id });
  if (next === 'scheduled') {
    API.logAudit({ brand: post.brand, action: 'scheduled', detail:
'Scheduled for ' + fmtDate(post.scheduledAt) + ': ' + post.title,
postId: id });
  }
  renderApprovals();
}

// Reject -> back to draft, with Jose's note attached so the fix is clear.
function rejectPost(id) {
  const post = API.getPost(id);
  if (!post) return;
  const note = prompt('Rejection note (what should change?):');
  if (note === null) return; // Jose hit Cancel — leave the post alone.
  API.updatePost(id, { status: 'draft', rejectionNote: note.trim() });
  API.logAudit({ brand: post.brand, action: 'rejected', detail:
'Rejected: ' + post.title + ' — ' + note.trim(), postId: id });
  renderApprovals();
}


/* =====================================================================
   9. VIEW: AUDIT LOG
   Every lifecycle event, newest first: created, submitted, approved,
   rejected, scheduled, cancelled (+ updated, deleted). Filterable by
   brand. This is the paper trail — what happened, when, to which post.
   ===================================================================== */
function renderAudit() {
  const root = document.getElementById('audit-root');

  const filterOptions = ['<option value="">All brands</option>'].concat(
    Object.keys(BRAND_NAMES).map(function (key) {
      return '<option value="' + key + '"' + (key === auditBrandFilter
? ' selected' : '') + '>' +
        esc(BRAND_NAMES[key]) + '</option>';
    })
  ).join('');

  let entries = API.listAudit();
  if (auditBrandFilter) {
    entries = entries.filter(function (e) { return e.brand ===
auditBrandFilter; });
  }
  entries = entries.slice().reverse(); // newest first

  let html =
    '<div class="panel">' +
      '<h2>Audit log</h2>' +
      '<label for="audit-brand">Filter by brand</label>' +
      '<select id="audit-brand" onchange="onAuditFilter()">' +
filterOptions + '</select>' +
    '</div>';

  if (!entries.length) {
    html += '<div class="panel"><div class="empty-state">No audit events yet. ' +
      'Create, submit, approve, or cancel a post and it will appear here.</div></div>';
  } else {
    const rows = entries.map(function (e) {
      return '<tr>' +
        '<td>' + esc(fmtDate(e.ts)) + '</td>' +
        '<td>' + esc(BRAND_NAMES[e.brand] || e.brand || '—') + '</td>' +
        '<td><strong>' + esc(e.action) + '</strong></td>' +
        '<td>' + esc(e.detail) + '</td>' +
      '</tr>';
    }).join('');

    html += '<div class="panel"><div class="audit-table-wrap">' +
      '<table class="audit-table">' +
        '<thead><tr><th>Time</th><th>Brand</th><th>Event</th><th>Detail</th></tr></thead>'
+
        '<tbody>' + rows + '</tbody>' +
      '</table></div></div>';
  }

  root.innerHTML = html;
}

function onAuditFilter() {
  auditBrandFilter = val('audit-brand');
  renderAudit();
}


/* =====================================================================
   10. NAVIGATION + INIT
   showView(name): hide all sections, show one, mark its tab active,
   and re-render it so the data is always fresh.
   init(): runs once when the page loads — seeds accounts via API,
   wires the tab buttons, opens on the Upload view.
   ===================================================================== */
const VIEWS = ['upload', 'compose', 'queue', 'approvals', 'audit'];

function showView(name) {
  if (VIEWS.indexOf(name) === -1) name = 'upload';

  // Toggle sections.
  VIEWS.forEach(function (v) {
    const section = document.getElementById('view-' + v);
    if (section) section.classList.toggle('active', v === name);
  });

  // Toggle tab highlight.
  document.querySelectorAll('.tab').forEach(function (tab) {
    tab.classList.toggle('active', tab.getAttribute('data-view') === name);
  });

  // Re-render the view being opened.
  ({ upload: renderUpload,
     compose: renderCompose,
     queue: renderQueue,
     approvals: renderApprovals,
     audit: renderAudit })[name]();
}

function init() {
  API.getAccounts(); // seeds the 16 demo brand×platform accounts on first run

  // Wire the nav tabs.
  document.querySelectorAll('.tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      showView(tab.getAttribute('data-view'));
    });
  });

  showView('upload');
}

// Wait for the HTML to be fully parsed before touching the DOM.
document.addEventListener('DOMContentLoaded', init);