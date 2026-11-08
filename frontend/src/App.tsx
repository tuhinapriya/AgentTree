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
  process_create_time?: string | null
  stopped_at?: string | null
  children?: AgentNode[]
}
type EventEntry = {
  event_seq?: number
  timestamp?: string
  agent_id?: string
  branch_id?: string | null
  tool?: string
  type?: string
  decision?: string
  reason_code?: string
  detail?: string
  origin?: string
  payload?: Record<string, unknown>
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
type TimelineItem = { at: string; title: string; detail: string; state: string; agent?: string }
type BusinessState = {
  account: { customer_id: string; promo_credit_cents: number; version: number }
  order: { order_id: string; paid_cents: number; refunded_cents: number; version: number; status: string }
}
type DashboardPayload = {
  run_id: string
  run?: { run_id: string; scenario: string; status: string; created_at: string }
  hierarchy: { run_id: string; tree?: AgentNode[]; nodes?: AgentNode[]; agents?: AgentNode[]; edges?: Array<{ source: string; target: string }> }
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
const fullTime = (value?: string) => value ? new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' }) : 'Time unavailable'

function App() {
  const [runId, setRunId] = useState(DEMO_RUN_FALLBACKS[0])
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const runIdRef = useRef(runId)
  const requestInFlight = useRef(false)
  useEffect(() => { runIdRef.current = runId }, [runId])

  const loadDashboard = async (targetRunId: string = runIdRef.current, allowFallback = false) => {
    if (requestInFlight.current) return
    const requestedRunId = targetRunId.trim()
    const candidates = allowFallback
      ? Array.from(new Set(requestedRunId ? [requestedRunId, ...DEMO_RUN_FALLBACKS.filter((id) => id !== requestedRunId)] : DEMO_RUN_FALLBACKS))
      : requestedRunId ? [requestedRunId] : []
    if (!candidates.length) { setError('Run ID is required.'); return }
    requestInFlight.current = true
    let lastError: string | null = null
    try {
      for (const candidate of candidates) {
        try {
          const payload = await fetchJson<DashboardPayload>(`/runs/${candidate}/dashboard`)
          setRunId(candidate)
          setDashboard(payload)
          setError(null)
          return
        } catch (e) { lastError = e instanceof Error ? e.message : 'Unable to load dashboard data.' }
      }
      setError(lastError ?? 'Unable to load dashboard data.')
    } finally {
      requestInFlight.current = false
    }
  }
  useEffect(() => { void loadDashboard(runIdRef.current, true) }, [])
  useEffect(() => {
    const timer = window.setInterval(() => { void loadDashboard(runIdRef.current) }, 1500)
    return () => window.clearInterval(timer)
  }, [])

  const agents = dashboard?.hierarchy.nodes ?? dashboard?.hierarchy.agents ?? []
  const roots = dashboard?.hierarchy.tree ?? agents.filter((agent) => !agent.parent_agent_id)
  const events = dashboard?.events ?? []
  const effects = dashboard?.effects?.effects ?? []
  const branches = dashboard?.effects?.branches ?? []
  const state = dashboard?.business_state
  const runStatus = dashboard?.run?.status ?? (agents.length === 0 ? 'NOT STARTED' : agents.some((agent) => agent.status === 'RUNNING') ? 'RUNNING' : agents.every((agent) => ['STOPPED', 'FAILED'].includes(agent.status)) ? 'STOPPED' : 'MONITORING')
  const timeline = useMemo(() => {
    const items: TimelineItem[] = []
    if (dashboard?.run?.created_at) items.push({ at: dashboard.run.created_at, title: 'Run created', detail: dashboard.run.scenario, state: 'info' })
    for (const event of events) {
      if (!event.timestamp) continue
      const actor = event.branch_id ?? event.agent_id
      if (event.type === 'TOOL_STAGED') items.push({ at: event.timestamp, title: 'Effect staged', detail: `${event.tool ?? 'Action'}${Number(event.payload?.amount_cents) ? ` · ${money(Number(event.payload?.amount_cents))}` : ''}`, state: 'staged', agent: actor })
      else if (event.decision === 'DENY') items.push({ at: event.timestamp, title: 'Action denied', detail: `${event.tool ?? 'Tool'} · ${event.reason_code ?? 'Policy violation'}`, state: 'failed', agent: actor })
      else if (event.type === 'POLICY_VIOLATION_CONTAINED' || event.type === 'BRANCH_ABORTED') items.push({ at: event.timestamp, title: 'Branch aborted', detail: event.detail ?? String(event.payload?.reason ?? 'Pending work discarded'), state: 'failed', agent: actor })
      else if (event.type === 'BRANCH_COMMITTED') items.push({ at: event.timestamp, title: 'Branch committed', detail: `${Array.isArray(event.payload?.action_ids) ? event.payload.action_ids.length : 0} staged effect(s) applied`, state: 'committed', agent: actor })
      else if (event.tool === 'bedrock.delegate') items.push({ at: event.timestamp, title: 'Delegation started', detail: 'Parent assigned work to child agents', state: 'info', agent: event.agent_id })
      else if (event.tool === 'worker.complete') items.push({ at: event.timestamp, title: 'Agent task completed', detail: 'Worker reported successful completion', state: 'committed', agent: event.agent_id })
    }
    for (const effect of effects) if (effect.state === 'ABORTED' && !events.some((event) => event.type === 'POLICY_VIOLATION_CONTAINED' && event.branch_id === effect.branch_id)) items.push({ at: effect.created_at, title: 'Staged effect aborted', detail: effect.tool.replaceAll('_', ' '), state: 'failed', agent: effect.branch_id })
    return items.sort((a, b) => a.at.localeCompare(b.at))
  }, [agents, dashboard?.run, events, effects])

  const renderTreeNode = (agent: AgentNode) => {
    const branch = branches.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const effect = effects.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const outcome = agent.role === 'parent' ? 'COORDINATOR' : branch?.state ?? agent.task_state ?? 'IN PROGRESS'
    const process = agent.status === 'RUNNING' ? 'worker active' : agent.status === 'STOPPED' ? 'worker stopped' : agent.status.toLowerCase()
    const resultText = effect ? `${money(Number(effect.arguments.amount_cents ?? 0))} ${effect.tool === 'stage_refund' ? 'refund' : 'credit'}` : agent.role === 'parent' ? 'Delegates work to child agents' : 'No business change staged'
    return <div className="tree-branch" key={agent.agent_id}>
      <div className={`tree-node outcome-${outcome.toLowerCase()}`}>
        <span className="node-icon">{agent.role.slice(0, 1).toUpperCase()}</span><span className="node-copy"><span className="node-role">{agent.role === 'parent' ? 'Coordinator' : `${agent.role} agent`}</span><span className="node-result">{resultText}</span></span>
        <span className={`node-status ${outcome.toLowerCase()}`}>{outcome.replaceAll('_', ' ')}</span><span className="node-process">{process}</span>
      </div>
      {agent.children?.length ? <div className="tree-children">{agent.children.map(renderTreeNode)}</div> : null}
    </div>
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><div className="brand-mark">A</div><div><p className="eyebrow">AgentTree / Runtime security</p><h1>Customer operations run</h1><p className="run-id-label">{dashboard?.run_id ?? runId}</p></div></div>
      <div className="run-live-state"><i className={runStatus === 'RUNNING' ? 'live-dot' : 'idle-dot'} />{runStatus === 'RUNNING' ? 'Live · updates automatically' : runStatus}</div>
    </header>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}

    <section className="panel hierarchy-panel story-tree-panel">
      <div className="panel-header"><div><p className="section-kicker">WHO DID WHAT</p><h2>Agent tree</h2></div></div>
      <div className="tree-list">{agents.length === 0 ? <p className="empty-state">No agents in this run.</p> : roots.map(renderTreeNode)}</div>
    </section>

    <section className="panel transaction-panel">
      <div className="panel-header"><div><p className="section-kicker">BUSINESS RESULT</p><h2>What changed</h2></div></div>
      <div className="business-grid"><div className="business-card"><div className="business-title"><span className="resource-icon">ORD</span><div><strong>Order {state?.order.order_id ?? 'ORD-882'}</strong><span>Refund balance</span></div></div><div className="money-row"><div><small>REFUNDED</small><strong>{money(state?.order.refunded_cents ?? 0)}</strong></div><div><small>PAID</small><strong>{money(state?.order.paid_cents ?? 0)}</strong></div><span className="status-chip">{state?.order.status ?? 'PENDING'}</span></div></div>
        <div className="business-card"><div className="business-title"><span className="resource-icon account">ACC</span><div><strong>Account {state?.account.customer_id ?? 'C104'}</strong><span>Promotional credit</span></div></div><div className="money-row"><div><small>COMMITTED CREDIT</small><strong>{money(state?.account.promo_credit_cents ?? 0)}</strong></div><div><small>VERSION</small><strong>{state?.account.version ?? 0}</strong></div><span className="status-chip">LIVE</span></div></div></div>
      <div className="effects-table"><div className="effect-head"><span>EFFECT</span><span>BRANCH</span><span>AMOUNT</span><span>STATE</span><span>CREATED</span></div>{effects.length ? effects.map((effect) => <div className="effect-row" key={effect.action_id}><span><strong>{effect.tool.replaceAll('_', ' ')}</strong><small>{effect.action_id.slice(0, 12)}</small></span><span>{effect.branch_id}</span><span>{money(Number(effect.arguments.amount_cents ?? 0))}</span><span className={`effect-state ${effect.state.toLowerCase()}`}>{effect.state}</span><span>{shortTime(effect.created_at)}</span></div>) : <div className="empty-state effect-empty">No pending or resolved effects yet. Authorized state changes first appear as staged journal entries.</div>}</div>
    </section>

    <section className="panel run-story-panel">
      <div className="panel-header"><div><p className="section-kicker">RUN STORY</p><h2>What happened</h2></div>{dashboard?.run && <span className="run-started">Started {fullTime(dashboard.run.created_at)}</span>}</div>
      <ol className="run-timeline">{timeline.length === 0 ? <li className="empty-state">Run events will appear here.</li> : timeline.map((item, index) => <li key={`${item.at}-${item.title}-${index}`} className={`timeline-${item.state}`}><span className="timeline-marker"/><time>{fullTime(item.at)}</time><div><strong>{item.title}</strong>{item.agent && <span className="timeline-agent">{item.agent}</span>}<p>{String(item.detail)}</p></div></li>)}</ol>
    </section>
    <footer className="footer-note"><span>AgentTree · automatically refreshed</span><span>{dashboard?.run_id ?? runId}</span></footer>
  </div>
}
export default App
