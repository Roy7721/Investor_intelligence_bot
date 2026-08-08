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

async function boot() {
  try {
    filings = await (await fetch("/api/companies")).json();
  } catch (e) {
    $("kpis").innerHTML = `<div class="error">Could not reach the API: ${esc(e)}</div>`;
    return;
  }
  if (!filings.length) {
    $("kpis").innerHTML = `<div class="error">No filings in data/kpi/ yet.</div>`;
    return;
  }

  $("tabs").innerHTML = filings.map((f, i) => `
    <button class="tab" role="tab" aria-selected="${i === 0}"
            data-company="${esc(f.company)}" data-year="${f.year}">${esc(f.company)}</button>`
  ).join("");

  load(filings[0].company, filings[0].year);
}

async function load(company, year) {
  const res = await fetch(`/api/kpi/${encodeURIComponent(company)}/${year}`);
  if (!res.ok) {
    $("kpis").innerHTML = `<div class="error">No data for ${esc(company)} ${year}.</div>`;
    return;
  }
  current = await res.json();
  render(current);
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
  const tab = e.target.closest(".tab");
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

boot();
