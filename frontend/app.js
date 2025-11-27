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

function renderMarkdownLite(text) {
  const parts = text.split(/```/);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        return `<pre>${escapeHtml(part.trim())}</pre>`;
      }
      return escapeHtml(part).replace(/\n/g, "<br>");
    })
    .join("");
}

function displayMessage(content, sender) {
  const message = document.createElement("div");
  message.classList.add("message", sender);
  message.innerHTML = renderMarkdownLite(content);
  chatBox.appendChild(message);
  chatBox.scrollTop = chatBox.scrollHeight;
  return message;
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

  const loading = displayMessage("加载中...", "assistant");

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
    loading.innerHTML = renderMarkdownLite(reply);
    appendHistory("assistant", reply);
  } catch (error) {
    loading.innerHTML = renderMarkdownLite(`请求失败：${error.message}`);
    appendHistory("assistant", `请求失败：${error.message}`);
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
