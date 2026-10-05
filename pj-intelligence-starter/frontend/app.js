const GROUPS = [
  ["AI", /\b(ai|openai|anthropic|model|agent)\b/i],
  ["DEVELOPER", /\b(developer|coding|api)\b/i],
  ["PRODUCT", /\b(product|saas|startup)\b/i],
  ["FUNDING", /\bfunding\b/i],
];

const HIGH_SCORE = 60;

let items = [];
let selectedId = null;

const listEl = document.getElementById("list");
const radarEl = document.getElementById("radar-body");
const signalEl = document.getElementById("signal-body");
const detailEl = document.getElementById("detail");
const jobEl = document.getElementById("job");
const collectBtn = document.getElementById("collect");

function pad(value) {
  return String(value).padStart(2, "0");
}

function formatTime(iso) {
  if (!iso) return "--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function isToday(iso) {
  if (!iso) return false;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderRadar() {
  radarEl.replaceChildren();
  const counts = GROUPS.map(([label, pattern]) => {
    const count = items.filter((item) => pattern.test(item.title || "")).length;
    return [label, count];
  });
  const max = Math.max(1, ...counts.map((row) => row[1]));
  if (items.length === 0) {
    radarEl.append(el("div", "empty", "NO SIGNAL"));
    return;
  }
  counts.forEach(([label, count]) => {
    const row = el("div", "row");
    row.append(el("span", null, label));
    const bar = el("div", "bar");
    const fill = document.createElement("span");
    fill.style.width = `${Math.round((count / max) * 100)}%`;
    bar.append(fill);
    row.append(bar);
    row.append(el("span", "num", String(count)));
    radarEl.append(row);
  });
}

function renderSignals() {
  signalEl.replaceChildren();
  const today = items.filter((item) => isToday(item.fetched_at)).length;
  const high = items.filter((item) => Number(item.score) >= HIGH_SCORE).length;
  const sources = new Set(items.map((item) => item.source_name)).size;
  const rows = [
    ["TODAY", String(today)],
    ["HIGH ≥60", String(high)],
    ["SOURCES", String(sources)],
  ];
  rows.forEach(([label, value]) => {
    const row = el("div", "sig");
    row.append(el("span", null, label));
    row.append(el("b", null, value));
    signalEl.append(row);
  });
}

function renderList() {
  listEl.replaceChildren();
  if (items.length === 0) {
    listEl.append(el("div", "empty", "NO SIGNAL"));
    return;
  }
  items.forEach((item) => {
    const row = el("div", selectedId === item.id ? "item active" : "item");
    row.append(el("div", "title", item.title));
    const meta = el("div", "meta");
    meta.append(el("span", null, item.source_name));
    meta.append(el("span", "score", String(item.score)));
    meta.append(el("span", null, formatTime(item.published_at)));
    row.append(meta);
    row.addEventListener("click", () => openItem(item.id));
    listEl.append(row);
  });
}

function renderDetail(item, analysisText) {
  detailEl.replaceChildren();
  detailEl.append(el("div", "headline", item.title));

  const meta = el("div", "meta");
  meta.append(el("span", null, item.source_name));
  meta.append(el("span", "score", String(item.score)));
  meta.append(el("span", null, formatTime(item.published_at)));
  if (item.author) meta.append(el("span", null, item.author));
  detailEl.append(meta);

  const link = document.createElement("a");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = item.url;
  detailEl.append(link);

  detailEl.append(el("p", "summary", item.summary || "--"));

  const button = document.createElement("button");
  button.id = "analyze";
  button.type = "button";
  button.textContent = "AI 研判";
  button.addEventListener("click", () => runAnalyze(item.id));
  detailEl.append(button);

  const analysis = el("pre", "analysis", analysisText || "");
  analysis.id = "analysis";
  detailEl.append(analysis);
}

async function openItem(id) {
  selectedId = id;
  renderList();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/items/${id}`);
    const item = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", item.detail || "加载失败"));
      return;
    }
    let analysisText = "";
    const analysisResponse = await fetch(`/api/analysis/${id}`);
    if (analysisResponse.ok) {
      const analysis = await analysisResponse.json();
      analysisText = analysis.analysis || "";
    }
    renderDetail(item, analysisText);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

function formatError(detail) {
  if (typeof detail === "string" && detail) return detail;
  if (!detail || typeof detail !== "object") return "研判失败";
  const upstream = detail.upstream_response;
  const upstreamText = upstream == null
    ? ""
    : (typeof upstream === "string" ? upstream : JSON.stringify(upstream, null, 2));
  return [
    detail.message || "LLM upstream error",
    detail.status_code == null ? "" : `status_code: ${detail.status_code}`,
    detail.model ? `model: ${detail.model}` : "",
    detail.url ? `url: ${detail.url}` : "",
    upstreamText ? `upstream_response: ${upstreamText}` : "",
  ].filter(Boolean).join("\n");
}

async function runAnalyze(id) {
  const button = document.getElementById("analyze");
  const box = document.getElementById("analysis");
  if (!button || !box) return;
  button.disabled = true;
  box.className = "analysis";
  box.textContent = "研判中";
  try {
    const response = await fetch(`/api/items/${id}/analyze`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      box.className = "analysis error";
      box.textContent = formatError(data.detail);
      return;
    }
    box.className = "analysis";
    box.textContent = data.analysis || "";
  } catch (_error) {
    box.className = "analysis error";
    box.textContent = "研判失败";
  } finally {
    button.disabled = false;
  }
}

async function refresh() {
  const response = await fetch("/api/items?limit=50");
  if (!response.ok) throw new Error("items");
  items = await response.json();
  renderRadar();
  renderSignals();
  renderList();
}

async function runCollect() {
  collectBtn.disabled = true;
  jobEl.textContent = "采集中";
  try {
    const response = await fetch("/api/collect", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = "采集失败";
      return;
    }
    const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
    jobEl.textContent = `+${data.inserted}  SKIP ${data.skipped}${errorCount ? `  ERR ${errorCount}` : ""}`;
    await refresh();
  } catch (_error) {
    jobEl.textContent = "采集失败";
  } finally {
    collectBtn.disabled = false;
  }
}

collectBtn.addEventListener("click", runCollect);
refresh().catch(() => {
  listEl.replaceChildren(el("div", "error", "加载失败"));
});
