/* ======================================================================
   Teach_model 前端逻辑 · v26（v26: 结果卡片聚合：训练合并卡 + 评估对比表）
   TASK-102 ECharts teach-theme / TASK-106 标题+导出 / TASK-107 新图表
   ====================================================================== */

/* ---------------- ECharts theme (TASK-102) ---------------- */
(function registerEChartsTheme() {
  if (typeof echarts === "undefined") return;
  echarts.registerTheme("teach-theme", {
    color: ["#4F7CFF", "#8B5CF6", "#0EA5A4", "#F59E0B", "#EC4899"],
    textStyle: { fontFamily: "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif" },
    grid: { top: 40, left: 56, right: 28, bottom: 42 },
    categoryAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#5C6470", fontSize: 12 },
      splitLine: { show: true, lineStyle: { color: "#EEF1F5", type: "dashed" } },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#5C6470", fontSize: 12 },
      splitLine: { lineStyle: { color: "#EEF1F5", type: "dashed" } },
    },
    bar: { barMaxWidth: 34, itemStyle: { borderRadius: [6, 6, 0, 0] } },
    tooltip: {
      backgroundColor: "#fff", borderColor: "#E5E6EB", borderRadius: 10,
      textStyle: { color: "#1D2129", fontSize: 12 },
      axisPointer: { lineStyle: { color: "#4F7CFF" } },
    },
    animationDuration: 600,
    animationEasing: "cubicOut",
  });
  echarts.registerTheme("teach-theme-dark", {
    color: ["#6D93FF", "#A07BFF", "#2DD4BF", "#FBBF24", "#F472B6"],
    textStyle: { fontFamily: "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif" },
    grid: { top: 40, left: 56, right: 28, bottom: 42 },
    categoryAxis: {
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: "#A6ADBB", fontSize: 12 },
      splitLine: { show: true, lineStyle: { color: "#262B36", type: "dashed" } },
    },
    valueAxis: {
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: "#A6ADBB", fontSize: 12 },
      splitLine: { lineStyle: { color: "#262B36", type: "dashed" } },
    },
    bar: { barMaxWidth: 34, itemStyle: { borderRadius: [6, 6, 0, 0] } },
    tooltip: {
      backgroundColor: "#171A21", borderColor: "#262B36", borderRadius: 10,
      textStyle: { color: "#E6E9EF", fontSize: 12 },
    },
    animationDuration: 600,
    animationEasing: "cubicOut",
  });
})();

/* ---------------- constants & icons ---------------- */
const STORAGE_KEY = "chat_sessions";
const CURRENT_KEY = "current_session_id";
const SIDEBAR_KEY = "sidebar_collapsed";
const THEME_KEY = "theme_preference";

const SESSION_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
const TRASH_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
const ARROW_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>`;
const BOT_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M8 4h8"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/></svg>`;
const CHART_EMPTY_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 3v18h18"/><path d="M7 15v3M12 10v8M17 6v12"/></svg>`;

const ACTION_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

/* 动作名称 -> 中文标签（后端 result.title 缺失时的兜底） */
const ACTION_LABELS = {
  load: "数据集加载", preview: "数据预览", check_missing: "缺失值检查",
  fill_missing: "缺失值填充", encode: "特征编码", split: "数据分割",
  train: "模型训练", evaluate: "模型评估", plot: "图表生成",
  knn_train: "模型训练", svm_train: "模型训练", gbt_train: "模型训练",
};

const EXAMPLES = [
  { badge: "📊", cls: "b1", title: "加载并探索数据集", desc: "试试：\"加载 iris 数据集并预览前 5 行\"", text: "请加载 iris 数据集并预览前 5 行" },
  { badge: "🤖", cls: "b2", title: "一步完成建模", desc: "多步指令：\"训练随机森林并评估效果\"", text: "用随机森林训练模型并评估效果" },
  { badge: "🎨", cls: "b3", title: "数据可视化", desc: "试试：\"画一个 sepal length 的直方图\"", text: "请画一个 sepal length (cm) 的直方图" },
];

/* ---------------- DOM refs ---------------- */
const chatBox = document.getElementById("chat-box");
const sessionListEl = document.getElementById("session-list");
const newChatBtn = document.getElementById("new-chat-btn");
const menuToggleBtn = document.getElementById("menu-toggle");
const sidebarEl = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const userInput = document.getElementById("user-input");
const sendButton = document.getElementById("send-button");
const uploadBtn = document.getElementById("upload-csv-btn");
const fileInput = document.getElementById("csv-file-input");
const uploadStatus = document.getElementById("upload-status");
const toastEl = document.getElementById("toast");
const topbarTitle = document.getElementById("topbar-title");
const exportBtn = document.getElementById("export-chat-btn");
const themeToggleBtn = document.getElementById("theme-toggle");
const levelPickerBtn = document.getElementById("level-picker-btn");
const levelMenu = document.getElementById("level-menu");
const levelLabel = document.getElementById("current-level-label");
const levelPickerWrap = document.getElementById("level-picker");

/* ---------------- state ---------------- */
let sessions = [];
let currentSessionId = null;
let isSending = false;

/* ---------------- utils ---------------- */
function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => toastEl.classList.remove("show"), 2600);
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function isDark() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

/* ---------------- theme (TASK-108) ---------------- */
(function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (prefersDark ? "dark" : "light");
  if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
})();

themeToggleBtn.addEventListener("click", () => {
  const dark = !isDark();
  if (dark) document.documentElement.setAttribute("data-theme", "dark");
  else document.documentElement.removeAttribute("data-theme");
  localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
  renderHistory(currentSessionId); // 重新渲染以应用图表暗色主题
  renderSessionList();
});

/* ---------------- markdown rendering ---------------- */
if (typeof marked !== "undefined") {
  marked.setOptions({
    highlight: (code, lang) => {
      if (window.hljs && lang && hljs.getLanguage(lang)) {
        try { return hljs.highlight(code, { language: lang }).value; } catch (e) {}
      }
      return code;
    },
    breaks: true,
  });
}

function renderMarkdown(text) {
  if (typeof marked === "undefined") return escapeHtml(text);
  const html = marked.parse(text || "");
  return typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(html) : html;
}

/* ---------------- 表格增强：滚动容器 + 吸顶表头 ----------------
   宽表（如 breast_cancer 32 列）不能被 width:100% 压扁，
   统一包进 .table-scroll：横向可滚、纵向限高、表头 sticky。 */
function enhanceTables(container) {
  if (!container) return;
  container.querySelectorAll("table").forEach((table) => {
    if (table.parentElement && table.parentElement.classList.contains("table-scroll")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-scroll";
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
    addTableMeta(wrap, table);
  });
}

/* P1-2: 行数/列数徽标；长表默认折到 260px 并提供展开/收起 */
function addTableMeta(wrap, table) {
  const head = table.tHead;
  const bodyRows = table.tBodies.length ? table.tBodies[0].rows.length : 0;
  const cols = head && head.rows.length ? head.rows[0].cells.length : 0;
  if (!cols) return;

  const meta = document.createElement("div");
  meta.className = "table-meta";
  const size = document.createElement("span");
  size.className = "table-badge";
  size.textContent = `${bodyRows} 行 × ${cols} 列`;
  meta.appendChild(size);

  const tall = bodyRows > 8;
  if (tall) {
    wrap.classList.add("is-collapsed");
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "table-toggle";
    toggle.textContent = "展开全部";
    toggle.addEventListener("click", () => {
      const collapsed = wrap.classList.toggle("is-collapsed");
      toggle.textContent = collapsed ? "展开全部" : "收起";
    });
    meta.appendChild(toggle);
  }
  wrap.parentNode.insertBefore(meta, wrap.nextSibling);
}

/* ---------------- P0-4: CJK 强调渲染兼容层 ----------------
   CommonMark 对 CJK 边界的强调判定有缺陷：
   `**setosa（类别0）**与其` 中闭侧 `**` 前是全角标点、后是汉字，
   不满足 right-flanking 规则，marked 会保留字面星号。
   兼容策略：渲染后遍历文本节点，把残留的 **...** 转成 <strong>。
   （pre/code 内的星号不处理，保持代码原样。） */
const CJK_BOLD_RE = /\*\*([^*\n]+)\*\*/g;

function fixCjkEmphasis(rootEl) {
  if (!rootEl) return;
  const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      const parent = node.parentElement;
      if (!parent || parent.closest("pre, code")) return NodeFilter.FILTER_REJECT;
      return node.nodeValue.includes("**") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const text = node.nodeValue;
    CJK_BOLD_RE.lastIndex = 0;
    if (!CJK_BOLD_RE.test(text)) return;
    const frag = document.createDocumentFragment();
    let last = 0, m;
    CJK_BOLD_RE.lastIndex = 0;
    while ((m = CJK_BOLD_RE.exec(text)) !== null) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      const strong = document.createElement("strong");
      strong.textContent = m[1];
      frag.appendChild(strong);
      last = m.index + m[0].length;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  });
}

/* 深色代码块包装：语言角标 + 复制按钮 */
function enhanceCodeBlocks(container) {
  container.querySelectorAll("pre").forEach((pre) => {
    if (pre.parentElement.classList.contains("code-block")) return;
    const wrap = document.createElement("div");
    wrap.className = "code-block";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const codeEl = pre.querySelector("code");
    const langClass = codeEl ? (codeEl.className.match(/language-([\w-]+)/) || [])[1] : "";
    if (langClass) {
      const tag = document.createElement("span");
      tag.className = "code-lang-tag";
      tag.textContent = langClass;
      wrap.appendChild(tag);
    }
    const btn = document.createElement("button");
    btn.className = "code-copy-btn";
    btn.textContent = "复制";
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(codeEl ? codeEl.textContent : pre.textContent);
        btn.textContent = "已复制 ✓";
        btn.classList.add("copied");
        setTimeout(() => { btn.textContent = "复制"; btn.classList.remove("copied"); }, 1600);
      } catch (e) { showToast("复制失败"); }
    });
    wrap.appendChild(btn);
  });
}

/* ---------------- charts (TASK-102/107) ---------------- */
function buildEChartsOption(payload) {
  const seriesList = payload.series || [];
  switch (payload.type) {
    case "line":
      return {
        xAxis: { type: "category", name: payload.xLabel, data: seriesList[0].x },
        yAxis: { type: "value", name: payload.yLabel },
        series: seriesList.map((s) => ({ name: s.name, type: "line", data: s.y, symbolSize: 5, smooth: true })),
        legend: seriesList.length > 1 ? { top: 4 } : undefined,
        tooltip: { trigger: "axis" },
      };
    case "bar": {
      const isHist = payload.chartSubtype === "histogram";
      return {
        xAxis: { type: "category", name: payload.xLabel, data: isHist ? seriesList[0].x.map((v) => Number(v).toFixed(1)) : seriesList[0].x },
        yAxis: { type: "value", name: payload.yLabel },
        series: seriesList.map((s) => ({ name: s.name, type: "bar", data: s.y })),
        tooltip: { trigger: "axis" },
      };
    }
    case "scatter":
      return {
        xAxis: { type: "value", name: payload.xLabel },
        yAxis: { type: "value", name: payload.yLabel },
        series: seriesList.map((s) => ({ name: s.name, type: "scatter", data: s.points, symbolSize: 8 })),
        tooltip: { trigger: "item" },
      };
    case "boxplot":
      return {
        xAxis: { type: "category", data: seriesList.map((s) => s.name) },
        yAxis: { type: "value", name: payload.yLabel },
        series: [{ name: "箱线图", type: "boxplot", data: seriesList.map((s) => s.box) }],
        tooltip: { trigger: "item" },
      };
    case "heatmap": {
      const { xLabels, yLabels } = payload;
      const min = payload.min ?? 0, max = payload.max ?? 1;
      return {
        grid: { top: 30, left: 120, right: 60, bottom: 60 },
        xAxis: { type: "category", data: xLabels, splitArea: { show: true }, axisLabel: { rotate: 30, fontSize: 10 } },
        yAxis: { type: "category", data: yLabels, splitArea: { show: true }, axisLabel: { fontSize: 10 } },
        visualMap: {
          min, max, calculable: true, orient: "vertical", right: 4, top: "center",
          inRange: { color: ["#4F7CFF", "#FFFFFF", "#8B5CF6"] },
          textStyle: { fontSize: 11 },
        },
        series: [{
          name: seriesList[0]?.name || "heatmap", type: "heatmap",
          data: seriesList[0]?.data || [],
          label: { show: xLabels.length <= 10, fontSize: 9, formatter: (p) => Number(p.value[2]).toFixed(2) },
        }],
      };
    }
    default:
      return null;
  }
}

function renderChart(payload, container) {
  const card = document.createElement("div");
  card.className = "chart-card";
  const title = document.createElement("div");
  title.className = "chart-title";
  title.textContent = payload.title || "图表";
  card.appendChild(title);

  const body = document.createElement("div");
  body.className = "chart-body";
  card.appendChild(body);
  container.appendChild(card);

  const option = buildEChartsOption(payload);
  if (!option) {
    body.className = "";
    body.innerHTML = `<div class="chart-empty">${CHART_EMPTY_SVG}<span>该图表类型暂不支持渲染，请尝试其他可视化方式</span></div>`;
    return;
  }
  if (typeof echarts === "undefined") return;

  const chart = echarts.init(body, isDark() ? "teach-theme-dark" : "teach-theme");
  chart.setOption(option);
  const ro = new ResizeObserver(() => chart.resize());
  ro.observe(body);
}

/* ---------------- sessions ---------------- */
function loadSessions() {
  try { sessions = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch (e) { sessions = []; }
}
function saveSessions() {
  const s = sessions.find((x) => x.id === currentSessionId);
  if (s) s.updatedAt = Date.now();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  localStorage.setItem(CURRENT_KEY, currentSessionId || "");
}

function createNewSession() {
  const id = `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const session = { id, name: "新对话", title: "", history: [], createdAt: Date.now(), updatedAt: Date.now() };
  sessions.unshift(session);
  currentSessionId = id;
  saveSessions();
  renderSessionList();
  renderHistory(id);
  userInput.focus();
}

function formatSessionTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "昨天";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function sessionGroupLabel(ts) {
  if (!ts) return null;
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "今天";
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "昨天";
  return "更早";
}

function renderSessionList() {
  sessionListEl.innerHTML = "";
  const sorted = [...sessions].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  let lastGroup = null;

  sorted.forEach((session) => {
    const group = sessionGroupLabel(session.updatedAt);
    if (group && group !== lastGroup) {
      const g = document.createElement("div");
      g.className = "session-group";
      g.textContent = group;
      sessionListEl.appendChild(g);
      lastGroup = group;
    }

    const item = document.createElement("div");
    item.className = "session-item" + (session.id === currentSessionId ? " active" : "");

    const icon = document.createElement("div");
    icon.className = "session-icon";
    icon.innerHTML = SESSION_ICON_SVG;

    const text = document.createElement("div");
    text.className = "session-text";
    const title = document.createElement("p");
    title.className = "session-title";
    title.textContent = session.name;
    title.title = "双击重命名";
    title.addEventListener("dblclick", (e) => { e.stopPropagation(); editSessionName(session.id, title); });
    const sub = document.createElement("p");
    sub.className = "session-subtitle";
    sub.textContent = session.history.length
      ? `${session.history.length} 条消息 · ${formatSessionTime(session.updatedAt)}`
      : "未开始";
    text.appendChild(title); text.appendChild(sub);

    const del = document.createElement("button");
    del.className = "session-delete";
    del.title = "删除会话";
    del.innerHTML = TRASH_ICON_SVG;
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteSession(session.id); });

    item.appendChild(icon); item.appendChild(text); item.appendChild(del);
    item.addEventListener("click", () => switchSession(session.id));
    sessionListEl.appendChild(item);
  });
}

function editSessionName(id, titleEl) {
  const session = sessions.find((s) => s.id === id);
  if (!session) return;
  const input = document.createElement("input");
  input.value = session.name;
  input.style.cssText = "width:100%;font-size:13.5px;padding:2px 4px;border:1px solid var(--primary);border-radius:6px;background:var(--surface);color:var(--text-primary);outline:none;";
  titleEl.replaceWith(input);
  input.focus(); input.select();
  const commit = () => {
    const v = input.value.trim();
    if (v) { session.name = v; saveSessions(); }
    renderSessionList(); updateTopBarTitle();
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });
}

async function deleteSession(id) {
  const idx = sessions.findIndex((s) => s.id === id);
  if (idx === -1) return;
  if (!window.confirm("确定删除该会话？")) return;
  const deletingCurrent = sessions[idx].id === currentSessionId;
  sessions.splice(idx, 1);
  saveSessions();
  try { await fetch(`/api/sessions/${id}`, { method: "DELETE" }); } catch (e) {}
  if (deletingCurrent) {
    currentSessionId = sessions.length ? sessions[0].id : null;
    if (!currentSessionId) createNewSession();
    else renderHistory(currentSessionId);
  }
  renderSessionList();
  updateTopBarTitle();
  showToast("会话已删除");
}

function switchSession(id) {
  if (id === currentSessionId) return;
  currentSessionId = id;
  saveSessions();
  renderSessionList();
  renderHistory(id);
  updateTopBarTitle();
}

function updateTopBarTitle() {
  const s = sessions.find((x) => x.id === currentSessionId);
  topbarTitle.textContent = s ? s.name : "";
}

/* ---------------- welcome hero ---------------- */
function renderWelcomeHero() {
  const hero = document.createElement("div");
  hero.className = "welcome-hero";
  hero.innerHTML = `
    <div class="hero-logo">${BOT_ICON_SVG}</div>
    <h2 class="hero-title">你好，老师！我是你的 <span class="grad-text">AI 学生</span></h2>
    <p class="hero-desc">我用 Markdown 回复、执行真实的数据分析与建模操作。选择一个示例开始，或直接在下方下达指令。</p>
    <div class="example-list"></div>
  `;
  const list = hero.querySelector(".example-list");
  EXAMPLES.forEach((ex) => {
    const chip = document.createElement("button");
    chip.className = "example-chip";
    chip.innerHTML = `
      <span class="example-badge ${ex.cls}">${ex.badge}</span>
      <span class="example-body"><b>${ex.title}</b><i>${ex.desc}</i></span>
      <span class="example-arrow">${ARROW_ICON_SVG}</span>
    `;
    chip.addEventListener("click", () => sendMessage(ex.text));
    list.appendChild(chip);
  });
  chatBox.appendChild(hero);
}

/* ---------------- P0-3: 结果卡片组件 ----------------
   每个动作的执行结果（表格/统计/图表）独立成卡片，
   支持一次指令输出多张图表、多张表格互不覆盖。

   v26: 聚合渲染，解决"一条指令训练 3 个模型就冒出 5 张碎片卡片"的问题：
   - 同一指令内的多次 train 合并成一张紧凑的「模型训练」卡（每模型一行）；
   - 多次 evaluate 聚合成一张自适应的「模型评估对比」表（自动标注每列最优）；
   - 其余动作仍走完整的独立卡片。 */
const TRAIN_ACTIONS = { train: 1, knn_train: 1, svm_train: 1, gbt_train: 1 };

/* P1-1: 评估指标卡片（大数字 + 标签 + 口径提示），用于单模型评估兜底 */
function buildMetricGrid(metrics) {
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  metrics.forEach((m) => {
    const cell = document.createElement("div");
    cell.className = "metric-card";

    const value = document.createElement("div");
    value.className = "metric-value";
    value.textContent = m.value === undefined || m.value === null ? "—" : String(m.value);
    cell.appendChild(value);

    const label = document.createElement("div");
    label.className = "metric-label";
    label.textContent = m.label || "";
    cell.appendChild(label);

    if (m.hint) {
      const hint = document.createElement("div");
      hint.className = "metric-hint";
      hint.textContent = m.hint;
      cell.appendChild(hint);
    }
    grid.appendChild(cell);
  });
  return grid;
}

function makeCardShell(title) {
  const card = document.createElement("div");
  card.className = "result-card";
  const head = document.createElement("div");
  head.className = "result-head";
  head.innerHTML = `<span class="result-check">${ACTION_ICON_SVG}</span><span class="result-title"></span>`;
  head.querySelector(".result-title").textContent = title;
  card.appendChild(head);
  return card;
}

/* 聚合状态：与一条助手消息（一个 resultsWrap）绑定 */
function createResultAggregator() {
  return {
    trainCard: null, trainList: null,
    evalCard: null, evalTableHead: null, evalTableBody: null,
    evalMetrics: [], evalHints: {}, evalRows: null,
    evalCharts: null,
  };
}

/* 完整独立卡片（无法聚合时的兜底路径） */
function renderFullResultCard(entry, container) {
  const card = document.createElement("div");
  card.className = "result-card";

  const head = document.createElement("div");
  head.className = "result-head";
  head.innerHTML = `<span class="result-check">${ACTION_ICON_SVG}</span><span class="result-title"></span>`;
  head.querySelector(".result-title").textContent =
    entry.title || ACTION_LABELS[entry.action] || entry.action || "执行结果";
  card.appendChild(head);

  if (Array.isArray(entry.metrics) && entry.metrics.length) {
    card.appendChild(buildMetricGrid(entry.metrics));
  }

  const body = document.createElement("div");
  body.className = "result-body markdown-body";
  const text = (entry.text || "").trim();
  if (text) {
    body.innerHTML = renderMarkdown(text);
    enhanceTables(body);
    enhanceCodeBlocks(body);
    fixCjkEmphasis(body);
    card.appendChild(body);
  }

  if (entry.chart) {
    renderChart(entry.chart, card);
  }

  container.appendChild(card);
  return card;
}

/* 同一指令内的多次训练 → 一张紧凑卡片，每模型一行 */
function upsertTrainCard(entry, state, container) {
  const t = entry.train || {};
  if (!state.trainCard) {
    state.trainCard = makeCardShell("模型训练");
    const body = document.createElement("div");
    body.className = "result-body";
    state.trainList = document.createElement("div");
    state.trainList.className = "train-rows";
    body.appendChild(state.trainList);
    state.trainCard.appendChild(body);
    container.appendChild(state.trainCard);
  }
  const row = document.createElement("div");
  row.className = "train-row";

  const name = document.createElement("span");
  name.className = "train-name";
  name.textContent = t.model || "模型";

  const meta = document.createElement("span");
  meta.className = "train-meta";
  const bits = [];
  if (t.task_type === "classification") bits.push("分类");
  else if (t.task_type === "regression") bits.push("回归");
  if (t.samples != null) bits.push(`${t.samples} 样本`);
  if (t.features != null) bits.push(`${t.features} 特征`);
  if (t.train_acc != null) bits.push(`训练准确率 ${(t.train_acc * 100).toFixed(2)}%`);
  meta.textContent = bits.join(" · ");

  row.appendChild(name);
  row.appendChild(meta);
  state.trainList.appendChild(row);
  return state.trainCard;
}

/* 多次 evaluate → 一张自适应对比表，自动标注每列最优值 */
function upsertEvalCard(entry, state, container) {
  if (!state.evalCard) {
    state.evalCard = makeCardShell("模型评估对比");
    const hint = document.createElement("div");
    hint.className = "eval-hint";
    hint.textContent = "同一测试集上的各模型表现 · 高亮为该列最优";
    state.evalCard.appendChild(hint);

    const wrap = document.createElement("div");
    wrap.className = "table-scroll eval-scroll";
    const table = document.createElement("table");
    table.className = "compare-table";
    state.evalTableHead = document.createElement("thead");
    state.evalTableBody = document.createElement("tbody");
    state.evalRows = new Map(); // 模型名 -> tr
    table.appendChild(state.evalTableHead);
    table.appendChild(state.evalTableBody);
    wrap.appendChild(table);
    state.evalCard.appendChild(wrap);

    state.evalCharts = document.createElement("div");
    state.evalCharts.className = "eval-charts";
    state.evalCard.appendChild(state.evalCharts);
    container.appendChild(state.evalCard);
  }

  // 列集合取并集（混跑分类+回归时列自适应扩展）
  entry.metrics.forEach((m) => {
    const label = m.label || "";
    if (!state.evalMetrics.includes(label)) {
      state.evalMetrics.push(label);
      if (m.hint) state.evalHints[label] = m.hint;
    }
  });

  // 重建表头
  state.evalTableHead.innerHTML = "";
  const headRow = document.createElement("tr");
  const headModel = document.createElement("th");
  headModel.textContent = "模型";
  headRow.appendChild(headModel);
  state.evalMetrics.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    if (state.evalHints[label]) th.title = state.evalHints[label];
    headRow.appendChild(th);
  });
  state.evalTableHead.appendChild(headRow);

  // 补齐所有行的单元格数
  state.evalRows.forEach((tr) => {
    while (tr.cells.length < state.evalMetrics.length + 1) {
      tr.appendChild(document.createElement("td"));
    }
  });

  // 按模型名 upsert 行
  let tr = state.evalRows.get(entry.model);
  if (!tr) {
    tr = document.createElement("tr");
    const tdModel = document.createElement("td");
    tdModel.className = "compare-model";
    tr.appendChild(tdModel);
    state.evalMetrics.forEach(() => tr.appendChild(document.createElement("td")));
    state.evalRows.set(entry.model, tr);
    state.evalTableBody.appendChild(tr);
  }
  tr.cells[0].textContent = entry.model;
  state.evalMetrics.forEach((label, i) => {
    const m = entry.metrics.find((x) => (x.label || "") === label);
    tr.cells[i + 1].textContent = m ? String(m.value) : "—";
  });

  highlightEvalBest(state);

  if (entry.chart) renderChart(entry.chart, state.evalCharts);
  return state.evalCard;
}

/* 指标方向：RMSE/MSE 越低越好，其余（准确率/R²）越高越好；样本数不参与 */
function highlightEvalBest(state) {
  const rows = Array.from(state.evalTableBody.rows);
  rows.forEach((r) => Array.from(r.cells).forEach((c) => c.classList.remove("is-best")));
  state.evalMetrics.forEach((label, i) => {
    if (/样本|数$/.test(label)) return;
    const lowerIsBetter = /RMSE|MSE/i.test(label);
    let bestVal = null, bestRow = null;
    rows.forEach((r) => {
      const v = parseFloat((r.cells[i + 1].textContent || "").replace(/[%\s]/g, ""));
      if (!isFinite(v)) return;
      if (
        bestVal === null ||
        (lowerIsBetter ? v < bestVal : v > bestVal)
      ) { bestVal = v; bestRow = r; }
    });
    if (bestRow) bestRow.cells[i + 1].classList.add("is-best");
  });
}

function renderResultCard(entry, container, agg) {
  if (!entry) return;
  const state = agg || createResultAggregator();
  if (TRAIN_ACTIONS[entry.action] && entry.train) {
    return upsertTrainCard(entry, state, container);
  }
  if (
    entry.action === "evaluate" &&
    entry.model &&
    Array.isArray(entry.metrics) && entry.metrics.length
  ) {
    return upsertEvalCard(entry, state, container);
  }
  return renderFullResultCard(entry, container);
}

/* ---------------- message rendering ---------------- */
function createMessageWrapper(sender) {
  const wrapper = document.createElement("div");
  wrapper.className = `message-wrapper ${sender}`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = sender === "assistant" ? BOT_ICON_SVG : "师";

  const content = document.createElement("div");
  content.className = "message-content";
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  content.appendChild(bubble);

  // 结果卡片区：与气泡同列，流式阶段逐张追加
  const resultsWrap = document.createElement("div");
  resultsWrap.className = "msg-results";
  content.appendChild(resultsWrap);

  wrapper.appendChild(avatar);
  wrapper.appendChild(content);
  return { wrapper, bubble, resultsWrap };
}

function displayParsedMessage(text, sender, options = {}) {
  const { chart = null, steps = null, results = null } = options;
  const { wrapper, bubble, resultsWrap } = createMessageWrapper(sender);
  bubble.innerHTML = renderMarkdown(text);
  fixCjkEmphasis(bubble);
  enhanceTables(bubble);
  enhanceCodeBlocks(bubble);
  if (steps && steps.length) {
    const stepEl = document.createElement("div");
    stepEl.className = "msg-step";
    stepEl.textContent = `🧾 执行步骤：${steps.join(" → ")}`;
    bubble.appendChild(stepEl);
  }
  if (results && results.length) {
    const agg = createResultAggregator();
    results.forEach((entry) => renderResultCard(entry, resultsWrap, agg));
  } else if (chart) {
    renderChart(chart, resultsWrap); // 旧历史记录的单图表兼容
  }
  chatBox.appendChild(wrapper);
  scrollBottom();
  return { wrapper, bubble, resultsWrap };
}

function appendHistory(sender, content, chart = null, steps = null, results = null) {
  const session = sessions.find((s) => s.id === currentSessionId);
  if (!session) return;
  session.history.push({ sender, content, chart, steps, results });
  saveSessions();
}

function renderHistory(sessionId) {
  const session = sessions.find((s) => s.id === sessionId);
  chatBox.innerHTML = "";
  if (!session) return;
  if (!session.history.length) { renderWelcomeHero(); return; }
  session.history.forEach((m) => {
    displayParsedMessage(m.content, m.sender, {
      chart: m.chart || null,
      steps: m.steps || null,
      results: m.results || null,
    });
  });
}

function scrollBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

/* ---------------- thinking / streaming helpers ---------------- */
function showThinking(bubble, label) {
  const preview = document.createElement("div");
  preview.className = "stream-preview";
  preview.innerHTML =
    `<span class="thinking-dots"><span></span><span></span><span></span></span>` +
    `<span class="thinking-text">${label || "正在思考"}</span>` +
    `<span class="stream-text" hidden></span>`;
  bubble.appendChild(preview);
  return preview;
}

/* v27: 流式预览净化。LLM 实际输出的是 JSON，把原文直接显示出来会满屏
   {"reply": "..."} 语法噪音。这里增量提取最后一段 reply 字段的内容，
   让"思考中"的预览只展示模型要说的话；reply 还没开始输出时保持思考动画。 */
const REPLY_FIELD_RE = /"reply"\s*:\s*"((?:[^"\\]|\\.)*)"/g;

function extractStreamingText(raw) {
  REPLY_FIELD_RE.lastIndex = 0;
  let m, last = null;
  while ((m = REPLY_FIELD_RE.exec(raw)) !== null) last = m;
  if (!last) return "";
  try {
    return JSON.parse(`"${last[1]}"`);
  } catch (e) {
    return last[1].replace(/\\n/g, "\n").replace(/\\"/g, '"');
  }
}

async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let ev = "message", d = "";
      raw.split("\n").forEach((line) => {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) d += line.slice(5).trim();
      });
      if (d) onEvent(ev, d);
    }
  }
}

/* ---------------- streaming chat (SSE) ---------------- */
async function sendMessage(presetText, options = {}) {
  const { showUser = true, uploadedFileId = null } = options;
  const text = (presetText !== undefined ? presetText : userInput.value).trim();
  if (!text || isSending) return;

  const requestSessionId = currentSessionId;
  const session = sessions.find((s) => s.id === requestSessionId);
  const isFirstMessage = session && session.history.length === 0;

  if (showUser) displayParsedMessage(text, "user");
  appendHistory("user", text);
  updateSessionTitleFallback(text);
  if (presetText === undefined) { userInput.value = ""; autoResize(); }

  isSending = true;
  setSendingUI(true);

  const { wrapper, bubble, resultsWrap } = createMessageWrapper("assistant");
  const agg = createResultAggregator(); // v26: 结果卡片聚合状态（train 合并 / evaluate 对比表）
  const preview = showThinking(bubble, uploadedFileId ? "正在分析上传的数据" : "正在思考");
  chatBox.appendChild(wrapper);
  scrollBottom();

  let fullText = "";
  let finalData = null;
  let pendingResults = []; // v27: 结果卡片先排队，等模型说完话（settle）再统一渲染
  const dotsEl = preview.querySelector(".thinking-dots");
  const streamText = preview.querySelector(".stream-text");
  let statusText = preview.querySelector(".thinking-text");

  try {
    const body = {
      session_id: requestSessionId,
      message: text,
      student_level: getCurrentLevel(),
      level_prompt: getCurrentLevelPrompt(),
    };
    if (uploadedFileId) body.uploaded_file_id = uploadedFileId;

    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok || !response.body) {
      let detail = `HTTP ${response.status}`;
      let rid = "";
      try {
        const j = await response.json();
        if (j.message) detail = j.message;
        if (j.request_id) rid = j.request_id;
      } catch (e) {}
      throw new Error(rid ? `${detail}（请求号 ${rid}）` : detail);
    }

    await readSSE(response, (ev, d) => {
      if (ev === "delta") {
        try {
          fullText += JSON.parse(d).text || "";
          const shown = extractStreamingText(fullText);
          if (shown) {
            dotsEl.style.display = "none";
            streamText.hidden = false;
            streamText.textContent = shown;
            const caret = document.createElement("span");
            caret.className = "typing-caret";
            streamText.appendChild(caret);
          }
          scrollBottom();
        } catch (e) {}
      } else if (ev === "status") {
        try {
          const msg = JSON.parse(d).message;
          if (statusText) statusText.textContent = msg;
        } catch (e) {}
      } else if (ev === "result") {
        // v27: 只入队不渲染——等模型把话说完再按序展示，先"想"后"画"
        try { pendingResults.push(JSON.parse(d)); } catch (e) {}
      } else if (ev === "final") {
        try { finalData = JSON.parse(d); } catch (e) {}
      } else if (ev === "error") {
        let msg = "未知错误";
        let rid = "";
        try {
          const payload = JSON.parse(d);
          msg = payload.message || "未知错误";
          rid = payload.request_id || "";
        } catch (e) {}
        throw new Error(rid ? `${msg}（请求号 ${rid}）` : msg);
      }
    });
  } catch (error) {
    preview.remove();
    bubble.innerHTML = renderMarkdown(`❌ 请求失败：${error.message}`);
    appendHistory("assistant", `❌ 请求失败：${error.message}`);
    showToast(`请求失败：${error.message}`);
    isSending = false; setSendingUI(false);
    return;
  }

  isSending = false;
  setSendingUI(false);

  if (currentSessionId !== requestSessionId) {
    // 离屏回复
    const target = sessions.find((s) => s.id === requestSessionId);
    if (target && finalData) {
      target.history.push({
        sender: "assistant",
        content: finalData.reply,
        chart: finalData.chart || null,
        steps: finalData.steps || null,
        results: finalData.results || null,
      });
      saveSessions();
      renderSessionList();
      showToast(`会话「${target.name}」收到新回复`);
    }
    wrapper.remove();
    return;
  }

  // 渲染最终结构化回复
  preview.remove();
  wrapper.classList.add("settle");
  const reply = finalData?.reply || fullText || "（没有收到回复）";
  bubble.innerHTML = renderMarkdown(reply);
  fixCjkEmphasis(bubble); // P0-4: CJK 强调兼容
  enhanceTables(bubble);
  enhanceCodeBlocks(bubble);
  if (finalData?.steps?.length) {
    const stepEl = document.createElement("div");
    stepEl.className = "msg-step";
    stepEl.textContent = `🧾 执行步骤：${finalData.steps.join(" → ")}`;
    bubble.appendChild(stepEl);
  }
  // 结果卡片：模型说完话后统一渲染（优先用 final 数据，SSE 断流时用排队数据兜底）
  const finalResults = (finalData?.results && finalData.results.length)
    ? finalData.results
    : pendingResults;
  if (finalResults.length) {
    finalResults.forEach((entry) => renderResultCard(entry, resultsWrap, agg));
  } else if (finalData?.chart) {
    renderChart(finalData.chart, resultsWrap); // 旧后端单图表兜底
  }
  appendHistory("assistant", reply, finalData?.chart || null, finalData?.steps || null, finalResults.length ? finalResults : null);
  scrollBottom();

  // TASK-106: 首条回复后自动生成标题
  if (isFirstMessage) autoGenerateTitle(requestSessionId);
}

function updateSessionTitleFallback(firstText) {
  const session = sessions.find((s) => s.id === currentSessionId);
  if (session && session.name === "新对话" && firstText) {
    session.name = firstText.slice(0, 16) + (firstText.length > 16 ? "…" : "");
    saveSessions(); renderSessionList(); updateTopBarTitle();
  }
}

async function autoGenerateTitle(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/generate-title`, { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.title) {
      const session = sessions.find((s) => s.id === sessionId);
      if (session) {
        session.name = data.title;
        saveSessions(); renderSessionList(); updateTopBarTitle();
        showToast(`已生成会话标题：${data.title}`);
      }
    }
  } catch (e) { /* 标题生成失败不影响主流程 */ }
}

/* ---------------- send button UI ---------------- */
function setSendingUI(sending) {
  sendButton.disabled = sending;
  sendButton.querySelector(".icon-send").style.display = sending ? "none" : "";
  sendButton.querySelector(".icon-stop").style.display = sending ? "" : "none";
}

sendButton.addEventListener("click", (e) => {
  const rect = sendButton.getBoundingClientRect();
  const ripple = document.createElement("span");
  ripple.className = "ripple";
  const size = Math.max(rect.width, rect.height);
  ripple.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - rect.left - size / 2}px;top:${e.clientY - rect.top - size / 2}px;`;
  sendButton.appendChild(ripple);
  setTimeout(() => ripple.remove(), 500);
  sendMessage();
});

/* ---------------- input ---------------- */
function autoResize() {
  userInput.style.height = "auto";
  userInput.style.height = Math.min(userInput.scrollHeight, 140) + "px";
}
userInput.addEventListener("input", autoResize);
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

/* ---------------- upload ---------------- */
uploadBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (file) handleFileUpload(file);
});

async function handleFileUpload(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    showUploadStatus("error", "请选择 CSV 文件"); return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showUploadStatus("error", `文件过大（${(file.size / 1024 / 1024).toFixed(1)}MB），单个文件上限 10MB`);
    setTimeout(() => hideUploadStatus(), 4000);
    return;
  }
  showUploadStatus("loading", `正在上传 ${file.name}...`);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.detail || `HTTP ${res.status}`);
    showUploadStatus("success", `✓ ${data.filename} 上传成功（${data.shape[0]} 行 × ${data.shape[1]} 列）`);
    await sendMessage(`已上传数据文件 ${data.filename}，请预览数据`, { uploadedFileId: data.upload_id });
    setTimeout(() => hideUploadStatus(), 2500);
  } catch (err) {
    showUploadStatus("error", `上传失败：${err.message}`);
    setTimeout(() => hideUploadStatus(), 3500);
  }
}

function showUploadStatus(type, msg) {
  uploadStatus.className = `upload-status ${type}`;
  uploadStatus.textContent = msg;
  uploadStatus.style.display = "";
}
function hideUploadStatus() { uploadStatus.style.display = "none"; }

/* ---------------- drag & drop upload ----------------
   start_server.sh 一直宣称"支持点击和拖拽上传"，但此前只实现了点击。
   这里补齐拖拽：整页可投放，带投放遮罩反馈，复用同一条上传链路。 */
const dropOverlay = document.getElementById("drop-overlay");
let dragDepth = 0;

function isFileDrag(e) {
  const types = e.dataTransfer && e.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, "Files") !== -1;
}
function setDragging(on) {
  document.body.classList.toggle("dragging-file", on);
  if (dropOverlay) dropOverlay.setAttribute("aria-hidden", on ? "false" : "true");
}

window.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth += 1;
  setDragging(true);
});
window.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();               // 必须阻止默认行为，否则浏览器会直接打开文件
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
});
window.addEventListener("dragleave", (e) => {
  if (!isFileDrag(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) setDragging(false);
});
window.addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  setDragging(false);
  const files = e.dataTransfer ? e.dataTransfer.files : null;
  if (files && files.length) handleFileUpload(files[0]);
});

/* ---------------- level picker ---------------- */
const LEVEL_ICONS = { beginner: "🌱", intermediate: "🌿", advanced: "🌳" };
levelPickerBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  levelMenu.style.display = levelMenu.style.display === "none" ? "" : "none";
});
document.addEventListener("click", (e) => {
  if (!levelPickerWrap.contains(e.target)) levelMenu.style.display = "none";
});
levelMenu.querySelectorAll(".level-option").forEach((opt) => {
  opt.addEventListener("click", () => {
    levelMenu.querySelectorAll(".level-option").forEach((o) => o.classList.remove("active"));
    opt.classList.add("active");
    levelLabel.textContent = LEVEL_ICONS[opt.dataset.level] || "🌿";
    levelMenu.style.display = "none";
  });
});
function getCurrentLevel() {
  const active = levelMenu.querySelector(".level-option.active");
  return active ? active.dataset.level : "intermediate";
}
function getCurrentLevelPrompt() {
  const active = levelMenu.querySelector(".level-option.active");
  if (!active) return null;
  const desc = active.querySelector("i");
  return desc ? desc.textContent.trim() : null;
}

/* ---------------- export (TASK-106) ---------------- */
exportBtn.addEventListener("click", () => {
  if (!currentSessionId) { showToast("没有可导出的会话"); return; }
  const session = sessions.find((s) => s.id === currentSessionId);
  if (!session || !session.history.length) { showToast("会话还没有对话内容"); return; }
  window.location.href = `/api/sessions/${currentSessionId}/export?format=html`;
});

/* ---------------- sidebar ---------------- */
newChatBtn.addEventListener("click", () => {
  if (isSending) { showToast("请等待当前回复完成"); return; }
  createNewSession();
  if (window.innerWidth <= 900) document.body.classList.remove("mobile-sidebar-open");
});
menuToggleBtn.addEventListener("click", () => {
  if (window.innerWidth <= 900) {
    document.body.classList.toggle("mobile-sidebar-open");
  } else {
    sidebarEl.classList.toggle("collapsed");
    localStorage.setItem(SIDEBAR_KEY, sidebarEl.classList.contains("collapsed") ? "1" : "");
  }
});
sidebarBackdrop.addEventListener("click", () => document.body.classList.remove("mobile-sidebar-open"));

/* ---------------- init ---------------- */
(function init() {
  loadSessions();
  if (!sessions.length) createNewSession();
  else {
    currentSessionId = localStorage.getItem(CURRENT_KEY) || sessions[0].id;
    if (!sessions.find((s) => s.id === currentSessionId)) currentSessionId = sessions[0].id;
    renderHistory(currentSessionId);
  }
  renderSessionList();
  updateTopBarTitle();
  if (localStorage.getItem(SIDEBAR_KEY) === "1") sidebarEl.classList.add("collapsed");
  autoResize();
})();
