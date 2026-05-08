import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from 'framer-motion';
import { Terminal, ArrowRight } from 'lucide-react';
import ChatInterface from './ChatInterface'; // <--- Separated component

const fontLink = document.createElement('link');
fontLink.href = 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Share+Tech+Mono&display=swap';
fontLink.rel = 'stylesheet';
document.head.appendChild(fontLink);

const globalStyles = `
  :root {
    --green: #00ff41;
    --green-dim: #00cc33;
    --green-muted: #00882288;
    --green-bg: #00ff4108;
    --black: #000000;
    --surface: #030803; /* Darkened surface */
    --border: #00ff4122;
    --border-active: #00ff4166;
    --text-primary: #00ff41;
    --text-muted: #007722; /* Slightly more readable muted text */
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--black);
    color: var(--green);
    font-family: 'JetBrains Mono', 'Share Tech Mono', monospace;
    overflow: hidden;
  }

  /* Scanline overlay */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0, 255, 65, 0.015) 2px,
      rgba(0, 255, 65, 0.015) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }

  /* CRT vignette REMOVED here to fix the unclickable edges issue */

  .chat-scroll {
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--green-dim) transparent;
    margin-right: -24px;
    padding-right: 24px;
  }

  .chat-scroll::-webkit-scrollbar { width: 3px; }
  .chat-scroll::-webkit-scrollbar-track { background: transparent; }
  .chat-scroll::-webkit-scrollbar-thumb {
    background: var(--green-dim);
    box-shadow: 0 0 6px var(--green);
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
    50% { opacity: 0; }
  }

  @keyframes flicker {
    0%, 100% { opacity: 1; }
    92% { opacity: 1; }
    93% { opacity: 0.8; }
    94% { opacity: 1; }
    96% { opacity: 0.9; }
    97% { opacity: 1; }
  }
`;

const StyleTag = () => <style dangerouslySetInnerHTML={{ __html: globalStyles }} />;

function MatrixBg() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const fontSize = 13;
    const cols = Math.floor(canvas.width / fontSize);
    const drops = Array(cols).fill(1);
    const chars = '01アイウエオカキクケコABCDEF{}[]<>/\\|=+-*&^%$#@!?'.split('');

    let animId;
    const draw = () => {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.font = `${fontSize}px JetBrains Mono, monospace`;

      drops.forEach((y, i) => {
        const char = chars[Math.floor(Math.random() * chars.length)];
        const x = i * fontSize;
        ctx.fillStyle = `rgba(0, 255, 65, ${Math.random() > 0.98 ? 1 : 0.15})`;
        ctx.fillText(char, x, y * fontSize);

        if (y * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
        drops[i]++;
      });
      animId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} style={{ position: 'fixed', inset: 0, opacity: 0.25, zIndex: 0, pointerEvents: 'none' }} />;
}

function BootSequence({ onDone }) {
  const lines = [
    '> INITIALIZING FIRSTPR MENTOR v2.4.1',
    '> LOADING NEURAL CODEBASE ENGINE...',
    '> CONNECTING TO GITHUB API...',
    '> READY.',
  ];
  const [shown, setShown] = useState([]);

  useEffect(() => {
    lines.forEach((line, i) => {
      setTimeout(() => {
        setShown(prev => [...prev, line]);
        if (i === lines.length - 1) setTimeout(onDone, 600);
      }, i * 400);
    });
  }, []);

  return (
    <div style={{ fontFamily: 'JetBrains Mono', color: 'var(--green)', padding: '8px 0', fontSize: 12 }}>
      {shown.map((l, i) => (
        <div key={i} style={{ marginBottom: 4, opacity: 0.7 }}>{l}</div>
      ))}
    </div>
  );
}

export default function App() {
  const [appState, setAppState] = useState('landing');
  const [repoUrl, setRepoUrl] = useState('');
  const [repoName, setRepoName] = useState('');
  const [booted, setBooted] = useState(false);

  const handleLoadRepo = async (e) => {
    e.preventDefault();
    if (!repoUrl) return;
    setAppState('loading');

    try {
      const res = await fetch('http://127.0.0.1:8000/api/load-repo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      const data = await res.json();
      if (res.ok) {
        setRepoName(data.repo_name);
        setAppState('chat');
      } else {
        alert('Failed to load repo: ' + data.detail);
        setAppState('landing');
      }
    } catch (error) {
      console.error(error);
      setAppState('landing');
    }
  };

  return (
    <>
      <StyleTag />
      <MatrixBg />
      <div style={{
        minHeight: '100vh',
        background: 'var(--surface)',
        color: 'var(--green)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        zIndex: 1,
      }}>
        <AnimatePresence mode="wait">
          {appState === 'landing' && (
            <motion.div
              key="landing"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              style={{ width: '100%', maxWidth: 520, padding: '0 24px', zIndex: 2 }}
            >
              <div style={{
                border: '1px solid var(--border-active)',
                borderRadius: 4,
                background: '#020602',
                boxShadow: '0 0 40px rgba(0,255,65,0.05)',
                overflow: 'hidden',
              }}>
                <div style={{ padding: '28px' }}>
                  {!booted ? (
                    <BootSequence onDone={() => setBooted(true)} />
                  ) : (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                      <div style={{ marginBottom: 28 }}>
                        <h1 style={{ fontSize: 26, fontWeight: 700, color: 'var(--green)', marginBottom: 8 }}>
                          FIRSTPR_MENTOR
                        </h1>
                        <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                          // Paste a GitHub repository URL to begin codebase ingestion.
                        </p>
                      </div>

                      <form onSubmit={handleLoadRepo}>
                        <div style={{
                          display: 'flex',
                          border: '1px solid var(--border-active)',
                          background: 'rgba(0,255,65,0.02)',
                          padding: '12px',
                          gap: 10,
                        }}>
                          <span style={{ color: 'var(--green-dim)', fontSize: 13 }}>▶</span>
                          <input
                            type="url"
                            placeholder="https://github.com/owner/repo"
                            value={repoUrl}
                            onChange={(e) => setRepoUrl(e.target.value)}
                            required
                            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--green)', fontSize: 13 }}
                          />
                          <button type="submit" style={{
                            background: 'var(--green)', border: 'none', borderRadius: 2,
                            width: 32, height: 32, cursor: 'pointer', boxShadow: '0 0 10px var(--green)'
                          }}>
                            <ArrowRight size={16} color="#000" />
                          </button>
                        </div>
                      </form>
                    </motion.div>
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {appState === 'loading' && (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ zIndex: 2, textAlign: 'center' }}>
              <div style={{ fontSize: 13, letterSpacing: 2 }}>CLONING REPOSITORY</div>
            </motion.div>
          )}

          {appState === 'chat' && (
            <ChatInterface key="chat" repoUrl={repoUrl} repoName={repoName} onReset={() => setAppState('landing')} />
          )}
        </AnimatePresence>
      </div>
    </>
  );
}