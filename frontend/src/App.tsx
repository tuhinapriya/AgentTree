import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

type AgentNode = {
  agent_id: string
  role: string
  parent_agent_id?: string | null
  status: string
  task_state?: string
  allowed_tools?: string[]
  branch_id?: string
  pid?: number | null
  exit_code?: number | null
}
type EventEntry = {
  event_seq?: number
  timestamp?: string
  agent_id?: string
  tool?: string
  type?: string
  decision?: string
  reason_code?: string
  detail?: string
  origin?: string
}
type Effect = {
  action_id: string
  branch_id: string
  tool: string
  arguments: Record<string, unknown>
  state: string
  created_at: string
}
type Branch = { branch_id: string; state: string; violation_count: number }
type BusinessState = {
  account: { customer_id: string; promo_credit_cents: number; version: number }
  order: { order_id: string; paid_cents: number; refunded_cents: number; version: number; status: string }
}
type DashboardPayload = {
  run_id: string
  hierarchy: { run_id: string; nodes?: AgentNode[]; agents?: AgentNode[]; edges?: Array<{ source: string; target: string }> }
  events: EventEntry[]
  effects?: { effects: Effect[]; branches: Branch[] }
  business_state?: BusinessState
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) throw new Error(`Request failed for ${path}: ${response.status}`)
  return (await response.json()) as T
}
const DEMO_RUN_FALLBACKS = ['agenttree-live-demo', 'agenttree-transactional-demo', 'run-demo-verify', 'run-demo-security', 'run-demo', 'demo-run']
const money = (cents: number) => `$${(cents / 100).toFixed(2)}`
const shortTime = (value?: string) => value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

function App() {
  const [runId, setRunId] = useState(DEMO_RUN_FALLBACKS[0])
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [selectedAgentId, setSelectedAgentId] = useState('parent-agent')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const runIdRef = useRef(runId)
  const requestInFlight = useRef(false)
  useEffect(() => { runIdRef.current = runId }, [runId])

  const loadDashboard = async (targetRunId: string = runIdRef.current, allowFallback = false, showLoading = false) => {
    if (requestInFlight.current) return
    const requestedRunId = targetRunId.trim()
    const candidates = allowFallback
      ? Array.from(new Set(requestedRunId ? [requestedRunId, ...DEMO_RUN_FALLBACKS.filter((id) => id !== requestedRunId)] : DEMO_RUN_FALLBACKS))
      : requestedRunId ? [requestedRunId] : []
    if (!candidates.length) { setError('Run ID is required.'); return }
    requestInFlight.current = true
    if (showLoading) setIsLoading(true)
    let lastError: string | null = null
    try {
      for (const candidate of candidates) {
        try {
          const payload = await fetchJson<DashboardPayload>(`/runs/${candidate}/dashboard`)
          setRunId(candidate)
          setDashboard(payload)
          const agents = payload.hierarchy.nodes ?? payload.hierarchy.agents ?? []
          if (agents.length && !agents.some((agent) => agent.agent_id === selectedAgentId)) setSelectedAgentId(agents[0].agent_id)
          setError(null)
          return
        } catch (e) { lastError = e instanceof Error ? e.message : 'Unable to load dashboard data.' }
      }
      setError(lastError ?? 'Unable to load dashboard data.')
    } finally {
      requestInFlight.current = false
      if (showLoading) setIsLoading(false)
    }
  }
  useEffect(() => { void loadDashboard(runIdRef.current, true, true) }, [])
  useEffect(() => {
    const timer = window.setInterval(() => { void loadDashboard(runIdRef.current) }, 1500)
    return () => window.clearInterval(timer)
  }, [])

  const agents = dashboard?.hierarchy.nodes ?? dashboard?.hierarchy.agents ?? []
  const selectedAgent = useMemo(() => agents.find((agent) => agent.agent_id === selectedAgentId) ?? agents[0] ?? null, [agents, selectedAgentId])
  const events = dashboard?.events ?? []
  const effects = dashboard?.effects?.effects ?? []
  const branches = dashboard?.effects?.branches ?? []
  const state = dashboard?.business_state
  const committed = effects.filter((effect) => effect.state === 'COMMITTED').length
  const pending = effects.filter((effect) => effect.state === 'STAGED').length
  const lastCommit = effects.filter((effect) => effect.state === 'COMMITTED').slice(-1)[0]
  const recentEvents = events.slice(-8).reverse()
  const runStatus = agents.length === 0 ? 'NOT STARTED' : agents.some((agent) => agent.status === 'RUNNING') ? 'ACTIVE' : agents.every((agent) => ['STOPPED', 'FAILED'].includes(agent.status)) ? 'STOPPED' : 'MONITORING'

  const handleStopBranch = async (agentId: string) => {
    setPendingAction(`stop:${agentId}`)
    try {
      await fetchJson(`/runs/${runIdRef.current}/branches/${agentId}/stop`, { method: 'POST' })
      await loadDashboard(runIdRef.current)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to stop branch.') }
    finally { setPendingAction(null) }
  }
  const handleResetDemo = async () => {
    setPendingAction('reset')
    try {
      await fetchJson(`/runs/${runIdRef.current}/demo/reset`, { method: 'POST' })
      await loadDashboard(runIdRef.current)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to reset demo.') }
    finally { setPendingAction(null) }
  }
  const handleStartRun = async () => {
    const id = runIdRef.current.trim()
    if (!id) { setError('Run ID is required.'); return }
    setPendingAction('start')
    try {
      await fetchJson(`/runs`, { method: 'POST', body: JSON.stringify({ run_id: id, scenario: 'customer-operations' }) })
      const agents = [
        { agent_id: 'parent-agent', role: 'parent', parent_agent_id: null, allowed_tools: [] },
        { agent_id: 'order-agent', role: 'order', parent_agent_id: 'parent-agent', allowed_tools: ['read_order', 'stage_refund', 'read_orders', 'process_order'] },
        { agent_id: 'account-agent', role: 'account', parent_agent_id: 'parent-agent', allowed_tools: ['read_account', 'stage_promo_credit'] },
      ]
      for (const agent of agents) await fetchJson(`/runs/${id}/agents`, { method: 'POST', body: JSON.stringify(agent) })
      await fetchJson(`/runs/${id}/supervise`, { method: 'POST', body: JSON.stringify({ agent_ids: agents.map((agent) => agent.agent_id) }) })
      await loadDashboard(id)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to start run.') }
    finally { setPendingAction(null) }
  }
  const handleReleaseBranch = async (branchId: string) => {
    setPendingAction(`release:${branchId}`)
    try {
      await fetchJson(`/runs/${runIdRef.current}/branches/${branchId}/complete`, { method: 'POST' })
      const result = await fetchJson<{ state: string }>(`/runs/${runIdRef.current}/branches/${branchId}/commit`, { method: 'POST' })
      await loadDashboard(runIdRef.current)
      setError(result.state === 'COMMITTED' ? null : `Branch release finished with state ${result.state}.`)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to release branch.') }
    finally { setPendingAction(null) }
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><div className="brand-mark">A</div><div><p className="eyebrow">AgentTree / Runtime security</p><h1>Execution Control</h1></div></div>
      <div className="toolbar">
        <label className="run-input"><span>ACTIVE RUN</span><input aria-label="Run ID" value={runId} onChange={(e) => setRunId(e.target.value)} /></label>
        <button type="button" onClick={() => void loadDashboard(runId, false, true)} disabled={isLoading || pendingAction !== null}>{isLoading ? 'Refreshing…' : 'Refresh'}</button>
        {agents.length === 0 && <button type="button" onClick={() => void handleStartRun()} disabled={pendingAction !== null}>{pendingAction === 'start' ? 'Starting…' : 'Start run'}</button>}
        <button type="button" className="secondary" onClick={() => void handleResetDemo()}>Reset demo</button>
      </div>
    </header>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}

    <section className="summary-strip" aria-label="Run summary">
      <div><span className="summary-label">RUN STATUS</span><strong>{runStatus === 'ACTIVE' && <i className="live-dot" />}{runStatus}</strong></div>
      <div><span className="summary-label">AGENTS</span><strong>{agents.length.toString().padStart(2, '0')} <small>in hierarchy</small></strong></div>
      <div><span className="summary-label">PENDING EFFECTS</span><strong>{pending.toString().padStart(2, '0')} <small>staged</small></strong></div>
      <div><span className="summary-label">COMMITTED</span><strong>{committed.toString().padStart(2, '0')} <small>effects</small></strong></div>
      <div className="sequence"><span className="summary-label">LATEST EVENT</span><strong>#{Math.max(0, ...events.map((event) => event.event_seq ?? 0)).toString().padStart(4, '0')}</strong></div>
    </section>

    <main className="content-grid">
      <section className="panel hierarchy-panel">
        <div className="panel-header"><div><p className="section-kicker">TOPOLOGY</p><h2>Agent hierarchy</h2></div><span className="count-pill">{agents.length} agents</span></div>
        <div className="tree-list">{agents.length === 0 ? <p className="empty-state">No agents available for this run yet.</p> : agents.map((agent) => {
          const branch = branches.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
          return <button key={agent.agent_id} type="button" className={`tree-node ${selectedAgent?.agent_id === agent.agent_id ? 'active' : ''}`} onClick={() => setSelectedAgentId(agent.agent_id)}>
            <span className="node-icon">{agent.role.slice(0, 1).toUpperCase()}</span><span className="node-copy"><span className="node-role">{agent.role}</span><span className="node-id">{agent.agent_id}</span></span>
            <span className="node-meta">{branch?.state ?? agent.task_state ?? ''}</span><span className={`node-status ${agent.status.toLowerCase()}`}>{agent.status}</span>
          </button>
        })}</div>
        <div className="panel-subhead"><span>BRANCH CONTROL</span><span>Persistent state</span></div>
        <div className="branch-list">{branches.length ? branches.map((branch) => <div className="branch-row" key={branch.branch_id}><span>{branch.branch_id}</span><strong className={`state-${branch.state.toLowerCase()}`}>{branch.state.replaceAll('_', ' ')}</strong>{branch.violation_count > 0 && <small>{branch.violation_count} violation{branch.violation_count > 1 ? 's' : ''}</small>}</div>) : <p className="empty-state compact">Branch state appears when agents are registered.</p>}</div>
      </section>

      <aside className="panel details-panel">
        <div className="panel-header"><div><p className="section-kicker">IDENTITY & SCOPE</p><h2>Agent details</h2></div>{selectedAgent && <span className="count-pill">{selectedAgent.role}</span>}</div>
        {selectedAgent ? <>
          <div className="identity-card"><span className="identity-icon">{selectedAgent.role.slice(0, 1).toUpperCase()}</span><div><strong>{selectedAgent.agent_id}</strong><span>{selectedAgent.parent_agent_id ? `Reports to ${selectedAgent.parent_agent_id}` : 'Root coordinator'}</span></div></div>
          <div className="detail-grid"><div className="detail-block"><p className="label">PROCESS</p><strong>{selectedAgent.pid ? `PID ${selectedAgent.pid}` : '—'}</strong></div><div className="detail-block"><p className="label">EXIT CODE</p><strong>{selectedAgent.exit_code ?? '—'}</strong></div><div className="detail-block"><p className="label">TASK STATE</p><strong>{(selectedAgent.task_state ?? '—').replaceAll('_', ' ')}</strong></div><div className="detail-block"><p className="label">STATUS</p><strong>{selectedAgent.status}</strong></div></div>
          <div className="detail-block"><p className="label">AUTHORIZED TOOLS</p><div className="tool-tags">{(selectedAgent.allowed_tools ?? []).map((tool) => <span key={tool}>{tool}</span>)}</div></div>
          <div className="action-stack"><button type="button" onClick={() => void handleStopBranch(selectedAgent.agent_id)} disabled={pendingAction !== null || ['STOPPED', 'FAILED'].includes(selectedAgent.status)}>{pendingAction === `stop:${selectedAgent.agent_id}` ? 'Containing…' : 'Contain branch'}</button><button type="button" className="secondary" onClick={() => void handleResetDemo()} disabled={pendingAction !== null}>{pendingAction === 'reset' ? 'Resetting…' : 'Reset run'}</button></div>
          {effects.some((effect) => effect.branch_id === selectedAgent.agent_id && effect.state === 'STAGED') && <button type="button" className="release-button" onClick={() => void handleReleaseBranch(selectedAgent.agent_id)} disabled={pendingAction !== null || selectedAgent.status !== 'RUNNING'}>{pendingAction === `release:${selectedAgent.agent_id}` ? 'Committing…' : 'Mark complete & commit staged work'}</button>}
        </> : <p className="empty-state">Select an agent to inspect its runtime state.</p>}
      </aside>
    </main>

    <section className="panel transaction-panel">
      <div className="panel-header"><div><p className="section-kicker">CONTROLLED BUSINESS STATE</p><h2>Transactional effects</h2></div><span className="truth-label">Authoritative · persisted journal + database</span></div>
      <div className="business-grid"><div className="business-card"><div className="business-title"><span className="resource-icon">ORD</span><div><strong>Order {state?.order.order_id ?? 'ORD-882'}</strong><span>Refund balance</span></div></div><div className="money-row"><div><small>REFUNDED</small><strong>{money(state?.order.refunded_cents ?? 0)}</strong></div><div><small>PAID</small><strong>{money(state?.order.paid_cents ?? 0)}</strong></div><span className="status-chip">{state?.order.status ?? 'PENDING'}</span></div></div>
        <div className="business-card"><div className="business-title"><span className="resource-icon account">ACC</span><div><strong>Account {state?.account.customer_id ?? 'C104'}</strong><span>Promotional credit</span></div></div><div className="money-row"><div><small>COMMITTED CREDIT</small><strong>{money(state?.account.promo_credit_cents ?? 0)}</strong></div><div><small>VERSION</small><strong>{state?.account.version ?? 0}</strong></div><span className="status-chip">LIVE</span></div></div></div>
      <div className="effects-table"><div className="effect-head"><span>EFFECT</span><span>BRANCH</span><span>AMOUNT</span><span>STATE</span><span>CREATED</span></div>{effects.length ? effects.map((effect) => <div className="effect-row" key={effect.action_id}><span><strong>{effect.tool.replaceAll('_', ' ')}</strong><small>{effect.action_id.slice(0, 12)}</small></span><span>{effect.branch_id}</span><span>{money(Number(effect.arguments.amount_cents ?? 0))}</span><span className={`effect-state ${effect.state.toLowerCase()}`}>{effect.state}</span><span>{shortTime(effect.created_at)}</span></div>) : <div className="empty-state effect-empty">No pending or resolved effects yet. Authorized state changes first appear as staged journal entries.</div>}</div>
      {lastCommit && <div className="commit-receipt"><span className="receipt-check">✓</span><div><small>COMMIT RECEIPT · {lastCommit.action_id.slice(0, 12)}</small><strong>{lastCommit.tool.replaceAll('_', ' ')} · {money(Number(lastCommit.arguments.amount_cents ?? 0))}</strong><span>Branch {lastCommit.branch_id} · action staged {shortTime(lastCommit.created_at)} · committed state confirmed in journal</span></div><b>COMMITTED</b></div>}
    </section>

    <section className="bottom-grid">
      <div className="panel"><div className="panel-header"><div><p className="section-kicker">AUDIT TRAIL</p><h2>Authorization events</h2></div><span className="count-pill">{events.length} events</span></div>
        <ul className="event-list">{events.length === 0 ? <li className="empty-state">No authorization events recorded yet.</li> : recentEvents.map((event, index) => <li key={event.event_seq ?? `${event.agent_id}-${index}`}><div className="event-row"><span className={`event-tag ${(event.decision ?? 'info').toLowerCase()}`}>{event.decision ?? event.type ?? 'INFO'}</span><strong>{event.agent_id ?? 'system'}</strong><span>{event.tool ?? 'runtime'}</span>{event.origin && <span className="origin-tag">{event.origin.replaceAll('_', ' ')}</span>}</div><p>{event.detail ?? event.reason_code ?? 'No additional detail'}</p><small>{shortTime(event.timestamp)}{event.event_seq ? ` · #${event.event_seq}` : ''}</small></li>)}</ul>
      </div>
      <div className="panel"><div className="panel-header"><div><p className="section-kicker">RUNTIME FEED</p><h2>Recent activity</h2></div><span className="live-indicator"><i className="live-dot" />Persisted snapshot · 1.5s</span></div>
        <ul className="activity-list">{events.length === 0 ? <li className="empty-state">Activity will appear as events are recorded.</li> : recentEvents.map((event, index) => <li key={`activity-${event.event_seq ?? index}`}><span className="time">{shortTime(event.timestamp)}</span><strong>{event.agent_id ?? 'system'}</strong><span>{event.type ?? event.decision ?? 'activity'}</span><em>{event.origin ?? ''}</em></li>)}</ul>
      </div>
    </section>
    <footer className="footer-note"><span>AGENTTREE TRANSACTIONAL HARNESS</span><span>{dashboard?.run_id ?? runId} · Refresh reconstructs state from backend records</span></footer>
  </div>
}
export default App
