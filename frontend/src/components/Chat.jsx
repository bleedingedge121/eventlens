import React, { useState, useEffect, useRef } from "react";

function Chat({ apiBase }) {
  const [messages, setMessages] = useState([
    { role: "bot", text: "Hello. I'm your EventLens surveillance intelligence assistant. Ask me about detected security events, camera activity, or daily incidents in plain English.", meta: "Every query is securely validated into read-only SQL for complete audit transparency." }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const quickQueries = [
    "Show all tailgating events from camera 1 today",
    "Did anyone fall down in camera 2?",
    "Show all fighting incidents",
    "List suspicious loitering activity",
  ];

  // Handle URL pre-fill
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q) {
      setInput(q);
      setTimeout(() => handleSubmit(new Event("submit")), 200);
    }
  }, []);

  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); };
  useEffect(() => { scrollToBottom(); }, [messages]);

  const escapeHtml = (str) => {
        if (!str) return "";
        return str.replace(/[&<>'"]/g, tag => ({ "&": "&", "<": "<", ">": ">", "'": "'", '"': """ }[tag] || tag));
      };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || loading) return;

    setMessages(m => [...m, { role: "user", text: q }]);
    setInput("");
    setLoading(true);

    const loadingId = Date.now();
    setMessages(m => [...m, { role: "bot", text: "", loading: true, id: loadingId }]);

    try {
      const resp = await fetch(`${apiBase}/api/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const data = await resp.json();

      setMessages(m => m.filter(x => x.id !== loadingId));

      if (resp.ok) {
        setMessages(m => [...m, { role: "bot", text: data.answer, sql: data.sql, events: data.events || [] }]);
      } else {
        setMessages(m => [...m, { role: "bot", text: `Error: ${data.detail || "Unable to process query."}` }]);
      }
    } catch {
      setMessages(m => m.filter(x => x.id !== loadingId));
      setMessages(m => [...m, { role: "bot", text: "Network error communicating with local query engine." }]);
    } finally {
      setLoading(false);
    }
  };

  const copySql = (sql) => {
    navigator.clipboard.writeText(sql);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              <path d="M12 5v7l4 2"/>
            </svg>
          </span>
          <div>
            <div className="brand-title">EventLens</div>
            <div className="brand-sub">Conversational Query Engine</div>
          </div>
        </div>

        <div className="topbar-actions">
          <div className="status-indicator">
            <span className="status-dot" aria-hidden="true"></span>
            <span>Text-to-SafeSQL (Ollama + Read-Only SQLite)</span>
          </div>
          <nav className="nav-links">
            <a href="/" onClick={e => { e.preventDefault(); window.location.href = "/"; }}>Dashboard</a>
            <a href="/chat.html" className="active">Query</a>
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="chat-layout">
          <div className="quick-queries">
            <span style={{ fontSize: "12px", color: "var(--muted-2)", display: "flex", alignItems: "center" }}>Try:</span>
            {quickQueries.map((qq, i) => (
              <button key={i} className="quick-btn" onClick={() => { setInput(qq); handleSubmit(new Event("submit")); }}>
                {qq}
              </button>
            ))}
          </div>

          <div className="chat-messages" id="chat-messages">
            {messages.map((msg, idx) => (
              <div key={idx} className="msg-bubble" style={{ alignSelf: msg.role === "user" ? "flex-end" : "flex-start" }}>
                {msg.loading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--muted-2)" }}>
                    <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }}></span>
                    <span>Translating to validated SQLite query and analyzing events…</span>
                  </div>
                ) : (
                  <>
                    <div
                      className={msg.role === "user" ? "msg-user" : "msg-bot"}
                      dangerouslySetInnerHTML={{ __html: escapeHtml(msg.text).replace(/\n/g, "<br>") }}
                    />
                    {msg.sql && (
                      <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: 11, color: "var(--muted-2)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
                          Audited Safe SQL
                        </span>
                        <button className="btn btn-ghost" style={{ fontSize: 11, padding: "2px 8px" }} onClick={() => copySql(msg.sql)}>
                          Copy SQL
                        </button>
                      </div>
                    )}
                    {msg.sql && (
                      <div className="sql-pill" dangerouslySetInnerHTML={{ __html: escapeHtml(msg.sql) }} />
                    )}
                    {msg.events && msg.events.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600, marginBottom: 8 }}>
                          Matching Events ({msg.events.length})
                        </div>
                        <div className="chat-event-grid">
                          {msg.events.map(ev => (
                            <div key={ev.id} className="chat-event-card">
                              <img
                                src={ev.keyframe_url}
                                alt={`Event ${ev.id}`}
                                onError={e => { e.target.onerror = null; e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='60'><rect width='100%' height='100%' fill='%230a0e12'/></svg>"; }}
                              />
                              <div className="chat-event-body">
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                  <span style={{ fontWeight: 700, color: "var(--accent)", textTransform: "uppercase", fontSize: 11 }}>{ev.category.replace("_", " ")}</span>
                                  <span style={{ color: "var(--muted-2)", fontSize: 11 }}>{ev.camera_id}</span>
                                </div>
                                <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>{escapeHtml(ev.summary)}</div>
                                <div style={{ fontSize: 11, color: "var(--muted-2)", fontFamily: "var(--mono)" }}>
                                  Conf: {(ev.confidence * 100).toFixed(0)}% · ID #{ev.id}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSubmit} className="chat-input-row">
            <input
              className="input"
              type="text"
              id="query-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask a question (e.g. 'Show all tailgating events today')…"
              autocomplete="off"
              disabled={loading}
            />
            <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()} style={{ padding: "8px 24px" }}>
              {loading ? "Querying…" : "Ask"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

export default Chat;