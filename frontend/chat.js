// EventLens Conversational Querying Client Logic (UI/UX Pro Max)

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("query-input");
  const messagesContainer = document.getElementById("chat-messages");
  const quickBtns = document.querySelectorAll(".quick-btn");

  // Quick suggestion chips
  quickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.textContent.trim();
      form.dispatchEvent(new Event("submit"));
    });
  });

  // Handle URL pre-fill from dashboard links (e.g. chat.html?q=...)
  const urlParams = new URLSearchParams(window.location.search);
  const prefillQuery = urlParams.get("q");
  if (prefillQuery) {
    input.value = prefillQuery;
    setTimeout(() => {
      form.dispatchEvent(new Event("submit"));
    }, 200);
  }

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
    div.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <span class="spinner" style="width: 14px; height: 14px; border-width: 2px;"></span>
        <span>Translating to validated SQLite query and analyzing events...</span>
      </div>
    `;
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
      const sqlId = "sql-" + Date.now();
      html += `
        <div style="margin-top: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 0.72rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">
            Audited Safe SQL:
          </span>
          <button class="pill-btn" onclick="copySql('${sqlId}')" style="font-size: 0.7rem; padding: 2px 8px;">Copy SQL</button>
        </div>
        <div id="${sqlId}" class="sql-pill">${escapeHtml(sql)}</div>
      `;
    }

    if (events && events.length > 0) {
      html += `
        <div style="margin-top: 12px; font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">
          Matching Events (${events.length}):
        </div>
        <div class="chat-event-grid">
          ${events.map(ev => {
            const formattedCat = ev.category.replace(/_/g, " ");
            return `
              <div class="chat-event-card">
                <img src="${ev.keyframe_url}" alt="Event Keyframe" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'60\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23161f30\\'/></svg>';">
                <div class="chat-event-card-body">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-weight: 700; color: var(--accent-cyan); text-transform: uppercase; font-size: 0.72rem;">${formattedCat}</span>
                    <span style="color: var(--text-dim); font-size: 0.72rem;">${ev.camera_id}</span>
                  </div>
                  <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(ev.summary)}</div>
                  <div style="margin-top: 4px; font-size: 0.68rem; color: var(--text-dim); font-family: var(--font-mono);">
                    Confidence: ${(ev.confidence * 100).toFixed(0)}% • ID #${ev.id}
                  </div>
                </div>
              </div>
            `;
          }).join("")}
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

function copySql(elementId) {
  const el = document.getElementById(elementId);
  if (el) {
    navigator.clipboard.writeText(el.textContent.trim());
    const btn = el.previousElementSibling.querySelector("button");
    if (btn) {
      btn.textContent = "✓ Copied";
      setTimeout(() => { btn.textContent = "Copy SQL"; }, 1500);
    }
  }
}
window.copySql = copySql;
