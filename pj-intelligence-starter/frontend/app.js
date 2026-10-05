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
let selectedId = null;
let selectedEventId = null;
let selectedKeywordId = null;
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
  document.getElementById("build-events").hidden = mode !== "events";
  document.getElementById("seed-keywords").hidden = mode !== "keywords";
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
  detailEl.textContent = selectedKeywordId ? "加载中" : "选择一个关键词簇";
  loadKeywords()
    .then(() => {
      if (selectedKeywordId) return openKeyword(selectedKeywordId);
    })
    .catch(() => {
      listEl.replaceChildren(el("div", "error", "加载失败"));
    });
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

collectBtn.addEventListener("click", runCollect);
document.getElementById("view-items").addEventListener("click", () => setView("items"));
document.getElementById("view-events").addEventListener("click", () => setView("events"));
document.getElementById("view-keywords").addEventListener("click", () => setView("keywords"));
document.getElementById("build-events").addEventListener("click", buildEventList);
document.getElementById("seed-keywords").addEventListener("click", seedKeywordPool);
refresh().catch(() => {
  listEl.replaceChildren(el("div", "error", "加载失败"));
});
