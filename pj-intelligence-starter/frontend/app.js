const GROUPS = [
  ["AI", /\b(ai|openai|anthropic|model|agent)\b/i],
  ["DEVELOPER", /\b(developer|coding|api)\b/i],
  ["PRODUCT", /\b(product|saas|startup)\b/i],
  ["FUNDING", /\bfunding\b/i],
];

const HIGH_SCORE = 60;

let items = [];
let events = [];
let keywords = [];
let competitors = [];
let opportunities = [];
let dataSources = [];
let sourceImports = [];
let selectedId = null;
let selectedEventId = null;
let selectedKeywordId = null;
let selectedPageId = null;
let selectedOpportunityId = null;
let selectedSourceId = null;
let selectedImportId = null;
let viewMode = "dashboard";
let dashboardOpportunityId = null;
let evidenceStats = { groups: [], record_types: [] };
let dashboardFeeds = {
  imports: [],
  serp: [],
  payment: [],
  traffic: [],
  keywords: [],
  crawl: [],
  authority: [],
  validation: [],
};
let analyzeToken = 0;
let timerId = null;

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

function signalCounts() {
  return {
    today: items.filter((item) => isToday(item.fetched_at)).length,
    high: items.filter((item) => Number(item.score) >= HIGH_SCORE).length,
    sources: new Set(items.map((item) => item.source_name)).size,
  };
}

function setStat(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function renderStats(counts) {
  const today = counts ? String(counts.today) : "-";
  const high = counts ? String(counts.high) : "-";
  const sources = counts ? String(counts.sources) : "-";
  setStat("stat-today", today);
  setStat("stat-high", high);
  setStat("stat-sources", sources);
  signalEl.replaceChildren();
  if (!counts) return;
  [
    ["TODAY", today],
    ["HIGH ≥60", high],
    ["SOURCES", sources],
  ].forEach(([label, value]) => {
    const row = el("div", "sig");
    row.append(el("span", null, label));
    row.append(el("b", null, value));
    signalEl.append(row);
  });
}

function renderSignals() {
  renderStats(signalCounts());
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
    row.dataset.id = String(item.id);
    row.addEventListener("click", () => openItem(item.id));
    listEl.append(row);
  });
}

function stopTimer() {
  if (timerId) {
    clearInterval(timerId);
    timerId = null;
  }
}

function startTimer(node) {
  stopTimer();
  const started = Date.now();
  node.textContent = "0s";
  timerId = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    node.textContent = `${seconds}s`;
  }, 1000);
}

function hasAnalysis(record) {
  return Boolean(record && typeof record === "object" && (record.analysis || record.model));
}

function formatElapsed(record) {
  if (!record || typeof record !== "object") return "未记录";
  if (record.elapsedMs != null && record.elapsedMs !== "") {
    const ms = Number(record.elapsedMs);
    if (!Number.isNaN(ms)) return `${Math.round(ms / 1000)} 秒`;
  }
  if (record.elapsed_seconds != null && record.elapsed_seconds !== "") {
    return `${record.elapsed_seconds} 秒`;
  }
  return "未记录";
}

function fillAnalysisMeta(record, statusLabel) {
  const meta = document.getElementById("analysis-meta");
  if (!meta) return;
  meta.replaceChildren();
  if (!hasAnalysis(record)) return;
  [
    ["状态", statusLabel],
    ["模型", record.model || "--"],
    ["耗时", formatElapsed(record)],
    ["创建时间", formatTime(record.created_at)],
    ["分析类型", record.analysis_type || "manual"],
  ].forEach(([label, value]) => {
    const row = el("div", "meta-line");
    row.append(el("span", "k", label));
    row.append(el("span", null, String(value)));
    meta.append(row);
  });
}

function renderDetail(item, saved) {
  stopTimer();
  const existing = hasAnalysis(saved);
  detailEl.replaceChildren();
  detailEl.append(el("div", "headline", item.title));

  const meta = el("div", "meta");
  meta.append(el("span", null, item.source_name));
  meta.append(el("span", "score", String(item.score)));
  meta.append(el("span", null, formatTime(item.published_at)));
  detailEl.append(meta);

  const link = document.createElement("a");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = item.url;
  detailEl.append(link);

  detailEl.append(el("p", "summary", item.summary || "--"));

  const savedHint = el("div", "hint", existing ? "已有本地研判结果" : "");
  savedHint.id = "saved-hint";
  detailEl.append(savedHint);

  const actions = el("div", "actions");
  const button = document.createElement("button");
  button.id = "analyze";
  button.type = "button";
  button.textContent = existing ? "重新研判" : "AI 研判";
  button.addEventListener("click", () => runAnalyze(item.id));
  actions.append(button);
  const elapsed = el("span", null, "");
  elapsed.id = "elapsed";
  actions.append(elapsed);
  detailEl.append(actions);

  const waitHint = el("div", "hint", "");
  waitHint.id = "analyze-status";
  detailEl.append(waitHint);

  const analysisMeta = el("div", "analysis-meta");
  analysisMeta.id = "analysis-meta";
  detailEl.append(analysisMeta);
  if (existing) fillAnalysisMeta(saved, "已有本地研判结果");

  const analysis = el("pre", "analysis", existing ? (saved.analysis || "") : "");
  analysis.id = "analysis";
  detailEl.append(analysis);
}

async function openItem(id) {
  analyzeToken += 1;
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
    let saved = null;
    const analysisResponse = await fetch(`/api/analysis/${id}`);
    if (analysisResponse.ok) {
      saved = await analysisResponse.json();
    }
    renderDetail(item, saved);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

function formatError(detail) {
  if (typeof detail === "string" && detail) return detail;
  if (!detail || typeof detail !== "object") return "研判失败";
  return [
    detail.message || "研判失败",
    detail.status_code == null ? "" : `status_code: ${detail.status_code}`,
    detail.model ? `model: ${detail.model}` : "",
    detail.url ? `url: ${detail.url}` : "",
  ].filter(Boolean).join("\n");
}

function showAnalysis(data) {
  const box = document.getElementById("analysis");
  fillAnalysisMeta(data, "新研判完成");
  if (box) {
    box.className = "analysis";
    box.textContent = data.analysis || "";
  }
}

async function runAnalyze(id) {
  const token = ++analyzeToken;
  const button = document.getElementById("analyze");
  const box = document.getElementById("analysis");
  const status = document.getElementById("analyze-status");
  const elapsed = document.getElementById("elapsed");
  const savedHint = document.getElementById("saved-hint");
  if (!button || !box || !status || !elapsed) return;
  const previousLabel = button.textContent === "重新研判" ? "重新研判" : "AI 研判";
  button.disabled = true;
  button.textContent = "分析中...";
  status.textContent = "模型分析可能需要 30–90 秒，请勿重复点击";
  startTimer(elapsed);
  try {
    const response = await fetch(`/api/items/${id}/analyze`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (token !== analyzeToken) return;
    if (!response.ok) {
      box.className = "analysis error";
      box.textContent = formatError(data.detail);
      button.textContent = previousLabel;
      return;
    }
    if (savedHint) savedHint.textContent = "新研判完成";
    status.textContent = "";
    elapsed.textContent = "";
    showAnalysis(data);
    button.textContent = "重新研判";
  } catch (_error) {
    if (token !== analyzeToken) return;
    box.className = "analysis error";
    box.textContent = "研判失败";
    button.textContent = previousLabel;
  } finally {
    if (token === analyzeToken) {
      stopTimer();
      button.disabled = false;
    }
  }
}

function renderEventList() {
  listEl.replaceChildren();
  if (events.length === 0) {
    listEl.append(el("div", "empty", "NO SIGNAL"));
    return;
  }
  events.forEach((event) => {
    const row = el("div", selectedEventId === event.id ? "item active" : "item");
    row.append(el("div", "title", event.title || "--"));
    const meta = el("div", "meta");
    meta.append(el("span", "score", String(event.event_score)));
    meta.append(el("span", null, event.primary_keyword || "--"));
    meta.append(el("span", null, `items ${event.item_count}`));
    meta.append(el("span", null, `src ${event.source_count}`));
    meta.append(el("span", null, formatTime(event.last_seen_at)));
    row.append(meta);
    row.dataset.id = String(event.id);
    row.addEventListener("click", () => openEvent(event.id));
    listEl.append(row);
  });
}

function renderEventDetail(event, itemsForEvent, saved) {
  stopTimer();
  const existing = Boolean(saved && saved.analysis);
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "市场信号详情"));
  detailEl.append(el("div", "headline", event.title || "--"));
  detailEl.append(el("p", "summary", event.summary || "--"));

  const meta = el("div", "meta");
  meta.append(el("span", null, event.primary_keyword || "--"));
  meta.append(el("span", "score", String(event.event_score)));
  meta.append(el("span", null, `items ${event.item_count}`));
  meta.append(el("span", null, `src ${event.source_count}`));
  detailEl.append(meta);

  const hint = el("div", "hint", existing ? "已有本地市场信号研判结果" : "");
  hint.id = "saved-hint";
  detailEl.append(hint);

  const included = el("div", "event-items");
  (itemsForEvent || []).forEach((item) => {
    const row = el("div", "item");
    row.append(el("div", "title", item.title || "--"));
    const rowMeta = el("div", "meta");
    rowMeta.append(el("span", null, item.source_name || "--"));
    rowMeta.append(el("span", "score", String(item.score)));
    rowMeta.append(el("span", null, formatTime(item.published_at)));
    const link = document.createElement("a");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.url;
    rowMeta.append(link);
    row.append(rowMeta);
    included.append(row);
  });
  detailEl.append(included);

  const actions = el("div", "actions");
  const button = document.createElement("button");
  button.id = "event-analyze";
  button.type = "button";
  button.textContent = existing ? "重新研判市场信号" : "AI 研判市场信号";
  button.addEventListener("click", () => runEventAnalyze(event.id));
  actions.append(button);
  const elapsed = el("span", null, "");
  elapsed.id = "elapsed";
  actions.append(elapsed);
  detailEl.append(actions);

  const waitHint = el("div", "hint", "");
  waitHint.id = "analyze-status";
  detailEl.append(waitHint);

  if (existing) {
    const analysisMeta = el("div", "analysis-meta");
    [
      ["模型", saved.model || "--"],
      ["耗时", saved.elapsed_seconds == null ? "未记录" : `${saved.elapsed_seconds} 秒`],
      ["创建时间", formatTime(saved.created_at)],
      ["分析类型", saved.analysis_type || "manual"],
    ].forEach(([label, value]) => {
      const line = el("div", "meta-line");
      line.append(el("span", "k", label));
      line.append(el("span", null, value));
      analysisMeta.append(line);
    });
    detailEl.append(analysisMeta);
  }

  const analysis = el("pre", "analysis", existing ? (saved.analysis || "") : "");
  analysis.id = "analysis";
  detailEl.append(analysis);
}

async function openEvent(id) {
  analyzeToken += 1;
  selectedEventId = id;
  selectedId = null;
  renderEventList();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/events/${id}`);
    const payload = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", payload.detail || "加载失败"));
      return;
    }
    let saved = null;
    const analysisResponse = await fetch(`/api/event-analysis/${id}`);
    if (analysisResponse.ok) saved = await analysisResponse.json();
    renderEventDetail(payload.event, payload.items, saved);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function loadEvents() {
  const response = await fetch("/api/events?limit=50");
  if (!response.ok) throw new Error("events");
  events = await response.json();
  renderEventList();
}

async function runEventAnalyze(id) {
  const token = ++analyzeToken;
  const button = document.getElementById("event-analyze");
  const box = document.getElementById("analysis");
  const status = document.getElementById("analyze-status");
  const elapsed = document.getElementById("elapsed");
  const savedHint = document.getElementById("saved-hint");
  if (!button || !box || !status || !elapsed) return;
  const previousLabel = button.textContent === "重新研判市场信号" ? "重新研判市场信号" : "AI 研判市场信号";
  button.disabled = true;
  button.textContent = "分析中...";
  status.textContent = "模型分析可能需要 30–90 秒，请勿重复点击";
  startTimer(elapsed);
  try {
    const response = await fetch(`/api/events/${id}/analyze`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (token !== analyzeToken) return;
    if (!response.ok) {
      box.className = "analysis error";
      box.textContent = formatError(data.detail);
      button.textContent = previousLabel;
      return;
    }
    if (savedHint) savedHint.textContent = "已有本地市场信号研判结果";
    status.textContent = "";
    elapsed.textContent = "";
    box.className = "analysis";
    box.textContent = data.analysis || "";
    button.textContent = "重新研判市场信号";
  } catch (_error) {
    if (token !== analyzeToken) return;
    box.className = "analysis error";
    box.textContent = "研判失败";
    button.textContent = previousLabel;
  } finally {
    if (token === analyzeToken) {
      stopTimer();
      button.disabled = false;
    }
  }
}

function keywordGrade(score) {
  const value = Number(score);
  if (value >= 85) return "Build Candidate";
  if (value >= 70) return "Research";
  if (value >= 50) return "Observe";
  return "Low Priority";
}

function renderKeywordList() {
  listEl.replaceChildren();
  if (keywords.length === 0) {
    listEl.append(el("div", "empty", "NO KEYWORD"));
    return;
  }
  keywords.forEach((cluster) => {
    const row = el("div", selectedKeywordId === cluster.id ? "item active" : "item");
    row.append(el("div", "title", cluster.name || "--"));
    const meta = el("div", "meta");
    meta.append(el("span", "score", `${cluster.score} ${keywordGrade(cluster.score)}`));
    meta.append(el("span", null, cluster.category || "--"));
    meta.append(el("span", null, cluster.search_intent || "--"));
    meta.append(el("span", null, cluster.page_type || "--"));
    meta.append(el("span", null, cluster.status || "--"));
    row.append(meta);
    row.dataset.id = String(cluster.id);
    row.addEventListener("click", () => openKeyword(cluster.id));
    listEl.append(row);
  });
}

function renderKeywordDetail(cluster, keywordItems, saved) {
  stopTimer();
  const existing = Boolean(saved && saved.analysis);
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "关键词簇详情"));
  detailEl.append(el("div", "headline", cluster.name || "--"));

  const meta = el("div", "meta");
  meta.append(el("span", null, cluster.category || "--"));
  meta.append(el("span", null, cluster.search_intent || "--"));
  meta.append(el("span", null, cluster.page_type || "--"));
  meta.append(el("span", "score", `${cluster.score} ${keywordGrade(cluster.score)}`));
  meta.append(el("span", null, cluster.status || "--"));
  detailEl.append(meta);

  const hint = el("div", "hint", existing ? "已有本地关键词研判结果" : "");
  hint.id = "saved-hint";
  detailEl.append(hint);

  const included = el("div", "event-items");
  (keywordItems || []).forEach((item) => {
    const row = el("div", "item");
    row.append(el("div", "title", item.keyword || "--"));
    const rowMeta = el("div", "meta");
    rowMeta.append(el("span", null, item.intent || "--"));
    rowMeta.append(el("span", null, item.difficulty || "--"));
    rowMeta.append(el("span", null, item.status || "--"));
    row.append(rowMeta);
    included.append(row);
  });
  detailEl.append(included);

  const actions = el("div", "actions");
  const googleSearch = document.createElement("button");
  googleSearch.id = "google-competitor-search";
  googleSearch.type = "button";
  googleSearch.textContent = "SERP 查竞品 / 导入 SERP";
  googleSearch.addEventListener("click", () => searchCompetitors(cluster));
  actions.append(googleSearch);
  const generate = document.createElement("button");
  generate.id = "opportunity-generate";
  generate.type = "button";
  generate.textContent = "生成项目卡";
  generate.addEventListener("click", () => generateOpportunity(cluster.id));
  actions.append(generate);
  const button = document.createElement("button");
  button.id = "keyword-analyze";
  button.type = "button";
  button.textContent = existing ? "重新研判关键词机会" : "AI 研判关键词机会";
  button.addEventListener("click", () => runKeywordAnalyze(cluster.id));
  actions.append(button);
  const elapsed = el("span", null, "");
  elapsed.id = "elapsed";
  actions.append(elapsed);
  detailEl.append(actions);

  const waitHint = el("div", "hint", "");
  waitHint.id = "analyze-status";
  detailEl.append(waitHint);

  if (existing) {
    const analysisMeta = el("div", "analysis-meta");
    [
      ["模型", saved.model || "--"],
      ["耗时", saved.elapsed_seconds == null ? "未记录" : `${saved.elapsed_seconds} 秒`],
      ["创建时间", formatTime(saved.created_at)],
    ].forEach(([label, value]) => {
      const line = el("div", "meta-line");
      line.append(el("span", "k", label));
      line.append(el("span", null, value));
      analysisMeta.append(line);
    });
    detailEl.append(analysisMeta);
  }

  const analysis = el("pre", "analysis", existing ? (saved.analysis || "") : "");
  analysis.id = "analysis";
  detailEl.append(analysis);
}

async function openKeyword(id) {
  analyzeToken += 1;
  selectedKeywordId = id;
  selectedId = null;
  selectedEventId = null;
  renderKeywordList();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/keywords/${id}`);
    const payload = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", payload.detail || "加载失败"));
      return;
    }
    let saved = null;
    const analysisResponse = await fetch(`/api/keyword-analysis/${id}`);
    if (analysisResponse.ok) saved = await analysisResponse.json();
    renderKeywordDetail(payload.cluster, payload.items, saved);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function loadKeywords() {
  const response = await fetch("/api/keywords");
  if (!response.ok) throw new Error("keywords");
  keywords = await response.json();
  renderKeywordList();
}

async function runKeywordAnalyze(id) {
  const token = ++analyzeToken;
  const button = document.getElementById("keyword-analyze");
  const box = document.getElementById("analysis");
  const status = document.getElementById("analyze-status");
  const elapsed = document.getElementById("elapsed");
  const savedHint = document.getElementById("saved-hint");
  if (!button || !box || !status || !elapsed) return;
  const previousLabel = button.textContent === "重新研判关键词机会" ? "重新研判关键词机会" : "AI 研判关键词机会";
  button.disabled = true;
  button.textContent = "分析中...";
  status.textContent = "模型分析可能需要 30–90 秒，请勿重复点击";
  startTimer(elapsed);
  try {
    const response = await fetch(`/api/keywords/${id}/analyze`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (token !== analyzeToken) return;
    if (!response.ok) {
      box.className = "analysis error";
      box.textContent = formatError(data.detail);
      button.textContent = previousLabel;
      return;
    }
    if (savedHint) savedHint.textContent = "已有本地关键词研判结果";
    status.textContent = "";
    elapsed.textContent = "";
    box.className = "analysis";
    box.textContent = data.analysis || "";
    button.textContent = "重新研判关键词机会";
  } catch (_error) {
    if (token !== analyzeToken) return;
    box.className = "analysis error";
    box.textContent = "研判失败";
    button.textContent = previousLabel;
  } finally {
    if (token === analyzeToken) {
      stopTimer();
      button.disabled = false;
    }
  }
}

async function seedKeywordPool() {
  const button = document.getElementById("seed-keywords");
  button.disabled = true;
  jobEl.textContent = "初始化中";
  try {
    const response = await fetch("/api/keywords/seed", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = "初始化失败";
      return;
    }
    jobEl.textContent = `KW +${data.clusters_created} SKIP ${data.clusters_skipped}`;
    await loadKeywords();
  } catch (_error) {
    jobEl.textContent = "初始化失败";
  } finally {
    button.disabled = false;
  }
}

const ADMIN_MODES = ["intake", "health", "sources", "imports", "trace", "items", "events"];
const VERDICT_RANK = { Build: 0, Research: 1, Observe: 2, Reject: 3 };
const DASH_RANK = {
  Build: 0,
  "Build Candidate / Evidence Partial": 1,
  "Research / Payment Signal Only": 2,
  "Research / Traffic Signal Only": 2,
  "Research / Authority Signal Only": 2,
  "Research / SERP Missing": 4,
  "Research / Competitor Missing": 4,
  Research: 3,
  "Research / Evidence Missing": 4,
  Observe: 5,
  Reject: 6,
};
const COPYABLE_TYPES = ["tutorial", "api_docs", "comparison"];
const EVIDENCE_GAP = "证据不足：当前只能作为 Research / Observe，不能作为 Build 最终依据。";

function applyChrome(mode) {
  const admin = ADMIN_MODES.includes(mode);
  const focused = mode === "opportunities" || mode === "keywords" || mode === "competitors";
  document.body.dataset.screen = mode === "dashboard" ? "dashboard" : "workspace";
  document.body.dataset.focus = focused ? "work" : "admin";
  document.getElementById("admin-nav").hidden = !admin;
  document.getElementById("view-dashboard").classList.toggle("on", mode === "dashboard");
  document.getElementById("view-opportunities").classList.toggle("on", mode === "opportunities");
  document.getElementById("view-keywords").classList.toggle("on", mode === "keywords");
  document.getElementById("view-competitors").classList.toggle("on", mode === "competitors");
  document.getElementById("view-admin").classList.toggle("on", admin);
  document.getElementById("view-health").classList.toggle("on", mode === "health");
  document.getElementById("view-intake").classList.toggle("on", mode === "intake");
  document.getElementById("view-sources").classList.toggle("on", mode === "sources");
  document.getElementById("view-imports").classList.toggle("on", mode === "imports");
  document.getElementById("view-trace").classList.toggle("on", mode === "trace");
  document.getElementById("view-items").classList.toggle("on", mode === "items");
  document.getElementById("view-events").classList.toggle("on", mode === "events");
  document.getElementById("build-events").hidden = mode !== "events";
  document.getElementById("seed-keywords").hidden = mode !== "keywords";
  document.getElementById("add-competitor").hidden = mode !== "competitors";
  document.getElementById("add-source").hidden = mode !== "sources";
  document.getElementById("import-csv").hidden = mode !== "imports";
  document.getElementById("collect").hidden = mode !== "items";
  const titles = {
    opportunities: "OPPORTUNITIES",
    keywords: "KEYWORDS",
    competitors: "COMPETITORS",
    health: "PROVIDER HEALTH",
    intake: "DATA INTAKE",
    sources: "SOURCES",
    imports: "DATA IMPORTS",
    trace: "API TRACE",
    items: "ITEMS",
    events: "MARKET SIGNALS",
  };
  const title = document.getElementById("list-title");
  if (title) title.textContent = titles[mode] || "LIST";
}

function rankedOpportunities() {
  return [...opportunities].sort((left, right) => {
    const rank = (VERDICT_RANK[left.verdict] ?? 9) - (VERDICT_RANK[right.verdict] ?? 9);
    if (rank !== 0) return rank;
    return Number(right.score) - Number(left.score);
  });
}

function lacksSample(card) {
  const reason = String(card.verdict_reason || "");
  return Number(card.competitor_count) === 0 || reason.includes("样本不足") || reason.includes("来源不足");
}

function hostOf(value) {
  const text = String(value || "").trim().toLowerCase();
  if (!text) return "";
  try {
    const url = text.includes("://") ? new URL(text) : new URL(`https://${text}`);
    return url.hostname.replace(/^www\./, "");
  } catch (_error) {
    return text.replace(/^www\./, "").split("/")[0];
  }
}

function isSampleDomain(value) {
  const host = hostOf(value);
  return host === "example.com" || host === "test.com" || host.endsWith(".example.com") || host.endsWith(".test.com");
}

function isSampleText(value) {
  const text = String(value || "").toLowerCase();
  return ["sample", "demo", "draft check", "browser form"].some((token) => text.includes(token));
}

function isSerperRecord(row) {
  if (!row || row.record_type !== "serp_result") return false;
  const label = `${row.provider || ""} ${row.source_name || ""} ${row.confidence || ""}`.toLowerCase();
  return label.includes("serper");
}

function serperLinks() {
  return new Set(evidenceStats.serp_urls || []);
}

function isSamplePage(page) {
  if (!page) return false;
  if (serperLinks().has(page.url)) return false;
  return isSampleDomain(page.domain) || isSampleDomain(page.url) || isSampleText(page.title) || isSampleText(page.notes);
}

function parsedRaw(row) {
  try {
    return JSON.parse(row.raw_json || "{}");
  } catch (_error) {
    return {};
  }
}

function isImportedRow(row) {
  const status = String((row && row.status) || "").toLowerCase();
  return status === "imported" || status === "confirmed";
}

function isSampleRaw(row) {
  if (!row) return false;
  if (isSerperRecord(row)) return false;
  const raw = parsedRaw(row);
  const notes = `${row.normalized_title || ""} ${row.notes || ""} ${raw.title || ""} ${raw.notes || ""} ${raw.source_note || ""}`;
  return isSampleDomain(row.normalized_domain) || isSampleDomain(row.normalized_url) || isSampleDomain(raw.domain) || isSampleDomain(raw.url) || isSampleText(notes);
}

function sourceBlob(row) {
  return `${row.source_name || ""} ${row.provider || ""} ${row.source_type || ""} ${row.record_type || ""}`.toLowerCase();
}

function realPages(pages) {
  return pages.filter((page) => !isSamplePage(page));
}

function clusterPages(card) {
  if (!card) return [];
  return competitors.filter((page) => page.cluster_id === card.cluster_id);
}

function sampleBackedBuild(card) {
  if (!card || card.verdict !== "Build") return false;
  const related = clusterPages(card);
  if (realPages(related).length > 0) return false;
  return related.some(isSamplePage) || isSampleDomain(card.best_competitor_domain) || isSampleText(card.best_competitor_domain);
}

function displayVerdict(card) {
  if (sampleBackedBuild(card)) return "Research / Evidence Missing";
  return card.verdict || "--";
}

function liveStatus(status) {
  return status === "Partial" || status === "Ready";
}

function dashboardVerdict(card) {
  const serp = serpStatus();
  const comp = competitorSlotStatus(clusterPages(card));
  const pay = paymentStatus();
  const traffic = trafficStatus();
  const authority = authorityStatus();
  const payLive = liveStatus(pay);
  const trafficLive = liveStatus(traffic);
  const authorityLive = liveStatus(authority);
  const marketLive = payLive || trafficLive || authorityLive;
  const marketReady = pay === "Ready" || traffic === "Ready" || authority === "Ready";
  if (liveStatus(serp) && liveStatus(comp) && marketLive) {
    if (serp === "Ready" && comp === "Ready" && marketReady) return "Build";
    return "Build Candidate / Evidence Partial";
  }
  if (!liveStatus(serp)) return "Research / SERP Missing";
  if (!liveStatus(comp)) return "Research / Competitor Missing";
  if (authorityLive && !payLive && !trafficLive) return "Research / Authority Signal Only";
  if (payLive && !trafficLive && !authorityLive) return "Research / Payment Signal Only";
  if (trafficLive && !payLive && !authorityLive) return "Research / Traffic Signal Only";
  return "Research / Evidence Missing";
}

function countedRows(rows) {
  return (rows || []).filter(isImportedRow);
}

function evidenceBucket(recordType) {
  return (evidenceStats.record_types || []).find((row) => row.record_type === recordType) || null;
}

function statusFromBucket(bucket, ready) {
  if (!bucket) return "Missing";
  if (ready(bucket)) return "Ready";
  if (Number(bucket.real_count) >= 1) return "Partial";
  if (Number(bucket.sample_count) >= 1) return "Sample Only";
  return "Missing";
}

function searchDemandStatus() {
  return statusFromBucket(evidenceBucket("keyword_signal"), (bucket) => Number(bucket.keyword_count) >= 20);
}

function serpStatus() {
  return statusFromBucket(evidenceBucket("serp_result"), (bucket) => Number(bucket.best_keyword_count) >= 10);
}

function competitorSlotStatus(pages) {
  const real = realPages(pages);
  const sample = pages.filter(isSamplePage);
  if (real.length >= 5) return "Ready";
  if (real.length >= 1) return "Partial";
  if (sample.length) return "Sample Only";
  return "Missing";
}

function periodMonth(row) {
  const raw = parsedRaw(row);
  const month = String(raw.period_month || row.time_range || "");
  return /^\d{4}-\d{2}$/.test(month) ? month : "";
}

function coverageStatus(recordType) {
  return statusFromBucket(
    evidenceBucket(recordType),
    (bucket) => Number(bucket.real_count) >= 100 && Number(bucket.month_count) >= 3,
  );
}

function paymentStatus() {
  return coverageStatus("payment_signal");
}

function realTrafficRows() {
  return countedRows(dashboardFeeds.traffic).filter((row) => !isSampleRaw(row));
}

function trafficFact(row) {
  const raw = parsedRaw(row);
  return {
    domain: row.normalized_domain || raw.domain || "--",
    traffic: raw.current_traffic || raw.monthly_traffic || raw.traffic || (row.metric_name === "traffic" ? row.metric_value : "") || "--",
    growth: raw.traffic_growth || raw.growth_rate || "--",
  };
}

function trafficStatus() {
  return coverageStatus("traffic_signal");
}

function authorityStatus() {
  return coverageStatus("authority_signal");
}

function crawlStatus() {
  return statusFromBucket(evidenceBucket("crawl_signal"), (bucket) => Number(bucket.real_count) >= 10);
}

function validationStatus() {
  return statusFromBucket(evidenceBucket("validation_signal"), (bucket) => Number(bucket.validation_streak) >= 7);
}

function evidenceSlots() {
  return [
    ["Demand Signal", searchDemandStatus()],
    ["SERP Signal", serpStatus()],
    ["Competitor Signal", competitorSlotStatus(competitors)],
    ["Crawl Signal", crawlStatus()],
    ["Traffic Signal", trafficStatus()],
    ["Authority Signal", authorityStatus()],
    ["Payment Signal", paymentStatus()],
    ["Validation Signal", validationStatus()],
  ];
}

function decisionGaps() {
  const gaps = [];
  const serpReal = serpStatus();
  if (serpReal === "Partial") gaps.push("SERP Top 10 数据不足");
  else if (serpReal !== "Ready") gaps.push("SERP Top 10 未导入");
  const competitorReal = realPages(competitors).length;
  if (competitorReal < 5) gaps.push("真实竞品页面不足");
  if (paymentStatus() === "Partial") gaps.push("支付信号不足");
  else if (paymentStatus() !== "Ready") gaps.push("支付信号缺失");
  if (trafficStatus() === "Partial") gaps.push("流量信号不足");
  else if (trafficStatus() !== "Ready") gaps.push("流量信号缺失");
  if (authorityStatus() === "Partial") gaps.push("权威信号不足");
  else if (authorityStatus() !== "Ready") gaps.push("权威信号缺失");
  if (validationStatus() === "Partial") gaps.push("验证数据不足");
  else if (validationStatus() !== "Ready") gaps.push("验证数据缺失");
  return gaps;
}

function slotClass(status) {
  return `slot-status ${String(status || "").toLowerCase().replace(/\s+/g, "-")}`;
}

function sampleTag() {
  return el("span", "sample-tag", "SAMPLE / 测试样本");
}

function evidenceSummary(slotName) {
  if (slotName === "Competitor Signal") {
    const real = realPages(competitors);
    const sample = competitors.filter(isSamplePage);
    const domains = [];
    real.forEach((page) => {
      const domain = page.domain || hostOf(page.url);
      if (domain && !domains.includes(domain)) domains.push(domain);
    });
    return {
      record_count: real.length,
      sample_count: sample.length,
      month_count: 0,
      latest_month: "--",
      domains: domains.slice(0, 3),
      source_name: "Competitors",
      dataset_type: "competitor_page",
      noun: "竞品页面",
    };
  }
  const recordType = {
    "Demand Signal": "keyword_signal",
    "SERP Signal": "serp_result",
    "Crawl Signal": "crawl_signal",
    "Traffic Signal": "traffic_signal",
    "Authority Signal": "authority_signal",
    "Payment Signal": "payment_signal",
    "Validation Signal": "validation_signal",
  }[slotName] || "";
  const bucket = evidenceBucket(recordType) || {};
  const dataset = bucket.dataset_type || "";
  const noun = {
    "Demand Signal": "关键词信号",
    "SERP Signal": "SERP 结果",
    "Crawl Signal": "公开抓取",
    "Traffic Signal": "流量增长记录",
    "Authority Signal": "DR 增长记录",
    "Payment Signal": dataset === "stripe_payment_ranking" ? "Stripe 支付信号" : "支付信号",
    "Validation Signal": "验证数据",
  }[slotName] || "记录";
  return {
    record_count: Number(bucket.row_count) || 0,
    sample_count: Number(bucket.sample_count) || 0,
    month_count: Number(bucket.month_count) || 0,
    latest_month: bucket.latest_month || "--",
    domains: bucket.top_domains || [],
    source_name: bucket.source_name || "--",
    dataset_type: dataset || "--",
    noun,
  };
}

const EVIDENCE_HOLES = [
  ["Demand Signal", "Demand Signal", "暂无真实需求数据，等待导入 Google Trends / GSC / Keyword CSV"],
  ["SERP Signal", "SERP Signal", "暂无真实 SERP，等待导入 SERP CSV"],
  ["Competitor Signal", "Competitor Signal", "暂无真实竞品，等待 SERP 转竞品草稿"],
  ["Crawl Evidence", "Crawl Signal", "暂无公开网页抓取"],
  ["Traffic Evidence", "Traffic Signal", "暂无流量信号，等待导入流量增长榜"],
  ["Authority Evidence", "Authority Signal", "暂无权威信号，等待导入 DR 增长榜"],
  ["Payment Evidence", "Payment Signal", "暂无支付信号，等待导入 Stripe 支付流量榜"],
  ["Validation Evidence", "Validation Signal", "暂无验证数据，等待接入 GSC / GA4 / 注册 / 支付"],
];

function copyablePages() {
  return realPages(competitors)
    .filter((page) => Number(page.copyability_score) >= 75 && COPYABLE_TYPES.includes(page.page_type))
    .sort((left, right) => Number(right.copyability_score) - Number(left.copyability_score));
}

function metricNode(label, value, build) {
  const node = el("div", build ? "metric build" : "metric");
  node.append(el("span", null, label));
  node.append(el("b", null, String(value)));
  return node;
}

function verdictTag(verdict) {
  const name = verdict || "--";
  const kind = name === "Build" ? "build" : name.toLowerCase();
  return el("span", `verdict-tag ${kind}`, name);
}

function renderDashboard() {
  const root = document.getElementById("cockpit");
  if (!root) return;
  const ranked = [...opportunities].sort((left, right) => {
    const rank = (DASH_RANK[dashboardVerdict(left)] ?? 9) - (DASH_RANK[dashboardVerdict(right)] ?? 9);
    if (rank !== 0) return rank;
    return Number(right.score) - Number(left.score);
  });
  const counts = { Build: 0, Research: 0, Observe: 0, Reject: 0 };
  ranked.forEach((card) => {
    const shown = dashboardVerdict(card);
    if (shown === "Build") counts.Build += 1;
    else if (counts[card.verdict] != null && card.verdict !== "Build") counts[card.verdict] += 1;
  });
  const thin = ranked.filter(lacksSample);
  const evidenced = ranked.filter((card) => Number(card.competitor_count) > 0);
  const week = ranked.filter((card) => card.verdict !== "Reject" && String(card.seven_day_action || "").trim());
  const priority = ranked.find((card) => dashboardVerdict(card) === "Build") || null;
  if (!dashboardOpportunityId && ranked[0]) dashboardOpportunityId = ranked[0].id;
  const selected = ranked.find((card) => card.id === dashboardOpportunityId) || ranked[0] || null;
  if (selected) dashboardOpportunityId = selected.id;
  const gaps = decisionGaps();

  root.replaceChildren();
  const summary = el("section", "deck");
  summary.id = "decision-summary";
  summary.append(el("h2", null, "DECISION SUMMARY"));
  if (gaps.length) {
    summary.append(el("p", "today", "当前不能下 Build 决策"));
    summary.append(el("div", "hint", "缺口："));
    gaps.forEach((gap) => summary.append(el("div", "gap-line", gap)));
    summary.append(el("div", "hint", "下一步："));
    [
      "1. 手动搜索目标关键词",
      "2. 复制前 10 个搜索结果",
      "3. Admin → Sources → Data Imports 导入 SERP CSV",
      "4. 将 SERP 批次转为竞品页面草稿",
    ].forEach((step) => summary.append(el("div", "clamp", step)));
  }
  const metrics = el("div", "metrics");
  metrics.append(metricNode("Build", counts.Build, true));
  metrics.append(metricNode("Research", counts.Research, false));
  metrics.append(metricNode("Observe", counts.Observe, false));
  metrics.append(metricNode("Reject", counts.Reject, false));
  metrics.append(metricNode("证据不足", thin.length, false));
  metrics.append(metricNode("有竞品证据", evidenced.length, false));
  metrics.append(metricNode("待 7 天动作", week.length, false));
  summary.append(metrics);
  let today = "今天没有可执行的真实 Build。";
  if (priority) today = `今天优先做这一页：${priority.first_page_plan || priority.title}`;
  if (!gaps.length) summary.append(el("p", "today", today));
  if (thin.length) {
    summary.append(el("p", "gap-line", `证据不足：${thin.map((card) => card.title || card.target_keyword || "未命名").join("、")}`));
  }
  const pages = copyablePages();
  if (pages.length) {
    summary.append(el("p", "copy-line", `可复制：${pages.slice(0, 5).map((page) => `${page.domain || page.title} ${page.page_type} ${page.copyability_score}`).join(" · ")}`));
  }
  root.append(summary);

  const holes = el("div", "slot-grid");
  holes.id = "evidence-holes";
  const slotMap = Object.fromEntries(evidenceSlots(selected));
  EVIDENCE_HOLES.forEach(([title, slotName, waiting]) => {
    const status = slotMap[slotName] || "Missing";
    const card = el("section", "cockpit-card");
    card.append(el("h2", null, title));
    card.append(el("b", slotClass(status), status));
    const summary = evidenceSummary(slotName);
    if (summary.record_count || summary.sample_count) {
      card.append(el("p", "clamp", `已导入 ${summary.month_count} 个月，${summary.record_count} 条${summary.noun}`));
      card.append(el("div", "clamp", `最近月份：${summary.latest_month}`));
      card.append(el("div", "clamp", `Top domains: ${summary.domains.join(", ") || "--"}`));
      card.append(el("div", "clamp", `${summary.source_name} · ${summary.dataset_type}`));
      if (summary.sample_count) card.append(el("div", "clamp", `sample_count ${summary.sample_count}`));
    } else {
      card.append(el("p", "clamp", waiting));
    }
    holes.append(card);
  });
  root.append(holes);

  const queue = el("section", "cockpit-card");
  queue.id = "opportunity-queue";
  queue.append(el("h2", null, "OPPORTUNITY QUEUE"));
  const queueRows = ranked.slice(0, 10);
  if (queueRows.length === 0) {
    queue.append(el("div", "empty", "NO CARD"));
  }
  queueRows.forEach((card) => {
    const row = el("div", card.id === dashboardOpportunityId ? "queue-item active" : "queue-item");
    row.dataset.opportunityId = String(card.id);
    const shown = dashboardVerdict(card);
    const top = el("div", "queue-top");
    top.append(el("span", shown === "Build" ? "verdict-tag build" : "verdict-tag", shown));
    top.append(el("span", "title", card.title || "--"));
    top.append(el("span", "score-num", String(card.score)));
    row.append(top);
    row.append(el("div", "clamp", `${card.target_keyword || "--"} · ${card.page_type || "--"}`));
    if (sampleBackedBuild(card)) row.append(el("div", "gap-line", "当前只有样例数据，不能作为 Build 判断依据。"));
    if (!sampleBackedBuild(card) && shown === card.verdict && card.first_page_plan) row.append(el("div", "clamp", card.first_page_plan));
    if (!sampleBackedBuild(card) && shown === card.verdict && card.seven_day_action) row.append(el("div", "clamp", card.seven_day_action));
    row.addEventListener("click", () => {
      dashboardOpportunityId = card.id;
      renderDashboard();
    });
    queue.append(row);
  });
  root.append(queue);

  const evidence = el("section", "cockpit-card");
  evidence.id = "dash-evidence";
  evidence.append(el("h2", null, "EVIDENCE"));
  const plan = el("section", "cockpit-card");
  plan.id = "dash-plan";
  plan.append(el("h2", null, "Next 7 / 14 / 30 / 60 Days"));
  if (!selected) {
    evidence.append(el("div", "empty", "选择一张项目卡，看证据。"));
    plan.append(el("div", "empty", "选择一张项目卡，看 7 / 14 / 30 / 60 天动作。"));
  } else {
    evidence.append(el("div", "headline", selected.title || "--"));
    evidence.append(el("div", "hint", dashboardVerdict(selected)));
    if (sampleBackedBuild(selected)) evidence.append(el("div", "gap-line", "当前只有样例数据，不能作为 Build 判断依据。"));
    evidence.append(el("div", "hint", "Evidence Slots"));
    evidenceSlots(selected).forEach(([name, status]) => {
      const line = el("div", "slot-row");
      line.append(el("span", null, name));
      line.append(el("b", slotClass(status), status));
      evidence.append(line);
    });
    const sourceBox = el("div");
    sourceBox.id = "dash-source-evidence";
    evidence.append(sourceBox);
    [
      ["先做这一页", selected.first_page_plan],
      ["7 天", selected.seven_day_action],
      ["14 天", selected.fourteen_day_action],
      ["30 天", selected.thirty_day_metric],
      ["60 天", selected.sixty_day_stop_rule],
    ].forEach(([label, value]) => {
      const step = el("div", "action-step");
      step.append(el("b", null, label));
      step.append(el("span", null, value || "--"));
      plan.append(step);
    });
  }
  root.append(evidence, plan);
  if (selected) loadDashboardEvidence(selected.id);
}

async function loadDashboardEvidence(cardId) {
  const box = document.getElementById("dash-source-evidence");
  if (!box) return;
  box.replaceChildren(el("div", "hint", "Source Evidence"));
  try {
    const response = await fetch(`/api/source-records?linked_table=opportunity_cards&linked_id=${cardId}`);
    const rows = await response.json();
    if (cardId !== dashboardOpportunityId) return;
    if (!response.ok || !Array.isArray(rows) || rows.length === 0) {
      box.append(el("div", "gap", EVIDENCE_GAP));
      return;
    }
    rows.forEach((row) => {
      const label = row.raw_ref || row.record_type || "record";
      const from = row.source_name || row.provider || "未知来源";
      const item = el("div", "item", `${label} from ${from}`);
      box.append(item);
    });
  } catch (_error) {
    if (cardId !== dashboardOpportunityId) return;
    box.append(el("div", "error", "来源加载失败"));
  }
}

async function loadJsonList(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return [];
    const data = await response.json();
    return Array.isArray(data) ? data : [];
  } catch (_error) {
    return [];
  }
}

async function loadEvidenceStats() {
  try {
    const response = await fetch("/api/evidence/stats");
    if (!response.ok) return { groups: [], record_types: [] };
    const data = await response.json();
    return data && Array.isArray(data.record_types) ? data : { groups: [], record_types: [], serp_urls: [] };
  } catch (_error) {
    return { groups: [], record_types: [], serp_urls: [] };
  }
}

async function loadDashboard() {
  const [oppRes, kwRes, compRes, stats] = await Promise.all([
    fetch("/api/opportunities"),
    fetch("/api/keywords"),
    fetch("/api/competitors"),
    loadEvidenceStats(),
  ]);
  if (!oppRes.ok || !kwRes.ok || !compRes.ok) throw new Error("dashboard");
  opportunities = await oppRes.json();
  keywords = await kwRes.json();
  competitors = await compRes.json();
  evidenceStats = stats;
  dashboardFeeds = { imports: [], serp: [], payment: [], traffic: [], keywords: [], crawl: [], authority: [], validation: [] };
  if (viewMode === "dashboard") renderDashboard();
}

function setView(mode) {
  viewMode = mode;
  applyChrome(mode);
  if (mode === "dashboard") {
    loadDashboard().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "看板加载失败"));
    });
    return;
  }
  if (mode === "health") {
    listEl.replaceChildren(el("div", "empty", "状态在右侧"));
    loadProviderHealth();
    return;
  }
  if (mode === "intake") {
    listEl.replaceChildren(el("div", "empty", "Data Intake"));
    detailEl.replaceChildren(el("div", "empty", "加载中"));
    loadIntake();
    return;
  }
  if (mode === "trace") {
    listEl.replaceChildren(el("div", "empty", "记录在下方"));
    showTrace();
    return;
  }
  if (mode === "imports") {
    detailEl.textContent = selectedImportId ? "加载中" : "选择一个导入批次";
    loadSources()
      .then(() => {
        if (selectedImportId) return openImport(selectedImportId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  if (mode === "items") {
    detailEl.textContent = selectedId ? "加载中" : "选择一条资讯";
    refresh()
      .then(() => {
        if (selectedId) return openItem(selectedId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  if (mode === "events") {
    detailEl.textContent = selectedEventId ? "加载中" : "选择一个市场信号";
    loadEvents()
      .then(() => {
        if (selectedEventId) return openEvent(selectedEventId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  if (mode === "keywords") {
    detailEl.textContent = selectedKeywordId ? "加载中" : "选择一个关键词簇";
    loadKeywords()
      .then(() => {
        if (selectedKeywordId) return openKeyword(selectedKeywordId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  if (mode === "opportunities") {
    detailEl.textContent = selectedOpportunityId ? "加载中" : "选择一张项目卡";
    loadOpportunities()
      .then(() => {
        if (selectedOpportunityId) return openOpportunity(selectedOpportunityId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  if (mode === "sources") {
    detailEl.textContent = selectedSourceId ? "加载中" : "选择一个数据源";
    loadSources()
      .then(() => {
        if (selectedSourceId) return openSource(selectedSourceId);
      })
      .catch(() => {
        listEl.replaceChildren(el("div", "error", "加载失败"));
      });
    return;
  }
  detailEl.textContent = selectedPageId ? "加载中" : "选择一个竞品页面";
  loadCompetitors()
    .then(() => {
      if (selectedPageId) return openCompetitor(selectedPageId);
    })
    .catch(() => {
      listEl.replaceChildren(el("div", "error", "加载失败"));
    });
}

const PAGE_TYPES = ["tutorial", "comparison", "tool", "api_docs", "listicle", "template", "landing", "unknown"];

function renderCompetitorList() {
  listEl.replaceChildren();
  if (competitors.length === 0) {
    listEl.append(el("div", "empty", "NO PAGE"));
    return;
  }
  competitors.forEach((page) => {
    const row = el("div", selectedPageId === page.id ? "item active" : "item");
    row.append(el("div", "title", page.title || page.domain || "--"));
    const meta = el("div", "meta");
    if (isSamplePage(page)) meta.append(sampleTag());
    meta.append(el("span", null, page.domain || "--"));
    meta.append(el("span", null, page.page_type || "--"));
    meta.append(el("span", null, page.target_keyword || "--"));
    meta.append(el("span", "score", String(page.copyability_score)));
    meta.append(el("span", null, page.risk_level || "--"));
    row.append(meta);
    row.dataset.id = String(page.id);
    row.addEventListener("click", () => openCompetitor(page.id));
    listEl.append(row);
  });
}

function renderCompetitorDetail(page, saved) {
  stopTimer();
  const existing = Boolean(saved && saved.analysis);
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "竞品页面详情"));
  detailEl.append(el("div", "headline", page.title || "--"));
  if (isSamplePage(page)) detailEl.append(sampleTag());
  const meta = el("div", "meta");
  meta.append(el("span", null, page.domain || "--"));
  meta.append(el("span", null, page.page_type || "--"));
  meta.append(el("span", null, page.target_keyword || "--"));
  meta.append(el("span", "score", String(page.copyability_score)));
  meta.append(el("span", null, page.risk_level || "--"));
  detailEl.append(meta);
  [
    ["URL", page.url],
    ["H1", page.h1],
    ["CTA", page.cta_text],
    ["pricing_signal", page.pricing_signal],
    ["signup_signal", page.signup_signal],
    ["payment_signal", page.payment_signal],
    ["geo_signal", page.geo_signal],
    ["notes", page.notes],
  ].forEach(([label, value]) => {
    const line = el("div", "meta-line");
    line.append(el("span", "k", label));
    if (label === "URL" && value) {
      const link = document.createElement("a");
      link.href = value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = value;
      line.append(link);
    } else {
      line.append(el("span", null, value || "--"));
    }
    detailEl.append(line);
  });
  const hint = el("div", "hint", existing ? "已有本地竞品研判结果" : "");
  hint.id = "saved-hint";
  detailEl.append(hint);
  const actions = el("div", "actions");
  const button = document.createElement("button");
  button.id = "competitor-analyze";
  button.type = "button";
  button.textContent = existing ? "重新研判竞品页面" : "AI 研判竞品页面";
  button.addEventListener("click", () => runCompetitorAnalyze(page.id));
  actions.append(button);
  const elapsed = el("span", null, "");
  elapsed.id = "elapsed";
  actions.append(elapsed);
  detailEl.append(actions);
  const waitHint = el("div", "hint", "");
  waitHint.id = "analyze-status";
  detailEl.append(waitHint);
  const analysis = el("pre", "analysis", existing ? (saved.analysis || "") : "");
  analysis.id = "analysis";
  detailEl.append(analysis);
  appendSourceBind(detailEl, {
    linkedTable: "competitor_pages",
    linkedId: page.id,
    recordType: "competitor_page",
  });
}

async function openCompetitor(id) {
  analyzeToken += 1;
  selectedPageId = id;
  selectedId = null;
  selectedEventId = null;
  selectedKeywordId = null;
  renderCompetitorList();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/competitors/${id}`);
    const page = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", page.detail || "加载失败"));
      return;
    }
    let saved = null;
    const analysisResponse = await fetch(`/api/competitor-analysis/${id}`);
    if (analysisResponse.ok) saved = await analysisResponse.json();
    renderCompetitorDetail(page, saved);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function loadCompetitors() {
  const response = await fetch("/api/competitors");
  if (!response.ok) throw new Error("competitors");
  competitors = await response.json();
  renderCompetitorList();
}

async function runCompetitorAnalyze(id) {
  const token = ++analyzeToken;
  const button = document.getElementById("competitor-analyze");
  const box = document.getElementById("analysis");
  const status = document.getElementById("analyze-status");
  const elapsed = document.getElementById("elapsed");
  const savedHint = document.getElementById("saved-hint");
  if (!button || !box || !status || !elapsed) return;
  const previousLabel = button.textContent === "重新研判竞品页面" ? "重新研判竞品页面" : "AI 研判竞品页面";
  button.disabled = true;
  button.textContent = "分析中...";
  status.textContent = "模型分析可能需要 30–90 秒，请勿重复点击";
  startTimer(elapsed);
  try {
    const response = await fetch(`/api/competitors/${id}/analyze?type=fast`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (token !== analyzeToken) return;
    if (!response.ok) {
      const detail = data.detail;
      const timedOut = detail && typeof detail === "object" && (
        detail.timeout_seconds != null || String(detail.message || "").includes("超时")
      );
      box.className = "analysis error";
      box.textContent = timedOut
        ? "模型接口超时。本次没有写入分析结果，可以稍后重试，或先手动记录页面判断。"
        : formatError(detail);
      status.textContent = timedOut ? box.textContent : "";
      button.textContent = previousLabel;
      return;
    }
    if (savedHint) savedHint.textContent = "已有本地竞品研判结果";
    status.textContent = "";
    elapsed.textContent = "";
    box.className = "analysis";
    box.textContent = data.analysis || "";
    button.textContent = "重新研判竞品页面";
  } catch (_error) {
    if (token !== analyzeToken) return;
    box.className = "analysis error";
    box.textContent = "研判失败";
    button.textContent = previousLabel;
  } finally {
    if (token === analyzeToken) {
      stopTimer();
      button.disabled = false;
    }
  }
}

async function showCompetitorForm() {
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "新增竞品页面"));
  const form = document.createElement("form");
  form.className = "page-form";
  let clusterOptions = `<option value="">选择关键词簇</option>`;
  try {
    const response = await fetch("/api/keywords");
    if (response.ok) {
      const clusters = await response.json();
      clusterOptions += clusters.map((cluster) => {
        const name = String(cluster.name || "").replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[char]));
        return `<option value="${Number(cluster.id)}">${Number(cluster.id)} ${name}</option>`;
      }).join("");
    }
  } catch (_error) {
    clusterOptions = `<option value="">关键词簇加载失败</option>`;
  }
  const typeOptions = PAGE_TYPES.map((type) => `<option value="${type}">${type}</option>`).join("");
  form.innerHTML = `
    <label>cluster_id<select name="cluster_id">${clusterOptions}</select></label>
    <label>url<input name="url" required></label>
    <label>title<input name="title"></label>
    <label>h1<input name="h1"></label>
    <label>page_type<select name="page_type">${typeOptions}</select></label>
    <label>target_keyword<input name="target_keyword"></label>
    <label>cta_text<input name="cta_text"></label>
    <label>pricing_signal<input name="pricing_signal"></label>
    <label>signup_signal<input name="signup_signal"></label>
    <label>payment_signal<input name="payment_signal"></label>
    <label>geo_signal<input name="geo_signal"></label>
    <label>notes<textarea name="notes" rows="3"></textarea></label>
    <button type="submit">保存竞品页面</button>
  `;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(form).entries());
    body.cluster_id = Number(body.cluster_id);
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const response = await fetch("/api/competitors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        jobEl.textContent = "保存失败";
        button.disabled = false;
        return;
      }
      jobEl.textContent = `PAGE ${data.id} SCORE ${data.copyability_score}`;
      selectedPageId = data.id;
      await loadCompetitors();
      await openCompetitor(data.id);
    } catch (_error) {
      jobEl.textContent = "保存失败";
      button.disabled = false;
    }
  });
  detailEl.append(form);
}

async function buildEventList() {
  const button = document.getElementById("build-events");
  button.disabled = true;
  jobEl.textContent = "构建中";
  try {
    const response = await fetch("/api/events/build", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = "构建失败";
      return;
    }
    const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
    jobEl.textContent = `EVT ${data.events_created}+${data.events_updated} LINK ${data.linked_items}${errorCount ? ` ERR ${errorCount}` : ""}`;
    await loadEvents();
  } catch (_error) {
    jobEl.textContent = "构建失败";
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
  if (viewMode === "items") renderList();
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

function traceCell(text) {
  return el("span", null, text == null || text === "" ? "--" : String(text));
}

async function showTrace() {
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch("/api/debug/trace");
    const rows = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", "加载失败"));
      return;
    }
    detailEl.replaceChildren();
    const actions = el("div", "actions");
    actions.append(el("div", "hint", "API Trace"));
    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.textContent = "清空记录";
    clearButton.addEventListener("click", async () => {
      await fetch("/api/debug/trace", { method: "DELETE" });
      showTrace();
    });
    actions.append(clearButton);
    detailEl.append(actions);
    const head = el("div", "trace-row trace-head");
    ["时间", "方法", "路径", "状态", "耗时", "类型", "备注"].forEach((label) => head.append(traceCell(label)));
    detailEl.append(head);
    if (!rows.length) {
      detailEl.append(el("div", "empty", "NO TRACE"));
      return;
    }
    rows.forEach((row) => {
      const line = el("div", "trace-row");
      line.append(traceCell(formatTime(row.timestamp)));
      line.append(traceCell(row.method));
      line.append(traceCell(row.path));
      line.append(traceCell(row.status_code));
      line.append(traceCell(row.elapsed_ms == null ? "--" : `${row.elapsed_ms}ms`));
      line.append(traceCell(row.kind));
      line.append(traceCell(row.note));
      detailEl.append(line);
    });
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

function renderOpportunityList() {
  listEl.replaceChildren();
  if (opportunities.length === 0) {
    listEl.append(el("div", "empty", "NO CARD"));
    return;
  }
  opportunities.forEach((card) => {
    const row = el("div", selectedOpportunityId === card.id ? "item active" : "item");
    row.append(el("div", "title", card.title || "--"));
    const meta = el("div", "meta");
    meta.append(el("span", null, card.verdict || "--"));
    meta.append(el("span", null, card.target_keyword || "--"));
    meta.append(el("span", null, card.page_type || "--"));
    meta.append(el("span", "score", String(card.score)));
    meta.append(el("span", null, card.status || "--"));
    row.append(meta);
    row.dataset.id = String(card.id);
    row.addEventListener("click", () => openOpportunity(card.id));
    listEl.append(row);
  });
}

function renderOpportunityDetail(card, saved) {
  stopTimer();
  const existing = Boolean(saved && saved.analysis);
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "项目卡详情"));
  detailEl.append(el("div", "headline", card.title || "--"));
  const meta = el("div", "meta");
  meta.append(el("span", null, card.verdict || "--"));
  meta.append(el("span", "score", String(card.score)));
  meta.append(el("span", null, card.target_keyword || "--"));
  meta.append(el("span", null, card.page_type || "--"));
  meta.append(el("span", null, card.status || "--"));
  detailEl.append(meta);
  const lines = [
    ["verdict_reason", card.verdict_reason],
    ["keyword_score", card.keyword_score],
    ["competitor_count", card.competitor_count],
    ["best_competitor_score", card.best_competitor_score],
    ["best_competitor_domain", card.best_competitor_domain],
    ["第一页计划", card.first_page_plan],
    ["7 天动作", card.seven_day_action],
    ["14 天动作", card.fourteen_day_action],
    ["30 天指标", card.thirty_day_metric],
    ["60 天止损线", card.sixty_day_stop_rule],
  ];
  if (!card.competitor_count && card.verdict_reason !== "竞品样本不足，当前只能 Research 或 Observe。") {
    lines.unshift(["verdict_reason", "竞品样本不足，当前只能 Research 或 Observe。"]);
  }
  lines.forEach(([label, value]) => {
    const line = el("div", "meta-line");
    line.append(el("span", "k", label));
    const text = value === undefined || value === null || value === "" ? "--" : String(value);
    line.append(el("span", null, text));
    detailEl.append(line);
  });
  const hint = el("div", "hint", existing ? "已有本地项目卡研判结果" : "");
  hint.id = "saved-hint";
  detailEl.append(hint);
  const actions = el("div", "actions");
  const button = document.createElement("button");
  button.id = "opportunity-analyze";
  button.type = "button";
  button.textContent = existing ? "重新研判项目卡" : "AI 研判项目卡";
  button.addEventListener("click", () => runOpportunityAnalyze(card.id));
  actions.append(button);
  const elapsed = el("span", null, "");
  elapsed.id = "elapsed";
  actions.append(elapsed);
  detailEl.append(actions);
  const waitHint = el("div", "hint", "");
  waitHint.id = "analyze-status";
  detailEl.append(waitHint);
  const analysis = el("pre", "analysis", existing ? (saved.analysis || "") : "");
  analysis.id = "analysis";
  detailEl.append(analysis);
  const evidence = el("div", "event-items");
  evidence.id = "source-evidence";
  evidence.append(el("div", "hint", "Source Evidence"));
  detailEl.append(evidence);
  loadSourceEvidence(card.id);
  appendSourceBind(detailEl, {
    linkedTable: "opportunity_cards",
    linkedId: card.id,
    recordType: "opportunity_card",
    onSaved: () => loadSourceEvidence(card.id),
  });
}

async function openOpportunity(id) {
  analyzeToken += 1;
  selectedOpportunityId = id;
  selectedId = null;
  selectedEventId = null;
  selectedKeywordId = null;
  selectedPageId = null;
  renderOpportunityList();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/opportunities/${id}`);
    const card = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", card.detail || "加载失败"));
      return;
    }
    let saved = null;
    const analysisResponse = await fetch(`/api/opportunity-analysis/${id}`);
    if (analysisResponse.ok) saved = await analysisResponse.json();
    renderOpportunityDetail(card, saved);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function loadOpportunities() {
  const response = await fetch("/api/opportunities");
  if (!response.ok) throw new Error("opportunities");
  opportunities = await response.json();
  renderOpportunityList();
}

function serpFailureText(detail) {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    const parts = [detail.google_message, detail.suggestion].filter((item) => typeof item === "string" && item);
    if (parts.length) return parts.join(" ");
  }
  return "SERP 查询失败";
}

async function searchCompetitors(cluster) {
  const button = document.getElementById("google-competitor-search");
  if (button) button.disabled = true;
  jobEl.textContent = "查询 SERP";
  try {
    const response = await fetch("/api/google-search/import-competitors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cluster_id: cluster.id,
        query: cluster.name || "",
        num: 10,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      jobEl.textContent = serpFailureText(data.detail);
      return;
    }
    const skipped = data.skipped ?? 0;
    if (data.provider === "serper") {
      jobEl.textContent = `Serper 已导入 ${data.raw_records_created} 条 SERP，生成 ${data.competitors_created} 条竞品草稿，跳过 ${skipped} 条重复 URL。`;
    } else {
      jobEl.textContent = `已导入 ${data.raw_records_created} 条 SERP 结果，生成 ${data.competitors_created} 条竞品页面草稿。`;
    }
  } catch (_error) {
    jobEl.textContent = "SERP 查询失败";
  } finally {
    if (button) button.disabled = false;
  }
}

async function generateOpportunity(clusterId) {
  const button = document.getElementById("opportunity-generate");
  if (button) button.disabled = true;
  jobEl.textContent = "生成项目卡";
  try {
    const response = await fetch(`/api/opportunities/from-keyword/${clusterId}`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      jobEl.textContent = "生成失败";
      return;
    }
    selectedOpportunityId = data.id;
    jobEl.textContent = `CARD ${data.id} ${data.verdict}`;
    setView("opportunities");
  } catch (_error) {
    jobEl.textContent = "生成失败";
  } finally {
    if (button) button.disabled = false;
  }
}

async function runOpportunityAnalyze(id) {
  const token = ++analyzeToken;
  const button = document.getElementById("opportunity-analyze");
  const box = document.getElementById("analysis");
  const status = document.getElementById("analyze-status");
  const elapsed = document.getElementById("elapsed");
  const savedHint = document.getElementById("saved-hint");
  if (!button || !box || !status || !elapsed) return;
  const previousLabel = button.textContent === "重新研判项目卡" ? "重新研判项目卡" : "AI 研判项目卡";
  button.disabled = true;
  button.textContent = "分析中...";
  status.textContent = "模型分析可能需要 30–90 秒，请勿重复点击";
  startTimer(elapsed);
  try {
    const response = await fetch(`/api/opportunities/${id}/analyze`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (token !== analyzeToken) return;
    if (!response.ok) {
      const detail = data.detail;
      const timedOut = detail && typeof detail === "object" && (
        detail.timeout_seconds != null || String(detail.message || "").includes("超时")
      );
      box.className = "analysis error";
      box.textContent = timedOut
        ? "模型接口超时。本次没有写入分析结果，可以稍后重试。"
        : formatError(detail);
      status.textContent = timedOut ? box.textContent : "";
      button.textContent = previousLabel;
      return;
    }
    if (savedHint) savedHint.textContent = "已有本地项目卡研判结果";
    status.textContent = "";
    elapsed.textContent = "";
    box.className = "analysis";
    box.textContent = data.analysis || "";
    button.textContent = "重新研判项目卡";
  } catch (_error) {
    if (token !== analyzeToken) return;
    box.className = "analysis error";
    box.textContent = "研判失败";
    button.textContent = previousLabel;
  } finally {
    if (token === analyzeToken) {
      stopTimer();
      button.disabled = false;
    }
  }
}

const SOURCE_TYPES = [
  "news",
  "google_trends",
  "search_console",
  "keyword_tool",
  "site_traffic",
  "new_site_growth",
  "dr_growth",
  "payment_ranking",
  "serp",
  "ai_search",
  "manual",
  "csv_import",
];
const SOURCE_GAP = "当前项目卡来源不足，仅作内部假设，不作为 Build 最终依据。";

const IMPORT_RECORD_TYPES = [
  "keyword_signal",
  "traffic_signal",
  "payment_signal",
  "competitor_url",
  "serp_result",
  "trend_signal",
  "manual_note",
];

function renderSourceList() {
  listEl.replaceChildren();
  if (dataSources.length === 0) {
    listEl.append(el("div", "empty", "NO SOURCE"));
    return;
  }
  dataSources.forEach((source) => {
    const row = el("div", selectedSourceId === source.id ? "item active" : "item");
    row.append(el("div", "title", source.name || "--"));
    const meta = el("div", "meta");
    meta.append(el("span", null, source.source_type || "--"));
    meta.append(el("span", null, source.provider || "--"));
    meta.append(el("span", null, source.region || "--"));
    meta.append(el("span", null, source.time_range || "--"));
    meta.append(el("span", null, source.enabled ? "enabled" : "off"));
    row.append(meta);
    row.dataset.id = String(source.id);
    row.addEventListener("click", () => openSource(source.id));
    listEl.append(row);
  });
}

function importTemplates() {
  const box = el("div", "import-templates");
  box.append(el("div", "hint", "CSV 模板"));
  [
    ["SERP CSV", "title,url,domain,snippet,rank"],
    ["Payment Ranking CSV", "domain,url,provider,rank,traffic,month"],
    ["Traffic Signal CSV", "domain,url,traffic,traffic_growth,source,month"],
    ["Keyword Signal CSV", "keyword,score,source,region,time_range"],
  ].forEach(([name, header]) => {
    box.append(el("div", "template-name", name));
    box.append(el("pre", "template-csv", header));
  });
  return box;
}

function renderImportList() {
  listEl.replaceChildren();
  listEl.append(importTemplates());
  if (sourceImports.length === 0) {
    listEl.append(el("div", "empty", "NO IMPORT"));
    return;
  }
  sourceImports.forEach((batch) => {
    const row = el("div", selectedImportId === batch.id ? "item active" : "item");
    row.append(el("div", "title", batch.import_name || "--"));
    const meta = el("div", "meta");
    if (isSampleText(batch.import_name)) meta.append(sampleTag());
    meta.append(el("span", null, batch.source_name || "--"));
    meta.append(el("span", null, batch.provider || "--"));
    meta.append(el("span", null, batch.source_type || "--"));
    meta.append(el("span", null, batch.record_type || "--"));
    meta.append(el("span", null, String(batch.row_count)));
    meta.append(el("span", null, formatTime(batch.created_at)));
    meta.append(el("span", null, batch.status || "--"));
    row.append(meta);
    row.dataset.importId = String(batch.id);
    row.addEventListener("click", () => openImport(batch.id));
    listEl.append(row);
  });
}

function renderLedger() {
  if (viewMode === "imports") renderImportList();
  else renderSourceList();
}

function renderSourceDetail(source) {
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "数据来源"));
  detailEl.append(el("div", "headline", source.name || "--"));
  [
    ["source_type", source.source_type],
    ["provider", source.provider],
    ["region", source.region],
    ["time_range", source.time_range],
    ["enabled", source.enabled ? "enabled" : "off"],
    ["notes", source.notes],
  ].forEach(([label, value]) => {
    const line = el("div", "meta-line");
    line.append(el("span", "k", label));
    line.append(el("span", null, value || "--"));
    detailEl.append(line);
  });
}

async function openSource(id) {
  selectedSourceId = id;
  selectedImportId = null;
  selectedId = null;
  selectedEventId = null;
  selectedKeywordId = null;
  selectedPageId = null;
  selectedOpportunityId = null;
  renderLedger();
  const source = dataSources.find((item) => item.id === id);
  if (!source) {
    detailEl.replaceChildren(el("div", "error", "数据源不存在"));
    return;
  }
  renderSourceDetail(source);
}

async function loadSources() {
  const response = await fetch("/api/sources");
  if (!response.ok) throw new Error("sources");
  dataSources = await response.json();
  const importsResponse = await fetch("/api/imports");
  sourceImports = importsResponse.ok ? await importsResponse.json() : [];
  renderLedger();
}

function showSourceForm() {
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "新增数据源"));
  const form = el("form", "page-form");
  const name = document.createElement("input");
  name.required = true;
  name.placeholder = "name";
  const sourceType = document.createElement("select");
  SOURCE_TYPES.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    sourceType.append(option);
  });
  sourceType.value = "manual";
  const provider = document.createElement("input");
  provider.placeholder = "provider";
  const region = document.createElement("input");
  region.placeholder = "region";
  const timeRange = document.createElement("input");
  timeRange.placeholder = "time_range";
  const notes = document.createElement("textarea");
  notes.placeholder = "notes";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "保存数据源";
  [name, sourceType, provider, region, timeRange, notes, button].forEach((node) => form.append(node));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    try {
      const response = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.value.trim(),
          source_type: sourceType.value,
          provider: provider.value.trim(),
          region: region.value.trim(),
          time_range: timeRange.value.trim(),
          notes: notes.value.trim(),
          enabled: 1,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        jobEl.textContent = "保存失败";
        button.disabled = false;
        return;
      }
      jobEl.textContent = `SOURCE ${data.id}`;
      selectedSourceId = data.id;
      await loadSources();
      renderSourceDetail(data);
    } catch (_error) {
      jobEl.textContent = "保存失败";
      button.disabled = false;
    }
  });
  detailEl.append(form);
}

function showImportForm() {
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "导入 CSV"));
  const form = el("form", "page-form");
  const sourceSelect = document.createElement("select");
  dataSources.forEach((source) => {
    const option = document.createElement("option");
    option.value = String(source.id);
    option.textContent = `${source.name} · ${source.source_type || "--"} · ${source.provider || "--"}`;
    sourceSelect.append(option);
  });
  const importName = document.createElement("input");
  importName.required = true;
  importName.placeholder = "import_name";
  const recordType = document.createElement("select");
  IMPORT_RECORD_TYPES.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    recordType.append(option);
  });
  recordType.value = "payment_signal";
  const csvText = document.createElement("textarea");
  csvText.placeholder = "csv_text";
  csvText.rows = 8;
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".csv,text/csv";
  const upload = document.createElement("button");
  upload.type = "button";
  upload.textContent = "上传 CSV 文件";
  const notes = document.createElement("textarea");
  notes.placeholder = "notes";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "导入";
  [sourceSelect, importName, recordType, fileInput, upload, csvText, notes, button].forEach((node) => form.append(node));
  upload.addEventListener("click", async () => {
    if (!fileInput.files || !fileInput.files[0]) {
      jobEl.textContent = "请选择 CSV 文件";
      return;
    }
    upload.disabled = true;
    const body = new FormData();
    body.append("file", fileInput.files[0]);
    body.append("source_id", sourceSelect.value);
    body.append("record_type", recordType.value);
    body.append("import_name", importName.value.trim());
    try {
      const response = await fetch("/api/imports/upload-csv", { method: "POST", body });
      const data = await response.json();
      if (!response.ok) {
        jobEl.textContent = typeof data.detail === "string" ? data.detail : "导入失败";
        upload.disabled = false;
        return;
      }
      jobEl.textContent = `IMPORT ${data.import_id} ROWS ${data.row_count}`;
      await loadSources();
      await openImport(data.import_id, "");
    } catch (_error) {
      jobEl.textContent = "导入失败";
      upload.disabled = false;
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    try {
      const response = await fetch("/api/imports/csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: Number(sourceSelect.value),
          import_name: importName.value.trim(),
          record_type: recordType.value,
          csv_text: csvText.value,
          notes: notes.value.trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        jobEl.textContent = "导入失败";
        button.disabled = false;
        return;
      }
      jobEl.textContent = data.warning || `IMPORT ${data.import_id} ROWS ${data.row_count}`;
      await loadSources();
      await openImport(data.import_id, data.warning || "");
    } catch (_error) {
      jobEl.textContent = "导入失败";
      button.disabled = false;
    }
  });
  detailEl.append(form);
}

async function openImport(id, warning) {
  selectedImportId = id;
  selectedSourceId = null;
  renderLedger();
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch(`/api/imports/${id}`);
    const batch = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", batch.detail || "加载失败"));
      return;
    }
    detailEl.replaceChildren();
    detailEl.append(el("div", "hint", "Data Imports"));
    detailEl.append(el("div", "headline", batch.import_name || "--"));
    if (warning) detailEl.append(el("div", "error", warning));
    [
      ["source", batch.source_name],
      ["provider", batch.provider],
      ["source_type", batch.source_type],
      ["record_type", batch.record_type],
      ["row_count", batch.row_count],
      ["status", batch.status],
      ["created_at", formatTime(batch.created_at)],
      ["notes", batch.notes],
    ].forEach(([label, value]) => {
      const line = el("div", "meta-line");
      line.append(el("span", "k", label));
      line.append(el("span", null, value === undefined || value === null || value === "" ? "--" : String(value)));
      detailEl.append(line);
    });
    if (batch.record_type === "serp_result") {
      const form = el("form", "page-form");
      const clusterId = document.createElement("input");
      clusterId.type = "number";
      clusterId.min = "1";
      clusterId.required = true;
      clusterId.placeholder = "cluster_id";
      clusterId.value = "1";
      const promote = document.createElement("button");
      promote.type = "submit";
      promote.textContent = "转为竞品页面草稿";
      form.append(clusterId, promote);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        promote.disabled = true;
        try {
          const response = await fetch(`/api/imports/${id}/promote-serp-competitors`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cluster_id: Number(clusterId.value) }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            jobEl.textContent = typeof data.detail === "string" ? data.detail : "生成失败";
            return;
          }
          jobEl.textContent = `已生成 ${data.created} 条竞品页面草稿，跳过 ${data.skipped} 条重复 URL。`;
        } catch (_error) {
          jobEl.textContent = "生成失败";
        } finally {
          promote.disabled = false;
        }
      });
      detailEl.append(form);
    }
    const rows = Array.isArray(batch.records) ? batch.records : [];
    if (rows.length === 0) {
      detailEl.append(el("div", "empty", "NO ROW"));
      return;
    }
    rows.forEach((row) => {
      const item = el("div", "item");
      const title = row.normalized_domain || row.normalized_keyword || row.normalized_title || row.normalized_url || `ROW ${row.id}`;
      item.append(el("div", "title", title));
      const meta = el("div", "meta");
      meta.append(el("span", null, row.source_name || "--"));
      meta.append(el("span", null, row.provider || "--"));
      meta.append(el("span", null, row.normalized_url || "--"));
      meta.append(el("span", null, row.metric_name ? `${row.metric_name} ${row.metric_value}` : "--"));
      item.append(meta);
      detailEl.append(item);
    });
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function loadSourceEvidence(cardId) {
  const box = document.getElementById("source-evidence");
  if (!box) return;
  box.replaceChildren(el("div", "hint", "Source Evidence"));
  try {
    const response = await fetch(`/api/source-records?linked_table=opportunity_cards&linked_id=${cardId}`);
    const rows = await response.json();
    if (!response.ok || !Array.isArray(rows) || rows.length === 0) {
      box.append(el("div", "empty", SOURCE_GAP));
      return;
    }
    rows.forEach((row) => {
      const label = row.raw_ref || row.record_type || "record";
      const from = row.source_name || row.provider || "未知来源";
      box.append(el("div", "item", `${label} from ${from}`));
    });
  } catch (_error) {
    box.append(el("div", "error", "来源加载失败"));
  }
}

function appendSourceBind(host, options) {
  const form = el("form", "page-form");
  form.append(el("div", "hint", "绑定来源"));
  const sourceSelect = document.createElement("select");
  const rawRef = document.createElement("input");
  rawRef.placeholder = "raw_ref";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "绑定来源";
  form.append(sourceSelect, rawRef, button);
  host.append(form);
  fetch("/api/sources")
    .then((response) => response.json())
    .then((sources) => {
      (Array.isArray(sources) ? sources : []).forEach((source) => {
        const option = document.createElement("option");
        option.value = String(source.id);
        option.textContent = source.name;
        sourceSelect.append(option);
      });
    })
    .catch(() => {
      sourceSelect.append(el("option", null, "来源加载失败"));
    });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!sourceSelect.value) return;
    button.disabled = true;
    try {
      const response = await fetch("/api/source-records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: Number(sourceSelect.value),
          record_type: options.recordType,
          linked_table: options.linkedTable,
          linked_id: options.linkedId,
          raw_ref: rawRef.value.trim(),
          confidence: "manual",
        }),
      });
      if (!response.ok) {
        jobEl.textContent = "绑定失败";
        button.disabled = false;
        return;
      }
      jobEl.textContent = "来源已绑定";
      rawRef.value = "";
      if (options.onSaved) await options.onSaved();
    } catch (_error) {
      jobEl.textContent = "绑定失败";
    } finally {
      button.disabled = false;
    }
  });
}

const GCLOUD_CHECKS = [
  "gcloud config get-value project",
  "gcloud services list --enabled | grep customsearch",
  "gcloud services list --enabled | grep searchconsole",
  "gcloud services list --enabled | grep analyticsdata",
];

function renderProviderHealth(payload) {
  detailEl.replaceChildren();
  detailEl.append(el("div", "hint", "Provider Health"));
  detailEl.append(el("div", "headline", `SERP_PROVIDER = ${payload.serp_provider || "--"}`));
  (payload.providers || []).forEach((item) => {
    const row = el("div", "slot-row");
    row.append(el("span", null, item.name || "--"));
    row.append(el("b", slotClass(item.status), item.status || "--"));
    detailEl.append(row);
    if (item.message) detailEl.append(el("div", "clamp", item.message));
    (item.details || []).forEach((line) => detailEl.append(el("div", "clamp", line)));
    if (item.action) detailEl.append(el("div", "clamp", item.action));
    if (item.last_status_code != null) detailEl.append(el("div", "clamp", `last_status_code ${item.last_status_code}`));
  });
  const check = document.createElement("button");
  check.id = "provider-google-check";
  check.type = "button";
  check.textContent = "检测";
  check.addEventListener("click", () => runGoogleHealthCheck(check));
  detailEl.append(check);
  detailEl.append(el("div", "hint", "这些命令只能检查配置，不能解决项目无 Custom Search JSON API 权限。"));
  GCLOUD_CHECKS.forEach((command) => detailEl.append(el("pre", "template-csv", command)));
}

async function loadProviderHealth() {
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const response = await fetch("/api/providers/health");
    const data = await response.json();
    if (!response.ok) {
      detailEl.replaceChildren(el("div", "error", "加载失败"));
      return;
    }
    renderProviderHealth(data);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function runGoogleHealthCheck(button) {
  button.disabled = true;
  jobEl.textContent = "检测 Google CSE";
  try {
    const response = await fetch("/api/providers/google-cse/check", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = "检测失败";
      button.disabled = false;
      return;
    }
    const google = (data.providers || []).find((item) => item.name === "Google CSE");
    jobEl.textContent = google ? `Google CSE ${google.status}` : "检测完成";
    renderProviderHealth(data);
  } catch (_error) {
    jobEl.textContent = "检测失败";
    button.disabled = false;
  }
}

const INTAKE_DATASETS = [
  ["", "未识别"],
  ["stripe_payment_ranking", "stripe_payment_ranking"],
  ["dr_growth_ranking", "dr_growth_ranking"],
  ["traffic_growth_ranking", "traffic_growth_ranking"],
  ["new_website_ranking", "new_website_ranking"],
  ["serp_result", "serp_result"],
  ["keyword_signal", "keyword_signal"],
];
const INTAKE_DATASET_META = {
  stripe_payment_ranking: ["payment_signal", "Stripe"],
  dr_growth_ranking: ["authority_signal", ""],
  traffic_growth_ranking: ["traffic_signal", ""],
  new_website_ranking: ["market_signal", ""],
  serp_result: ["serp_result", ""],
  keyword_signal: ["keyword_signal", ""],
};
const INTAKE_RECORD_TYPES = ["payment_signal", "traffic_signal", "authority_signal", "market_signal", "serp_result", "keyword_signal", "validation_signal", "crawl_signal"];
let intakePreview = null;
let intakeFiles = [];
let intakeSources = [];

function statusBadge(status) {
  return el("b", slotClass(status || "missing"), status || "missing");
}

async function loadIntake() {
  try {
    const [overviewRes, sourceRes] = await Promise.all([
      fetch("/api/intake/overview"),
      fetch("/api/sources"),
    ]);
    if (!overviewRes.ok) throw new Error("intake");
    const overview = await overviewRes.json();
    intakeSources = sourceRes.ok ? await sourceRes.json() : [];
    renderIntake(overview);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "Data Intake 加载失败"));
  }
}

function renderIntake(overview) {
  listEl.replaceChildren();
  [
    ["Crawl Jobs", overview.crawl.status],
    ["API Connectors", (overview.connectors.find((item) => item.provider === "serper") || {}).status || "missing"],
    ["Batch Imports", overview.imports.status],
    ["Source Ledger", overview.ledger.length ? "ready" : "missing"],
  ].forEach(([name, status]) => {
    const row = el("div", "item");
    row.append(el("div", null, name));
    row.append(statusBadge(status));
    listEl.append(row);
  });
  detailEl.replaceChildren();
  detailEl.append(renderCrawlBlock(overview.crawl));
  detailEl.append(renderConnectorBlock(overview.connectors));
  detailEl.append(renderImportBlock());
  detailEl.append(renderLedgerBlock(overview.ledger));
  if (intakePreview) renderIntakePreview(intakePreview);
}

function renderCrawlBlock(crawl) {
  const block = el("section", "intake-block");
  const head = el("div", "slot-row");
  head.append(el("h2", null, "Crawl Jobs"));
  head.append(statusBadge(crawl.status));
  block.append(head);
  block.append(el("p", "clamp", `真实抓取 ${crawl.real_count} 条，测试样本 ${crawl.sample_count} 条。只抓公开单页，sitemap 最多 20 条。`));
  const form = el("div", "intake-actions");
  form.append(labeledInput("intake-url", "url"));
  form.append(labeledInput("intake-domain", "domain"));
  form.append(labeledInput("intake-keyword", "keyword"));
  const type = el("select");
  type.id = "intake-crawl-type";
  ["landing_page", "pricing_page", "docs_page", "blog_page", "sitemap", "rss", "checkout_signal"].forEach((name) => {
    const option = el("option", null, name);
    option.value = name;
    type.append(option);
  });
  form.append(type);
  const button = el("button", null, "抓取公开页面");
  button.type = "button";
  button.addEventListener("click", runIntakeCrawl);
  form.append(button);
  block.append(form);
  block.append(el("div", null, ""));
  const recent = el("div");
  recent.id = "intake-crawl-result";
  (crawl.recent || []).forEach((row) => {
    recent.append(el("div", "clamp", `${row.normalized_domain || "--"} · ${row.normalized_title || row.normalized_url || "--"} · ${row.status || "--"}`));
  });
  block.append(recent);
  return block;
}

function labeledInput(id, placeholder) {
  const input = el("input");
  input.id = id;
  input.placeholder = placeholder;
  return input;
}

function renderConnectorBlock(connectors) {
  const block = el("section", "intake-block");
  block.append(el("h2", null, "API Connectors"));
  (connectors || []).forEach((item) => {
    const card = el("div", "file-row");
    const head = el("div", "slot-row");
    head.append(el("b", null, `${item.name} · ${item.provider}`));
    head.append(statusBadge(item.status));
    card.append(head);
    card.append(el("div", "clamp", item.message || ""));
    if (item.fallback) card.append(el("div", "clamp", `fallback = ${item.fallback}`));
    (item.details || []).forEach((line) => card.append(el("div", "clamp", line)));
    if ((item.uses || []).length) card.append(el("div", "clamp", item.uses.join(" · ")));
    if (item.provider === "gsc" || item.provider === "ga4") {
      const button = el("button", null, "占位查询");
      button.type = "button";
      button.addEventListener("click", () => pingConnector(item.provider === "gsc" ? "/api/gsc/query" : "/api/ga4/run-report"));
      card.append(button);
    }
    block.append(card);
  });
  return block;
}

function renderImportBlock() {
  const block = el("section", "intake-block");
  const head = el("div", "slot-row");
  head.append(el("h2", null, "Batch Imports"));
  block.append(head);
  block.append(el("p", "clamp", "上传后只生成 preview，不写入证据，也不改变 Dashboard。Confirm Import 后才入库。"));
  const form = el("div", "intake-actions");
  form.append(labeledInput("intake-name", "import_name"));
  form.append(labeledInput("intake-note", "import_note"));
  const source = el("select");
  source.id = "intake-source";
  const auto = el("option", null, "自动选择数据源");
  auto.value = "";
  source.append(auto);
  intakeSources.forEach((item) => {
    const option = el("option", null, item.name);
    option.value = String(item.id);
    source.append(option);
  });
  form.append(source);
  block.append(form);
  const files = el("input");
  files.id = "intake-files";
  files.type = "file";
  files.multiple = true;
  files.accept = ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const folder = el("input");
  folder.id = "intake-folder";
  folder.type = "file";
  folder.multiple = true;
  folder.webkitdirectory = true;
  folder.setAttribute("webkitdirectory", "");
  folder.setAttribute("directory", "");
  const actions = el("div", "intake-actions");
  const fileButton = el("button", null, "Upload Files");
  fileButton.type = "button";
  fileButton.addEventListener("click", () => files.click());
  const folderButton = el("button", null, "Upload Folder");
  folderButton.type = "button";
  folderButton.addEventListener("click", () => folder.click());
  actions.append(fileButton, folderButton, files, folder);
  block.append(actions);
  const drop = el("div", "drop-zone", "拖拽多个 CSV / XLSX 到这里");
  drop.id = "intake-drop";
  block.append(drop);
  const chosen = el("div");
  chosen.id = "intake-chosen";
  block.append(chosen);
  const previewButton = el("button", null, "识别文件");
  previewButton.type = "button";
  previewButton.addEventListener("click", previewIntake);
  block.append(previewButton);
  const preview = el("div");
  preview.id = "intake-preview";
  block.append(preview);
  files.addEventListener("change", () => {
    intakeFiles = [...files.files];
    renderChosenFiles();
  });
  folder.addEventListener("change", () => {
    intakeFiles = [...folder.files];
    renderChosenFiles();
  });
  drop.addEventListener("dragover", (event) => event.preventDefault());
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    intakeFiles = [...event.dataTransfer.files];
    renderChosenFiles();
  });
  return block;
}

function renderChosenFiles() {
  const box = document.getElementById("intake-chosen");
  if (!box) return;
  box.replaceChildren();
  if (!intakeFiles.length) {
    box.append(el("div", "clamp", "还没有选择文件"));
    return;
  }
  intakeFiles.forEach((file) => {
    box.append(el("div", "clamp", file.webkitRelativePath || file.name));
  });
}

function renderIntakePreview(preview) {
  const box = document.getElementById("intake-preview");
  if (!box) return;
  box.replaceChildren();
  const low = (preview.files || []).some((file) => Number(file.confidence) < 0.8);
  if (low) {
    box.append(el("div", "gap-line", "有文件置信度低于 0.8。请核对类型后再导入，系统不会自动入库。"));
    const label = el("label", "clamp");
    const check = el("input");
    check.type = "checkbox";
    check.id = "intake-review-confirmed";
    label.append(check, document.createTextNode(" 我已确认低置信度识别"));
    box.append(label);
  }
  (preview.files || []).forEach((file, index) => {
    const card = el("div", "file-row");
    card.append(el("div", null, file.file_name || "--"));
    card.append(el("div", "clamp", `relative_path ${file.relative_path || "--"}`));
    card.append(el("div", "clamp", `detected_dataset_type ${file.detected_dataset_type || "--"} · period_month ${file.period_month || "--"} · confidence ${file.confidence}`));
    const type = el("select");
    type.id = `intake-type-${index}`;
    INTAKE_DATASETS.forEach(([value, labelText]) => {
      const option = el("option", null, labelText);
      option.value = value;
      if (value === file.detected_dataset_type) option.selected = true;
      type.append(option);
    });
    const record = el("select");
    record.id = `intake-record-${index}`;
    INTAKE_RECORD_TYPES.forEach((value) => {
      const option = el("option", null, value);
      option.value = value;
      if (value === file.record_type) option.selected = true;
      record.append(option);
    });
    const provider = labeledInput(`intake-provider-${index}`, "provider");
    provider.value = file.provider || "";
    const note = labeledInput(`intake-file-note-${index}`, "import_note");
    note.value = document.getElementById("intake-note") ? document.getElementById("intake-note").value : "";
    type.addEventListener("change", () => {
      const meta = INTAKE_DATASET_META[type.value];
      if (!meta) return;
      record.value = meta[0];
      if (!provider.dataset.touched) provider.value = meta[1];
    });
    provider.addEventListener("input", () => {
      provider.dataset.touched = "1";
    });
    card.append(type, record, provider, note);
    card.append(el("div", "clamp", `columns: ${(file.columns || []).join(", ") || "--"}`));
    (file.warnings || []).forEach((warning) => card.append(el("div", "gap-line", warning)));
    (file.sample_rows || []).slice(0, 3).forEach((row) => {
      const domain = row.domain || row.url || row.keyword || "";
      card.append(el("div", "clamp", `${domain} · ${row.title || row.rank || ""}`.trim()));
    });
    box.append(card);
  });
  const button = el("button", null, "Confirm Import");
  button.type = "button";
  button.id = "intake-confirm";
  button.addEventListener("click", confirmIntake);
  box.append(button);
}

async function previewIntake() {
  if (!intakeFiles.length) {
    jobEl.textContent = "请选择文件";
    return;
  }
  const body = new FormData();
  intakeFiles.forEach((file) => {
    body.append("files", file, file.name);
    body.append("relative_paths", file.webkitRelativePath || file.name);
  });
  body.append("import_name", document.getElementById("intake-name").value.trim());
  body.append("import_note", document.getElementById("intake-note").value.trim());
  const source = document.getElementById("intake-source").value;
  if (source) body.append("source_id", source);
  body.append("auto_detect", "true");
  jobEl.textContent = "识别中";
  try {
    const response = await fetch("/api/imports/upload-batch", { method: "POST", body });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = typeof data.detail === "string" ? data.detail : "识别失败";
      return;
    }
    intakePreview = data;
    renderIntakePreview(data);
    jobEl.textContent = `已识别 ${data.files.length} 个文件，尚未入库`;
  } catch (_error) {
    jobEl.textContent = "识别失败";
  }
}

async function confirmIntake() {
  if (!intakePreview) return;
  const low = (intakePreview.files || []).some((file) => Number(file.confidence) < 0.8);
  const review = document.getElementById("intake-review-confirmed");
  if (low && !(review && review.checked)) {
    jobEl.textContent = "置信度低于 0.8，请确认后再导入";
    return;
  }
  const files = (intakePreview.files || []).map((file, index) => ({
    file_name: file.file_name,
    relative_path: file.relative_path || "",
    dataset_type: document.getElementById(`intake-type-${index}`).value,
    record_type: document.getElementById(`intake-record-${index}`).value,
    provider: document.getElementById(`intake-provider-${index}`).value.trim(),
    import_note: document.getElementById(`intake-file-note-${index}`).value.trim(),
  }));
  const payload = {
    preview_id: intakePreview.preview_id,
    import_name: document.getElementById("intake-name").value.trim(),
    import_note: document.getElementById("intake-note").value.trim(),
    review_confirmed: !low || Boolean(review && review.checked),
    files,
  };
  const source = document.getElementById("intake-source").value;
  if (source) payload.source_id = Number(source);
  jobEl.textContent = "导入中";
  try {
    const response = await fetch("/api/imports/confirm-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = typeof data.detail === "string" ? data.detail : "导入失败";
      return;
    }
    const imported = (data.imports || []).filter((item) => item.status === "imported" || item.status === "empty");
    jobEl.textContent = `已入库 ${imported.length} 个文件`;
    intakePreview = null;
    intakeFiles = [];
    await loadIntake();
  } catch (_error) {
    jobEl.textContent = "导入失败";
  }
}

async function runIntakeCrawl() {
  const payload = {
    url: document.getElementById("intake-url").value.trim(),
    domain: document.getElementById("intake-domain").value.trim(),
    keyword: document.getElementById("intake-keyword").value.trim(),
    crawl_type: document.getElementById("intake-crawl-type").value,
  };
  jobEl.textContent = "抓取中";
  try {
    const response = await fetch("/api/crawl/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = typeof data.detail === "string" ? data.detail : "抓取失败";
      return;
    }
    jobEl.textContent = `抓取 ${data.pages} 页 · ${data.status}`;
    await loadIntake();
  } catch (_error) {
    jobEl.textContent = "抓取失败";
  }
}

async function pingConnector(path) {
  jobEl.textContent = "占位查询";
  try {
    const response = await fetch(path, { method: "POST" });
    const data = await response.json();
    jobEl.textContent = typeof data.detail === "string" ? data.detail : "占位接口已返回";
  } catch (_error) {
    jobEl.textContent = "占位查询失败";
  }
}

function renderLedgerBlock(rows) {
  const block = el("section", "intake-block");
  block.append(el("h2", null, "Source Ledger"));
  if (!rows.length) {
    block.append(el("div", "empty", "NO SOURCE"));
    return block;
  }
  rows.forEach((row) => {
    const card = el("div", "file-row");
    const head = el("div", "slot-row");
    head.append(el("b", null, row.source_name || "--"));
    head.append(statusBadge(row.last_status || "missing"));
    card.append(head);
    const months = (row.months_covered || []).join(", ") || "--";
    card.append(el("div", "clamp", `${row.provider || "--"} · ${row.dataset_type || "--"} · ${row.access_mode} · rows ${row.row_count} · months ${months}`));
    card.append(el("div", "clamp", `configured ${row.configured ? "yes" : "no"} · last_run ${row.last_run_at || "--"}`));
    block.append(card);
  });
  return block;
}

collectBtn.addEventListener("click", runCollect);
document.getElementById("view-dashboard").addEventListener("click", () => setView("dashboard"));
document.getElementById("view-opportunities").addEventListener("click", () => setView("opportunities"));
document.getElementById("view-keywords").addEventListener("click", () => setView("keywords"));
document.getElementById("view-competitors").addEventListener("click", () => setView("competitors"));
document.getElementById("view-admin").addEventListener("click", () => setView(ADMIN_MODES.includes(viewMode) ? viewMode : "sources"));
document.getElementById("view-intake").addEventListener("click", () => setView("intake"));
document.getElementById("view-health").addEventListener("click", () => setView("health"));
document.getElementById("view-sources").addEventListener("click", () => setView("sources"));
document.getElementById("view-imports").addEventListener("click", () => setView("imports"));
document.getElementById("view-trace").addEventListener("click", () => setView("trace"));
document.getElementById("view-items").addEventListener("click", () => setView("items"));
document.getElementById("view-events").addEventListener("click", () => setView("events"));
document.getElementById("build-events").addEventListener("click", buildEventList);
document.getElementById("seed-keywords").addEventListener("click", seedKeywordPool);
document.getElementById("add-competitor").addEventListener("click", showCompetitorForm);
document.getElementById("add-source").addEventListener("click", showSourceForm);
document.getElementById("import-csv").addEventListener("click", showImportForm);
loadDashboard().catch(() => {
  const root = document.getElementById("cockpit");
  if (root) root.replaceChildren(el("div", "error", "看板加载失败"));
});
