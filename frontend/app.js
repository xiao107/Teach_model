const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendButton = document.getElementById("send-button");
const newChatBtn = document.getElementById("new-chat");
const sessionListEl = document.getElementById("session-list");
const layout = document.getElementById("layout");
const toggleSidebarBtn = document.getElementById("toggle-sidebar");

const STORAGE_KEY = "chat_sessions";
const CURRENT_KEY = "current_session_id";
const SIDEBAR_KEY = "sidebar_collapsed";

let sessions = loadSessions();
let currentSessionId = localStorage.getItem(CURRENT_KEY);
let isSidebarCollapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
let isComposing = false;
let markedRenderer = null;

if (!sessions.length || !currentSessionId || !sessions.find((s) => s.id === currentSessionId)) {
  createNewSession(true);
} else {
  applySidebarState();
  renderSessionList();
  renderHistory(currentSessionId);
}

if (window.marked) {
  markedRenderer = new marked.Renderer();
  markedRenderer.link = function (href, title, text) {
    const safeHref = href || "";
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
    return `<a href="${safeHref}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
  };

  marked.setOptions({
    gfm: true,
    breaks: true,
    smartLists: true,
    mangle: false,
    headerIds: true,
    highlight(code, lang) {
      if (window.hljs) {
        try {
          if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
          }
          return hljs.highlightAuto(code).value;
        } catch {
          return escapeHtml(code);
        }
      }
      return escapeHtml(code);
    },
  });
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function parseModelOutput(raw) {
  const blocks = [];
  if (!raw) return [{ type: "text", content: "" }];

  const lines = raw.split("\n");
  let mode = "text";
  let buffer = [];

  const flush = (type) => {
    const text = buffer.join("\n").trim();
    if (text) {
      blocks.push({ type, content: text });
    }
    buffer = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // 进入代码模式的触发词
    if (/我执行了以下代码/.test(trimmed)) {
      flush(mode);
      mode = "code";
      continue;
    }

    // 进入输出模式
    if (/执行结果/.test(trimmed)) {
      flush(mode);
      mode = "output";
      continue;
    }

    // 从输出回到文本的简单启发
    if (mode === "output" && /^老师|^好的|^接下来|^请问/.test(trimmed)) {
      flush("output");
      mode = "text";
    }

    buffer.push(line);
  }

  flush(mode);

  if (!blocks.length) {
    blocks.push({ type: "text", content: raw });
  }

  return blocks;
}

function renderMarkdown(text) {
  // Collapse blank lines aggressively to keep bubbles tight
  const normalized = text.replace(/\r\n/g, "\n").replace(/\n\s*\n+/g, "\n\n");
  if (window.marked && window.DOMPurify) {
    const html = marked.parse(normalized, {
      renderer: markedRenderer || undefined,
    });
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }
  // Fallback: escape only, keep line breaks
  return escapeHtml(normalized).replace(/\n/g, "<br>");
}

function createMessageWrapper(sender) {
  const wrapper = document.createElement("div");
  wrapper.classList.add("message-wrapper", sender);
  return wrapper;
}

function addCopyButton(wrapperEl, textToCopy) {
  if (!textToCopy) return;
  const btn = document.createElement("button");
  btn.classList.add("copy-btn");
  btn.title = "复制";
  btn.setAttribute("aria-label", "复制");
  btn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M9 6.5C9 5.67157 9.67157 5 10.5 5H17.5C18.3284 5 19 5.67157 19 6.5V17.5C19 18.3284 18.3284 19 17.5 19H10.5C9.67157 19 9 18.3284 9 17.5V6.5Z" stroke="currentColor" stroke-width="1.4"/>
      <path d="M6.5 8.5H6C5.17157 8.5 4.5 9.17157 4.5 10V18C4.5 18.8284 5.17157 19.5 6 19.5H14C14.8284 19.5 15.5 18.8284 15.5 18V17.5" stroke="currentColor" stroke-width="1.4"/>
    </svg>
  `;
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(textToCopy);
      showToast("已复制");
    } catch (err) {
      showToast("复制失败");
      console.error("Copy failed:", err);
    }
  });
  const actions = document.createElement("div");
  actions.classList.add("message-actions");
  actions.appendChild(btn);
  wrapperEl.appendChild(actions);
}

function displayMessage(content, sender, enableCopy = true) {
  const wrapper = createMessageWrapper(sender);
  const message = document.createElement("div");
  message.classList.add("message", sender);
  const body = document.createElement("div");
  body.classList.add("markdown-body");
  body.innerHTML = renderMarkdown(content);
  message.appendChild(body);
  if (enableCopy) {
    addCopyButton(wrapper, content);
  }
  wrapper.appendChild(message);
  chatBox.appendChild(wrapper);
  chatBox.scrollTop = chatBox.scrollHeight;
  return { wrapper, message };
}

function renderBlock(block) {
  const wrapper = document.createElement("div");
  wrapper.classList.add("block");

  if (block.type === "text") {
    wrapper.classList.add("markdown-body");
    wrapper.innerHTML = renderMarkdown(block.content);
    return wrapper;
  }

  const label = document.createElement("div");
  label.classList.add("block-label");
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  code.textContent = block.content;
  pre.appendChild(code);

  if (block.type === "code") {
    wrapper.classList.add("code-block");
    label.textContent = "代码";
  } else if (block.type === "output") {
    wrapper.classList.add("output-block");
    label.textContent = "执行结果";
  } else {
    label.textContent = block.type;
  }

  wrapper.appendChild(label);
  wrapper.appendChild(pre);

  if (window.hljs && (block.type === "code" || block.type === "output")) {
    try {
      hljs.highlightElement(code);
    } catch {
      /* highlight optional */
    }
  }
  return wrapper;
}

function renderChart(chartPayload) {
  if (!chartPayload || !window.echarts) return null;
  const container = document.createElement("div");
  container.classList.add("chart-container");
  const height = chartPayload.height || 320;
  container.style.height = `${height}px`;
  container.style.width = "100%";

  const fmtCat = (val) => {
    if (typeof val === "number" && !Number.isInteger(val)) {
      return parseFloat(val.toFixed(3)).toString();
    }
    return `${val}`;
  };

  // Defer init to ensure DOM attached
  setTimeout(() => {
    try {
      const chart = echarts.init(container);
      const type = chartPayload.type || "line";
      const title = chartPayload.title || "";
      const xLabel = chartPayload.xLabel || "";
      const yLabel = chartPayload.yLabel || "";
      const series = chartPayload.series || [];

      let option = {
        title: { text: title },
        grid: { left: 48, right: 16, top: 50, bottom: 40 },
        tooltip: { trigger: "axis" },
      };

      if (type === "heatmap") {
        const data = chartPayload.data || [];
        const xCats = chartPayload.xCategories || [];
        const yCats = chartPayload.yCategories || [];
        const maxVal = data.length ? Math.max(...data.map((d) => d[2] || 0)) : 0;
        option = {
          title: { text: title },
          tooltip: { position: "top" },
          grid: { left: 80, right: 20, top: 60, bottom: 60, containLabel: true },
          xAxis: { type: "category", data: xCats.map(fmtCat), name: xLabel, splitArea: { show: true } },
          yAxis: { type: "category", data: yCats.map(fmtCat), name: yLabel, splitArea: { show: true } },
          visualMap: {
            min: 0,
            max: Math.max(maxVal, 1),
            calculable: true,
            orient: "horizontal",
            left: "center",
            bottom: 10,
          },
          series: [
            {
              name: title,
              type: "heatmap",
              data,
              label: { show: true },
              emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0, 0, 0, 0.5)" } },
            },
          ],
        };
      } else if (type === "scatter") {
        option = {
          title: { text: title },
          tooltip: { trigger: "item" },
          grid: { left: 60, right: 20, top: 50, bottom: 50 },
          xAxis: { type: "value", name: xLabel, axisLabel: { formatter: (v) => fmtCat(v) } },
          yAxis: { type: "value", name: yLabel, axisLabel: { formatter: (v) => fmtCat(v) } },
          series: series.map((s) => ({
            name: s.name || "series",
            type: "scatter",
            data: s.points || [],
            symbolSize: 6,
          })),
        };
      } else if (type === "bar") {
        const firstSeries = series[0] || {};
        const rawX = firstSeries.x || [];
        const xData = rawX.map(fmtCat);
        option = {
          title: { text: title },
          tooltip: { trigger: "axis" },
          grid: { left: 60, right: 20, top: 50, bottom: 60 },
          xAxis: {
            type: "category",
            data: xData,
            name: xLabel,
            axisLabel: { rotate: 30, formatter: (v) => fmtCat(v) },
          },
          yAxis: { type: "value", name: yLabel, axisLabel: { formatter: (v) => fmtCat(v) } },
          series: series.map((s) => ({
            name: s.name || "series",
            type: "bar",
            data: s.y || [],
            barMaxWidth: 30,
          })),
        };
      } else {
        // default line
        const firstSeries = series[0] || {};
        const rawX = firstSeries.x || [];
        const xData = rawX.map(fmtCat);
        option = {
          title: { text: title },
          tooltip: { trigger: "axis" },
          grid: { left: 48, right: 16, top: 50, bottom: 40 },
          xAxis: {
            type: "category",
            name: xLabel,
            data: xData,
            boundaryGap: false,
            axisLabel: { color: "#4b5563", fontSize: 12, formatter: (v) => fmtCat(v) },
            nameTextStyle: { color: "#6b7280", fontSize: 12 },
          },
          yAxis: {
            type: "value",
            name: yLabel,
            axisLabel: { color: "#4b5563", fontSize: 12, formatter: (v) => fmtCat(v) },
            nameTextStyle: { color: "#6b7280", fontSize: 12 },
            splitLine: { lineStyle: { color: "#e5e7eb" } },
          },
          series: series.map((s) => ({
            name: s.name || "series",
            type: "line",
            smooth: true,
            showSymbol: true,
            symbolSize: 4,
            data: s.y || [],
            emphasis: { focus: "series" },
            lineStyle: { width: 2 },
          })),
        };
      }
      chart.setOption(option);
    } catch (err) {
      console.error("Chart render error:", err);
    }
  }, 0);

  return container;
}

function displayParsedMessage(content, sender, extras = {}) {
  const wrapper = createMessageWrapper(sender);
  const message = document.createElement("div");
  message.classList.add("message", sender);

  if (sender === "assistant") {
    const blocks = parseModelOutput(content);
    blocks.forEach((b) => {
      message.appendChild(renderBlock(b));
    });
    if (extras.chart) {
      const chartEl = renderChart(extras.chart);
      if (chartEl) {
        message.appendChild(chartEl);
      }
    }
  } else {
    const p = document.createElement("div");
    p.classList.add("markdown-body");
    p.innerHTML = renderMarkdown(content);
    message.appendChild(p);
  }

  wrapper.appendChild(message);
  addCopyButton(wrapper, content);
  chatBox.appendChild(wrapper);
  chatBox.scrollTop = chatBox.scrollHeight;
  return message;
}

function streamIntoMessage(messageEl, content) {
  let index = 0;
  const total = content.length;
  const step = Math.max(1, Math.floor(total / 140)); // 慢一点，便于观察流式

  function tick() {
    index = Math.min(total, index + step);
    const partial = content.slice(0, index);
    let target = messageEl.querySelector(".markdown-body");
    if (!target) {
      target = document.createElement("div");
      target.classList.add("markdown-body");
      messageEl.innerHTML = "";
      messageEl.appendChild(target);
    }
    target.innerHTML = renderMarkdown(partial);
    chatBox.scrollTop = chatBox.scrollHeight;
    if (index < total) {
      setTimeout(tick, 18); // 控制速度
    }
  }

  tick();
}

function showToast(text) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2000);
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveSessions() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  localStorage.setItem(CURRENT_KEY, currentSessionId);
  localStorage.setItem(SIDEBAR_KEY, isSidebarCollapsed ? "1" : "0");
}

function createNewSession(autoStart = false) {
  const id = `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const session = {
    id,
    name: `会话 ${sessions.length + 1}`,
    history: [],
  };
  sessions.push(session);
  currentSessionId = id;
  saveSessions();
  renderSessionList();
  renderHistory(id);
  if (autoStart) {
    // 触发一次问候，由后端/大模型返回下一步提示
    sendMessage("你好", { showUser: true });
  }
}

function renderSessionList() {
  sessionListEl.innerHTML = "";
  sessions.forEach((session) => {
    const item = document.createElement("div");
    item.classList.add("session-item");
    if (session.id === currentSessionId) item.classList.add("active");

    const textWrap = document.createElement("div");
    textWrap.classList.add("session-text");

    const title = document.createElement("p");
    title.classList.add("session-title");
    title.textContent = session.name;

    const last = session.history[session.history.length - 1];
    const subtitle = document.createElement("p");
    subtitle.classList.add("session-subtitle");
    subtitle.textContent = last ? (last.content.slice(0, 28) || "（空）") : "（未开始）";

    textWrap.appendChild(title);
    textWrap.appendChild(subtitle);

    const deleteBtn = document.createElement("button");
    deleteBtn.classList.add("session-delete");
    deleteBtn.title = "删除会话";
    deleteBtn.textContent = "×";
    deleteBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSession(session.id);
    });

    item.appendChild(textWrap);
    item.appendChild(deleteBtn);
    item.addEventListener("click", () => switchSession(session.id));
    sessionListEl.appendChild(item);
  });
}

function switchSession(id) {
  if (id === currentSessionId) return;
  if (!sessions.find((s) => s.id === id)) return;
  currentSessionId = id;
  saveSessions();
  renderSessionList();
  renderHistory(id);
}

function deleteSession(id) {
  const idx = sessions.findIndex((s) => s.id === id);
  if (idx === -1) return;

  const confirmDelete = sessions.length === 1 ? true : window.confirm("确定删除该会话？");
  if (!confirmDelete) return;

  const deletingCurrent = sessions[idx].id === currentSessionId;
  sessions.splice(idx, 1);

  if (!sessions.length) {
    createNewSession(true);
    return;
  }

  if (deletingCurrent) {
    currentSessionId = sessions[sessions.length - 1].id;
  }

  saveSessions();
  renderSessionList();
  renderHistory(currentSessionId);
}

function renderHistory(sessionId) {
  const session = sessions.find((s) => s.id === sessionId);
  chatBox.innerHTML = "";
  if (!session) return;
  session.history.forEach((msg) => displayParsedMessage(msg.content, msg.sender));
}

function appendHistory(sender, content) {
  const session = sessions.find((s) => s.id === currentSessionId);
  if (!session) return;
  session.history.push({ sender, content });
  saveSessions();
}

function applySidebarState() {
  layout.classList.toggle("collapsed", isSidebarCollapsed);
}

// 提示逻辑移除，完全由大模型输出指引

async function sendMessage(presetText, options = {}) {
  const { showUser = true } = options;
  const text = (presetText !== undefined ? presetText : userInput.value).trim();
  if (!text) return;

  if (showUser) {
    displayParsedMessage(text, "user");
  }
  appendHistory("user", text);
  if (presetText === undefined) {
    userInput.value = "";
  }

  // 展示思考过程，不覆写最终回复
  const { wrapper: thinkingWrapper, message: thinkingMessage } = displayMessage(
    "🤔 大模型正在思考...",
    "assistant",
    false
  );

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSessionId, message: text }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const reply = data.reply || data.response || "没有收到回复。";
    const chartPayload = data.chart;
    const match = reply.match(/\*\*思考过程\*\*\s*([\s\S]*?)\n\s*\*\*最终回答\*\*\s*([\s\S]*)/);

    if (match) {
      const reasoning = match[1].trim();
      const finalAnswer = match[2].trim();
      thinkingMessage.classList.add("reasoning");
      streamIntoMessage(thinkingMessage, reasoning);
      appendHistory("assistant", `思考过程:\n${reasoning}`);

      const finalBubble = displayParsedMessage(finalAnswer, "assistant", { chart: chartPayload });
      finalBubble.classList.add("final-answer");
      appendHistory("assistant", finalAnswer);
    } else {
      thinkingWrapper.remove();
      const parsedBubble = displayParsedMessage(reply, "assistant", { chart: chartPayload });
      parsedBubble.classList.add("final-answer");
      appendHistory("assistant", reply);
    }
  } catch (error) {
    const errMsg = `请求失败：${error.message}`;
    const target = thinkingMessage.querySelector(".markdown-body") || thinkingMessage;
    target.innerHTML = renderMarkdown(errMsg);
    appendHistory("assistant", errMsg);
    showToast(errMsg);
  }
}

sendButton.addEventListener("click", sendMessage);
userInput.addEventListener("keydown", (event) => {
  const composingNow = event.isComposing || event.keyCode === 229 || isComposing;
  if (event.key === "Enter" && !composingNow) {
    event.preventDefault();
    sendMessage();
  }
});
userInput.addEventListener("compositionstart", () => {
  isComposing = true;
});
userInput.addEventListener("compositionend", () => {
  isComposing = false;
});
newChatBtn.addEventListener("click", () => createNewSession(true));
toggleSidebarBtn.addEventListener("click", () => {
  isSidebarCollapsed = !isSidebarCollapsed;
  applySidebarState();
  saveSessions();
});
