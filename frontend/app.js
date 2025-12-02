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

if (!sessions.length || !currentSessionId || !sessions.find((s) => s.id === currentSessionId)) {
  createNewSession(true);
} else {
  applySidebarState();
  renderSessionList();
  renderHistory(currentSessionId);
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(text) {
  const parts = text.split(/```/);
  const htmlParts = parts.map((seg, index) => {
    if (index % 2 === 1) {
      const [langLine, ...rest] = seg.trim().split("\n");
      const codeText = rest.length ? rest.join("\n") : langLine;
      const lang = rest.length ? langLine : "";
      return `<pre><code class="lang-${escapeHtml(lang)}">${escapeHtml(codeText)}</code></pre>`;
    }
    return renderInlineMarkdown(seg);
  });
  return htmlParts.join("");
}

function renderInlineMarkdown(text) {
  const lines = text.split("\n");
  const rendered = [];
  let inList = false;
  let listType = "ul";
  let inTable = false;
  let tableRows = [];

  const flushList = () => {
    if (inList) {
      rendered.push(`</${listType}>`);
      inList = false;
    }
  };

  const flushTable = () => {
    if (inTable) {
      rendered.push("<table>");
      tableRows.forEach((row, idx) => {
        const tag = idx === 0 ? "th" : "td";
        rendered.push("<tr>" + row.map((cell) => `<${tag}>${cell}</${tag}>`).join("") + "</tr>");
      });
      rendered.push("</table>");
      tableRows = [];
      inTable = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    // Skip excessive empty lines
    if (!line.trim()) {
      continue;
    }
    // Table detection: lines with pipes and at least 2 cells.
    if (line.includes("|")) {
      const cells = line.split("|").map((c) => escapeHtml(c.trim())).filter(Boolean);
      if (cells.length >= 2) {
        flushList();
        inTable = true;
        tableRows.push(cells);
        continue;
      }
    }

    flushTable();

    // Headings
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushList();
      const level = headingMatch[1].length;
      rendered.push(`<h${level}>${escapeHtml(headingMatch[2])}</h${level}>`);
      continue;
    }

    // Blockquote
    const quoteMatch = line.match(/^>\s+(.*)$/);
    if (quoteMatch) {
      flushList();
      rendered.push(`<blockquote>${escapeHtml(quoteMatch[1])}</blockquote>`);
      continue;
    }

    // Lists
    const listMatch = line.match(/^(\d+\.|[-*])\s+(.*)$/);
    if (listMatch) {
      const symbol = listMatch[1];
      const content = listMatch[2];
      const type = symbol.endsWith(".") ? "ol" : "ul";
      if (!inList || listType !== type) {
        flushList();
        listType = type;
        rendered.push(`<${type}>`);
        inList = true;
      }
      // Task list
      const taskMatch = content.match(/^\[( |x|X)\]\s+(.*)$/);
      if (taskMatch) {
        const checked = taskMatch[1].toLowerCase() === "x" ? "checked" : "";
        rendered.push(
          `<li><input type="checkbox" disabled ${checked}>${escapeHtml(taskMatch[2])}</li>`
        );
      } else {
        rendered.push(`<li>${escapeHtml(content)}</li>`);
      }
      continue;
    }

    // Bold
    let htmlLine = escapeHtml(line)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    rendered.push(htmlLine);
  }

  flushList();
  flushTable();
  return rendered.join("<br>");
}

function displayMessage(content, sender) {
  const message = document.createElement("div");
  message.classList.add("message", sender);
  message.innerHTML = renderMarkdown(content);
  chatBox.appendChild(message);
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
    messageEl.innerHTML = renderMarkdown(partial);
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

    const title = document.createElement("p");
    title.classList.add("session-title");
    title.textContent = session.name;

    const last = session.history[session.history.length - 1];
    const subtitle = document.createElement("p");
    subtitle.classList.add("session-subtitle");
    subtitle.textContent = last ? (last.content.slice(0, 28) || "（空）") : "（未开始）";

    item.appendChild(title);
    item.appendChild(subtitle);
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

function renderHistory(sessionId) {
  const session = sessions.find((s) => s.id === sessionId);
  chatBox.innerHTML = "";
  if (!session) return;
  session.history.forEach((msg) => displayMessage(msg.content, msg.sender));
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
    displayMessage(text, "user");
  }
  appendHistory("user", text);
  if (presetText === undefined) {
    userInput.value = "";
  }

  // 展示思考过程，不覆写最终回复
  const thinkingBubble = displayMessage("🤔 大模型正在思考...", "assistant");

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
    const reply = data.reply || "没有收到回复。";
    const match = reply.match(/\*\*思考过程\*\*\s*([\s\S]*?)\n\s*\*\*最终回答\*\*\s*([\s\S]*)/);

    if (match) {
      const reasoning = match[1].trim();
      const finalAnswer = match[2].trim();
      thinkingBubble.classList.add("reasoning");
      streamIntoMessage(thinkingBubble, reasoning);
      appendHistory("assistant", `思考过程:\n${reasoning}`);

      const finalBubble = displayMessage(finalAnswer, "assistant");
      finalBubble.classList.add("final-answer");
      appendHistory("assistant", finalAnswer);
    } else {
      streamIntoMessage(thinkingBubble, reply);
      appendHistory("assistant", reply);
    }
  } catch (error) {
    const errMsg = `请求失败：${error.message}`;
    thinkingBubble.innerHTML = renderMarkdown(errMsg);
    appendHistory("assistant", errMsg);
    showToast(errMsg);
  }
}

sendButton.addEventListener("click", sendMessage);
userInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendMessage();
  }
});
newChatBtn.addEventListener("click", () => createNewSession(true));
toggleSidebarBtn.addEventListener("click", () => {
  isSidebarCollapsed = !isSidebarCollapsed;
  applySidebarState();
  saveSessions();
});
