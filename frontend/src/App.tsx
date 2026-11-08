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
  const workerCount = agents.filter((agent) => agent.parent_agent_id !== null && agent.parent_agent_id !== undefined).length
  const events = dashboard?.events ?? []
  const effects = dashboard?.effects?.effects ?? []
  const branches = dashboard?.effects?.branches ?? []
  const state = dashboard?.business_state
  const timeline = useMemo(() => {
    const items: TimelineItem[] = []
    const processStarts = agents.map((agent) => agent.process_create_time).filter((value): value is string => Boolean(value)).sort()
    if (processStarts.length) items.push({ at: processStarts[0], title: 'Agents launched', detail: `${agents.length} configured agents started`, state: 'info' })
    else if (dashboard?.run?.created_at) items.push({ at: dashboard.run.created_at, title: 'Run configured', detail: `${agents.length} agents registered`, state: 'info' })
    for (const event of events) {
      if (!event.timestamp) continue
      const actor = event.branch_id ?? event.agent_id
      const displayName = (actor ?? 'Agent').replace(/-agent$/, '').replaceAll('-', ' ')
      const effect = effects.find((item) => item.branch_id === event.branch_id)
      const effectLabel = effect ? `${money(Number(effect.arguments.amount_cents ?? 0))} ${effect.tool === 'stage_refund' ? 'refund' : 'promotional credit'}` : 'Pending changes'
      if (event.type === 'TOOL_STAGED') items.push({ at: event.timestamp, title: `${displayName} staged an action`, detail: `${event.tool === 'stage_refund' ? 'Refund' : 'Promotional credit'} · ${money(Number(event.payload?.amount_cents ?? 0))}`, state: 'staged', agent: undefined })
      else if (event.decision === 'DENY') items.push({ at: event.timestamp, title: `Gateway blocked ${event.tool ?? 'an action'}`, detail: `This tool is outside the ${displayName} worker's permissions.`, state: 'failed' })
      else if (event.type === 'POLICY_VIOLATION_CONTAINED' || event.type === 'BRANCH_ABORTED') items.push({ at: event.timestamp, title: `${displayName} branch stopped`, detail: `${effectLabel} discarded after the blocked action.`, state: 'failed' })
      else if (event.type === 'COMMIT_ELIGIBLE') items.push({ at: event.timestamp, title: 'Order passed completion checks', detail: 'Refund is ready to be applied.', state: 'ready' })
      else if (event.type === 'BRANCH_COMMITTED') items.push({ at: event.timestamp, title: 'Order refund committed', detail: 'The $45 refund was applied to the order.', state: 'committed' })
      else if (event.tool === 'bedrock.delegate') items.push({ at: event.timestamp, title: 'Parent assigned two tasks', detail: 'Order and Account work were delegated.', state: 'info' })
    }
    for (const effect of effects) if (effect.state === 'ABORTED' && !events.some((event) => event.type === 'POLICY_VIOLATION_CONTAINED' && event.branch_id === effect.branch_id)) items.push({ at: effect.created_at, title: 'Staged effect aborted', detail: effect.tool.replaceAll('_', ' '), state: 'failed', agent: effect.branch_id })
    return items.sort((a, b) => a.at.localeCompare(b.at))
  }, [agents, dashboard?.run, events, effects])

  const renderTreeNode = (agent: AgentNode) => {
    const branch = branches.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const effect = effects.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const outcome = agent.role === 'parent' ? 'PARENT' : branch?.state ?? agent.task_state ?? 'IN PROGRESS'
    const effectDescription = effect ? `${money(Number(effect.arguments.amount_cents ?? 0))} ${effect.tool === 'stage_refund' ? 'refund' : 'promotional credit'}` : ''
    const resultText = agent.role === 'parent'
      ? `Delegates to ${agent.children?.length ?? 0} workers`
      : effect?.state === 'COMMITTED' ? `${effectDescription} applied`
        : effect?.state === 'ABORTED' ? `${effectDescription} discarded`
          : effect ? `${effectDescription} staged` : 'Task assigned'
    return <div className="tree-branch" key={agent.agent_id}>
      <div className={`tree-node outcome-${outcome.toLowerCase()}`}>
        <span className="node-icon">{agent.role.slice(0, 1).toUpperCase()}</span><span className="node-copy"><span className="node-role">{agent.role === 'parent' ? 'Coordinator' : `${agent.role} agent`}</span><span className="node-result">{resultText}</span></span>
        {agent.role !== 'parent' && <span className={`node-status ${outcome.toLowerCase()}`}>{outcome.replaceAll('_', ' ')}</span>}
      </div>
      {agent.children?.length ? <div className="tree-children">{agent.children.map(renderTreeNode)}</div> : null}
    </div>
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><div className="brand-mark">A</div><div><p className="eyebrow">AgentTree / Runtime security</p><h1>Customer transaction demo</h1></div></div>
      <span className="run-id-label">{dashboard?.run_id ?? runId}</span>
    </header>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}

    <section className="panel hierarchy-panel story-tree-panel">
      <div className="panel-header"><div><h2>Agents in this run</h2><p className="tree-caption">{agents.length} registered · {roots.length} parent · {workerCount} child agents</p></div></div>
      <div className="tree-list">{agents.length === 0 ? <p className="empty-state">No agents in this run.</p> : roots.map(renderTreeNode)}</div>
    </section>

    <details className="panel policy-panel">
      <summary>How this demo is configured</summary>
      <p className="policy-intro">This is a fixed customer-transaction scenario with {roots.length} coordinator{roots.length === 1 ? '' : 's'} and {workerCount} worker{workerCount === 1 ? '' : 's'}. The demo script sets the count; Bedrock assigns tasks but does not create extra agents.</p>
      <div className="policy-grid">
        <div><strong>Order worker</strong><span>May read ORD-882 and stage a refund up to $45.</span></div>
        <div><strong>Account worker</strong><span>May read C104 and stage promotional credit up to $50. Neither worker may modify billing; an account scope violation aborts its branch.</span></div>
      </div>
      <p className="policy-source">Topology: <code>demo/run_live_demo.py</code> · Permissions and limits: <code>backend/app/services/demo_policy.py</code></p>
    </details>

    <section className="panel transaction-panel">
      <div className="panel-header"><div><h2>Final database state</h2></div></div>
      <div className="record-results"><div><span>Order {state?.order.order_id ?? 'ORD-882'} · refund applied</span><strong>{money(state?.order.refunded_cents ?? 0)}</strong></div><div><span>Account {state?.account.customer_id ?? 'C104'} · committed credit</span><strong>{money(state?.account.promo_credit_cents ?? 0)}</strong></div></div>
    </section>

    <section className="panel run-story-panel">
      <div className="panel-header"><div><h2>Timeline</h2></div></div>
      <ol className="run-timeline">{timeline.length === 0 ? <li className="empty-state">Run events will appear here.</li> : timeline.map((item, index) => <li key={`${item.at}-${item.title}-${index}`} className={`timeline-${item.state}`}><span className="timeline-marker"/><time>{fullTime(item.at)}</time><div><strong>{item.title}</strong>{item.agent && <span className="timeline-agent">{item.agent}</span>}<p>{String(item.detail)}</p></div></li>)}</ol>
    </section>
  </div>
}
export default App
