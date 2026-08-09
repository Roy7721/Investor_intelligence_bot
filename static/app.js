/* ---------------------------------------------------------------------------
   Dashboard frontend.

   Flow: ask /api/companies for what exists -> build the tabs -> ask
   /api/kpi/{company}/{year} for one filing -> fill the empty slots in
   index.html. Clicking a tab repeats the last two steps. No page reload, which
   is why the chat panel can live on the same page later.
   --------------------------------------------------------------------------- */

// Which metrics get a card, in display order, with the label to show. The API
// returns them in a dict, so order has to be decided here rather than there.
const MONEY = [
  ["revenue",             "Total revenues"],
  ["net_income",          "Net income"],
  ["operating_income",    "Operating income"],
  ["operating_cash_flow", "Operating cash flow"],
  ["total_assets",        "Total assets"],
  ["total_liabilities",   "Total liabilities"],
];

const pct   = v => v == null ? "—" : (v * 100).toFixed(1) + "%";
const mult  = v => v == null ? "—" : v.toFixed(2) + "×";
const money = v => v == null ? "—" : "$" + Number(v).toLocaleString("en-US");

const RATIOS = [
  ["operating_margin", "Operating margin", pct],
  ["net_margin",       "Net margin",       pct],
  ["return_on_equity", "Return on equity", pct],
  ["return_on_assets", "Return on assets", pct],
  ["cash_conversion",  "Cash conversion",  mult],
];

// Scale-free only. Absolute revenue bars would just say "Apple is bigger",
// which nobody needed a chart to learn.
const PEER_METRICS = [
  ["net_margin",       "Net margin",       pct],
  ["return_on_equity", "Return on equity", pct],
  ["cash_conversion",  "Cash conversion",  mult],
];

const $ = id => document.getElementById(id);

// Escape anything that came from the filing before it touches innerHTML.
// Source quotes are verbatim table rows and can contain < and &.
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const marks = () =>
  '<span class="corner tl"></span><span class="corner tr"></span>' +
  '<span class="corner bl"></span><span class="corner br"></span>';

let filings = [];
let current = null;
let pendingFile = null;   // held so a NeedsIdentification retry can resend it

function showView(name) {
  $("view-upload").hidden = name !== "upload";
  $("view-dashboard").hidden = name !== "dashboard";
  window.scrollTo(0, 0);
}

async function refreshFilings() {
  try {
    filings = await (await fetch("/api/companies")).json();
  } catch {
    filings = [];
  }
  $("existing-chips").innerHTML = filings.length
    ? filings.map(f => `<button class="chip-link" data-company="${esc(f.company)}"
                                data-year="${f.year}">${esc(f.company)} FY${f.year}</button>`).join("")
    : `<span class="chip">nothing ingested yet</span>`;

  $("tabs").innerHTML = filings.map(f => `
    <button class="tab" role="tab" aria-selected="false"
            data-company="${esc(f.company)}" data-year="${f.year}">${esc(f.company)}</button>`
  ).join("");
}

async function boot() {
  await refreshFilings();
  showView("upload");
}

async function load(company, year) {
  const res = await fetch(`/api/kpi/${encodeURIComponent(company)}/${year}`);
  if (!res.ok) {
    $("kpis").innerHTML = `<div class="error">No data for ${esc(company)} ${year}.</div>`;
    return;
  }
  current = await res.json();
  document.querySelectorAll("#tabs .tab").forEach(t =>
    t.setAttribute("aria-selected",
      String(t.dataset.company === company && Number(t.dataset.year) === year)));
  render(current);
  showView("dashboard");
}

function render(d) {
  const m = d.metrics;

  $("meta").textContent  = `FY${d.year}`;
  $("scope").textContent = `scope: ${d.company} · FY${d.year}`;
  $("footer").textContent =
    "Figures extracted from the filing. Expand a source to see the row each came from.";

  // --- KPI cards. Each carries its own source disclosure. ---
  $("kpis").innerHTML = MONEY.map(([key, label], i) => {
    const entry = m[key] || {};
    const quote = entry.source_quote;
    return `
      <article class="bp">${marks()}
        <p class="kicker">${esc(label)}</p>
        <p class="figure">${money(entry.value)}<span class="unit"> M</span></p>
        ${quote ? `
          <button class="src-toggle" aria-expanded="false" data-src="src-${i}">source</button>
          <div class="src" id="src-${i}">${esc(quote)}</div>` : ""}
      </article>`;
  }).join("");

  // --- derived ratios ---
  $("ratios").innerHTML = RATIOS.map(([key, label, fmt]) => `
    <div class="ratio bp">${marks()}
      <p class="kicker">${esc(label)}</p>
      <p class="figure">${fmt(d.derived[key])}</p>
    </div>`).join("");

  // --- peer bars, one block per metric, each scaled to its own max ---
  $("peers").innerHTML = PEER_METRICS.map(([key, label, fmt]) => {
    const vals = d.peers.map(p => p[key]).filter(v => v != null);
    const max = vals.length ? Math.max(...vals) : 1;
    const rows = d.peers.map(p => {
      const v = p[key];
      const width = v == null ? 0 : (v / max) * 100;
      return `
        <div class="bar-row" data-me="${p.company === d.company}">
          <span class="bar-label">${esc(p.company)}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${width}%"></span></span>
          <span class="bar-val">${fmt(v)}</span>
        </div>`;
    }).join("");
    return `<div class="metric-block"><span class="metric-name">${esc(label)}</span>${rows}</div>`;
  }).join("");

  // --- risk factors, or an explanation of why there are none ---
  const risk = m.risk_factors || {};
  if (Array.isArray(risk.value) && risk.value.length) {
    // One <span> only. The bullet comes from li::before, so a second child
    // would make three grid items in a two-column grid and push the text onto
    // its own row — which is what was doubling this section's height.
    $("risks").innerHTML =
      `<ul class="risks">${risk.value.map(r => `<li><span>${esc(r)}</span></li>`).join("")}</ul>`;
  } else {
    // A blank panel reads as broken. Saying WHY reads as a system that knows
    // what it does not have.
    const why = risk.absent
      || risk.error
      || "No risk factors were extracted from this filing.";
    $("risks").innerHTML =
      `<div class="absent-note"><strong>Section absent</strong><p>${esc(why)}</p></div>`;
  }

  // --- growth drivers ---
  const drivers = (m.growth_drivers || {}).value;
  $("drivers").innerHTML = Array.isArray(drivers) && drivers.length
    ? drivers.map(t => `<span class="chip">${esc(t)}</span>`).join("")
    : `<span class="chip">not disclosed</span>`;


  // The composer starts disabled in the HTML so it can't be used before a
  // filing is loaded — there would be nothing to scope the question to.
  $("q").disabled = false;
  $("composer").querySelector("button").disabled = false;
}


document.addEventListener("click", e => {
  // "+ New filing" carries .tab for styling but is not a filing tab.
  const tab = e.target.closest(".tab:not(#new-filing)");
  if (tab) {
    document.querySelectorAll(".tab").forEach(t => t.setAttribute("aria-selected", String(t === tab)));
    load(tab.dataset.company, Number(tab.dataset.year));
    return;
  }
  const btn = e.target.closest(".src-toggle");
  if (btn) {
    const box = $(btn.dataset.src);
    const open = box.dataset.open === "true";
    box.dataset.open = String(!open);
    btn.setAttribute("aria-expanded", String(!open));
  }
});


function addMessage(who, text, cite) {
  const log = $("chat-log");
  log.querySelector(".chat-empty")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML =
    `<div class="who">${who === "you" ? "You" : "Analyst"}</div>` +
    `<div class="body">${esc(text)}</div>` +
    (cite ? `<div class="cite">${esc(cite)}</div>` : "");
  log.appendChild(el);
  el.scrollIntoView({ block: "nearest" });
}

$("composer").addEventListener("submit", async e => {
  e.preventDefault();
  const input = $("q");
  const question = input.value.trim();
  if (!question || !current) return;

  addMessage("you", question);
  input.value = "";
  input.disabled = true;

  // A placeholder that gets replaced, so the panel never looks frozen while
  // retrieval and the model run.
  addMessage("bot", "…", "thinking");
  const pending = $("chat-log").lastElementChild;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question, company: current.company, year: current.year,
      }),
    });
    const data = await res.json();
    pending.querySelector(".body").textContent =
      res.ok ? data.answer : (data.detail || "Something went wrong.");
    pending.querySelector(".cite").textContent = `${current.company} FY${current.year}`;
  } catch (err) {
    pending.querySelector(".body").textContent = "Could not reach the server.";
    pending.querySelector(".cite").textContent = String(err);
  } finally {
    input.disabled = false;
    input.focus();
  }
});

/* ------------------------------- upload ------------------------------- */

const STAGE_LABEL = {
  hashing: "Fingerprint", cached: "Cached", converting: "Converting",
  identifying: "Identifying", chunking: "Chunking", embedding: "Embedding",
  extracting: "Extracting", done: "Done",
};

function resetUpload() {
  $("progress").hidden = true;
  $("identify").hidden = true;
  $("rejected").hidden = true;
  $("stages").innerHTML = "";
}

function addStage(stage, detail) {
  const stages = $("stages");
  const last = stages.lastElementChild;
  // Consecutive events for the same stage update in place rather than stacking.
  // "converting" emits twice — once on entry, once with the character count.
  if (last && last.dataset.stage === stage) {
    last.querySelector(".stage-detail").textContent = detail;
    return;
  }
  if (last) last.classList.add("settled");
  const li = document.createElement("li");
  li.dataset.stage = stage;
  li.innerHTML = `<span class="stage-name">${esc(STAGE_LABEL[stage] || stage)}</span>` +
                 `<span class="stage-detail">${esc(detail)}</span>`;
  stages.appendChild(li);
}

function showRejected(message) {
  $("progress").hidden = true;
  $("rejected-why").textContent = message;
  $("rejected").hidden = false;
}

function upload(file, company, year) {
  if (!file) return;
  pendingFile = file;              // kept so a NeedsIdentification retry can resend
  resetUpload();
  $("progress").hidden = false;
  addStage("hashing", "uploading");

  const form = new FormData();
  form.append("file", file);
  if (company) form.append("company", company);
  if (year) form.append("year", year);

  fetch("/api/upload", { method: "POST", body: form })
    .then(async res => {
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      follow(data.job_id);
    })
    .catch(err => showRejected(String(err.message || err)));
}

function follow(jobId) {
  // EventSource is the browser's built-in SSE client: it opens one long-lived
  // connection and fires onmessage for each "data:" line the server sends.
  const es = new EventSource(`/api/progress/${jobId}`);

  es.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.stage !== "finished") { addStage(msg.stage, msg.detail); return; }

    es.close();
    $("stages").lastElementChild?.classList.add("settled");

    if (msg.error) {
      if (msg.error.kind === "needs_identification") {
        // Not a failure — the document is usable, we just don't know whose.
        $("identify-why").textContent = msg.error.message;
        $("identify").hidden = false;
        $("in-company").focus();
      } else {
        showRejected(msg.error.message);
      }
      return;
    }
    refreshFilings().then(() => load(msg.result.company, msg.result.year));
  };

  es.onerror = () => { es.close(); showRejected("Lost the connection to the server."); };
}

const drop = $("drop");
drop.addEventListener("click", e => { if (!e.target.closest("button")) $("file").click(); });
$("browse").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", e => upload(e.target.files[0]));

["dragenter", "dragover"].forEach(t =>
  drop.addEventListener(t, e => { e.preventDefault(); drop.dataset.over = "true"; }));
["dragleave", "drop"].forEach(t =>
  drop.addEventListener(t, e => { e.preventDefault(); drop.dataset.over = "false"; }));
drop.addEventListener("drop", e => upload(e.dataTransfer.files[0]));

$("identify-form").addEventListener("submit", e => {
  e.preventDefault();
  $("identify").hidden = true;
  upload(pendingFile, $("in-company").value.trim(), $("in-year").value);
});

$("try-again").addEventListener("click", resetUpload);
$("new-filing").addEventListener("click", () => { resetUpload(); showView("upload"); });

document.addEventListener("click", e => {
  const chip = e.target.closest(".chip-link");
  if (chip) load(chip.dataset.company, Number(chip.dataset.year));
});

boot();
