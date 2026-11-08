import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

type AgentNode = {
  agent_id: string
  role: string
  parent_agent_id?: string | null
  status: string
  allowed_tools?: string[]
  branch_id?: string
}

type EventEntry = {
  timestamp?: string
  agent_id?: string
  tool?: string
  type?: string
  decision?: string
  reason_code?: string
  detail?: string
  origin?: string
}

type DashboardPayload = {
  run_id: string
  hierarchy: {
    run_id: string
    nodes?: AgentNode[]
    agents?: AgentNode[]
    edges?: Array<{ source: string; target: string }>
  }
  events: EventEntry[]
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`)
  }

  return (await response.json()) as T
}

const DEMO_RUN_FALLBACKS = ['run-demo-verify', 'run-demo-security', 'run-demo', 'demo-run']

function App() {
  const [runId, setRunId] = useState(DEMO_RUN_FALLBACKS[0])
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [selectedAgentId, setSelectedAgentId] = useState('parent-agent')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const runIdRef = useRef(runId)

  useEffect(() => {
    runIdRef.current = runId
  }, [runId])

  const loadDashboard = async (targetRunId: string = runIdRef.current) => {
    const requestedRunId = targetRunId.trim()
    const candidateRunIds = Array.from(
      new Set(
        requestedRunId ? [requestedRunId, ...DEMO_RUN_FALLBACKS.filter((candidate) => candidate !== requestedRunId)] : DEMO_RUN_FALLBACKS,
      ),
    )

    if (candidateRunIds.length === 0) {
      setError('Run ID is required.')
      return
    }

    setIsLoading(true)

    let lastError: string | null = null

    try {
      for (const candidateRunId of candidateRunIds) {
        try {
          const payload = await fetchJson<DashboardPayload>(`/runs/${candidateRunId}/dashboard`)
          setRunId(candidateRunId)
          setDashboard(payload)
          const hierarchyNodes = payload.hierarchy.nodes ?? payload.hierarchy.agents ?? []
          if (hierarchyNodes.length > 0 && !hierarchyNodes.some((agent) => agent.agent_id === selectedAgentId)) {
            setSelectedAgentId(hierarchyNodes[0].agent_id)
          }
          setError(null)
          return
        } catch (requestError) {
          lastError = requestError instanceof Error ? requestError.message : 'Unable to load dashboard data.'
        }
      }

      setError(lastError ?? 'Unable to load dashboard data.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void loadDashboard()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadDashboard(runIdRef.current)
    }, 5000)

    return () => window.clearInterval(timer)
  }, [])

  const nodes = dashboard?.hierarchy.nodes ?? dashboard?.hierarchy.agents ?? []
  const selectedAgent = useMemo(
    () => nodes.find((agent) => agent.agent_id === selectedAgentId) ?? nodes[0] ?? null,
    [nodes, selectedAgentId],
  )

  const events = dashboard?.events ?? []

  const handleStopBranch = async (agentId: string) => {
    try {
      await fetchJson<{ run_id: string; branch_id: string; status: string }>(`/runs/${runIdRef.current}/branches/${agentId}/stop`, {
        method: 'POST',
      })
      await loadDashboard(runIdRef.current)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to stop branch.')
    }
  }

  const handleResetDemo = async () => {
    try {
      await fetchJson<{ run_id: string; status: string }>(`/runs/${runIdRef.current}/demo/reset`, {
        method: 'POST',
      })
      await loadDashboard(runIdRef.current)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to reset demo.')
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AgentTree</p>
          <h1>Command Center</h1>
        </div>

        <div className="toolbar">
          <label className="run-input">
            <span>Run ID</span>
            <input
              aria-label="Run ID"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
            />
          </label>
          <button type="button" onClick={() => void loadDashboard(runId)}>
            Refresh
          </button>
          <button type="button" className="secondary" onClick={() => void handleResetDemo()}>
            Reset demo
          </button>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}
      {isLoading ? <div className="status-banner">Loading dashboard…</div> : null}

      <main className="content-grid">
        <section className="panel hierarchy-panel">
          <div className="panel-header">
            <h2>Agent hierarchy</h2>
            <span>{nodes.length} agents</span>
          </div>

          <div className="tree-list">
            {nodes.length === 0 ? (
              <p className="empty-state">No agents available for this run yet.</p>
            ) : (
              nodes.map((agent) => (
                <button
                  key={agent.agent_id}
                  type="button"
                  className={`tree-node ${selectedAgent?.agent_id === agent.agent_id ? 'active' : ''}`}
                  onClick={() => setSelectedAgentId(agent.agent_id)}
                >
                  <span className="node-role">{agent.role}</span>
                  <span className="node-id">{agent.agent_id}</span>
                  <span className={`node-status ${agent.status.toLowerCase()}`}>{agent.status}</span>
                </button>
              ))
            )}
          </div>
        </section>

        <aside className="panel details-panel">
          <div className="panel-header">
            <h2>Agent details</h2>
            {selectedAgent ? <span>{selectedAgent.role}</span> : null}
          </div>

          {selectedAgent ? (
            <>
              <div className="detail-block">
                <p className="label">Agent ID</p>
                <strong>{selectedAgent.agent_id}</strong>
              </div>
              <div className="detail-block">
                <p className="label">Status</p>
                <strong>{selectedAgent.status}</strong>
              </div>
              <div className="detail-block">
                <p className="label">Permissions</p>
                <div className="tool-tags">
                  {(selectedAgent.allowed_tools ?? ['read_orders', 'process_order']).map((tool) => (
                    <span key={tool}>{tool}</span>
                  ))}
                </div>
              </div>

              <div className="action-stack">
                <button type="button" onClick={() => void handleStopBranch(selectedAgent.agent_id)}>
                  Stop branch
                </button>
                <button type="button" className="secondary" onClick={() => void handleResetDemo()}>
                  Reset demo
                </button>
              </div>
            </>
          ) : (
            <p className="empty-state">Select an agent to inspect it.</p>
          )}
        </aside>
      </main>

      <section className="bottom-grid">
        <div className="panel">
          <div className="panel-header">
            <h2>Authorization events</h2>
            <span>{events.length} total</span>
          </div>

          <ul className="event-list">
            {events.length === 0 ? (
              <li className="empty-state">No authorization events recorded yet.</li>
            ) : (
              events.slice(0, 6).map((event, index) => (
                <li key={`${event.agent_id ?? 'event'}-${event.tool ?? 'tool'}-${index}`}>
                  <div className="event-row">
                    <span className="event-tag">{event.decision ?? 'INFO'}</span>
                    <strong>{event.agent_id ?? 'system'}</strong>
                    <span>{event.tool ?? 'run'}</span>
                  </div>
                  <p>{event.detail ?? event.reason_code ?? 'No additional detail'}</p>
                </li>
              ))
            )}
          </ul>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>Live activity</h2>
            <span>Realtime</span>
          </div>

          <ul className="activity-list">
            {events.length === 0 ? (
              <li className="empty-state">Stream is idle.</li>
            ) : (
              events.slice(0, 5).map((event, index) => (
                <li key={`activity-${event.agent_id ?? 'activity'}-${index}`}>
                  <span className="time">{event.timestamp ?? 'now'}</span>
                  <strong>{event.agent_id ?? 'system'}</strong>
                  <span>{event.type ?? event.decision ?? 'activity'}</span>
                </li>
              ))
            )}
          </ul>
        </div>
      </section>
    </div>
  )
}

export default App
