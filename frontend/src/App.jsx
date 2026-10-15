import React, { useState, useEffect } from "react";
import Dashboard from "./components/Dashboard.jsx";
import Chat from "./components/Chat.jsx";

const API_BASE = "";

function App() {
  const [page, setPage] = useState(() => {
    if (typeof window !== "undefined") {
      return window.location.pathname.includes("chat") ? "chat" : "dashboard";
    }
    return "dashboard";
  });

  // Sync page with URL for direct linking
  useEffect(() => {
    const handlePopState = () => {
      setPage(window.location.pathname.includes("chat") ? "chat" : "dashboard");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (newPage) => {
    setPage(newPage);
    window.history.pushState(null, "", newPage === "chat" ? "/chat.html" : "/");
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
            <div className="brand-sub">Security Operations Console</div>
          </div>
        </div>

        <div className="topbar-actions">
          <div className="status-indicator">
            <span className="status-dot" aria-hidden="true"></span>
            <span>Local inference active</span>
          </div>

          <nav className="nav-links">
            <a
              href="#"
              className={page === "dashboard" ? "active" : ""}
              onClick={(e) => { e.preventDefault(); navigate("dashboard"); }}
            >
              Dashboard
            </a>
            <a
              href="#"
              className={page === "chat" ? "active" : ""}
              onClick={(e) => { e.preventDefault(); navigate("chat"); }}
            >
              Query
            </a>
          </nav>
        </div>
      </header>

      <main className="main">
        {page === "dashboard" ? <Dashboard apiBase={API_BASE} /> : <Chat apiBase={API_BASE} />}
      </main>
    </div>
  );
}

export default App;