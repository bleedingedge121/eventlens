// EventLens Chat Client Logic

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("query-input");
  const messagesContainer = document.getElementById("chat-messages");
  const quickBtns = document.querySelectorAll(".quick-btn");

  quickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.textContent.trim();
      form.dispatchEvent(new Event("submit"));
    });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question) return;

    // Append user message
    appendUserMessage(question);
    input.value = "";
    input.disabled = true;

    // Append loading placeholder
    const loadingId = appendLoadingMessage();

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      const data = await resp.json();
      removeLoadingMessage(loadingId);

      if (resp.ok) {
        appendBotResponse(data.answer, data.sql, data.events || []);
      } else {
        appendBotResponse(`Error: ${data.detail || "Unable to process query."}`, null, []);
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      appendBotResponse("Network connection error communicating with local query engine.", null, []);
    } finally {
      input.disabled = false;
      input.focus();
    }
  });

  function appendUserMessage(text) {
    const div = document.createElement("div");
    div.className = "msg-bubble msg-user";
    div.textContent = text;
    messagesContainer.appendChild(div);
    scrollToBottom();
  }

  function appendLoadingMessage() {
    const id = "loading-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "msg-bubble msg-bot";
    div.style.color = "var(--text-dim)";
    div.textContent = "Analyzing question and validating SQL...";
    messagesContainer.appendChild(div);
    scrollToBottom();
    return id;
  }

  function removeLoadingMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function appendBotResponse(answer, sql, events) {
    const div = document.createElement("div");
    div.className = "msg-bubble msg-bot";

    let html = `<div>${escapeHtml(answer)}</div>`;

    if (sql) {
      html += `
        <div style="margin-top: 10px; font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em;">
          Executed SQL:
        </div>
        <div class="sql-pill">${escapeHtml(sql)}</div>
      `;
    }

    if (events && events.length > 0) {
      html += `
        <div style="margin-top: 12px; font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">
          Matching Events (${events.length}):
        </div>
        <div class="chat-event-grid">
          ${events.map(ev => `
            <div class="chat-event-card">
              <img src="${ev.keyframe_url}" alt="Event Keyframe" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'60\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23161f30\\'/></svg>';">
              <div class="chat-event-card-body">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                  <span style="font-weight: 700; color: var(--accent-cyan);">${ev.category}</span>
                  <span style="color: var(--text-dim);">${ev.camera_id}</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(ev.summary)}</div>
              </div>
            </div>
          `).join("")}
        </div>
      `;
    }

    div.innerHTML = html;
    messagesContainer.appendChild(div);
    scrollToBottom();
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>'"]/g, 
      tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
  }
});
