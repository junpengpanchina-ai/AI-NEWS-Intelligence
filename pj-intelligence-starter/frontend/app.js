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
let viewMode = "items";
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

function setView(mode) {
  viewMode = mode;
  document.getElementById("view-items").classList.toggle("on", mode === "items");
  document.getElementById("view-events").classList.toggle("on", mode === "events");
  document.getElementById("view-keywords").classList.toggle("on", mode === "keywords");
  document.getElementById("view-competitors").classList.toggle("on", mode === "competitors");
  document.getElementById("view-opportunities").classList.toggle("on", mode === "opportunities");
  document.getElementById("view-sources").classList.toggle("on", mode === "sources");
  document.getElementById("build-events").hidden = mode !== "events";
  document.getElementById("seed-keywords").hidden = mode !== "keywords";
  document.getElementById("add-competitor").hidden = mode !== "competitors";
  document.getElementById("add-source").hidden = mode !== "sources";
  document.getElementById("import-csv").hidden = mode !== "sources";
  if (mode === "items") {
    renderList();
    detailEl.textContent = selectedId ? "加载中" : "选择一条资讯";
    if (selectedId) openItem(selectedId);
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
  } else {
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
  listEl.append(el("div", "hint", "Data Imports"));
  if (sourceImports.length === 0) {
    listEl.append(el("div", "empty", "NO IMPORT"));
    return;
  }
  sourceImports.forEach((batch) => {
    const row = el("div", selectedImportId === batch.id ? "item active" : "item");
    row.append(el("div", "title", batch.import_name || "--"));
    const meta = el("div", "meta");
    meta.append(el("span", null, batch.source_name || "--"));
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
  renderSourceList();
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
  renderSourceList();
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
    option.textContent = source.name;
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
  csvText.required = true;
  csvText.placeholder = "csv_text";
  csvText.rows = 8;
  const notes = document.createElement("textarea");
  notes.placeholder = "notes";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "导入";
  [sourceSelect, importName, recordType, csvText, notes, button].forEach((node) => form.append(node));
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
      jobEl.textContent = `IMPORT ${data.import_id} ROWS ${data.row_count}`;
      await loadSources();
      await openImport(data.import_id);
    } catch (_error) {
      jobEl.textContent = "导入失败";
      button.disabled = false;
    }
  });
  detailEl.append(form);
}

async function openImport(id) {
  selectedImportId = id;
  selectedSourceId = null;
  renderSourceList();
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
    [
      ["source", batch.source_name],
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

collectBtn.addEventListener("click", runCollect);
document.getElementById("api-trace").addEventListener("click", showTrace);
document.getElementById("view-items").addEventListener("click", () => setView("items"));
document.getElementById("view-events").addEventListener("click", () => setView("events"));
document.getElementById("view-keywords").addEventListener("click", () => setView("keywords"));
document.getElementById("view-competitors").addEventListener("click", () => setView("competitors"));
document.getElementById("view-opportunities").addEventListener("click", () => setView("opportunities"));
document.getElementById("view-sources").addEventListener("click", () => setView("sources"));
document.getElementById("build-events").addEventListener("click", buildEventList);
document.getElementById("seed-keywords").addEventListener("click", seedKeywordPool);
document.getElementById("add-competitor").addEventListener("click", showCompetitorForm);
document.getElementById("add-source").addEventListener("click", showSourceForm);
document.getElementById("import-csv").addEventListener("click", showImportForm);
refresh().catch(() => {
  listEl.replaceChildren(el("div", "error", "加载失败"));
});
