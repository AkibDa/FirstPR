import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from 'framer-motion';
import { GitBranch, ArrowRight, Loader2, Send, Terminal } from 'lucide-react';
import ChatBox from './Chatbox';

// Import JetBrains Mono from Google Fonts via a style tag
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
    --surface: #050f05;
    --surface-2: #0a1a0a;
    --border: #00ff4122;
    --border-active: #00ff4166;
    --text-primary: #00ff41;
    --text-secondary: #00bb2f;
    --text-muted: #006618;
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

  /* CRT vignette */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.8) 100%);
    pointer-events: none;
    z-index: 9998;
  }

  /* Custom scrollbar - glued to rightmost edge */
  .chat-scroll {
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--green-dim) transparent;
    /* Extend scroll area to screen edge */
    margin-right: -24px;
    padding-right: 24px;
  }

  .chat-scroll::-webkit-scrollbar {
    width: 3px;
  }
  .chat-scroll::-webkit-scrollbar-track {
    background: transparent;
  }
  .chat-scroll::-webkit-scrollbar-thumb {
    background: var(--green-dim);
    border-radius: 0;
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

  .terminal-input::placeholder {
    color: var(--text-muted);
  }

  .glow-text {
    text-shadow: 0 0 10px var(--green), 0 0 20px var(--green-dim);
  }

  .glow-border {
    box-shadow: 0 0 0 1px var(--border-active), 0 0 15px var(--green-muted);
  }

  .glow-border-subtle {
    box-shadow: 0 0 0 1px var(--border), inset 0 0 20px rgba(0,255,65,0.02);
  }

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

  @keyframes matrixRain {
    0% { transform: translateY(-100%); opacity: 1; }
    100% { transform: translateY(100vh); opacity: 0; }
  }

  .cursor-blink::after {
    content: '█';
    animation: blink 1s step-end infinite;
    color: var(--green);
  }

  .boot-text {
    animation: flicker 8s infinite;
  }

  .scanline-fast {
    position: absolute;
    inset: 0;
    background: linear-gradient(transparent 50%, rgba(0,255,65,0.02) 50%);
    background-size: 100% 4px;
    pointer-events: none;
    border-radius: inherit;
  }

  /* Typing animation for assistant messages */
  @keyframes typeIn {
    from { width: 0; }
    to { width: 100%; }
  }
`;

const StyleTag = () => (
  <style dangerouslySetInnerHTML={{ __html: globalStyles }} />
);

// Matrix rain background component
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
        // Leading char is bright
        ctx.fillStyle = `rgba(0, 255, 65, ${Math.random() > 0.98 ? 1 : 0.15})`;
        ctx.fillText(char, x, y * fontSize);

        if (y * fontSize > canvas.height && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i]++;
      });
      animId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animId);
  }, []);

  return <canvas ref={canvasRef} style={{ position: 'fixed', inset: 0, opacity: 0.35, zIndex: 0, pointerEvents: 'none' }} />;
}

function GlitchText({ text, className = '' }) {
  return (
    <span className={className} style={{ position: 'relative', display: 'inline-block' }}>
      {text}
    </span>
  );
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
        fontFamily: "'JetBrains Mono', monospace",
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        zIndex: 1,
        overflow: 'hidden',
      }}>
        <AnimatePresence mode="wait">

          {/* VIEW 1: LANDING */}
          {appState === 'landing' && (
            <motion.div
              key="landing"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.5 }}
              style={{ width: '100%', maxWidth: 520, padding: '0 24px', position: 'relative', zIndex: 2 }}
            >
              {/* Terminal window frame */}
              <div style={{
                border: '1px solid var(--border-active)',
                borderRadius: 4,
                background: 'rgba(0,10,0,0.95)',
                boxShadow: '0 0 40px rgba(0,255,65,0.1), 0 0 80px rgba(0,255,65,0.05)',
                overflow: 'hidden',
              }}>
                {/* Terminal title bar */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '10px 16px',
                  borderBottom: '1px solid var(--border)',
                  background: 'rgba(0,255,65,0.03)',
                }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#ff5f57', boxShadow: '0 0 6px #ff5f57' }} />
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#febc2e', boxShadow: '0 0 6px #febc2e' }} />
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#28c840', boxShadow: '0 0 6px #28c840' }} />
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)', letterSpacing: 2 }}>
                    FIRSTPR_MENTOR — bash
                  </span>
                </div>

                <div style={{ padding: '28px 28px 32px' }}>
                  {!booted ? (
                    <BootSequence onDone={() => setBooted(true)} />
                  ) : (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
                      {/* Header */}
                      <div style={{ marginBottom: 28 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                          <Terminal size={18} color="var(--green)" />
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: 3 }}>
                            SYSTEM READY
                          </span>
                        </div>
                        <h1 style={{
                          fontSize: 26,
                          fontWeight: 700,
                          letterSpacing: -0.5,
                          color: 'var(--green)',
                          textShadow: '0 0 20px var(--green-dim)',
                          lineHeight: 1.2,
                          marginBottom: 8,
                        }}>
                          FIRSTPR<span style={{ color: 'var(--text-muted)' }}>_</span>MENTOR
                        </h1>
                        <p style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.6, letterSpacing: 0.5 }}>
                          // Paste a GitHub repository URL to begin codebase ingestion.
                        </p>
                      </div>

                      {/* Input */}
                      <form onSubmit={handleLoadRepo}>
                        <div style={{ marginBottom: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                          $ repo_url=
                        </div>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          border: '1px solid var(--border-active)',
                          borderRadius: 3,
                          background: 'rgba(0,255,65,0.04)',
                          padding: '12px 14px',
                          gap: 10,
                          transition: 'box-shadow 0.2s',
                        }}
                          onFocus={() => { }}
                        >
                          <span style={{ color: 'var(--green-dim)', fontSize: 13 }}>▶</span>
                          <input
                            type="url"
                            placeholder="https://github.com/owner/repo"
                            value={repoUrl}
                            onChange={(e) => setRepoUrl(e.target.value)}
                            required
                            style={{
                              flex: 1,
                              background: 'transparent',
                              border: 'none',
                              outline: 'none',
                              color: 'var(--green)',
                              fontFamily: "'JetBrains Mono', monospace",
                              fontSize: 13,
                              caretColor: 'var(--green)',
                            }}
                          />
                          <button
                            type="submit"
                            style={{
                              background: 'var(--green)',
                              border: 'none',
                              borderRadius: 2,
                              width: 32,
                              height: 32,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              cursor: 'pointer',
                              flexShrink: 0,
                              boxShadow: '0 0 12px var(--green)',
                              transition: 'all 0.2s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.boxShadow = '0 0 20px var(--green)'}
                            onMouseLeave={e => e.currentTarget.style.boxShadow = '0 0 12px var(--green)'}
                          >
                            <ArrowRight size={16} color="#000" strokeWidth={3} />
                          </button>
                        </div>
                      </form>

                      <div style={{ marginTop: 20, fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1 }}>
                        {'>'} SUPPORTED: public github repositories only
                      </div>
                    </motion.div>
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {/* VIEW 2: LOADING */}
          {appState === 'loading' && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20, zIndex: 2 }}
            >
              <div style={{ position: 'relative' }}>
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ repeat: Infinity, duration: 1.2, ease: 'linear' }}
                  style={{
                    width: 56, height: 56,
                    border: '2px solid var(--border)',
                    borderTop: '2px solid var(--green)',
                    borderRadius: '50%',
                    boxShadow: '0 0 20px var(--green-muted)',
                  }}
                />
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 13, color: 'var(--green)', letterSpacing: 2, marginBottom: 6 }}>
                  CLONING REPOSITORY
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1 }}>
                  indexing codebase... please wait
                </div>
              </div>
              {/* Progress bar */}
              <div style={{ width: 200, height: 2, background: 'var(--border)', borderRadius: 2 }}>
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: '100%' }}
                  transition={{ duration: 3, ease: 'easeInOut' }}
                  style={{ height: '100%', background: 'var(--green)', boxShadow: '0 0 8px var(--green)', borderRadius: 2 }}
                />
              </div>
            </motion.div>
          )}

          {/* VIEW 3: CHAT */}
          {appState === 'chat' && (
            <ChatBox
              key="chat"
              repoUrl={repoUrl}
              repoName={repoName}
              onReset={() => setAppState('landing')}
            />
          )}
        </AnimatePresence>
      </div>
    </>
  );
}

// --- CHAT INTERFACE ---
// function ChatInterface({ repoUrl, repoName, onReset }) {
//   const [messages, setMessages] = useState([
//     { role: 'assistant', content: `Repository [${repoName}] indexed successfully.\n\nAre you looking to understand a specific issue, or do you have a general question about the codebase?` }
//   ]);
//   const [input, setInput] = useState('');
//   const [isTyping, setIsTyping] = useState(false);
//   const bottomRef = useRef(null);
//   const chatRef = useRef(null);

//   useEffect(() => {
//     bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
//   }, [messages, isTyping]);

//   const handleSendMessage = async (e) => {
//     e.preventDefault();
//     if (!input.trim()) return;

//     const userMsg = input;
//     setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
//     setInput('');
//     setIsTyping(true);

//     const isIssue = userMsg.includes('github.com') && userMsg.includes('/issues/');
//     const endpoint = isIssue ? '/api/analyze-issue' : '/api/ask';
//     const payload = isIssue
//       ? { repo_url: repoUrl, issue_url: userMsg }
//       : { repo_url: repoUrl, question: userMsg };

//     try {
//       const res = await fetch(`http://127.0.0.1:8000${endpoint}`, {
//         method: 'POST',
//         headers: { 'Content-Type': 'application/json' },
//         body: JSON.stringify(payload),
//       });
//       const data = await res.json();
//       let botReply = isIssue
//         ? `[ANALYSIS] ${data.issue.title}\n\nSTART_AT: ${data.reasoning.where_to_start}\n\n${data.reasoning.explanation}`
//         : data.answer;

//       setMessages(prev => [...prev, { role: 'assistant', content: botReply }]);
//     } catch {
//       setMessages(prev => [...prev, { role: 'assistant', content: '[ERROR] Failed to reach backend. Check your connection.' }]);
//     } finally {
//       setIsTyping(false);
//     }
//   };

//   return (
//     <motion.div
//       initial={{ opacity: 0 }}
//       animate={{ opacity: 1 }}
//       style={{
//         width: '100vw',
//         height: '100vh',
//         display: 'flex',
//         flexDirection: 'column',
//         position: 'relative',
//         zIndex: 2,
//         background: 'rgba(0,5,0,0.92)',
//       }}
//     >
//       {/* Header */}
//       <div style={{
//         display: 'flex',
//         alignItems: 'center',
//         justifyContent: 'space-between',
//         padding: '14px 28px',
//         borderBottom: '1px solid var(--border)',
//         background: 'rgba(0,20,0,0.8)',
//         backdropFilter: 'blur(10px)',
//         flexShrink: 0,
//       }}>
//         <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
//           <div style={{
//             border: '1px solid var(--border-active)',
//             borderRadius: 3,
//             padding: '6px 10px',
//             display: 'flex',
//             alignItems: 'center',
//             gap: 6,
//             background: 'rgba(0,255,65,0.05)',
//           }}>
//             <GitBranch size={14} color="var(--green)" />
//             <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, color: 'var(--green)', textShadow: '0 0 10px var(--green)' }}>
//               {repoName.toUpperCase()}
//             </span>
//           </div>
//           <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
//             <span style={{
//               width: 6, height: 6, borderRadius: '50%',
//               background: 'var(--green)',
//               boxShadow: '0 0 8px var(--green)',
//               display: 'inline-block',
//               animation: 'blink 2s step-end infinite',
//             }} />
//             <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 2 }}>INDEX ACTIVE</span>
//           </div>
//         </div>
//         <button
//           onClick={onReset}
//           style={{
//             background: 'transparent',
//             border: '1px solid var(--border)',
//             borderRadius: 3,
//             padding: '6px 14px',
//             color: 'var(--text-muted)',
//             fontFamily: "'JetBrains Mono', monospace",
//             fontSize: 11,
//             cursor: 'pointer',
//             letterSpacing: 1,
//             transition: 'all 0.2s',
//           }}
//           onMouseEnter={e => {
//             e.currentTarget.style.borderColor = 'var(--green)';
//             e.currentTarget.style.color = 'var(--green)';
//           }}
//           onMouseLeave={e => {
//             e.currentTarget.style.borderColor = 'var(--border)';
//             e.currentTarget.style.color = 'var(--text-muted)';
//           }}
//         >
//           [SWITCH REPO]
//         </button>
//       </div>

//       {/* Chat messages - scroll area extends to screen edge */}
//       <div
//         ref={chatRef}
//         className="chat-scroll"
//         style={{
//           flex: 1,
//           padding: '28px 28px 20px 28px',
//           display: 'flex',
//           flexDirection: 'column',
//           gap: 20,
//           /* extend to right edge for scrollbar */
//           paddingRight: 28,
//           marginRight: 0,
//           overflowX: 'hidden',
//         }}
//       >
//         {messages.map((msg, idx) => (
//           <motion.div
//             key={idx}
//             initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
//             animate={{ opacity: 1, x: 0 }}
//             transition={{ duration: 0.3 }}
//             style={{
//               display: 'flex',
//               justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
//             }}
//           >
//             {msg.role === 'assistant' && (
//               <div style={{ display: 'flex', flexDirection: 'column', maxWidth: '80%', gap: 4 }}>
//                 <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 2, paddingLeft: 2 }}>
//                   MENTOR@FIRSTPR $
//                 </span>
//                 <div style={{
//                   background: 'rgba(0,255,65,0.03)',
//                   border: '1px solid var(--border)',
//                   borderRadius: '0 6px 6px 6px',
//                   padding: '14px 18px',
//                   position: 'relative',
//                   boxShadow: '0 0 20px rgba(0,255,65,0.04)',
//                 }}>
//                   <div className="scanline-fast" />
//                   <p style={{
//                     whiteSpace: 'pre-wrap',
//                     lineHeight: 1.75,
//                     fontSize: 13,
//                     color: 'var(--green)',
//                     fontFamily: "'JetBrains Mono', monospace",
//                   }}>
//                     {msg.content}
//                   </p>
//                 </div>
//               </div>
//             )}
//             {msg.role === 'user' && (
//               <div style={{ display: 'flex', flexDirection: 'column', maxWidth: '70%', gap: 4, alignItems: 'flex-end' }}>
//                 <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 2, paddingRight: 2 }}>
//                   YOU $
//                 </span>
//                 <div style={{
//                   background: 'rgba(0,255,65,0.08)',
//                   border: '1px solid var(--border-active)',
//                   borderRadius: '6px 0 6px 6px',
//                   padding: '12px 16px',
//                   boxShadow: '0 0 12px rgba(0,255,65,0.06)',
//                 }}>
//                   <p style={{
//                     whiteSpace: 'pre-wrap',
//                     lineHeight: 1.7,
//                     fontSize: 13,
//                     color: 'var(--green)',
//                     fontFamily: "'JetBrains Mono', monospace",
//                     textShadow: '0 0 8px rgba(0,255,65,0.3)',
//                   }}>
//                     {msg.content}
//                   </p>
//                 </div>
//               </div>
//             )}
//           </motion.div>
//         ))}

//         {isTyping && (
//           <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ display: 'flex', justifyContent: 'flex-start' }}>
//             <div style={{
//               border: '1px solid var(--border)',
//               borderRadius: '0 6px 6px 6px',
//               padding: '14px 18px',
//               display: 'flex',
//               alignItems: 'center',
//               gap: 4,
//               background: 'rgba(0,255,65,0.02)',
//             }}>
//               {[0, 150, 300].map((delay, i) => (
//                 <motion.span
//                   key={i}
//                   animate={{ opacity: [0.2, 1, 0.2], scaleY: [0.5, 1, 0.5] }}
//                   transition={{ repeat: Infinity, duration: 0.9, delay: delay / 1000 }}
//                   style={{
//                     display: 'inline-block',
//                     width: 3,
//                     height: 14,
//                     background: 'var(--green)',
//                     boxShadow: '0 0 6px var(--green)',
//                     borderRadius: 1,
//                   }}
//                 />
//               ))}
//               <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8, letterSpacing: 1 }}>
//                 processing...
//               </span>
//             </div>
//           </motion.div>
//         )}
//         <div ref={bottomRef} />
//       </div>

//       {/* Input */}
//       <div style={{
//         padding: '16px 28px 20px',
//         borderTop: '1px solid var(--border)',
//         background: 'rgba(0,10,0,0.9)',
//         flexShrink: 0,
//       }}>
//         <form onSubmit={handleSendMessage}>
//           <div style={{
//             display: 'flex',
//             alignItems: 'flex-end',
//             border: '1px solid var(--border-active)',
//             borderRadius: 4,
//             background: 'rgba(0,255,65,0.03)',
//             padding: '12px 14px',
//             gap: 12,
//             boxShadow: '0 0 20px rgba(0,255,65,0.05)',
//             transition: 'box-shadow 0.2s',
//           }}>
//             <span style={{ color: 'var(--green-dim)', fontSize: 13, paddingBottom: 1, flexShrink: 0 }}>▶</span>
//             <textarea
//               rows={1}
//               value={input}
//               onChange={(e) => setInput(e.target.value)}
//               onKeyDown={(e) => {
//                 if (e.key === 'Enter' && !e.shiftKey) {
//                   e.preventDefault();
//                   handleSendMessage(e);
//                 }
//               }}
//               placeholder="paste an issue URL or query the codebase..."
//               className="terminal-input"
//               style={{ fontSize: 13, lineHeight: 1.5, paddingBottom: 0, flex: 1 }}
//             />
//             <button
//               type="submit"
//               disabled={!input.trim() || isTyping}
//               style={{
//                 background: input.trim() && !isTyping ? 'var(--green)' : 'transparent',
//                 border: '1px solid ' + (input.trim() && !isTyping ? 'var(--green)' : 'var(--border)'),
//                 borderRadius: 3,
//                 width: 34,
//                 height: 34,
//                 display: 'flex',
//                 alignItems: 'center',
//                 justifyContent: 'center',
//                 cursor: input.trim() && !isTyping ? 'pointer' : 'not-allowed',
//                 flexShrink: 0,
//                 transition: 'all 0.2s',
//                 boxShadow: input.trim() && !isTyping ? '0 0 14px var(--green-muted)' : 'none',
//               }}
//             >
//               <Send size={15} color={input.trim() && !isTyping ? '#000' : 'var(--text-muted)'} strokeWidth={2.5} />
//             </button>
//           </div>
//           <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)', letterSpacing: 0.5, paddingLeft: 2 }}>
//             ENTER to send · SHIFT+ENTER for newline · paste issue URL for deep analysis
//           </div>
//         </form>
//       </div>
//     </motion.div>
//   );
