import { useState, useEffect, useRef } from 'react'

const API_BASE = '/api'

// API helpers
async function fetchApi(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || 'Request failed')
  }
  return res.json()
}

function App() {
  const [view, setView] = useState('setup') // setup, interview
  const [studies, setStudies] = useState([])
  const [selectedStudy, setSelectedStudy] = useState(null)
  const [rubric, setRubric] = useState(null)
  const [interview, setInterview] = useState(null)
  const [messages, setMessages] = useState([])
  const [interviewState, setInterviewState] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showProbing, setShowProbing] = useState(true)

  // Load studies
  useEffect(() => {
    loadStudies()
  }, [])

  async function loadStudies() {
    try {
      const data = await fetchApi('/studies')
      setStudies(data)
    } catch (err) {
      setError(err.message)
    }
  }

  async function selectStudy(study) {
    setSelectedStudy(study)
    setRubric(null)
    setError(null)

    // Load rubrics
    try {
      const rubrics = await fetchApi(`/studies/${study.id}/rubrics`)
      const active = rubrics.find(r => r.is_active)
      if (active) {
        const detail = await fetchApi(`/rubrics/${active.id}`)
        setRubric(detail)
      }
    } catch (err) {
      setError(err.message)
    }
  }

  async function generateRubric() {
    if (!selectedStudy) return
    setLoading(true)
    setError(null)

    try {
      const data = await fetchApi(`/studies/${selectedStudy.id}/rubrics/generate`, {
        method: 'POST',
      })
      setRubric(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function approveRubric() {
    if (!rubric) return
    setLoading(true)
    setError(null)

    try {
      const data = await fetchApi(`/rubrics/${rubric.id}/approve`, {
        method: 'POST',
      })
      setRubric(data)
      loadStudies() // Refresh study list
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function startInterview(participantId) {
    if (!selectedStudy || !rubric?.is_approved) return
    setLoading(true)
    setError(null)

    try {
      const data = await fetchApi(`/studies/${selectedStudy.id}/interviews`, {
        method: 'POST',
        body: JSON.stringify({ participant_id: participantId }),
      })
      setInterview({ id: data.interview_id, status: data.status })
      setMessages(data.messages)
      setView('interview')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Anthropic Interviewer</h1>
        <p>AI-powered qualitative research interviews</p>
      </header>

      {error && <div className="error">{error}</div>}

      {view === 'setup' && (
        <SetupView
          studies={studies}
          selectedStudy={selectedStudy}
          rubric={rubric}
          loading={loading}
          onSelectStudy={selectStudy}
          onGenerateRubric={generateRubric}
          onApproveRubric={approveRubric}
          onStartInterview={startInterview}
          onRefresh={loadStudies}
        />
      )}

      {view === 'interview' && interview && (
        <InterviewView
          interview={interview}
          messages={messages}
          setMessages={setMessages}
          interviewState={interviewState}
          setInterviewState={setInterviewState}
          showProbing={showProbing}
          setShowProbing={setShowProbing}
          onEnd={() => {
            setView('setup')
            setInterview(null)
            setMessages([])
            loadStudies()
          }}
        />
      )}
    </div>
  )
}

function SetupView({
  studies,
  selectedStudy,
  rubric,
  loading,
  onSelectStudy,
  onGenerateRubric,
  onApproveRubric,
  onStartInterview,
  onRefresh,
}) {
  const [showCreate, setShowCreate] = useState(false)
  const [participantId, setParticipantId] = useState('')

  return (
    <>
      {/* Study Selection */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2>Select Study</h2>
          <div>
            <button className="btn btn-secondary" onClick={onRefresh} style={{ marginRight: 8 }}>
              Refresh
            </button>
            <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
              {showCreate ? 'Cancel' : 'New Study'}
            </button>
          </div>
        </div>

        {showCreate && (
          <CreateStudyForm
            onCreated={(study) => {
              setShowCreate(false)
              onRefresh()
              onSelectStudy(study)
            }}
          />
        )}

        <div className="study-list">
          {studies.length === 0 && <p style={{ color: '#666' }}>No studies yet. Create one to get started.</p>}
          {studies.map(study => (
            <div
              key={study.id}
              className={`study-item ${selectedStudy?.id === study.id ? 'selected' : ''}`}
              onClick={() => onSelectStudy(study)}
            >
              <div>
                <h4>{study.name}</h4>
                <div className="meta">
                  {study.research_goals.length} goals | {study.interview_count} interviews | {study.target_duration_minutes} min
                </div>
              </div>
              <span className={`badge ${study.status === 'active' ? 'badge-active' : 'badge-draft'}`}>
                {study.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Rubric */}
      {selectedStudy && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2>Interview Rubric</h2>
            {!rubric && (
              <button className="btn btn-primary" onClick={onGenerateRubric} disabled={loading}>
                {loading ? 'Generating...' : 'Generate Rubric'}
              </button>
            )}
            {rubric && !rubric.is_approved && (
              <button className="btn btn-success" onClick={onApproveRubric} disabled={loading}>
                {loading ? 'Approving...' : 'Approve Rubric'}
              </button>
            )}
          </div>

          {loading && !rubric && <div className="loading">Generating rubric with AI...</div>}

          {rubric && (
            <>
              <div style={{ marginBottom: 16 }}>
                <strong>{rubric.title}</strong>
                <span className={`badge ${rubric.is_approved ? 'badge-active' : 'badge-draft'}`} style={{ marginLeft: 8 }}>
                  {rubric.is_approved ? 'Approved' : 'Draft'}
                </span>
              </div>

              {rubric.sections.map((section, i) => (
                <div key={i} className="rubric-section">
                  <h4>{section.name}</h4>
                  {section.purpose && <p className="purpose">{section.purpose}</p>}
                  {section.questions.map((q, j) => (
                    <div key={j} className="question-item">
                      <span className="q-id">{q.question_id}</span>
                      {q.text}
                      {q.probes.length > 0 && (
                        <ul className="probes">
                          {q.probes.map((probe, k) => (
                            <li key={k}>{probe}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Start Interview */}
      {selectedStudy && rubric?.is_approved && (
        <div className="card">
          <h2>Start Interview</h2>
          <div className="form-group">
            <label>Participant ID</label>
            <input
              type="text"
              value={participantId}
              onChange={(e) => setParticipantId(e.target.value)}
              placeholder="e.g., P001"
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={() => onStartInterview(participantId)}
            disabled={!participantId || loading}
          >
            {loading ? 'Starting...' : 'Start Interview'}
          </button>
        </div>
      )}
    </>
  )
}

function CreateStudyForm({ onCreated }) {
  const [name, setName] = useState('')
  const [goals, setGoals] = useState('')
  const [population, setPopulation] = useState('')
  const [duration, setDuration] = useState(15)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const study = await fetchApi('/studies', {
        method: 'POST',
        body: JSON.stringify({
          name,
          research_goals: goals.split('\n').filter(g => g.trim()),
          target_population: population,
          target_duration_minutes: duration,
        }),
      })
      onCreated(study)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginBottom: 20, padding: 16, background: '#f9f9f9', borderRadius: 8 }}>
      {error && <div className="error">{error}</div>}
      <div className="form-group">
        <label>Study Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="form-group">
        <label>Research Goals (one per line)</label>
        <textarea value={goals} onChange={(e) => setGoals(e.target.value)} required />
      </div>
      <div className="form-group">
        <label>Target Population</label>
        <input value={population} onChange={(e) => setPopulation(e.target.value)} required />
      </div>
      <div className="form-group">
        <label>Target Duration (minutes)</label>
        <input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))} min={5} max={60} />
      </div>
      <button type="submit" className="btn btn-success" disabled={loading}>
        {loading ? 'Creating...' : 'Create Study'}
      </button>
    </form>
  )
}

function InterviewView({
  interview,
  messages,
  setMessages,
  interviewState,
  setInterviewState,
  showProbing,
  setShowProbing,
  onEnd,
}) {
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage() {
    if (!input.trim() || loading || isComplete) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'participant', content: userMessage }])
    setLoading(true)

    try {
      const data = await fetchApi(`/interviews/${interview.id}/respond`, {
        method: 'POST',
        body: JSON.stringify({ message: userMessage }),
      })

      setMessages(prev => [
        ...prev,
        {
          role: 'interviewer',
          content: data.message,
          probe_decision: data.probe_decision,
        },
      ])

      if (data.is_complete) {
        setIsComplete(true)
      }

      // Update state if available
      if (data.state) {
        setInterviewState(data.state)
      }
    } catch (err) {
      // Check if interview ended
      if (err.message.includes('not in progress')) {
        setIsComplete(true)
        setMessages(prev => [...prev, {
          role: 'interviewer',
          content: 'Thank you for participating in this interview. The session has ended.'
        }])
      } else {
        // Remove the user message that failed
        setMessages(prev => prev.slice(0, -1))
        setMessages(prev => [...prev, { role: 'system', content: `Error: ${err.message}. Please try again.` }])
      }
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  async function endInterview() {
    setLoading(true)
    try {
      const data = await fetchApi(`/interviews/${interview.id}/end`, { method: 'POST' })
      // Add the closing message to the chat
      setMessages(prev => [...prev, {
        role: 'interviewer',
        content: data.message,
      }])
      setIsComplete(true)
    } catch (err) {
      console.error(err)
      // Still mark as complete if it fails (interview may already be ended)
      setIsComplete(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="chat-container">
        <div className="chat-header" style={isComplete ? { background: '#34c759' } : {}}>
          <h3>{isComplete ? 'Interview Complete' : 'Interview in Progress'}</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <input
                type="checkbox"
                checked={showProbing}
                onChange={(e) => setShowProbing(e.target.checked)}
              />
              Show probing analysis
            </label>
            {!isComplete && (
              <button className="btn btn-secondary" onClick={endInterview} disabled={loading}>
                {loading ? 'Ending...' : 'End Interview'}
              </button>
            )}
            {isComplete && (
              <button className="btn btn-primary" onClick={onEnd}>
                Back to Setup
              </button>
            )}
          </div>
        </div>

        <div className="chat-messages">
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              <div className="message-label">
                {msg.role === 'interviewer' ? 'Interviewer' : 'You'}
              </div>
              <div className="message-bubble">{msg.content}</div>
              {showProbing && msg.probe_decision && (
                <div className="probe-info">
                  <div className="action">
                    Action: {msg.probe_decision.action}
                  </div>
                  <div className="reasoning">
                    {msg.probe_decision.reasoning}
                  </div>
                  {msg.probe_decision.signals?.length > 0 && (
                    <div style={{ marginTop: 4, fontSize: 11 }}>
                      Signals: {msg.probe_decision.signals.map(s => s.type).join(', ')}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="message interviewer">
              <div className="message-label">Interviewer</div>
              <div className="message-bubble" style={{ opacity: 0.6 }}>
                Thinking...
              </div>
            </div>
          )}
          {isComplete && (
            <div style={{
              textAlign: 'center',
              padding: '20px',
              margin: '20px 0',
              background: '#d4edda',
              borderRadius: '8px',
              color: '#155724',
            }}>
              <strong>Interview Complete</strong>
              <p style={{ margin: '8px 0 0', fontSize: '14px' }}>
                Thank you for your participation. You can now close this window or return to setup.
              </p>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isComplete ? 'Interview complete' : 'Type your response...'}
            disabled={loading || isComplete}
          />
          <button
            className="btn btn-primary"
            onClick={sendMessage}
            disabled={!input.trim() || loading || isComplete}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
