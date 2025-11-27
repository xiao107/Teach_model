const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendButton = document.getElementById("send-button");

let sessionId = localStorage.getItem("session_id");
if (!sessionId) {
  sessionId = `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem("session_id", sessionId);
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

async function sendMessage() {
  const text = userInput.value.trim();
  if (!text) return;

  displayMessage(text, "user");
  userInput.value = "";

  const loading = displayMessage("加载中...", "assistant");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    loading.innerHTML = renderMarkdownLite(data.reply || "没有收到回复。");
  } catch (error) {
    loading.innerHTML = renderMarkdownLite(`请求失败：${error.message}`);
  }
}

sendButton.addEventListener("click", sendMessage);
userInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendMessage();
  }
});

// Greet the user following the prescribed opening template.
displayMessage(
  "您好！我是一个数据科学助手。我可以帮您加载以下数据集：Iris, Wine, Breast Cancer, California Housing, dot 数据集。您想加载哪一个？",
  "assistant"
);
