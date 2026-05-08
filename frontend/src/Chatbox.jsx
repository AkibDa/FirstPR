import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Terminal } from "lucide-react";
import ChatBox from "./ChatBox";

// ─── FONT INJECTION ───────────────────────────────────────────────────────────
const fontLink = document.createElement("link");
fontLink.href = "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap";
fontLink.rel = "stylesheet";
document.head.appendChild(fontLink);

// ─── GLOBAL STYLES ────────────────────────────────────────────────────────────
const globalStyles = `
  :root {
    --green:          #00cc2e;
    --green-dim:      #009922;
    --green-muted:    #00661888;
    --green-bg:       #00cc2e06;
    --black:          #000000;
    --surface:        #030a03;
    --surface-2:      #060f06;
    --border:         rgba(0,200,46,0.12);
    --border-active:  rgba(0,180,50,0.35);
    --text-primary:   #00cc2e;
    --text-secondary: #009922;
    --text-muted:     #005015;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--black);
    color: var(--green);
    font-family: 'JetBrains Mono', monospace;
    overflow: hidden;
  }

  /* Scanline overlay — very subtle */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,200,46,0.008) 2px,
      rgba(0,200,46,0.008) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }

  /* No side gradient — removed CRT vignette */

  .chat-scroll {
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--green-dim) transparent;
  }
  .chat-scroll::-webkit-scrollbar { width: 3px; }
  .chat-scroll::-webkit-scrollbar-track { background: transparent; }
  .chat-scroll::-webkit-scrollbar-thumb {
    background: #006618;
    border-radius: 0;
  }

  .terminal-input {
    background: transparent;
    border: none;
    outline: none;
    color: var(--green);
    font-family: 'JetBrains Mono', monospace;
    caret-color: var(--green);
    resize: none;
    width: 100%;
  }
  .terminal-input::placeholder { color: var(--text-muted); }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
  }
  @keyframes flicker {
    0%, 100% { opacity: 1; }
    92%      { opacity: 1; }
    93%      { opacity: 0.8; }
    94%      { opacity: 1; }
    96%      { opacity: 0.9; }
    97%      { opacity: 1; }
  }
`;

const StyleTag = () => <style dangerouslySetInnerHTML={{ __html: globalStyles }} />;

// ─── MATRIX BACKGROUND ───────────────────────────────────────────────────────
function MatrixBg() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const fontSize = 13;
    const cols = Math.floor(canvas.width / fontSize);
    const drops = Array(cols).fill(1);
    const chars = "01アイウエオカキABCDEF{}[]<>/\\=+-*&".split("");
    let animId;
    const draw = () => {
      ctx.fillStyle = "rgba(0,0,0,0.05)";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.font = `${fontSize}px JetBrains Mono, monospace`;
      drops.forEach((y, i) => {
        const char = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillStyle = `rgba(0,180,46,${Math.random() > 0.98 ? 0.6 : 0.1})`;
        ctx.fillText(char, i * fontSize, y * fontSize);
        if (y * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
        drops[i]++;
      });
      animId = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(animId);
  }, []);
  return (
    <canvas
      ref={canvasRef}
      style={{ position: "fixed", inset: 0, opacity: 0.28, zIndex: 0, pointerEvents: "none" }}
    />
  );
}

// ─── BOOT SEQUENCE ────────────────────────────────────────────────────────────
function BootSequence({ onDone }) {
  const lines = [
    "> INITIALIZING FIRSTPR MENTOR v2.4.1",
    "> LOADING NEURAL CODEBASE ENGINE...",
    "> CONNECTING TO GITHUB API...",
    "> READY.",
  ];
  const [shown, setShown] = useState([]);
  useEffect(() => {
    lines.forEach((line, i) => {
      setTimeout(() => {
        setShown(prev => [...prev, line]);
        if (i === lines.length - 1) setTimeout(onDone, 600);
      }, i * 380);
    });
  }, []);
  return (
    <div style={{ fontFamily: "'JetBrains Mono', monospace", color: "#009922", padding: "8px 0", fontSize: 11 }}>
      {shown.map((l, i) => (
        <div key={i} style={{ marginBottom: 4, opacity: 0.65, animation: "flicker 8s infinite" }}>{l}</div>
      ))}
    </div>
  );
}

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
export default function App() {
  const [appState, setAppState] = useState("landing");
  const [repoUrl, setRepoUrl]   = useState("");
  const [repoName, setRepoName] = useState("");
  const [booted, setBooted]     = useState(false);

  const handleLoadRepo = async (e) => {
    e.preventDefault();
    if (!repoUrl) return;
    setAppState("loading");
    try {
      const res = await fetch("http://127.0.0.1:8000/api/load-repo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      const data = await res.json();
      if (res.ok) {
        setRepoName(data.repo_name);
        setAppState("chat");
      } else {
        alert("Failed to load repo: " + data.detail);
        setAppState("landing");
      }
    } catch (err) {
      console.error(err);
      setAppState("landing");
    }
  };

  return (
    <>
      <StyleTag />
      <MatrixBg />
      <div style={{
        minHeight: "100vh",
        background: "var(--surface)",
        color: "var(--green)",
        fontFamily: "'JetBrains Mono', monospace",
        display: "flex", alignItems: "center", justifyContent: "center",
        position: "relative", zIndex: 1, overflow: "hidden",
      }}>
        <AnimatePresence mode="wait">

          {/* ── LANDING ── */}
          {appState === "landing" && (
            <motion.div
              key="landing"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              style={{ width: "100%", maxWidth: 500, padding: "0 24px", position: "relative", zIndex: 2 }}
            >
              <div style={{
                border: "1px solid rgba(0,180,50,0.3)",
                borderRadius: 4,
                background: "rgba(0,8,2,0.97)",
                /* Corner glow — no side gradient */
                boxShadow: [
                  "0 0 0 1px rgba(0,150,40,0.07)",
                  "0 0 30px rgba(0,150,40,0.08)",
                  "0 0 60px rgba(0,0,0,0.6)",
                  "inset 0 0 60px rgba(0,0,0,0.3)",
                ].join(", "),
                overflow: "hidden",
              }}>
                {/* Title bar */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "10px 16px",
                  borderBottom: "1px solid rgba(0,255,65,0.08)",
                  background: "rgba(0,20,5,0.5)",
                }}>
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57", boxShadow: "0 0 5px #ff5f57" }} />
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#febc2e", boxShadow: "0 0 5px #febc2e" }} />
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840", boxShadow: "0 0 5px #28c840" }} />
                  <span style={{ marginLeft: "auto", fontSize: 11, color: "#005015", letterSpacing: 2 }}>
                    FIRSTPR_MENTOR — bash
                  </span>
                </div>

                <div style={{ padding: "26px 28px 30px" }}>
                  {!booted ? (
                    <BootSequence onDone={() => setBooted(true)} />
                  ) : (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.35 }}>
                      <div style={{ marginBottom: 26 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                          <Terminal size={17} color="#009922" />
                          <span style={{ fontSize: 11, color: "#005015", letterSpacing: 3 }}>SYSTEM READY</span>
                        </div>
                        <h1 style={{
                          fontSize: 25, fontWeight: 700, letterSpacing: -0.5,
                          color: "#00cc2e",
                          textShadow: "0 0 18px rgba(0,150,40,0.4)",
                          lineHeight: 1.2, marginBottom: 8,
                        }}>
                          FIRSTPR<span style={{ color: "#005015" }}>_</span>MENTOR
                        </h1>
                        <p style={{ color: "#005015", fontSize: 11, lineHeight: 1.65, letterSpacing: 0.5 }}>
                          // Paste a GitHub repository URL to begin codebase ingestion.
                        </p>
                      </div>

                      <form onSubmit={handleLoadRepo}>
                        <div style={{ marginBottom: 6, fontSize: 11, color: "#005015" }}>$ repo_url=</div>
                        <div style={{
                          display: "flex", alignItems: "center",
                          border: "1px solid rgba(0,180,50,0.3)",
                          borderRadius: 3,
                          background: "rgba(0,20,5,0.4)",
                          padding: "11px 13px", gap: 10,
                          transition: "border-color 0.2s, box-shadow 0.2s",
                        }}
                          onFocusCapture={e => { e.currentTarget.style.borderColor = "rgba(0,180,50,0.55)"; e.currentTarget.style.boxShadow = "0 0 0 1px rgba(0,150,40,0.1)"; }}
                          onBlurCapture={e => { e.currentTarget.style.borderColor = "rgba(0,180,50,0.3)"; e.currentTarget.style.boxShadow = "none"; }}
                        >
                          <span style={{ color: "#009922", fontSize: 13 }}>▶</span>
                          <input
                            type="url"
                            placeholder="https://github.com/owner/repo"
                            value={repoUrl}
                            onChange={e => setRepoUrl(e.target.value)}
                            required
                            style={{
                              flex: 1, background: "transparent", border: "none", outline: "none",
                              color: "#00cc2e", fontFamily: "'JetBrains Mono', monospace",
                              fontSize: 13, caretColor: "#00cc2e",
                            }}
                          />
                          <button
                            type="submit"
                            style={{
                              background: "rgba(0,180,50,0.8)", border: "none", borderRadius: 2,
                              width: 32, height: 32, display: "flex", alignItems: "center",
                              justifyContent: "center", cursor: "pointer", flexShrink: 0,
                              boxShadow: "0 0 10px rgba(0,150,40,0.3)",
                              transition: "all 0.2s",
                            }}
                            onMouseEnter={e => e.currentTarget.style.boxShadow = "0 0 18px rgba(0,150,40,0.5)"}
                            onMouseLeave={e => e.currentTarget.style.boxShadow = "0 0 10px rgba(0,150,40,0.3)"}
                          >
                            <ArrowRight size={16} color="#000" strokeWidth={3} />
                          </button>
                        </div>
                      </form>

                      <div style={{ marginTop: 18, fontSize: 10, color: "#004010", letterSpacing: 1 }}>
                        {">"} SUPPORTED: public github repositories only
                      </div>
                    </motion.div>
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {/* ── LOADING ── */}
          {appState === "loading" && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20, zIndex: 2 }}
            >
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
                style={{
                  width: 52, height: 52,
                  border: "2px solid rgba(0,255,65,0.1)",
                  borderTop: "2px solid #00b432",
                  borderRadius: "50%",
                  boxShadow: "0 0 14px rgba(0,150,40,0.2)",
                }}
              />
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 12, color: "#00cc2e", letterSpacing: 2, marginBottom: 5 }}>
                  CLONING REPOSITORY
                </div>
                <div style={{ fontSize: 10, color: "#005015", letterSpacing: 1 }}>
                  indexing codebase... please wait
                </div>
              </div>
              <div style={{ width: 180, height: 2, background: "rgba(0,255,65,0.1)", borderRadius: 2 }}>
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: "100%" }}
                  transition={{ duration: 3, ease: "easeInOut" }}
                  style={{ height: "100%", background: "#00b432", boxShadow: "0 0 6px rgba(0,150,40,0.4)", borderRadius: 2 }}
                />
              </div>
            </motion.div>
          )}

          {/* ── CHAT ── */}
          {appState === "chat" && (
            <ChatBox
              key="chat"
              repoUrl={repoUrl}
              repoName={repoName}
              onReset={() => { setAppState("landing"); setRepoUrl(""); setRepoName(""); }}
            />
          )}

        </AnimatePresence>
      </div>
    </>
  );
}