import React, { useState, useCallback, useEffect } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

// Follow whichever host the page was served from: a tab on 127.0.0.1 calling
// localhost:8000 is a cross-origin request the browser may block outright.
const API = `http://${window.location.hostname || "localhost"}:8000`;

function SectionHeader({ number, title, subtitle }) {
  return (
    <div className="section-header">
      <div className="section-num">{number}</div>
      <div>
        <h2>{title}</h2>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
    </div>
  );
}

function Badge({ variant, children }) {
  return <span className={`badge badge--${variant}`}>{children}</span>;
}

// The Task Agent answers in markdown; bold is the only markup worth honouring
// here, and rendering it beats showing raw ** in the demo.
function Answer({ text }) {
  return (
    <div className="answer">
      {String(text).split(/\*\*(.+?)\*\*/gs).map((part, i) =>
        i % 2 ? <strong key={i}>{part}</strong> : part
      )}
    </div>
  );
}

async function downloadReleased(url) {
  const res = await fetch(`${API}${url}`);
  if (!res.ok) throw new Error(`Could not fetch ${url}`);
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = `redacted-${url.split("/").pop()}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

const isPdf = (name) => /\.pdf$/i.test(name || "");

function DocView({ src, name, className }) {
  if (!src) return <div className="compare-empty">Not available</div>;
  return isPdf(name)
    ? <embed src={src} type="application/pdf" className={`${className} doc-embed`} />
    : <img src={src} alt={name} className={className} />;
}

function actionVariant(action) {
  if (action === "keep") return "keep";
  if (action === "review") return "review";
  return "redact";
}

function App() {
  const [task, setTask] = useState("");
  const [files, setFiles] = useState([]);
  const [fileUrls, setFileUrls] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedTab, setSelectedTab] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    const urls = files.map(f => URL.createObjectURL(f));
    setFileUrls(urls);
    return () => urls.forEach(u => URL.revokeObjectURL(u));
  }, [files]);

  const addFiles = useCallback((incoming) => {
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name));
      const fresh = Array.from(incoming).filter(f => !names.has(f.name));
      return [...prev, ...fresh];
    });
  }, []);

  const removeFile = useCallback((i) => {
    setFiles(prev => prev.filter((_, idx) => idx !== i));
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  }, [addFiles]);

  async function analyze() {
    if (!files.length || !task.trim()) return;
    const form = new FormData();
    form.append("task", task.trim());
    files.forEach(f => form.append("files", f));
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetch(`${API}/api/analyze`, { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Analysis failed (HTTP ${res.status})`);
      setResult(data);
      setSelectedTab(0);
    } catch (err) {
      // A TypeError here means the request never reached the API at all.
      setError(
        err instanceof TypeError
          ? `Cannot reach the ContextGuard API at ${API}. Start the backend with: cd backend && uvicorn app.main:app --reload --port 8000`
          : err.message
      );
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocs(urls) {
    try {
      for (const url of urls) await downloadReleased(url);
    } catch (err) {
      setError(err.message);
    }
  }

  function originalForReleasedUrl(releasedUrl) {
    const name = releasedUrl.split("/").pop();
    const idx = files.findIndex(f => f.name === name);
    return { name, previewUrl: idx >= 0 ? fileUrls[idx] : null };
  }

  return (
    <div className={`workspace${result ? " has-results" : ""}`}>
      <header>
        <div className="logo">
          <div className="logo-mark">CG</div>
          <div>
            <div className="eyebrow">Multimodal Context Governance</div>
            <h1>ContextGuard</h1>
          </div>
        </div>
        <span className="header-tag">Privacy boundary active</span>
      </header>

      <div className="columns">
        <div className="col-left">
          {/* 1. Task */}
          <section className="card">
            <SectionHeader
              number="1"
              title="Task"
              subtitle="What should the downstream agent accomplish?"
            />
            <textarea
              value={task}
              onChange={e => setTask(e.target.value)}
              placeholder="e.g. Which item has the highest cost?"
              rows={4}
            />
          </section>

          {/* 2. Input Documents */}
          <section className="card">
            <SectionHeader
              number="2"
              title="Input Documents"
              subtitle="Upload images or documents."
            />
            <div
              className={`dropzone${dragOver ? " dragover" : ""}`}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => document.getElementById("file-input").click()}
            >
              <input
                id="file-input"
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp,application/pdf"
                hidden
                onChange={e => addFiles(e.target.files)}
              />
              <div className="dropzone-icon">↑</div>
              <div className="dropzone-text">
                Drop files here or <span className="link">browse</span>
              </div>
            </div>

            {files.length > 0 && (
              <div className="thumbs">
                {files.map((f, i) => (
                  <div key={i} className="thumb">
                    {isPdf(f.name)
                      ? <div className="thumb-pdf">PDF</div>
                      : <img src={fileUrls[i]} alt={f.name} />}
                    <div className="thumb-label">{f.name}</div>
                    <button
                      className="thumb-rm"
                      onClick={e => { e.stopPropagation(); removeFile(i); }}
                      title="Remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            <button
              className="btn-primary"
              onClick={analyze}
              disabled={busy || !files.length || !task.trim()}
            >
              {busy ? "Analyzing…" : "Analyze context"}
            </button>
            {!busy && (!files.length || !task.trim()) && (
              <p className="hint">
                {!task.trim() && !files.length
                  ? "Describe a task and add at least one image."
                  : !task.trim()
                    ? "Describe a task above to continue."
                    : "Add at least one image to continue."}
              </p>
            )}
            {error && <p className="error">{error}</p>}
          </section>
        </div>

        {result && (
          <div className="col-right">
            {result.mode === "local" && (
              <div className="mode-warning">
                <strong>Local fallback mode — Claude never ran.</strong>
                <span>
                  Privacy decisions and redaction are stubbed, so Released is
                  identical to Original. Set <code>CONTEXTGUARD_MODE=claude</code>{" "}
                  in <code>backend/.env</code> and <em>restart</em> uvicorn —{" "}
                  <code>--reload</code> watches <code>.py</code> files only and
                  will not pick up an <code>.env</code> change.
                </span>
              </div>
            )}

            {/* 3. Privacy Decisions */}
            <section className="card">
              <div className="card-top-row">
                <SectionHeader
                  number="3"
                  title="Privacy Decisions"
                  subtitle="Task-relative release plan."
                />
                <Badge variant="keep">Privacy Gate: {result.gate}</Badge>
              </div>

              {result.privacy_plan.documents.map(doc => (
                <div key={doc.document_id} className="doc-block">
                  <div className="doc-title-row">
                    <span className="doc-filename">{doc.document_id}</span>
                    <Badge variant={doc.document_required ? "keep" : "redact"}>
                      {doc.document_required ? "KEEP DOCUMENT" : "DROP DOCUMENT"}
                    </Badge>
                  </div>
                  {doc.reason && (
                    <p className="doc-reason">{doc.reason}</p>
                  )}
                  {doc.regions.length > 0 && (
                    <div className="regions">
                      {doc.regions.map((r, i) => (
                        <div key={i} className="region-row">
                          <span className="region-category">{r.category}</span>
                          <Badge variant={actionVariant(r.action)}>
                            {r.action.toUpperCase()}
                          </Badge>
                          <span className="region-reason">{r.reason}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </section>

            {/* 4. Released Context */}
            <section className="card">
              <div className="card-top-row">
                <SectionHeader
                  number="4"
                  title="Released Context"
                  subtitle="Exactly what the Task Agent can access."
                />
                {result.released_urls.length > 0 && (
                  <div className="download-actions">
                    <button
                      className="btn-secondary"
                      onClick={() => downloadDocs([result.released_urls[selectedTab]])}
                    >
                      Download redacted
                    </button>
                    {result.released_urls.length > 1 && (
                      <button
                        className="btn-secondary"
                        onClick={() => downloadDocs(result.released_urls)}
                      >
                        Download all ({result.released_urls.length})
                      </button>
                    )}
                  </div>
                )}
              </div>
              {result.withheld?.length > 0 && (
                <div className="withheld">
                  {result.withheld.map((w, i) => (
                    <div key={i} className="withheld-row">
                      <span className="doc-filename">{w.document_id}</span>
                      <Badge variant="redact">WITHHELD</Badge>
                      <span className="region-reason">{w.reason}</span>
                    </div>
                  ))}
                </div>
              )}
              {result.released_urls.length === 0 && (
                <p className="hint">No documents were released to the Task Agent.</p>
              )}
              {result.released_urls.length > 0 && (
                <>
                  {result.released_urls.length > 1 && (
                    <div className="tabs">
                      {result.released_urls.map((url, i) => (
                        <button
                          key={i}
                          className={`tab${selectedTab === i ? " active" : ""}`}
                          onClick={() => setSelectedTab(i)}
                        >
                          {url.split("/").pop()}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="compare">
                    {(() => {
                      const { name, previewUrl } = originalForReleasedUrl(
                        result.released_urls[selectedTab]
                      );
                      return (
                        <>
                          <div className="compare-pane">
                            <div className="pane-label">Original</div>
                            <DocView src={previewUrl} name={name} className="compare-img" />
                          </div>
                          <div className="compare-pane">
                            <div className="pane-label pane-label--released">Released</div>
                            <DocView
                              src={`${API}${result.released_urls[selectedTab]}`}
                              name={name}
                              className="compare-img"
                            />
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </>
              )}
            </section>

            {/* 5. Final Answer */}
            <section className="card">
              <div className="card-top-row">
                <SectionHeader number="5" title="Final Answer" />
                <Badge variant="keep">Answered from released context only</Badge>
              </div>
              <Answer text={result.final_answer} />
            </section>

            {/* 6. Agent Trace */}
            <details className="card trace">
              <summary>
                Agent Trace
                <span className="trace-mode">{result.mode} mode</span>
              </summary>
              <ol className="trace-list">
                <li>Privacy Agent inspected originals</li>
                <li>Privacy plan generated</li>
                <li>OCR localized text targets</li>
                <li>Redaction executed</li>
                <li>Policy gate passed</li>
                <li>Task Agent received released files only</li>
              </ol>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
