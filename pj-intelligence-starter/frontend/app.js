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
let viewMode = "briefing";
let dashboardOpportunityId = null;
let evidenceStats = { groups: [], record_types: [] };
let dashboardLatest = { items: [] };
let dashboardExternal = { items: [] };
let dashboardFeed = { items: [] };
let dashboardToday = { items: [] };
let dashboardDossiers = { items: [] };
let dashboardSiteSignals = { items: [] };
let dashboardSiteOpps = { items: [] };
let sitedataSettings = { auto_create_dossier: false };
let sitedataConnector = null;
let dashboardRanks = { payment: [], traffic: [], authority: [] };
let collectStatus = { finished_at: "", sources_checked: 0, new_items: 0, error_count: 0, top_signal: "" };
let explorerQuery = { dataset_type: "", record_type: "", provider: "", batch_id: "", period_month: "", domain: "", keyword: "", source_name: "", offset: 0 };
let explorerPage = { total: 0, limit: 50, offset: 0, items: [] };
let explorerOpenId = null;
let externalQuery = { min_score: "", evidence_type: "", domain: "", offset: 0 };
let externalPage = { total: 0, limit: 50, offset: 0, items: [] };
let selectedBatchId = null;
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

const ADMIN_MODES = ["intake", "health", "storage", "imports", "trace", "items", "events", "opportunities", "keywords", "competitors"];
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
  const board = mode === "explorer" || mode === "external" || mode === "feed" || mode === "dossier" || mode === "dossiers";
  const briefing = mode === "briefing" || mode === "signals";
  document.body.dataset.screen = briefing ? "briefing" : board ? "board" : "workspace";
  document.body.dataset.focus = focused ? "work" : "admin";
  document.getElementById("admin-nav").hidden = !(admin || mode === "sources");
  document.querySelectorAll("#admin-nav > button").forEach((button) => {
    if (button.id === "add-source") button.hidden = mode !== "sources";
    else if (button.id === "import-csv") button.hidden = mode !== "imports";
    else if (button.id === "collect") button.hidden = mode !== "items";
    else if (button.id === "build-events") button.hidden = mode !== "events";
    else button.hidden = mode === "sources";
  });
  const collectNow = document.getElementById("collect-now");
  const collectStatusBox = document.getElementById("collect-status");
  if (collectNow) collectNow.hidden = briefing || mode === "dossier" || mode === "dossiers";
  if (collectStatusBox) collectStatusBox.hidden = briefing || mode === "dossier" || mode === "dossiers";
  document.getElementById("view-briefing").classList.toggle("on", mode === "briefing");
  document.getElementById("view-signals").classList.toggle("on", mode === "signals");
  document.getElementById("view-dossiers").classList.toggle("on", mode === "dossiers" || mode === "dossier");
  document.getElementById("view-explorer").classList.toggle("on", mode === "explorer");
  document.getElementById("view-external").classList.toggle("on", mode === "external");
  document.getElementById("view-opportunities").classList.toggle("on", mode === "opportunities");
  document.getElementById("view-keywords").classList.toggle("on", mode === "keywords");
  document.getElementById("view-competitors").classList.toggle("on", mode === "competitors");
  document.getElementById("view-admin").classList.toggle("on", admin);
  document.getElementById("view-health").classList.toggle("on", mode === "health");
  document.getElementById("view-storage").classList.toggle("on", mode === "storage");
  document.getElementById("view-intake").classList.toggle("on", mode === "intake");
  document.getElementById("view-sources").classList.toggle("on", mode === "sources");
  document.getElementById("view-imports").classList.toggle("on", mode === "imports");
  document.getElementById("view-trace").classList.toggle("on", mode === "trace");
  document.getElementById("view-items").classList.toggle("on", mode === "items");
  document.getElementById("view-events").classList.toggle("on", mode === "events");
  document.getElementById("seed-keywords").hidden = mode !== "keywords";
  document.getElementById("add-competitor").hidden = mode !== "competitors";
  const titles = {
    opportunities: "OPPORTUNITIES",
    keywords: "KEYWORDS",
    competitors: "COMPETITORS",
    health: "PROVIDER HEALTH",
    storage: "STORAGE HEALTH",
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

function tierLabel(tier) {
  if (tier === "P0_priority" || tier === "P0") return "P0";
  if (tier === "P1_research" || tier === "P1") return "P1";
  if (tier === "P2_watch" || tier === "P2") return "P2";
  return "P3";
}

function priorityBadge(tier) {
  const label = tierLabel(tier);
  return el("span", `prio prio-${label.toLowerCase()}`, label);
}

function signalKind(row) {
  const tags = row.evidence_tags || row.tags || [];
  if (tags.includes("Payment") || row.signal === "payment") return "Payment";
  if (tags.includes("Traffic") || row.signal === "traffic_growth") return "Traffic";
  if (tags.includes("Authority") || row.signal === "authority_growth") return "Authority";
  if (tags.includes("SERP") || row.signal === "serp") return "SERP";
  if (tags.includes("Product Hunt") || row.feed_type === "launch") return "Launch";
  return row.signal || "Signal";
}

function visibleOpportunities() {
  return (dashboardExternal.items || []).filter((row) => !isDeskNoise(row.domain) && row.opportunity_tier !== "P3_noise");
}

function evidenceNarrative(name, status) {
  const ready = status === "Ready";
  const partial = status === "Partial" || status === "Sample Only";
  if (name === "Payment") {
    if (ready) return "支付信号已充足，但仍需确认 pricing / checkout，不能单独作为 Build 依据。";
    if (partial) return "已有一些支付痕迹，还不够判断商业化是否稳定。";
    return "还没有支付信号，不能判断是否有人付钱。";
  }
  if (name === "Traffic") {
    if (ready) return "流量增长已经能看出分发迹象，下一步要核对关键词和付费入口。";
    if (partial) return "流量证据还不完整，只能作为观察，不能单独下判断。";
    return "还没有流量增长证据。";
  }
  if (name === "Authority") {
    if (ready) return "权重增长已能看出外链或内容集群，仍需查反链和页面。";
    if (partial) return "权重信号零散，还不能判断 SEO 策略。";
    return "还没有权重增长证据。";
  }
  if (name === "SERP") {
    if (ready) return "搜索结果已够用来看竞争页面。";
    if (partial) return "搜索结果还不完整，还不能判断这个词的竞争页面。";
    return "还没有搜索结果，竞争页面是空的。";
  }
  if (name === "Competitor") {
    if (ready) return "竞品页已够做拆解。";
    if (partial) return "竞品页不够，还不能做正式拆解。";
    return "还没有竞品页。";
  }
  if (ready) return "验证证据已够支持正式判断。";
  return "缺少验证证据。当前只能进入 Research，不能正式 Build。";
}

function statusClass(status) {
  if (status === "Ready") return "status-ready";
  if (status === "Partial" || status === "Sample Only") return "status-partial";
  return "status-missing";
}

function renderSignalCard(row) {
  const card = el("article", "intel-card");
  const top = el("div", "slot-row");
  const title = el("h3", null, row.domain || "--");
  top.append(title);
  top.append(priorityBadge(row.opportunity_tier));
  card.append(top);
  const tags = (row.evidence_tags || row.tags || []).join(" + ") || signalKind(row);
  card.append(el("div", "clamp", `${signalKind(row)} · Score ${row.opportunity_score ?? row.score ?? "--"}`));
  card.append(el("div", "clamp", tags));
  card.append(el("p", null, `判断：${row.reason || row.why_it_matters || row.why || "多条线索同时出现，值得先看一眼。"}`));
  const missing = Array.isArray(row.missing_evidence) ? row.missing_evidence.join(" / ") : (row.missing_evidence || "--");
  card.append(el("div", "clamp", `缺口：${missing}`));
  card.append(el("div", "clamp", `下一步：${row.next_action || "--"}`));
  card.append(deskDossierActions(row.domain, row.dossier_id, row.id ? row : null));
  return card;
}

function queueBuckets() {
  const rows = visibleOpportunities();
  const used = new Set();
  const take = (list) => list.filter((row) => {
    const domain = row.domain || "";
    if (!domain || used.has(domain)) return false;
    used.add(domain);
    return true;
  }).slice(0, 5);
  const priority = take(rows.filter((row) => row.opportunity_tier === "P0_priority"));
  let research = take(rows.filter((row) => row.opportunity_tier === "P1_research"));
  let watch = take(rows.filter((row) => row.opportunity_tier === "P2_watch"));
  const dossiers = dashboardDossiers.items || [];
  if (!research.length) {
    research = take(dossiers.filter((row) => /research/i.test(row.opportunity_status || "") || row.priority_level === "P1").map((row) => ({
      domain: row.domain,
      opportunity_tier: "P1_research",
      opportunity_score: row.evidence_score,
      reason: row.one_line_judgment,
      evidence_tags: row.evidence_tags || [],
      missing_evidence: row.missing_evidence || [],
      next_action: row.next_action || "Open Dossier",
      dossier_id: row.id,
    })));
  }
  if (!watch.length) {
    watch = take(dossiers.filter((row) => /watch/i.test(row.opportunity_status || "") || row.priority_level === "P2" || row.priority_level === "P3").map((row) => ({
      domain: row.domain,
      opportunity_tier: "P2_watch",
      opportunity_score: row.evidence_score,
      reason: row.one_line_judgment,
      evidence_tags: row.evidence_tags || [],
      missing_evidence: row.missing_evidence || [],
      next_action: row.next_action || "保持观察",
      dossier_id: row.id,
    })));
  }
  return { priority, research, watch };
}

function renderQueueColumn(title, rows, empty) {
  const column = el("section", "queue-col");
  column.append(el("h3", null, title));
  if (!rows.length) column.append(el("div", "empty", empty));
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    line.append(el("b", null, row.domain || "--"));
    line.append(el("div", "clamp", `Score ${row.opportunity_score ?? "--"} · ${(row.evidence_tags || []).join(" + ") || signalKind(row)}`));
    line.append(el("div", "clamp", row.reason || row.next_action || "--"));
    line.addEventListener("click", () => {
      if (row.dossier_id && !row.opportunity_tier) openDossier(row.dossier_id);
      else if (row.dossier_id && row.opportunity_tier !== "P0_priority") openDossier(row.dossier_id);
      else {
        externalQuery = { ...externalQuery, domain: row.domain || "", offset: 0 };
        setView("external");
      }
    });
    column.append(line);
  });
  return column;
}

function renderEvidenceBoard() {
  const board = el("div", "evidence-board");
  const cards = [
    ["Payment Evidence", "Payment", "Payment Signal", paymentStatus()],
    ["Traffic Evidence", "Traffic", "Traffic Signal", trafficStatus()],
    ["Authority Evidence", "Authority", "Authority Signal", authorityStatus()],
    ["SERP Evidence", "SERP", "SERP Signal", serpStatus()],
    ["Competitor Evidence", "Competitor", "Competitor Signal", competitorSlotStatus(competitors)],
    ["Validation Evidence", "Validation", "Validation Signal", validationStatus()],
  ];
  cards.forEach(([title, name, slot, status]) => {
    const summary = evidenceSummary(slot);
    const card = el("article", "evidence-card");
    card.append(el("h3", null, title));
    const meta = el("div", statusClass(status), `${status} · ${summary.record_count} 条记录 · 最近 ${summary.latest_month || "--"}`);
    card.append(meta);
    card.append(el("div", "clamp", `Top: ${(summary.domains || []).slice(0, 3).join(", ") || "--"}`));
    card.append(el("p", null, evidenceNarrative(name, status)));
    board.append(card);
  });
  return board;
}

function renderBriefFeed() {
  const section = el("section", "cockpit-card");
  section.id = "intelligence-feed";
  section.append(el("p", "section-label", "Intelligence Feed"));
  const rows = (dashboardFeed.items || []).slice(0, 20);
  if (!rows.length) {
    section.append(el("div", "empty", "今天还没有新的情报流。"));
    return section;
  }
  rows.forEach((row) => {
    const line = el("article", "intel-card");
    line.append(el("div", "clamp", `${formatCollectTime(row.time || row.created_at)} · ${row.source || row.source_name || "--"} · ${row.domain || "--"} · ${row.signal || "--"}`));
    line.append(el("h3", null, row.title || row.domain || "--"));
    line.append(el("p", null, row.why_it_matters || row.why || "--"));
    line.append(el("div", "clamp", `下一步：${row.next_action || "--"}`));
    line.append(deskDossierActions(row.domain, row.dossier_id, row));
    section.append(line);
  });
  return section;
}

function renderBriefing() {
  const root = document.getElementById("cockpit");
  if (!root) return;
  const signals = visibleOpportunities().slice(0, 8);
  const buckets = queueBuckets();
  const names = signals.slice(0, 3).map((row) => row.domain).filter(Boolean);
  const validation = validationStatus();
  const lead = `今日先看 ${signals.length} 条优先线索，队列中 ${buckets.priority.length} 条进入优先研究、${buckets.research.length} 条继续研究、${buckets.watch.length} 条保持观察。当前不能正式 Build，主要缺口是 Validation。建议优先研究 ${names.join("、") || "还没有足够干净的域名"}。`;
  root.replaceChildren();
  const hero = el("section", "cockpit-card brief-hero");
  hero.id = "daily-brief";
  hero.append(el("p", "section-label", "Daily Intelligence Brief"));
  hero.append(el("p", "brief-lead", lead));
  const metrics = el("div", "brief-metrics");
  [
    ["New signals", String((dashboardFeed.items || []).length)],
    ["P0 / P1", `${buckets.priority.length} / ${buckets.research.length}`],
    ["Payment", paymentStatus()],
    ["Traffic", trafficStatus()],
    ["Authority", authorityStatus()],
    ["Validation", validation],
    ["Last updated", formatCollectTime((dashboardFeed.items || [])[0]?.created_at || collectStatus.finished_at)],
  ].forEach(([label, value]) => metrics.append(metricNode(label, value, label === "Validation" && validation === "Missing")));
  hero.append(metrics);
  hero.append(el("p", "clamp", `外部机会池已聚合 ${Number(dashboardExternal.total) || visibleOpportunities().length} 条记录，首页仅展示 P0 / P1 机会。`));
  root.append(hero);

  const priority = el("section", "cockpit-card");
  priority.id = "priority-signals";
  priority.append(el("p", "section-label", "Priority Signals"));
  if (!signals.length) priority.append(el("div", "empty", "今天还没有够格进入优先研究的域名。"));
  signals.forEach((row) => priority.append(renderSignalCard(row)));
  root.append(priority);

  const queue = el("section", "cockpit-card");
  queue.id = "opportunity-queue";
  queue.append(el("p", "section-label", "Opportunity Queue"));
  const board = el("div", "queue-board");
  board.append(renderQueueColumn("Priority Research", buckets.priority, "这一档暂无优先域名。"));
  board.append(renderQueueColumn("Research", buckets.research, "这一档暂无待研究域名。"));
  board.append(renderQueueColumn("Watch", buckets.watch, "这一档暂无观察域名。"));
  queue.append(board);
  root.append(queue);

  const evidence = el("section", "cockpit-card");
  evidence.id = "evidence-board";
  evidence.append(el("p", "section-label", "Evidence Board"));
  evidence.append(renderEvidenceBoard());
  root.append(evidence);
  root.append(renderBriefFeed());
}

function renderSignals() {
  const root = document.getElementById("cockpit");
  if (!root) return;
  root.replaceChildren();
  const section = el("section", "cockpit-card");
  section.id = "signal-desk";
  section.append(el("p", "section-label", "Signals"));
  section.append(el("p", "clamp", "这里只放值得分析师先看的信号，不放库表和备份。"));
  visibleOpportunities().slice(0, 10).forEach((row) => section.append(renderSignalCard(row)));
  if (!visibleOpportunities().length) section.append(el("div", "empty", "还没有优先信号。"));
  root.append(section);
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

async function loadJsonObject(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    return await response.json();
  } catch (_error) {
    return null;
  }
}

async function loadDashboard() {
  const [oppRes, kwRes, compRes, stats, latest, external, feed, today, ranks, status, dossiers, siteSignals, siteOpps] = await Promise.all([
    fetch("/api/opportunities"),
    fetch("/api/keywords"),
    fetch("/api/competitors"),
    loadEvidenceStats(),
    loadJsonObject("/api/explorer/records?limit=10"),
    loadJsonObject("/api/external-opportunities?limit=15&home=true"),
    loadJsonObject("/api/intelligence/feed?limit=20"),
    loadJsonObject("/api/dashboard/today?limit=10"),
    loadJsonObject("/api/dashboard/ranks?limit=10"),
    loadJsonObject("/api/intake/collect-status"),
    loadJsonObject("/api/dossiers?limit=10"),
    loadJsonObject("/api/sitedata/signals?limit=20"),
    loadJsonObject("/api/sitedata/opportunities?limit=10"),
  ]);
  if (!oppRes.ok || !kwRes.ok || !compRes.ok) throw new Error("dashboard");
  opportunities = await oppRes.json();
  keywords = await kwRes.json();
  competitors = await compRes.json();
  evidenceStats = stats;
  dashboardLatest = latest && Array.isArray(latest.items) ? latest : { items: [] };
  dashboardExternal = external && Array.isArray(external.items) ? external : { items: [] };
  dashboardFeed = feed && Array.isArray(feed.items) ? feed : { items: [] };
  dashboardToday = today && Array.isArray(today.items) ? today : { items: [] };
  dashboardDossiers = dossiers && Array.isArray(dossiers.items) ? dossiers : { items: [] };
  dashboardSiteSignals = siteSignals && Array.isArray(siteSignals.items) ? siteSignals : { items: [] };
  dashboardSiteOpps = siteOpps && Array.isArray(siteOpps.items) ? siteOpps : { items: [] };
  dashboardRanks = ranks && Array.isArray(ranks.payment) ? ranks : { payment: [], traffic: [], authority: [] };
  collectStatus = status || collectStatus;
  renderCollectStatus();
  dashboardFeeds = { imports: [], serp: [], payment: [], traffic: [], keywords: [], crawl: [], authority: [], validation: [] };
  if (viewMode === "briefing") renderBriefing();
  if (viewMode === "signals") renderSignals();
}

function setView(mode) {
  viewMode = mode;
  if (mode !== "dossier" && location.pathname.startsWith("/dossiers/")) {
    history.pushState({}, "", "/");
  }
  applyChrome(mode);
  if (mode === "briefing" || mode === "signals") {
    loadDashboard().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "简报加载失败"));
    });
    return;
  }
  if (mode === "explorer") {
    loadExplorer().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "Data Explorer 加载失败"));
    });
    return;
  }
  if (mode === "external") {
    loadExternal().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "External Opportunities 加载失败"));
    });
    return;
  }
  if (mode === "feed") {
    loadFeedPage().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "Feed 加载失败"));
    });
    return;
  }
  if (mode === "dossiers") {
    loadDossierList().catch(() => {
      const root = document.getElementById("cockpit");
      if (root) root.replaceChildren(el("div", "error", "案卷加载失败"));
    });
    return;
  }
  if (mode === "health") {
    listEl.replaceChildren(el("div", "empty", "状态在右侧"));
    loadProviderHealth();
    return;
  }
  if (mode === "storage") {
    listEl.replaceChildren(el("div", "empty", "状态在右侧"));
    loadStorageHealth();
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
  const headerCollect = document.getElementById("collect-now");
  collectBtn.disabled = true;
  if (headerCollect) headerCollect.disabled = true;
  jobEl.textContent = "采集中";
  try {
    const response = await fetch("/api/intake/collect-now", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      jobEl.textContent = "采集失败";
      return;
    }
    const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
    jobEl.textContent = `+${data.new_items || data.inserted || 0}  SKIP ${data.skipped || 0}${errorCount ? `  ERR ${errorCount}` : ""}`;
    collectStatus = {
      finished_at: data.finished_at || "",
      sources_checked: data.sources_checked || 0,
      new_items: data.new_items || 0,
      error_count: errorCount,
      top_signal: data.top_signal || "",
    };
    renderCollectStatus();
    if (viewMode === "briefing" || viewMode === "signals" || viewMode === "feed") await loadDashboard();
    else await refresh();
  } catch (_error) {
    jobEl.textContent = "采集失败";
  } finally {
    collectBtn.disabled = false;
    if (headerCollect) headerCollect.disabled = false;
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
  "rss",
  "website",
  "product_hunt",
  "hacker_news",
  "github",
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
  listEl.append(renderSiteDataRunner());
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
    meta.append(el("span", null, source.last_status || "missing"));
    meta.append(el("span", null, String(source.records_collected || 0)));
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
    ["url", source.url],
    ["enabled", source.enabled ? "enabled" : "off"],
    ["last_run_at", source.last_run_at],
    ["last_status", source.last_status],
    ["records_collected", String(source.records_collected || 0)],
    ["error_message", source.error_message],
    ["notes", source.notes],
  ].forEach(([label, value]) => {
    const line = el("div", "meta-line");
    line.append(el("span", "k", label));
    line.append(el("span", null, value || "--"));
    detailEl.append(line);
  });
  const actions = el("div", "filter-bar");
  const run = el("button", null, "Run");
  run.type = "button";
  run.addEventListener("click", () => runSource(source.id, run));
  const toggle = el("button", null, source.enabled ? "Disable" : "Enable");
  toggle.type = "button";
  toggle.addEventListener("click", () => toggleSource(source, toggle));
  const view = el("button", null, "View records");
  view.type = "button";
  view.addEventListener("click", () => viewSourceRecords(source.id));
  actions.append(run, toggle, view);
  detailEl.append(actions);
  const records = el("div");
  records.id = "source-records";
  detailEl.append(records);
}

async function runSource(sourceId, button) {
  button.disabled = true;
  jobEl.textContent = "采集来源";
  try {
    const response = await fetch(`/api/sources/${sourceId}/run`, { method: "POST" });
    const data = await response.json();
    jobEl.textContent = response.ok ? `${data.status} +${data.records_collected || 0}` : (data.detail || "采集失败");
    await loadSources();
    await openSource(sourceId);
  } catch (_error) {
    jobEl.textContent = "采集失败";
  } finally {
    button.disabled = false;
  }
}

async function toggleSource(source, button) {
  button.disabled = true;
  const enabled = source.enabled ? 0 : 1;
  try {
    const response = await fetch(`/api/sources/${source.id}/enabled?enabled=${enabled}`, { method: "POST" });
    if (!response.ok) {
      jobEl.textContent = "更新失败";
      return;
    }
    await loadSources();
    await openSource(source.id);
  } catch (_error) {
    jobEl.textContent = "更新失败";
  } finally {
    button.disabled = false;
  }
}

async function viewSourceRecords(sourceId) {
  const box = document.getElementById("source-records");
  if (!box) return;
  box.replaceChildren(el("div", "hint", "加载记录"));
  try {
    const response = await fetch(`/api/sources/${sourceId}/records`);
    const rows = await response.json();
    if (!response.ok || !Array.isArray(rows) || !rows.length) {
      box.replaceChildren(el("div", "empty", "这个来源还没有采集记录"));
      return;
    }
    box.replaceChildren();
    rows.forEach((row) => box.append(el("div", "clamp", `${row.title || "--"} · ${row.domain || "--"} · ${row.url || "--"}`)));
  } catch (_error) {
    box.replaceChildren(el("div", "error", "记录加载失败"));
  }
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
  const settings = await loadJsonObject("/api/sitedata/settings");
  if (settings) sitedataSettings = settings;
  const overview = await loadJsonObject("/api/intake/overview");
  sitedataConnector = (overview?.connectors || []).find((item) => item.provider === "sitedata") || null;
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
  const url = document.createElement("input");
  url.placeholder = "url";
  const region = document.createElement("input");
  region.placeholder = "region";
  const timeRange = document.createElement("input");
  timeRange.placeholder = "time_range";
  const notes = document.createElement("textarea");
  notes.placeholder = "notes";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "保存数据源";
  [name, sourceType, provider, url, region, timeRange, notes, button].forEach((node) => form.append(node));
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
          url: url.value.trim(),
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
  if (payload.sitedata) {
    const site = payload.sitedata;
    detailEl.append(el("div", "clamp", `SiteData CLI: ${site.status}`));
    detailEl.append(el("div", "clamp", `OAuth status: ${site.auth || "missing"}`));
    detailEl.append(el("div", "clamp", `Available APIs: ${(site.available_apis || []).join(", ") || "--"}`));
    detailEl.append(el("div", "clamp", `Last run time: ${site.last_run_at || "--"}`));
    detailEl.append(el("div", "clamp", `Last status: ${site.last_status || "--"}`));
    detailEl.append(el("div", "clamp", `Last error: ${site.last_error || "--"}`));
    if (site.note) detailEl.append(el("div", "clamp", site.note));
  }
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

function renderStorageHealth(data, backups) {
  detailEl.replaceChildren();
  const card = el("section", "cockpit-card");
  card.id = "storage-health";
  card.append(el("h2", null, "STORAGE HEALTH"));
  if (!data.persistent_volume) {
    card.append(el("div", "error", "当前数据库可能在容器内部，重建容器可能导致数据丢失。建议挂载 ./data:/app/data。"));
  }
  [
    `DB 路径：${data.database_path || "--"}`,
    `DB 大小：${data.database_size_mb ?? "--"} MB`,
    `是否持久化：${data.persistent_volume ? "是" : "否"}`,
    `最近备份时间：${data.last_backup_at || "--"}`,
    `备份数量：${data.backup_count ?? 0}`,
    `导出数量：${data.export_count ?? 0}`,
  ].forEach((line) => card.append(el("div", "clamp", line)));
  const tables = data.tables || {};
  ["raw_source_records", "intelligence_feed", "external_opportunities", "intelligence_dossiers", "dossier_evidence_items"].forEach((name) => {
    card.append(el("div", "clamp", `${name}：${tables[name] ?? "--"}`));
  });
  const actions = el("div", "filter-bar");
  const backup = el("button", null, "Backup Now");
  backup.type = "button";
  backup.id = "storage-backup-now";
  backup.addEventListener("click", () => runStorageBackup(backup));
  const exportButton = el("button", null, "Export CSV");
  exportButton.type = "button";
  exportButton.id = "storage-export-csv";
  exportButton.addEventListener("click", () => runStorageExport(exportButton));
  actions.append(backup, exportButton);
  card.append(actions);
  const result = el("div", "clamp", "");
  result.id = "storage-backup-result";
  card.append(result);
  card.append(el("h3", null, "BACKUPS"));
  const rows = backups || [];
  if (!rows.length) card.append(el("div", "empty", "还没有备份"));
  rows.forEach((row) => {
    card.append(el("div", "clamp", `${row.file_name} · ${row.size_mb} MB · ${row.created_at}`));
  });
  const restore = el("section");
  restore.id = "storage-restore";
  restore.append(el("h3", null, "RESTORE"));
  restore.append(el("div", "error", "恢复会覆盖当前数据库。当前版本只允许手动恢复，避免误操作。"));
  restore.append(el("div", "clamp", "1. 停止容器"));
  restore.append(el("div", "clamp", "2. 复制备份 db 覆盖 ./data/pj_intelligence.db"));
  restore.append(el("div", "clamp", "3. 重启容器"));
  restore.append(el("pre", "template-csv", "docker compose stop\ncp data/backups/<backup_file> data/pj_intelligence.db\ndocker compose start"));
  card.append(restore);
  detailEl.append(card);
}

async function loadStorageHealth() {
  detailEl.replaceChildren(el("div", "empty", "加载中"));
  try {
    const [healthRes, backupRes] = await Promise.all([
      fetch("/api/storage/health"),
      fetch("/api/storage/backups"),
    ]);
    const data = await healthRes.json();
    const backups = await backupRes.json();
    if (!healthRes.ok || !backupRes.ok) {
      detailEl.replaceChildren(el("div", "error", "加载失败"));
      return;
    }
    renderStorageHealth(data, backups.items || []);
  } catch (_error) {
    detailEl.replaceChildren(el("div", "error", "加载失败"));
  }
}

async function runStorageBackup(button) {
  button.disabled = true;
  const result = document.getElementById("storage-backup-result");
  if (result) result.textContent = "正在备份";
  try {
    const response = await fetch("/api/storage/backup", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      if (result) result.textContent = data.detail || "备份失败";
      button.disabled = false;
      return;
    }
    await loadStorageHealth();
    const next = document.getElementById("storage-backup-result");
    if (next) next.textContent = `${data.backup_file} · ${data.size_mb} MB · ${data.created_at}`;
  } catch (_error) {
    if (result) result.textContent = "备份失败";
    button.disabled = false;
  }
}

async function runStorageExport(button) {
  button.disabled = true;
  const result = document.getElementById("storage-backup-result");
  if (result) result.textContent = "正在导出";
  try {
    const response = await fetch("/api/storage/export", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      if (result) result.textContent = data.detail || "导出失败";
      button.disabled = false;
      return;
    }
    const summary = (data.files || []).map((file) => `${file.file_name} (${file.rows})`).join(" · ");
    await loadStorageHealth();
    const next = document.getElementById("storage-backup-result");
    if (next) next.textContent = summary || "导出完成";
  } catch (_error) {
    if (result) result.textContent = "导出失败";
    button.disabled = false;
  }
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
    await loadBatchList();
    if (selectedBatchId) await loadBatchDetail(selectedBatchId);
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
  const batches = el("div");
  batches.id = "intake-batches";
  block.append(batches);
  const batchDetail = el("div");
  batchDetail.id = "batch-detail";
  block.append(batchDetail);
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

function coverageText(label, recordType, status) {
  const bucket = evidenceBucket(recordType);
  if (!bucket || !Number(bucket.row_count)) return `${label}: ${status}`;
  return `${label}: ${bucket.month_count} months / ${bucket.row_count} rows / ${status}`;
}

function mainMetric(row) {
  if (row.record_type === "payment_signal") return row.payment_traffic || "--";
  if (row.record_type === "traffic_signal") return [row.traffic_growth, row.current_traffic].filter(Boolean).join(" / ") || "--";
  if (row.record_type === "authority_signal") return [row.dr_growth, row.current_dr].filter(Boolean).join(" / ") || "--";
  return "--";
}

function coverageDetail(label, summary, status) {
  const top = (summary.domains || []).slice(0, 3).join(", ") || "--";
  return `${label}：${status}，记录数 ${summary.record_count}，最新月份 ${summary.latest_month || "--"}，Top 3 ${top}`;
}

function coverageGap(label, status, gap) {
  const shown = status === "Ready" ? "partial" : String(status || "missing").toLowerCase();
  return `${label}：${shown}，缺口：${gap}`;
}

function renderCoverageCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "data-coverage";
  card.append(el("h2", null, "EVIDENCE COVERAGE"));
  card.append(el("div", "clamp", coverageDetail("Payment", evidenceSummary("Payment Signal"), paymentStatus())));
  card.append(el("div", "clamp", coverageDetail("Traffic", evidenceSummary("Traffic Signal"), trafficStatus())));
  card.append(el("div", "clamp", coverageDetail("Authority", evidenceSummary("Authority Signal"), authorityStatus())));
  const serp = serpStatus();
  const competitor = competitorSlotStatus(competitors);
  const validation = validationStatus();
  card.append(el("div", "clamp", serp === "Ready"
    ? coverageDetail("SERP", evidenceSummary("SERP Signal"), serp)
    : coverageGap("SERP", serp, serp === "Partial" ? "SERP Top 10 未齐" : "没有 SERP 结果")));
  card.append(el("div", "clamp", competitor === "Ready"
    ? coverageDetail("Competitor", evidenceSummary("Competitor Signal"), competitor)
    : coverageGap("Competitor", competitor, competitor === "Partial" ? "竞品页不足 5 个" : "没有竞品页")));
  card.append(el("div", "clamp", validation === "Ready"
    ? coverageDetail("Validation", evidenceSummary("Validation Signal"), validation)
    : coverageGap("Validation", validation, "没有验证记录")));
  return card;
}

function renderLatestCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "latest-signals";
  card.append(el("h2", null, "LATEST IMPORTED SIGNALS"));
  const rows = dashboardLatest.items || [];
  if (!rows.length) {
    card.append(el("div", "empty", "暂无导入记录"));
    return card;
  }
  const table = document.createElement("table");
  table.className = "data-table";
  const head = document.createElement("tr");
  ["domain", "dataset_type", "provider", "period_month", "main_metric", "source"].forEach((name) => head.append(el("th", null, name)));
  table.append(head);
  rows.forEach((row) => {
    const line = document.createElement("tr");
    [row.domain, row.dataset_type, row.provider, row.period_month, mainMetric(row), row.source_name].forEach((value) => {
      line.append(el("td", null, value || "--"));
    });
    line.addEventListener("click", () => {
      explorerQuery = { ...explorerQuery, domain: row.domain || "", offset: 0 };
      setView("explorer");
    });
    table.append(line);
  });
  const wrap = el("div", "data-scroll");
  wrap.append(table);
  card.append(wrap);
  return card;
}

function isDeskNoise(domain) {
  const host = String(domain || "").toLowerCase().split(":")[0];
  const parts = host.split(".").filter(Boolean);
  if (["example.com", "test.com", "localhost", "demo.com", "sample.com"].includes(host)) return true;
  return parts.some((part) => ["demo", "sample", "test", "example", "localhost"].includes(part));
}

function renderExternalTopCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "external-top";
  card.append(el("h2", null, "TOP EXTERNAL OPPORTUNITIES"));
  card.append(el("p", "clamp", "按 P0、P1、P2 排序。样例域名留在 Data Explorer。"));
  const rows = (dashboardExternal.items || []).filter((row) => !isDeskNoise(row.domain) && row.opportunity_tier !== "P3_noise").slice(0, 10);
  if (!rows.length) {
    card.append(el("div", "empty", "暂无外部机会"));
    return card;
  }
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    const top = el("div", "slot-row");
    top.append(el("b", null, row.domain || "--"));
    top.append(el("span", null, `score ${row.opportunity_score} · ${row.opportunity_tier || "--"}`));
    line.append(top);
    line.append(el("div", "clamp", `evidence ${(row.evidence_tags || row.tags || []).join(", ") || "--"}`));
    line.append(el("div", "clamp", `latest ${row.latest_signal || "--"}`));
    line.append(el("div", "clamp", `missing ${(row.missing_evidence || []).join(", ") || "--"}`));
    line.append(el("div", "clamp", `next ${row.next_action || "--"}`));
    line.append(deskDossierActions(row.domain));
    line.addEventListener("click", () => {
      externalQuery = { ...externalQuery, domain: row.domain || "", offset: 0 };
      setView("external");
    });
    card.append(line);
  });
  return card;
}

function formatCollectTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace("T", " ").slice(0, 16);
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function renderCollectStatus() {
  const box = document.getElementById("collect-status");
  if (!box) return;
  const when = formatCollectTime(collectStatus.finished_at);
  box.textContent = `Last collect: ${when} · Sources checked: ${collectStatus.sources_checked || 0} · New items: ${collectStatus.new_items || 0} · Errors: ${collectStatus.error_count || 0} · Top signal: ${collectStatus.top_signal || "--"}`;
}

function feedActions(row) {
  const actions = el("div", "filter-bar");
  const open = el("button", null, "查看来源");
  open.type = "button";
  open.addEventListener("click", () => {
    if (row.url) window.open(row.url, "_blank", "noopener");
  });
  actions.append(open);
  [
    ["加入机会", "opportunity"],
    ["抓取页面", "crawl"],
    ["转成竞品页", "competitor"],
    ["加入关键词池", "keyword"],
  ].forEach(([label, action]) => {
    const button = el("button", null, label);
    button.type = "button";
    button.addEventListener("click", () => runFeedAction(row.id, action, button));
    actions.append(button);
  });
  actions.append(deskDossierActions(row.domain, row.dossier_id, row));
  const ignore = el("button", null, "Ignore");
  ignore.type = "button";
  ignore.addEventListener("click", () => runDossierFeedAction(row, "ignore", ignore));
  actions.append(ignore);
  return actions;
}

async function runFeedAction(feedId, action, button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/intelligence/feed/${feedId}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await response.json();
    jobEl.textContent = data.message || data.detail || (response.ok ? "已处理" : "操作失败");
  } catch (_error) {
    jobEl.textContent = "操作失败";
  } finally {
    button.disabled = false;
  }
}

function appendFeedRows(card, rows) {
  if (!rows.length) {
    card.append(el("div", "empty", "暂无资讯。点击顶部“立即采集”抓取公开 RSS。"));
    return;
  }
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    line.append(el("div", "clamp", `${formatCollectTime(row.time || row.created_at)} · ${row.source || row.source_name || "--"} · ${row.domain || "--"} · ${row.signal || "--"}`));
    line.append(el("div", null, `[${row.source || row.source_name || "--"}] ${row.title || "--"}`));
    line.append(el("div", "clamp", row.why || row.why_it_matters || "--"));
    line.append(el("div", "clamp", `tags ${(row.evidence_tags || []).join(", ") || "--"} · score ${row.score ?? "--"}`));
    line.append(el("div", "clamp", `evidence ${row.evidence_count ?? 0} · missing ${row.missing_evidence || "--"} · next ${row.next_action || "--"}`));
    line.append(feedActions(row));
    card.append(line);
  });
}

function renderTodayCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "top-intelligence-today";
  card.append(el("h2", null, "TOP INTELLIGENCE TODAY"));
  const rows = (dashboardToday.items || []).filter((row) => !isDeskNoise(row.domain)).slice(0, 10);
  if (!rows.length) {
    card.append(el("div", "empty", "今天还没有可看的情报。"));
    return card;
  }
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    line.append(el("div", "clamp", `${row.domain || "--"} · ${row.signal || "--"} · score ${row.score ?? "--"}`));
    line.append(el("div", null, row.title || "--"));
    line.append(el("div", "clamp", `${row.source || row.source_name || "--"} · ${(row.evidence_tags || []).join(", ") || "--"}`));
    line.append(el("div", "clamp", row.why_it_matters || row.why || "--"));
    line.append(el("div", "clamp", `missing ${row.missing_evidence || "--"}`));
    line.append(el("div", "clamp", `next ${row.next_action || "--"}`));
    line.append(deskDossierActions(row.domain, row.dossier_id, row));
    card.append(line);
  });
  return card;
}

function renderFeedCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "intelligence-feed";
  card.append(el("h2", null, "INTELLIGENCE FEED"));
  appendFeedRows(card, (dashboardFeed.items || []).slice(0, 20));
  return card;
}

function renderRankCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "top-domains";
  card.append(el("h2", null, "TOP DOMAINS"));
  [
    ["Top Payment Domains", dashboardRanks.payment || []],
    ["Top Traffic Growth Domains", dashboardRanks.traffic || []],
    ["Top DR Growth Domains", dashboardRanks.authority || []],
  ].forEach(([title, rows]) => {
    card.append(el("h3", null, title));
    if (!rows.length) {
      card.append(el("div", "empty", "暂无"));
      return;
    }
    rows.forEach((row) => {
      card.append(el("div", "clamp", `#${row.rank} ${row.domain} · ${row.metric || "--"} · ${row.period_month || "--"}`));
    });
  });
  return card;
}

async function loadFeedPage() {
  const data = await loadJsonObject("/api/intelligence/feed?limit=50");
  const root = document.getElementById("cockpit");
  if (!root) return;
  root.replaceChildren();
  const page = el("section", "cockpit-card");
  page.id = "feed-page";
  page.append(el("h2", null, "INTELLIGENCE FEED"));
  appendFeedRows(page, (data && data.items) || []);
  root.append(page);
}

function filterInput(id, placeholder, value) {
  const input = el("input");
  input.id = id;
  input.placeholder = placeholder;
  input.value = value || "";
  return input;
}

function filterSelect(id, options, value) {
  const select = el("select");
  select.id = id;
  options.forEach(([label, optionValue]) => {
    const option = el("option", null, label);
    option.value = optionValue;
    if (optionValue === (value || "")) option.selected = true;
    select.append(option);
  });
  return select;
}

function pageBar(total, limit, offset, onMove) {
  const bar = el("div", "pager");
  const prev = el("button", null, "上一页");
  prev.type = "button";
  prev.disabled = offset <= 0;
  prev.addEventListener("click", () => onMove(Math.max(0, offset - limit)));
  const next = el("button", null, "下一页");
  next.type = "button";
  next.disabled = offset + limit >= total;
  next.addEventListener("click", () => onMove(offset + limit));
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + limit, total);
  bar.append(prev, el("span", null, `${from}-${to} / ${total}`), next);
  return bar;
}

async function loadExplorer() {
  const params = new URLSearchParams();
  ["dataset_type", "record_type", "provider", "batch_id", "period_month", "domain", "keyword", "source_name"].forEach((key) => {
    if (explorerQuery[key]) params.set(key, explorerQuery[key]);
  });
  params.set("limit", "50");
  params.set("offset", String(explorerQuery.offset || 0));
  const response = await fetch(`/api/explorer/records?${params.toString()}`);
  if (!response.ok) throw new Error("explorer");
  explorerPage = await response.json();
  if (viewMode === "explorer") renderExplorer();
}

function readExplorerFilters() {
  const read = (id) => (document.getElementById(id)?.value || "").trim();
  explorerQuery = {
    dataset_type: read("explorer-dataset"),
    record_type: read("explorer-record"),
    provider: read("explorer-provider"),
    batch_id: read("explorer-batch"),
    period_month: read("explorer-month"),
    domain: read("explorer-domain"),
    keyword: read("explorer-keyword"),
    source_name: read("explorer-source"),
    offset: 0,
  };
  explorerOpenId = null;
}

function renderExplorer() {
  const root = document.getElementById("cockpit");
  if (!root) return;
  root.replaceChildren();
  const page = el("section", "cockpit-card");
  page.id = "data-explorer";
  page.append(el("h2", null, "DATA EXPLORER"));
  page.append(el("p", "clamp", "数据仓库。列表只显示摘要，点开一条再看原始记录。"));
  const filters = el("div", "filter-bar");
  filters.append(filterSelect("explorer-dataset", [
    ["dataset_type", ""],
    ["stripe_payment_ranking", "stripe_payment_ranking"],
    ["dr_growth_ranking", "dr_growth_ranking"],
    ["traffic_growth_ranking", "traffic_growth_ranking"],
    ["serp_result", "serp_result"],
    ["sitedata_traffic_growth", "sitedata_traffic_growth"],
    ["sitedata_dr_growth", "sitedata_dr_growth"],
    ["sitedata_payment_traffic", "sitedata_payment_traffic"],
  ], explorerQuery.dataset_type));
  filters.append(filterSelect("explorer-record", [
    ["record_type", ""],
    ["payment_signal", "payment_signal"],
    ["authority_signal", "authority_signal"],
    ["traffic_signal", "traffic_signal"],
    ["serp_result", "serp_result"],
    ["crawl_signal", "crawl_signal"],
  ], explorerQuery.record_type));
  filters.append(filterInput("explorer-provider", "provider", explorerQuery.provider));
  filters.append(filterInput("explorer-batch", "batch_id", explorerQuery.batch_id));
  filters.append(filterInput("explorer-month", "period_month", explorerQuery.period_month));
  filters.append(filterInput("explorer-domain", "domain", explorerQuery.domain));
  filters.append(filterInput("explorer-keyword", "keyword", explorerQuery.keyword));
  filters.append(filterInput("explorer-source", "source_name", explorerQuery.source_name));
  const apply = el("button", null, "筛选");
  apply.type = "button";
  apply.addEventListener("click", () => {
    readExplorerFilters();
    loadExplorer().catch(() => page.append(el("div", "error", "查询失败")));
  });
  filters.append(apply);
  page.append(filters);
  const total = Number(explorerPage.total) || 0;
  const limit = Number(explorerPage.limit) || 50;
  const offset = Number(explorerPage.offset) || 0;
  page.append(pageBar(total, limit, offset, (next) => {
    explorerQuery.offset = next;
    loadExplorer().catch(() => page.append(el("div", "error", "查询失败")));
  }));
  const table = document.createElement("table");
  table.className = "data-table";
  const head = document.createElement("tr");
  const columns = ["source_name", "record_type", "period_month", "main_metric", "imported_at"];
  const labels = { source_name: "source", record_type: "signal type", period_month: "period", main_metric: "metric", imported_at: "imported_at" };
  ["domain", ...columns].forEach((name) => {
    head.append(el("th", null, labels[name] || name));
  });
  table.append(head);
  (explorerPage.items || []).forEach((row) => {
    const line = document.createElement("tr");
    const domainCell = el("td");
    domainCell.append(el("span", null, row.domain || "--"));
    if (row.sample) domainCell.append(document.createTextNode(" "), sampleTag());
    line.append(domainCell);
    columns.forEach((key) => {
      line.append(el("td", null, row[key] || "--"));
    });
    line.addEventListener("click", () => {
      explorerOpenId = explorerOpenId === row.id ? null : row.id;
      renderExplorer();
    });
    table.append(line);
    if (explorerOpenId === row.id) {
      const detail = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 20;
      cell.append(el("div", "hint", "raw_json"));
      cell.append(el("pre", "raw-block", row.raw_json || "{}"));
      const attach = el("button", null, "Attach to Dossier");
      attach.type = "button";
      attach.addEventListener("click", () => attachExplorerRecord(row.id, attach));
      cell.append(attach);
      detail.append(cell);
      table.append(detail);
    }
  });
  if (!(explorerPage.items || []).length) table.append(el("tr", null, ""));
  const wrap = el("div", "data-scroll");
  wrap.append(table);
  page.append(wrap);
  if (!total) page.append(el("div", "empty", "没有匹配的记录"));
  root.append(page);
}

async function loadExternal() {
  const params = new URLSearchParams();
  if (externalQuery.min_score !== "") params.set("min_score", externalQuery.min_score);
  if (externalQuery.evidence_type) params.set("evidence_type", externalQuery.evidence_type);
  if (externalQuery.domain) params.set("domain", externalQuery.domain);
  params.set("limit", "50");
  params.set("offset", String(externalQuery.offset || 0));
  const response = await fetch(`/api/external-opportunities?${params.toString()}`);
  if (!response.ok) throw new Error("external");
  externalPage = await response.json();
  if (viewMode === "external") renderExternal();
}

function renderExternal() {
  const root = document.getElementById("cockpit");
  if (!root) return;
  root.replaceChildren();
  const page = el("section", "cockpit-card");
  page.id = "external-opportunities";
  page.append(el("h2", null, "OPPORTUNITIES"));
  page.append(el("p", "clamp", `外部机会池已聚合 ${Number(externalPage.total) || 0} 条记录。这里按优先级翻页，首页只展示优先研究。`));
  const filters = el("div", "filter-bar");
  filters.append(filterInput("external-score", "min_score", externalQuery.min_score));
  filters.append(filterSelect("external-type", [
    ["evidence_type", ""],
    ["payment", "payment"],
    ["traffic", "traffic"],
    ["authority", "authority"],
    ["serp", "serp"],
    ["competitor", "competitor"],
  ], externalQuery.evidence_type));
  filters.append(filterInput("external-domain", "domain", externalQuery.domain));
  const apply = el("button", null, "筛选");
  apply.type = "button";
  apply.addEventListener("click", () => {
    externalQuery = {
      min_score: (document.getElementById("external-score")?.value || "").trim(),
      evidence_type: (document.getElementById("external-type")?.value || "").trim(),
      domain: (document.getElementById("external-domain")?.value || "").trim(),
      offset: 0,
    };
    loadExternal().catch(() => page.append(el("div", "error", "查询失败")));
  });
  filters.append(apply);
  page.append(filters);
  const total = Number(externalPage.total) || 0;
  const limit = Number(externalPage.limit) || 50;
  const offset = Number(externalPage.offset) || 0;
  page.append(pageBar(total, limit, offset, (next) => {
    externalQuery.offset = next;
    loadExternal().catch(() => page.append(el("div", "error", "查询失败")));
  }));
  const table = document.createElement("table");
  table.className = "data-table";
  const head = document.createElement("tr");
  ["domain", "opportunity_score", "opportunity_tier", "evidence_tags", "missing_evidence", "next_action", "reason", "evidence_count", "payment_status", "traffic_status", "authority_status", "serp_status", "competitor_status", "latest_signal", "latest_month", "recommended_action", "dossier"].forEach((name) => {
    head.append(el("th", null, name));
  });
  table.append(head);
  (externalPage.items || []).forEach((row) => {
    const line = document.createElement("tr");
    ["domain", "opportunity_score", "opportunity_tier", "evidence_tags", "missing_evidence", "next_action", "reason", "evidence_count", "payment_status", "traffic_status", "authority_status", "serp_status", "competitor_status", "latest_signal", "latest_month", "recommended_action"].forEach((key) => {
      const value = row[key];
      line.append(el("td", null, Array.isArray(value) ? value.join(", ") : value === 0 ? "0" : value || "--"));
    });
    const actionCell = document.createElement("td");
    actionCell.append(domainDossierActions(row.domain));
    line.append(actionCell);
    table.append(line);
  });
  const wrap = el("div", "data-scroll");
  wrap.append(table);
  page.append(wrap);
  if (!total) page.append(el("div", "empty", "没有匹配的外部机会"));
  root.append(page);
}

async function loadBatchList() {
  const box = document.getElementById("intake-batches");
  if (!box) return;
  box.replaceChildren(el("h2", null, "Import Batches"));
  const response = await fetch("/api/import-batches");
  if (!response.ok) {
    box.append(el("div", "error", "批次加载失败"));
    return;
  }
  const rows = await response.json();
  if (!Array.isArray(rows) || !rows.length) {
    box.append(el("div", "empty", "暂无批次"));
    return;
  }
  rows.forEach((row) => {
    const card = el("div", "file-row");
    const button = el("button", null, `batch ${row.batch_id}`);
    button.type = "button";
    button.addEventListener("click", () => {
      selectedBatchId = row.batch_id;
      loadBatchDetail(row.batch_id);
    });
    card.append(button);
    card.append(el("div", "clamp", `${row.dataset_type || "--"} · ${row.record_type || "--"} · ${row.provider || "--"} · files ${row.file_count} · rows ${row.row_count} · ${row.status || "--"}`));
    box.append(card);
  });
}

async function loadBatchDetail(batchId) {
  const box = document.getElementById("batch-detail");
  if (!box) return;
  box.replaceChildren(el("div", "hint", "加载批次详情"));
  const response = await fetch(`/api/import-batches/${batchId}`);
  const data = await response.json();
  if (!response.ok) {
    box.replaceChildren(el("div", "error", "批次不存在"));
    return;
  }
  box.replaceChildren();
  box.append(el("h2", null, `BATCH ${data.batch_id}`));
  [
    `batch_id ${data.batch_id}`,
    `dataset_type ${data.dataset_type || "--"}`,
    `record_type ${data.record_type || "--"}`,
    `provider ${data.provider || "--"}`,
    `file_count ${data.file_count}`,
    `row_count ${data.row_count}`,
    `month_count ${data.month_count}`,
    `latest_month ${data.latest_month || "--"}`,
    `imported_rows ${data.imported_rows}`,
    `skipped_rows ${data.skipped_rows}`,
    `failed_files ${(data.failed_files || []).join(", ") || "--"}`,
    `source_name ${data.source_name || "--"}`,
    `created_at ${data.created_at || "--"}`,
  ].forEach((line) => box.append(el("div", "clamp", line)));
  const open = el("button", null, "在 Data Explorer 打开");
  open.type = "button";
  open.addEventListener("click", () => {
    explorerQuery = { ...explorerQuery, batch_id: String(data.batch_id), dataset_type: data.dataset_type || "", offset: 0 };
    setView("explorer");
  });
  box.append(open);
  box.append(el("h2", null, "Files"));
  (data.files || []).forEach((file) => {
    box.append(el("div", "clamp", `${file.original_file_name} · ${file.period_month || "--"} · rows ${file.row_count} · ${file.status}${(file.warnings || []).length ? ` · ${file.warnings.join(", ")}` : ""}`));
  });
  box.append(el("h2", null, "Sample Rows"));
  (data.sample_rows || []).forEach((row) => {
    const normalized = Object.entries(row.normalized || {}).map(([key, value]) => `${key}=${value || "--"}`).join(" · ");
    box.append(el("div", "file-row", `${row.domain || "--"} · rank ${row.rank || "--"} · ${row.title || "--"}`));
    box.append(el("div", "clamp", normalized));
  });
}

function renderSiteSignalCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "sitedata-signals";
  card.append(el("h2", null, "SITEDATA SIGNALS"));
  const rows = dashboardSiteSignals.items || [];
  if (!rows.length) {
    card.append(el("div", "empty", "还没有 SiteData 信号。到 Admin → Sources 手动运行榜单。"));
    return card;
  }
  rows.forEach((row) => {
    const names = (row.top_domains || []).join(", ") || "--";
    card.append(el("div", "clamp", `${row.label || row.ranking_type || "--"}: ${row.period_month || "--"} · ${row.count || 0} · ${names}`));
  });
  return card;
}

function renderSiteOppCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "sitedata-opportunities";
  card.append(el("h2", null, "TOP SITEDATA OPPORTUNITIES"));
  const rows = dashboardSiteOpps.items || [];
  if (!rows.length) {
    card.append(el("div", "empty", "暂无 SiteData 机会"));
    return card;
  }
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    line.append(el("div", null, `${row.domain} · score ${row.score}`));
    line.append(el("div", "clamp", `${(row.signals || []).join(" + ")} · ${row.latest_period || "--"}`));
    line.append(el("div", "clamp", `Next: ${row.next_action || "--"}`));
    line.addEventListener("click", () => {
      externalQuery = { ...externalQuery, domain: row.domain || "", offset: 0 };
      setView("external");
    });
    card.append(line);
  });
  return card;
}

function periodMonth(offset) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).formatToParts(new Date());
  let year = Number(parts.find((part) => part.type === "year").value);
  let month = Number(parts.find((part) => part.type === "month").value) + offset;
  while (month <= 0) {
    month += 12;
    year -= 1;
  }
  while (month > 12) {
    month -= 12;
    year += 1;
  }
  return `${year}-${String(month).padStart(2, "0")}`;
}

function renderSiteDataRunner() {
  const block = el("section", "intake-block");
  block.id = "sitedata-runner";
  block.append(el("h2", null, "SITEDATA"));
  block.append(el("p", "clamp", "只在点击按钮时调用 SiteData CLI。页面刷新不会拉榜单。"));
  if (sitedataConnector) {
    block.append(el("div", "clamp", `SiteData CLI: ${sitedataConnector.status || "not_configured"}`));
    (sitedataConnector.details || []).forEach((line) => block.append(el("div", "clamp", line)));
    if (sitedataConnector.message) block.append(el("div", "clamp", sitedataConnector.message));
  }
  const period = el("select");
  period.id = "sitedata-period";
  [
    ["current", "current"],
    ["archive", "archive"],
    [periodMonth(0), `当前月份 ${periodMonth(0)}`],
    [periodMonth(-1), `上个月 ${periodMonth(-1)}`],
    ["custom", "自定义 YYYY-MM"],
  ].forEach(([value, label]) => {
    const option = el("option", null, label);
    option.value = value;
    period.append(option);
  });
  const custom = el("input");
  custom.id = "sitedata-custom-period";
  custom.placeholder = "YYYY-MM";
  const toggle = el("label", null, " auto_create_dossier");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(sitedataSettings.auto_create_dossier);
  checkbox.addEventListener("change", async () => {
    checkbox.disabled = true;
    try {
      const data = await postDossier("/api/sitedata/settings", { auto_create_dossier: checkbox.checked });
      sitedataSettings = data;
      jobEl.textContent = checkbox.checked ? "已打开自动建档" : "已关闭自动建档";
    } catch (error) {
      jobEl.textContent = error.message || "设置失败";
    } finally {
      checkbox.disabled = false;
    }
  });
  toggle.prepend(checkbox);
  const actions = el("div", "filter-bar");
  actions.append(period, custom, toggle);
  [
    ["Run Traffic Growth", "traffic_growth"],
    ["Run DR Growth", "domain_rating_growth"],
    ["Run Payment Traffic", "payment_traffic"],
    ["Run All", ""],
  ].forEach(([label, rankingType]) => {
    const button = el("button", null, label);
    button.type = "button";
    button.addEventListener("click", () => runSiteDataRanking(rankingType, button));
    actions.append(button);
  });
  block.append(actions);
  const result = el("div");
  result.id = "sitedata-result";
  block.append(result);
  return block;
}

function showSiteDataResult(line) {
  jobEl.textContent = line;
  const box = document.getElementById("sitedata-result");
  if (box) box.textContent = line;
}

async function runSiteDataRanking(rankingType, button) {
  const selected = document.getElementById("sitedata-period")?.value || "current";
  const custom = (document.getElementById("sitedata-custom-period")?.value || "").trim();
  let period = "current";
  let month = "";
  if (selected === "current") {
    period = "current";
  } else if (selected === "archive" || selected === "custom") {
    period = "archive";
    month = custom;
  } else {
    period = "archive";
    month = selected;
  }
  if (period === "archive" && !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
    showSiteDataResult("month 必须是 YYYY-MM");
    return;
  }
  button.disabled = true;
  showSiteDataResult("运行 SiteData");
  try {
    const data = rankingType
      ? await postDossier("/api/sitedata/rankings/run", { ranking_type: rankingType, period, month, limit: 100 })
      : await postDossier("/api/sitedata/rankings/run-all", { period, month, limit: 100 });
    if (data.results) {
      const lines = data.results.map((item) => `${item.rankingType || item.ranking_type}: ${item.status} created ${item.records_created}${item.message ? ` · ${item.message}` : ""}`);
      showSiteDataResult([data.status, ...lines].join(" | "));
    } else if (data.status === "ok") {
      showSiteDataResult(`${data.status} · created ${data.records_created} · skipped ${data.records_skipped} · feed ${data.feed_created} · opportunities ${data.opportunities_updated} · ${data.elapsed_ms}ms`);
    } else {
      showSiteDataResult(data.message || data.status || "SiteData 运行失败");
    }
  } catch (error) {
    showSiteDataResult(error.message || "SiteData 运行失败");
  } finally {
    button.disabled = false;
  }
}

function statusLabel(value) {
  return String(value || "watch").replaceAll("_", " ");
}

function renderDossierCard() {
  const card = el("section", "cockpit-card dash-wide");
  card.id = "top-dossiers";
  card.append(el("h2", null, "TOP INTELLIGENCE DOSSIERS"));
  const rows = dashboardDossiers.items || [];
  if (!rows.length) {
    card.append(el("div", "empty", "还没有案卷。从 Feed、外部机会，或 Dossiers 里的手动录入创建。"));
    return card;
  }
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    const top = el("div", "slot-row");
    top.append(el("b", null, row.domain || row.title || "--"));
    top.append(el("span", null, `${row.priority_level || "P3"} / ${statusLabel(row.opportunity_status)} · score ${row.evidence_score}`));
    line.append(top);
    line.append(el("div", "clamp", row.one_line_judgment || "--"));
    line.append(el("div", "clamp", (row.evidence_tags || []).join(" + ") || "暂无证据标签"));
    line.append(el("div", "clamp", `缺口：${(row.missing_evidence || []).join("；") || "--"}`));
    line.append(el("div", "clamp", `Next: ${row.next_action || "--"}`));
    line.addEventListener("click", () => openDossier(row.id));
    card.append(line);
  });
  return card;
}

function deskDossierActions(domain, dossierId, feedRow) {
  const known = dossierId || (dashboardDossiers.items || []).find((row) => (row.domain || "") === domain)?.id;
  const actions = el("div", "filter-bar");
  const primary = el("button", null, known ? "Open Dossier" : "Create Dossier");
  primary.type = "button";
  primary.addEventListener("click", (event) => {
    event.stopPropagation();
    if (known) openDossier(known);
    else if (feedRow) runDossierFeedAction(feedRow, "create", primary);
    else runDomainDossier(domain, "create", primary);
  });
  const attach = el("button", null, "Attach Evidence");
  attach.type = "button";
  attach.addEventListener("click", (event) => {
    event.stopPropagation();
    if (feedRow) runDossierFeedAction(feedRow, "attach", attach);
    else runDomainDossier(domain, "create", attach);
  });
  actions.append(primary, attach);
  return actions;
}

function domainDossierActions(domain) {
  const actions = el("div", "filter-bar");
  [
    ["Open Dossier", "open"],
    ["Create Dossier", "create"],
    ["Add to Watchlist", "watch"],
    ["Research Next", "research"],
  ].forEach(([label, action]) => {
    const button = el("button", null, label);
    button.type = "button";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      runDomainDossier(domain, action, button);
    });
    actions.append(button);
  });
  return actions;
}

async function postDossier(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "操作失败");
  return data;
}

async function runDossierFeedAction(row, action, button) {
  button.disabled = true;
  try {
    const data = await postDossier("/api/dossiers/from-feed", { feed_id: row.id, action });
    jobEl.textContent = data.message || "已处理";
    if (action === "ignore") {
      if (viewMode === "feed") loadFeedPage();
      else if (viewMode === "briefing" || viewMode === "signals") loadDashboard();
      return;
    }
    if (data.dossier_id) openDossier(data.dossier_id);
  } catch (error) {
    jobEl.textContent = error.message || "操作失败";
  } finally {
    button.disabled = false;
  }
}

async function runDomainDossier(domain, action, button) {
  button.disabled = true;
  try {
    const data = await postDossier("/api/dossiers/from-domain", { domain, action });
    jobEl.textContent = data.message || "已处理";
    if (data.dossier_id) openDossier(data.dossier_id);
  } catch (error) {
    jobEl.textContent = error.message || "操作失败";
  } finally {
    button.disabled = false;
  }
}

async function attachExplorerRecord(recordId, button) {
  button.disabled = true;
  try {
    const data = await postDossier("/api/dossiers/from-record", { record_id: recordId });
    jobEl.textContent = data.message || "已挂到案卷";
    if (data.dossier_id) openDossier(data.dossier_id);
  } catch (error) {
    jobEl.textContent = error.message || "挂接失败";
    button.disabled = false;
  }
}

function manualIntakeForm(onDone) {
  const form = el("form", "page-form");
  form.id = "manual-intake";
  const fields = [
    ["title", "title"],
    ["domain", "domain"],
    ["source_name", "source_name"],
    ["note", "note / 群聊文字 / 人工判断"],
    ["metric_name", "metric_name"],
    ["metric_value", "metric_value"],
    ["period_month", "period_month"],
    ["confidence", "confidence"],
  ];
  const inputs = {};
  fields.forEach(([name, placeholder]) => {
    const input = name === "note" ? document.createElement("textarea") : document.createElement("input");
    input.name = name;
    input.placeholder = placeholder;
    if (name === "domain") input.required = true;
    inputs[name] = input;
    form.append(input);
  });
  const sourceType = document.createElement("select");
  ["manual_note", "chat_note", "news", "screenshot", "traffic", "payment", "authority", "serp", "crawl"].forEach((value) => {
    const option = el("option", null, value);
    option.value = value;
    sourceType.append(option);
  });
  sourceType.name = "source_type";
  const evidenceType = document.createElement("select");
  ["manual_note", "chat_note", "traffic", "payment", "authority", "serp", "competitor_page", "crawl", "gsc", "ga4", "news", "screenshot"].forEach((value) => {
    const option = el("option", null, value);
    option.value = value;
    evidenceType.append(option);
  });
  evidenceType.name = "evidence_type";
  form.append(sourceType, evidenceType);
  const button = el("button", null, "写入案卷");
  button.type = "submit";
  form.append(button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    try {
      const body = {
        title: inputs.title.value.trim(),
        domain: inputs.domain.value.trim(),
        source_name: inputs.source_name.value.trim(),
        source_type: sourceType.value,
        note: inputs.note.value.trim(),
        evidence_type: evidenceType.value,
        metric_name: inputs.metric_name.value.trim(),
        metric_value: inputs.metric_value.value.trim(),
        period_month: inputs.period_month.value.trim(),
        confidence: inputs.confidence.value.trim(),
      };
      const data = await postDossier("/api/dossiers/manual", body);
      jobEl.textContent = data.message || "已写入案卷";
      if (onDone) onDone(data);
      else if (data.dossier_id) openDossier(data.dossier_id);
    } catch (error) {
      jobEl.textContent = error.message || "写入失败";
      button.disabled = false;
    }
  });
  return form;
}

async function loadDossierList() {
  const data = await loadJsonObject("/api/dossiers?limit=50");
  const root = document.getElementById("cockpit");
  if (!root) return;
  root.replaceChildren();
  const page = el("section", "cockpit-card");
  page.id = "dossier-list";
  page.append(el("h2", null, "MANUAL INTELLIGENCE INTAKE"));
  page.append(el("p", "clamp", "粘贴群聊、网址、截图备注或人工判断。只写入本地案卷，不调用模型，不请求外部 API。"));
  page.append(manualIntakeForm());
  page.append(el("h2", null, "DOSSIERS"));
  const rows = (data && data.items) || [];
  if (!rows.length) page.append(el("div", "empty", "暂无案卷"));
  rows.forEach((row) => {
    const line = el("div", "feed-line");
    line.append(el("div", null, `${row.domain} · ${row.priority_level} · ${statusLabel(row.opportunity_status)} · ${row.evidence_score}`));
    line.append(el("div", "clamp", row.one_line_judgment || "--"));
    line.addEventListener("click", () => openDossier(row.id));
    page.append(line);
  });
  root.append(page);
}

function renderDossier(data) {
  const root = document.getElementById("cockpit");
  if (!root || !data || !data.dossier) return;
  const dossier = data.dossier;
  root.replaceChildren();
  const glance = el("section", "cockpit-card");
  glance.id = "dossier-profile";
  glance.append(el("p", "section-label", "Entity Profile"));
  glance.append(el("h2", null, dossier.domain || "--"));
  [
    ["Product", dossier.product_name || "--"],
    ["Category", dossier.category || "--"],
    ["Status", statusLabel(dossier.opportunity_status)],
    ["Priority", dossier.priority_level || "--"],
    ["Score", String(dossier.evidence_score ?? "--")],
    ["Confidence", dossier.confidence || "--"],
    ["First seen", formatCollectTime(dossier.created_at)],
    ["Last updated", formatCollectTime(dossier.updated_at)],
  ].forEach(([label, value]) => glance.append(el("div", "clamp", `${label}：${value}`)));
  const summary = el("section", "cockpit-card");
  summary.id = "dossier-summary";
  summary.append(el("p", "section-label", "Evidence Summary"));
  const grid = el("div", "slot-grid");
  (data.summary || []).forEach((card) => {
    const box = el("section", "cockpit-card");
    box.append(el("h2", null, card.name));
    box.append(el("b", slotClass(card.status), card.status));
    box.append(el("div", "clamp", `记录 ${card.count}`));
    box.append(el("div", "clamp", `最近月份 ${card.latest_month || "--"}`));
    box.append(el("div", "clamp", card.metric || "--"));
    box.append(el("div", "clamp", card.source || "--"));
    grid.append(box);
  });
  summary.append(grid);
  const timeline = el("section", "cockpit-card");
  timeline.id = "dossier-timeline";
  timeline.append(el("p", "section-label", "Evidence Timeline"));
  if (!(data.timeline || []).length) timeline.append(el("div", "empty", "暂无证据"));
  (data.timeline || []).forEach((item) => {
    const line = el("div", "feed-line");
    line.append(el("div", "clamp", `${formatCollectTime(item.created_at)} · ${item.evidence_type || "--"}`));
    line.append(el("div", null, item.title || "--"));
    line.append(el("div", "clamp", `来源：${item.source_name || "--"}`));
    const metric = [item.metric_name, item.metric_value, item.metric_unit].filter(Boolean).join(" ");
    line.append(el("div", "clamp", `指标：${metric || "--"}`));
    line.append(el("div", "clamp", `备注：${item.content || "--"}`));
    if (item.source_url) {
      const link = el("a", null, item.source_url);
      link.href = item.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      line.append(link);
    }
    if (item.screenshot_path) {
      const link = el("a", null, "查看截图");
      link.href = `/api/dossiers/${dossier.id}/evidence/${item.id}/file`;
      link.target = "_blank";
      line.append(link);
    }
    timeline.append(line);
  });
  const sources = el("section", "cockpit-card");
  sources.id = "dossier-sources";
  sources.append(el("p", "section-label", "Sources"));
  if (!(data.sources || []).length) sources.append(el("div", "empty", "暂无来源"));
  (data.sources || []).forEach((item) => {
    sources.append(el("div", "clamp", `${item.source_name || "--"} · ${item.source_type} · trust ${item.trust_level} · ${formatCollectTime(item.captured_at)} · ${item.original_file || item.original_url || "--"}`));
  });
  const missing = el("section", "cockpit-card");
  missing.id = "dossier-missing";
  missing.append(el("p", "section-label", "Missing Evidence"));
  (data.missing_evidence || []).forEach((gap) => missing.append(el("div", "gap-line", gap)));
  if (!(data.missing_evidence || []).length) missing.append(el("div", "clamp", "主要证据类型已覆盖。正式 Build 仍要看 Validation。"));
  const actions = el("section", "cockpit-card");
  actions.id = "dossier-actions";
  actions.append(el("p", "section-label", "Next Actions"));
  const bar = el("div", "filter-bar");
  [
    ["Run SERP", "run_serp"],
    ["Crawl Domain", "crawl"],
    ["Add Competitor Page", "competitor"],
    ["Add Keyword", "keyword"],
    ["Mark as Priority Research", "priority"],
    ["Reject", "reject"],
  ].forEach(([label, action]) => {
    const button = el("button", null, label);
    button.type = "button";
    button.addEventListener("click", () => runDossierAction(dossier.id, action, button));
    bar.append(button);
  });
  const noteButton = el("button", null, "Add Manual Note");
  noteButton.type = "button";
  const shotButton = el("button", null, "Upload Screenshot");
  shotButton.type = "button";
  bar.append(noteButton, shotButton);
  actions.append(bar);
  const noteBox = el("div");
  noteBox.hidden = true;
  noteButton.addEventListener("click", () => {
    noteBox.hidden = false;
    noteBox.replaceChildren(manualIntakeForm((result) => openDossier(result.dossier_id || dossier.id)));
    const domainInput = noteBox.querySelector("input[name=domain]");
    if (domainInput) domainInput.value = dossier.domain;
  });
  const shotBox = el("form", "page-form");
  shotBox.hidden = true;
  const file = document.createElement("input");
  file.type = "file";
  file.accept = "image/*";
  const shotNote = document.createElement("textarea");
  shotNote.placeholder = "note";
  const shotMetric = document.createElement("input");
  shotMetric.placeholder = "metric_name";
  const shotValue = document.createElement("input");
  shotValue.placeholder = "metric_value";
  const shotMonth = document.createElement("input");
  shotMonth.placeholder = "period_month";
  const shotSubmit = el("button", null, "保存截图证据");
  shotSubmit.type = "submit";
  shotBox.append(file, shotNote, shotMetric, shotValue, shotMonth, shotSubmit);
  shotBox.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!file.files || !file.files[0]) {
      jobEl.textContent = "请选择截图";
      return;
    }
    shotSubmit.disabled = true;
    const body = new FormData();
    body.append("file", file.files[0]);
    body.append("note", shotNote.value.trim());
    body.append("metric_name", shotMetric.value.trim());
    body.append("metric_value", shotValue.value.trim());
    body.append("period_month", shotMonth.value.trim());
    body.append("title", file.files[0].name);
    try {
      const response = await fetch(`/api/dossiers/${dossier.id}/screenshot`, { method: "POST", body });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "上传失败");
      jobEl.textContent = result.message || "已保存截图证据";
      openDossier(dossier.id);
    } catch (error) {
      jobEl.textContent = error.message || "上传失败";
      shotSubmit.disabled = false;
    }
  });
  shotButton.addEventListener("click", () => {
    shotBox.hidden = false;
  });
  actions.append(noteBox, shotBox);
  const judgment = el("section", "cockpit-card");
  judgment.id = "dossier-judgment";
  judgment.append(el("p", "section-label", "One-line Judgment"));
  judgment.append(el("p", null, dossier.one_line_judgment || "--"));
  const boundary = el("section", "cockpit-card");
  boundary.id = "dossier-boundary";
  boundary.append(el("p", "section-label", "Decision Boundary"));
  boundary.append(el("p", null, data.build_note || "当前只能进入 Research，不能正式 Build。原因：缺少 Validation Evidence。"));
  const layout = el("div", "dossier-layout");
  layout.id = "dossier-layout";
  const center = el("div", "dossier-center");
  center.append(timeline, summary, sources);
  const right = el("div", "dossier-side");
  right.append(judgment, missing, actions, boundary);
  layout.append(glance, center, right);
  root.append(layout);
}

async function openDossier(id) {
  viewMode = "dossier";
  applyChrome("dossier");
  const next = `/dossiers/${id}`;
  if (location.pathname !== next) history.pushState({}, "", next);
  const root = document.getElementById("cockpit");
  if (root) root.replaceChildren(el("div", "hint", "加载案卷"));
  const data = await loadJsonObject(`/api/dossiers/${id}`);
  if (!data || !data.dossier) {
    if (root) root.replaceChildren(el("div", "error", "案卷不存在"));
    return;
  }
  renderDossier(data);
}

async function runDossierAction(dossierId, action, button) {
  button.disabled = true;
  jobEl.textContent = action;
  try {
    const data = await postDossier(`/api/dossiers/${dossierId}/action`, { action });
    jobEl.textContent = data.message || "已处理";
    await openDossier(dossierId);
  } catch (error) {
    jobEl.textContent = error.message || "操作失败";
    button.disabled = false;
  }
}

collectBtn.addEventListener("click", runCollect);
document.getElementById("view-briefing").addEventListener("click", () => setView("briefing"));
document.getElementById("view-signals").addEventListener("click", () => setView("signals"));
document.getElementById("view-dossiers").addEventListener("click", () => setView("dossiers"));
document.getElementById("view-explorer").addEventListener("click", () => setView("explorer"));
document.getElementById("view-external").addEventListener("click", () => setView("external"));
document.getElementById("collect-now").addEventListener("click", runCollect);
document.getElementById("view-opportunities").addEventListener("click", () => setView("opportunities"));
document.getElementById("view-keywords").addEventListener("click", () => setView("keywords"));
document.getElementById("view-competitors").addEventListener("click", () => setView("competitors"));
document.getElementById("view-admin").addEventListener("click", () => setView(ADMIN_MODES.includes(viewMode) ? viewMode : "storage"));
document.getElementById("view-intake").addEventListener("click", () => setView("intake"));
document.getElementById("view-health").addEventListener("click", () => setView("health"));
document.getElementById("view-storage").addEventListener("click", () => setView("storage"));
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
window.addEventListener("popstate", () => {
  const match = location.pathname.match(/^\/dossiers\/(\d+)$/);
  if (match) openDossier(Number(match[1]));
  else setView("briefing");
});
const dossierRoute = location.pathname.match(/^\/dossiers\/(\d+)$/);
if (dossierRoute) {
  openDossier(Number(dossierRoute[1])).catch(() => {
    const root = document.getElementById("cockpit");
    if (root) root.replaceChildren(el("div", "error", "案卷加载失败"));
  });
} else {
  applyChrome("briefing");
  loadDashboard().catch(() => {
    const root = document.getElementById("cockpit");
    if (root) root.replaceChildren(el("div", "error", "看板加载失败"));
  });
}
