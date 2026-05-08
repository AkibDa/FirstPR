import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, ChevronDown, ChevronRight, FileCode, Brain,
  Search, MapPin, AlertTriangle, CheckCircle, Clock,
  Zap, BookOpen, GitCommit, Wrench, MessageSquare
} from "lucide-react";


function Badge({ label, color = "green" }) {
  const colors = {
    green:  { bg: "rgba(0,180,50,0.12)", border: "rgba(0,180,50,0.35)", text: "#00b432" },
    yellow: { bg: "rgba(200,160,0,0.12)", border: "rgba(200,160,0,0.35)", text: "#c8a000" },
    red:    { bg: "rgba(200,60,60,0.12)", border: "rgba(200,60,60,0.35)", text: "#c83c3c" },
    blue:   { bg: "rgba(40,120,200,0.12)", border: "rgba(40,120,200,0.35)", text: "#2878c8" },
    muted:  { bg: "rgba(0,100,30,0.10)", border: "rgba(0,100,30,0.25)", text: "#006618" },
  };
  const c = colors[color] || colors.muted;
  return (
    <span style={{
      background: c.bg, border: `1px solid ${c.border}`, color: c.text,
      borderRadius: 2, padding: "2px 7px", fontSize: 10, letterSpacing: 1,
      fontFamily: "'JetBrains Mono', monospace", fontWeight: 600,
      whiteSpace: "nowrap",
    }}>
      {label.toUpperCase()}
    </span>
  );
}

function Accordion({ title, icon: Icon, children, defaultOpen = false, accent = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{
      border: `1px solid ${accent ? "rgba(0,180,50,0.3)" : "rgba(0,255,65,0.1)"}`,
      borderRadius: 3,
      overflow: "hidden",
      marginBottom: 8,
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px", background: accent ? "rgba(0,150,40,0.08)" : "rgba(0,255,65,0.03)",
          border: "none", cursor: "pointer", color: accent ? "#00b432" : "#007a20",
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11, letterSpacing: 1,
          textAlign: "left", transition: "background 0.15s",
        }}
        onMouseEnter={e => e.currentTarget.style.background = "rgba(0,150,40,0.12)"}
        onMouseLeave={e => e.currentTarget.style.background = accent ? "rgba(0,150,40,0.08)" : "rgba(0,255,65,0.03)"}
      >
        {Icon && <Icon size={13} />}
        <span style={{ flex: 1 }}>{title}</span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <div style={{ padding: "12px 14px", background: "rgba(0,8,2,0.6)", borderTop: "1px solid rgba(0,255,65,0.08)" }}>
          {children}
        </div>
      )}
    </div>
  );
}

function MetaRow({ label, value, children }) {
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 7, alignItems: "flex-start" }}>
      <span style={{ color: "#005015", fontSize: 11, minWidth: 120, letterSpacing: 0.5, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ color: "#009922", fontSize: 11, lineHeight: 1.5 }}>
        {children || value}
      </span>
    </div>
  );
}

function FileCard({ file }) {
  const [open, setOpen] = useState(false);
  const relevanceColor = file.relevance === "high" ? "green" : file.relevance === "medium" ? "yellow" : "muted";
  const methodColor = file.method === "bm25" ? "blue" : "muted";

  return (
    <div style={{
      border: "1px solid rgba(0,255,65,0.1)", borderRadius: 3, marginBottom: 6,
      overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "9px 12px", background: "rgba(0,255,65,0.02)", border: "none",
          cursor: "pointer", textAlign: "left", transition: "background 0.15s",
        }}
        onMouseEnter={e => e.currentTarget.style.background = "rgba(0,255,65,0.05)"}
        onMouseLeave={e => e.currentTarget.style.background = "rgba(0,255,65,0.02)"}
      >
        <FileCode size={12} color="#006618" />
        <span style={{ flex: 1, color: "#009922", fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>
          {file.path}
        </span>
        <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
          <Badge label={file.relevance} color={relevanceColor} />
          <Badge label={file.method} color={methodColor} />
          <span style={{ color: "#004010", fontSize: 10 }}>{file.score?.toFixed(2)}</span>
          {open ? <ChevronDown size={11} color="#004010" /> : <ChevronRight size={11} color="#004010" />}
        </div>
      </button>
      {open && (
        <div style={{ padding: "10px 12px", background: "rgba(0,5,1,0.8)", borderTop: "1px solid rgba(0,255,65,0.06)" }}>
          <p style={{ color: "#007a20", fontSize: 11, lineHeight: 1.6, marginBottom: 8 }}>{file.reason}</p>
          {file.functions?.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {file.functions.map(fn => (
                <span key={fn} style={{
                  background: "rgba(0,100,30,0.12)", border: "1px solid rgba(0,100,30,0.2)",
                  color: "#00882288", borderRadius: 2, padding: "1px 6px", fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                }}>
                  fn:{fn}()
                </span>
              ))}
              {file.classes?.map(cls => (
                <span key={cls} style={{
                  background: "rgba(40,100,0,0.12)", border: "1px solid rgba(40,100,0,0.2)",
                  color: "#4a8800", borderRadius: 2, padding: "1px 6px", fontSize: 10,
                  fontFamily: "'JetBrains Mono', monospace",
                }}>
                  cls:{cls}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function IssueAnalysisCard({ data }) {
  const { issue, analysis, retrieval, reasoning } = data;
  const difficultyColor = { beginner: "green", intermediate: "yellow", advanced: "red" }[analysis.difficulty] || "muted";

  return (
    <div style={{
      background: "rgba(0,10,3,0.85)",
      border: "1px solid rgba(0,180,50,0.25)",
      borderRadius: 4,
      overflow: "hidden",
      boxShadow: "0 0 0 1px rgba(0,180,50,0.08), inset 0 0 40px rgba(0,0,0,0.3)",
    }}>
      {/* Header */}
      <div style={{
        padding: "14px 18px",
        borderBottom: "1px solid rgba(0,255,65,0.1)",
        background: "rgba(0,20,5,0.6)",
        display: "flex", alignItems: "flex-start", gap: 10,
      }}>
        <Brain size={16} color="#00b432" style={{ marginTop: 2, flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, color: "#005015", letterSpacing: 2, marginBottom: 4 }}>
            ISSUE ANALYSIS
          </div>
          <div style={{ color: "#009922", fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 8 }}>
            {issue.title}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <Badge label={analysis.issue_type} color="muted" />
            <Badge label={`difficulty: ${analysis.difficulty}`} color={difficultyColor} />
            {analysis.good_first_issue && <Badge label="good first issue ✓" color="green" />}
            <Badge label={`~${analysis.estimated_hours}h`} color="muted" />
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: "14px 16px" }}>

        {/* Analysis */}
        <Accordion title="ANALYSIS" icon={Zap} defaultOpen={true} accent={true}>
          <MetaRow label="Root cause">{analysis.root_cause_hypothesis}</MetaRow>
          <MetaRow label="Difficulty why">{analysis.difficulty_reason}</MetaRow>
          <MetaRow label="Skills needed">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.required_skills?.map(s => <Badge key={s} label={s} color="muted" />)}
            </div>
          </MetaRow>
          <MetaRow label="Affected areas">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {analysis.affected_areas?.map(a => <Badge key={a} label={a} color="muted" />)}
            </div>
          </MetaRow>
        </Accordion>

        {/* Relevant Files */}
        <Accordion title={`RELEVANT FILES (${retrieval.relevant_files?.length || 0})`} icon={Search}>
          {retrieval.relevant_files?.map((f, i) => <FileCard key={i} file={f} />)}
          {retrieval.key_functions?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: "#005015", letterSpacing: 1, marginBottom: 6 }}>KEY FUNCTIONS</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {retrieval.key_functions.map(fn => (
                  <span key={fn} style={{
                    background: "rgba(0,80,20,0.15)", border: "1px solid rgba(0,80,20,0.25)",
                    color: "#006618", borderRadius: 2, padding: "2px 7px", fontSize: 10,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {fn}()
                  </span>
                ))}
              </div>
            </div>
          )}
        </Accordion>

        {/* Contribution Path */}
        <Accordion title="CONTRIBUTION PATH" icon={GitCommit} accent={true}>
          <MetaRow label="Start here">{reasoning.where_to_start}</MetaRow>
          {reasoning.what_to_read_first?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, color: "#005015", letterSpacing: 1, marginBottom: 6 }}>READ FIRST</div>
              {reasoning.what_to_read_first.map((item, i) => (
                <div key={i} style={{
                  padding: "6px 10px", borderLeft: "2px solid rgba(0,150,40,0.3)",
                  marginBottom: 5, color: "#007a20", fontSize: 11, lineHeight: 1.5,
                }}>
                  {item}
                </div>
              ))}
            </div>
          )}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, color: "#005015", letterSpacing: 1, marginBottom: 8 }}>STEPS</div>
            {reasoning.contribution_path?.map((step) => (
              <div key={step.step} style={{
                display: "flex", gap: 10, marginBottom: 10, alignItems: "flex-start",
              }}>
                <div style={{
                  width: 20, height: 20, border: "1px solid rgba(0,180,50,0.3)",
                  borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, fontSize: 10, color: "#009922", background: "rgba(0,80,20,0.12)",
                }}>
                  {step.step}
                </div>
                <div>
                  <div style={{ color: "#009922", fontSize: 11, fontWeight: 600, marginBottom: 3 }}>{step.title}</div>
                  <div style={{ color: "#007a20", fontSize: 11, lineHeight: 1.5 }}>{step.description}</div>
                  {step.files_involved?.length > 0 && (
                    <div style={{ marginTop: 5, display: "flex", gap: 5, flexWrap: "wrap" }}>
                      {step.files_involved.map(f => (
                        <span key={f} style={{
                          background: "rgba(0,60,15,0.2)", border: "1px solid rgba(0,60,15,0.3)",
                          color: "#005015", borderRadius: 2, padding: "1px 6px", fontSize: 10,
                          fontFamily: "'JetBrains Mono', monospace",
                        }}>
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Accordion>

        {/* Logic Trace */}
        {reasoning.logic_trace?.length > 0 && (
          <Accordion title="LOGIC TRACE" icon={BookOpen}>
            {reasoning.logic_trace.map((step, i) => (
              <div key={i} style={{
                padding: "5px 0 5px 10px", borderLeft: "1px solid rgba(0,100,30,0.3)",
                marginBottom: 4, color: "#006618", fontSize: 11, lineHeight: 1.5,
              }}>
                {step}
              </div>
            ))}
          </Accordion>
        )}

        {/* Common Mistakes */}
        {reasoning.common_mistakes?.length > 0 && (
          <Accordion title="COMMON MISTAKES" icon={AlertTriangle}>
            {reasoning.common_mistakes.map((m, i) => (
              <div key={i} style={{
                display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 5,
                color: "#8a6000", fontSize: 11, lineHeight: 1.5,
              }}>
                <span style={{ color: "#c8a000", flexShrink: 0 }}>!</span>
                {m}
              </div>
            ))}
          </Accordion>
        )}

        {/* Patch */}
        {reasoning.suggested_patch && (
          <Accordion title="SUGGESTED PATCH" icon={Wrench} accent={true}>
            <pre style={{
              color: "#00b432", fontSize: 10, lineHeight: 1.6, overflowX: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontFamily: "'JetBrains Mono', monospace",
            }}>
              {reasoning.suggested_patch}
            </pre>
          </Accordion>
        )}
      </div>
    </div>
  );
}

function QAAnswerCard({ data }) {
  return (
    <div style={{
      background: "rgba(0,10,3,0.85)",
      border: "1px solid rgba(0,255,65,0.12)",
      borderRadius: 4,
      overflow: "hidden",
    }}>
      {/* Answer */}
      <div style={{ padding: "14px 18px" }}>
        <div style={{ fontSize: 10, color: "#005015", letterSpacing: 2, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
          <MessageSquare size={11} color="#005015" />
          ANSWER
        </div>
        <p style={{
          color: "#00dd33", fontSize: 13, lineHeight: 1.8,
          fontFamily: "'JetBrains Mono', monospace", whiteSpace: "pre-wrap",
        }}>
          {data.answer}
        </p>
      </div>

      {/* Relevant files */}
      {data.relevant_files?.length > 0 && (
        <div style={{ padding: "0 18px 14px" }}>
          <Accordion title={`REFERENCED FILES (${data.relevant_files.length})`} icon={FileCode}>
            {data.relevant_files.map((f, i) => <FileCard key={i} file={f} />)}
          </Accordion>
        </div>
      )}
    </div>
  );
}

// ─── MAIN CHATBOX COMPONENT ──────────────────────────────────────────────────

export default function ChatBox({ repoUrl, repoName, onReset }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      type: "text",
      content: `Repository [${repoName}] indexed successfully.\n\nPaste a GitHub issue URL for deep analysis, or ask anything about the codebase.`,
    },
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { role: "user", type: "text", content: userMsg }]);
    setInput("");
    setIsTyping(true);

    const isIssue = userMsg.includes("github.com") && userMsg.includes("/issues/");
    const endpoint = isIssue ? "/api/analyze-issue" : "/api/ask";
    const payload = isIssue
      ? { repo_url: repoUrl, issue_url: userMsg }
      : { repo_url: repoUrl, question: userMsg };

    try {
      const res = await fetch(`http://127.0.0.1:8000${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (isIssue) {
        setMessages(prev => [...prev, { role: "assistant", type: "issue_analysis", data }]);
      } else {
        setMessages(prev => [...prev, { role: "assistant", type: "qa_answer", data }]);
      }
    } catch {
      setMessages(prev => [...prev, {
        role: "assistant", type: "text",
        content: "[ERROR] Failed to reach backend. Check your connection.",
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <motion.div
      key="chat"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        width: "100vw", height: "100vh",
        display: "flex", flexDirection: "column",
        position: "relative", zIndex: 2,
        background: "rgba(0,5,1,0.93)",
      }}
    >
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "13px 28px",
        borderBottom: "1px solid rgba(0,255,65,0.1)",
        background: "rgba(0,12,3,0.9)",
        backdropFilter: "blur(10px)",
        flexShrink: 0,
        zIndex: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{
            border: "1px solid rgba(0,180,50,0.35)", borderRadius: 3,
            padding: "5px 10px", display: "flex", alignItems: "center", gap: 6,
            background: "rgba(0,180,50,0.06)",
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, color: "#00cc2e" }}>
              {repoName.toUpperCase()}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#00b432",
              boxShadow: "0 0 6px #00b432",
              display: "inline-block",
              animation: "blink 2s step-end infinite",
            }} />
            <span style={{ fontSize: 10, color: "#005015", letterSpacing: 2 }}>INDEX ACTIVE</span>
          </div>
        </div>
        <button
          onClick={onReset}
          style={{
            background: "transparent", border: "1px solid rgba(0,255,65,0.15)",
            borderRadius: 3, padding: "6px 14px", color: "#005015",
            fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
            cursor: "pointer", letterSpacing: 1, transition: "all 0.2s",
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = "#00b432"; e.currentTarget.style.color = "#00cc2e"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(0,255,65,0.15)"; e.currentTarget.style.color = "#005015"; }}
        >
          [SWITCH REPO]
        </button>
      </div>

      {/* Messages */}
      <div
        className="chat-scroll"
        style={{
          flex: 1, padding: "24px 28px 16px",
          display: "flex", flexDirection: "column", gap: 20,
          overflowX: "hidden",
        }}
      >
        {messages.map((msg, idx) => (
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            {msg.role === "assistant" && (
              <div style={{ display: "flex", flexDirection: "column", width: msg.type === "text" ? "auto" : "100%", maxWidth: msg.type === "text" ? "80%" : "100%", gap: 4 }}>
                <span style={{ fontSize: 10, color: "#005015", letterSpacing: 2, paddingLeft: 2 }}>
                  MENTOR@FIRSTPR $
                </span>
                {msg.type === "text" && (
                  <div style={{
                    background: "rgba(0,10,2,0.6)",
                    border: "1px solid rgba(0,200,50,0.12)",
                    borderRadius: "0 5px 5px 5px",
                    padding: "13px 17px",
                    boxShadow: "inset 0 0 30px rgba(0,0,0,0.4)",
                    position:"relative",
                    overflow:"hidden"
                  }}>
                    <div className="scanline-fast" />
                    <p style={{
                      whiteSpace: "pre-wrap", lineHeight: 1.8,
                      fontSize: 13, color: "#00dd33",
                      fontFamily: "'JetBrains Mono', monospace",
                      position:"relative", zIndex:1
                    }}>
                      {msg.content}
                    </p>
                  </div>
                )}
                {msg.type === "issue_analysis" && <IssueAnalysisCard data={msg.data} />}
                {msg.type === "qa_answer" && <QAAnswerCard data={msg.data} />}
              </div>
            )}

            {msg.role === "user" && (
              <div style={{ display: "flex", flexDirection: "column", maxWidth: "68%", gap: 4, alignItems: "flex-end" }}>
                <span style={{ fontSize: 10, color: "#004010", letterSpacing: 2, paddingRight: 2 }}>
                  YOU $
                </span>
                <div style={{
                  background: "transparent",
                  border: "1px solid rgba(0,160,45,0.35)",
                  borderRadius: "5px 0 5px 5px",
                  padding: "11px 15px",
                }}>
                  <p style={{
                    whiteSpace: "pre-wrap", lineHeight: 1.7,
                    fontSize: 13, color: "#31a400",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {msg.content}
                  </p>
                </div>
              </div>
            )}
          </motion.div>
        ))}

        {isTyping && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ display: "flex" }}>
            <div style={{
              border: "1px solid rgba(0,255,65,0.1)", borderRadius: "0 5px 5px 5px",
              padding: "13px 17px", display: "flex", alignItems: "center", gap: 5,
              background: "rgba(0,15,4,0.7)",
            }}>
              {[0, 150, 300].map((delay, i) => (
                <motion.span
                  key={i}
                  animate={{ opacity: [0.2, 1, 0.2], scaleY: [0.4, 1, 0.4] }}
                  transition={{ repeat: Infinity, duration: 0.9, delay: delay / 1000 }}
                  style={{
                    display: "inline-block", width: 3, height: 13,
                    background: "#00b432", boxShadow: "0 0 5px #00b432", borderRadius: 1,
                  }}
                />
              ))}
              <span style={{ fontSize: 11, color: "#026e1f", marginLeft: 8, letterSpacing: 1 }}>
                processing...
              </span>
            </div>
          </motion.div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{
        padding: "14px 28px 18px",
        borderTop: "1px solid rgba(0,255,65,0.1)",
        background: "rgba(0,8,2,0.95)",
        flexShrink: 0,
      }}>
        <form onSubmit={handleSendMessage}>
          <div style={{
            display: "flex", alignItems: "flex-end",
            border: "1px solid rgba(0,180,50,0.28)",
            borderRadius: 4,
            background: "rgba(0,15,4,0.6)",
            padding: "11px 13px", gap: 11,
            transition: "box-shadow 0.2s, border-color 0.2s",
          }}
            onFocusCapture={e => {
              e.currentTarget.style.borderColor = "rgba(0,180,50,0.5)";
              e.currentTarget.style.boxShadow = "0 0 0 1px rgba(0,150,40,0.1), inset 0 0 20px rgba(0,0,0,0.3)";
            }}
            onBlurCapture={e => {
              e.currentTarget.style.borderColor = "rgba(0,180,50,0.28)";
              e.currentTarget.style.boxShadow = "none";
            }}
          >
            <span style={{ color: "#005a15", fontSize: 13, paddingBottom: 1, flexShrink: 0 }}>▶</span>
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage(e);
                }
              }}
              placeholder="paste an issue URL or ask about the codebase..."
              className="terminal-input"
              style={{ fontSize: 13, lineHeight: 1.5, flex: 1 }}
            />
            <button
              type="submit"
              disabled={!input.trim() || isTyping}
              style={{
                background: input.trim() && !isTyping ? "rgba(0,180,50,0.85)" : "transparent",
                border: `1px solid ${input.trim() && !isTyping ? "rgba(0,180,50,0.6)" : "rgba(0,255,65,0.12)"}`,
                borderRadius: 3, width: 34, height: 34,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: input.trim() && !isTyping ? "pointer" : "not-allowed",
                flexShrink: 0, transition: "all 0.2s",
                boxShadow: input.trim() && !isTyping ? "0 0 10px rgba(0,150,40,0.25)" : "none",
              }}
            >
              <Send size={14} color={input.trim() && !isTyping ? "#000" : "#004010"} strokeWidth={2.5} />
            </button>
          </div>
          <div style={{ marginTop: 7, fontSize: 10, color: "#004010", letterSpacing: 0.5, paddingLeft: 2 }}>
            ENTER to send · SHIFT+ENTER for newline · paste github issue URL for deep analysis
          </div>
        </form>
      </div>
    </motion.div>
  );
}