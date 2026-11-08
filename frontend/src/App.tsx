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
  policy?: AgentPolicy
}
type AgentPolicy = {
  role: string
  allowed_tools: string[]
  customer_id?: string | null
  order_id?: string | null
  max_amount_cents?: number | null
  commit_on_verified_completion: boolean
  abort_on_scope_violation: boolean
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
type TimelineItem = { at: string; title: string; detail: string; state: string; agent?: string; source?: string }
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
  const [selectedAgentId, setSelectedAgentId] = useState('order-agent')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
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
          setLastUpdated(new Date())
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
  const selectedAgent = agents.find((agent) => agent.agent_id === selectedAgentId) ?? agents[0] ?? null
  const events = dashboard?.events ?? []
  const effects = dashboard?.effects?.effects ?? []
  const branches = dashboard?.effects?.branches ?? []
  const state = dashboard?.business_state
  const timeline = useMemo(() => {
    const items: TimelineItem[] = []
    const processStarts = agents.map((agent) => agent.process_create_time).filter((value): value is string => Boolean(value)).sort()
    if (processStarts.length) items.push({ at: processStarts[0], title: 'Agents launched', detail: `${agents.length} configured agents started`, state: 'info', source: 'Supervisor' })
    else if (dashboard?.run?.created_at) items.push({ at: dashboard.run.created_at, title: 'Run configured', detail: `${agents.length} agents registered`, state: 'info' })
    for (const event of events) {
      if (!event.timestamp) continue
      const actor = event.branch_id ?? event.agent_id
      const displayName = (actor ?? 'Agent').replace(/-agent$/, '').replaceAll('-', ' ')
      const effect = effects.find((item) => item.branch_id === event.branch_id)
      const effectLabel = effect ? `${money(Number(effect.arguments.amount_cents ?? 0))} ${effect.tool === 'stage_refund' ? 'refund' : 'promotional credit'}` : 'Pending changes'
      if (event.tool === 'bedrock.delegate') items.push({ at: event.timestamp, title: 'Parent delegated work', detail: 'Tasks assigned to child agents.', state: 'info', source: event.origin })
      else if (event.tool === 'worker.complete') items.push({ at: event.timestamp, title: `${displayName} finished its task`, detail: 'Worker reported successful completion.', state: 'ready', source: event.origin })
      else if (event.type === 'TOOL_DECISION' && event.tool !== 'bedrock.converse') items.push({ at: event.timestamp, title: `${displayName} · ${event.tool ?? 'tool call'}`, detail: event.decision === 'DENY' ? 'This tool is outside the agent’s permissions.' : 'Gateway allowed this tool call.', state: event.decision === 'DENY' ? 'denied' : 'allowed', source: event.origin })
      else if (event.type === 'TOOL_STAGED') items.push({ at: event.timestamp, title: 'Change staged', detail: `${event.tool === 'stage_refund' ? 'Refund' : 'Promotional credit'} · ${money(Number(event.payload?.amount_cents ?? 0))}`, state: 'staged', agent: displayName, source: event.origin })
      else if (event.type === 'POLICY_VIOLATION_CONTAINED' || event.type === 'BRANCH_ABORTED') items.push({ at: event.timestamp, title: `${displayName} branch stopped`, detail: `${effectLabel} discarded after the blocked action.`, state: 'failed', agent: displayName, source: event.origin })
      else if (event.type === 'COMMIT_ELIGIBLE') items.push({ at: event.timestamp, title: `${displayName} passed completion checks`, detail: `${effectLabel} is ready to apply.`, state: 'ready', agent: displayName, source: event.origin })
      else if (event.type === 'BRANCH_COMMITTED') items.push({ at: event.timestamp, title: `${displayName} committed its change`, detail: `${effectLabel} applied to the database.`, state: 'committed', agent: displayName, source: event.origin })
    }
    for (const effect of effects) if (effect.state === 'ABORTED' && !events.some((event) => event.type === 'POLICY_VIOLATION_CONTAINED' && event.branch_id === effect.branch_id)) items.push({ at: effect.created_at, title: 'Staged effect aborted', detail: effect.tool.replaceAll('_', ' '), state: 'failed', agent: effect.branch_id })
    return items.sort((a, b) => a.at.localeCompare(b.at))
  }, [agents, dashboard?.run, events, effects])

  const renderTreeNode = (agent: AgentNode) => {
    const branch = branches.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const effect = effects.find((item) => item.branch_id === (agent.branch_id ?? agent.agent_id))
    const callCount = toolCalls.filter((event) => event.agent_id === agent.agent_id).length
    const outcome = agent.role === 'parent' ? 'PARENT' : branch?.state ?? agent.task_state ?? 'IN PROGRESS'
    const effectDescription = effect ? `${money(Number(effect.arguments.amount_cents ?? 0))} ${effect.tool === 'stage_refund' ? 'refund' : 'promotional credit'}` : ''
    const resultText = agent.role === 'parent'
      ? `Delegates to ${agent.children?.length ?? 0} workers`
      : effect?.state === 'COMMITTED' ? `${effectDescription} applied`
        : effect?.state === 'ABORTED' ? `${effectDescription} discarded`
          : effect ? `${effectDescription} staged` : 'Task assigned'
    return <div className="tree-branch" key={agent.agent_id}>
      <button type="button" aria-pressed={selectedAgent?.agent_id === agent.agent_id} onClick={() => setSelectedAgentId(agent.agent_id)} className={`tree-node outcome-${outcome.toLowerCase()} ${selectedAgent?.agent_id === agent.agent_id ? 'selected' : ''}`}>
        <span className="node-icon">{agent.role.slice(0, 1).toUpperCase()}</span><span className="node-copy"><span className="node-role">{agent.role === 'parent' ? 'Coordinator' : `${agent.role} agent`}</span><span className="node-result">{resultText}</span></span>
        {agent.role !== 'parent' && <span className={`node-status ${outcome.toLowerCase()}`}>{outcome.replaceAll('_', ' ')}</span>}
        {agent.role !== 'parent' && <span className="node-calls">{callCount} tool calls</span>}
      </button>
      {agent.children?.length ? <div className="tree-children">{agent.children.map(renderTreeNode)}</div> : null}
    </div>
  }
  const toolCalls = events.filter((event) => event.type === 'TOOL_DECISION' && !['bedrock.converse', 'bedrock.delegate', 'worker.complete'].includes(event.tool ?? ''))
  const allowedCalls = toolCalls.filter((event) => event.decision === 'ALLOW').length
  const blockedCalls = toolCalls.filter((event) => event.decision === 'DENY').length
  const selectedPolicy = selectedAgent?.policy
  const allowedTools = selectedPolicy?.allowed_tools ?? selectedAgent?.allowed_tools ?? []
  const branchRule = selectedPolicy?.abort_on_scope_violation
    ? 'Abort branch and discard staged changes after a scope violation'
    : selectedPolicy?.commit_on_verified_completion
      ? 'Commit only after task completion is verified'
      : 'Coordinates workers; no transactional tools'

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><div className="brand-mark">A</div><div><p className="eyebrow">AgentTree / Runtime security</p><h1>Customer transaction demo</h1></div></div>
      <span className="run-id-label">{dashboard?.run_id ?? runId}</span>
    </header>
    {error ? <div className="error-banner" role="alert">{error}</div> : null}

    <section className="panel hierarchy-panel story-tree-panel">
      <div className="panel-header"><div><h2>Agents in this run</h2><p className="tree-caption">{agents.length} registered · {roots.length} parent · {workerCount} child agents · select a node for its rules</p></div></div>
      <div className="tree-list">{agents.length === 0 ? <p className="empty-state">No agents in this run.</p> : roots.map(renderTreeNode)}</div>
    </section>

    {selectedAgent && <section className="panel policy-panel">
      <div className="panel-header"><div><h2>{selectedAgent.role === 'parent' ? 'Coordinator permissions' : `${selectedAgent.role} agent permissions`}</h2></div><span className="policy-enforced">Gateway enforced</span></div>
      <div className="permission-summary">
        <div><small>ALLOWED TOOLS</small><div className="tool-tags">{allowedTools.length ? allowedTools.map((tool) => <span key={tool}>{tool.replaceAll('_', ' ')}</span>) : <span>No business tools</span>}</div></div>
        <div><small>DATA SCOPE</small><strong>{selectedPolicy?.order_id ? `Order ${selectedPolicy.order_id}` : selectedPolicy?.customer_id ? `Customer ${selectedPolicy.customer_id}` : 'Delegation only'}</strong></div>
        {selectedPolicy?.max_amount_cents != null && <div><small>{selectedAgent.role === 'order' ? 'MAX REFUND' : 'MAX PROMO CREDIT'}</small><strong>{money(selectedPolicy.max_amount_cents)}</strong></div>}
        <div><small>TRANSACTION RULE</small><strong>{branchRule}</strong></div>
      </div>
    </section>}

    <section className="panel transaction-panel">
      <div className="panel-header"><div><h2>Final database state</h2></div></div>
      <div className="record-results"><div><span>Order {state?.order.order_id ?? 'ORD-882'} · refund applied</span><strong>{money(state?.order.refunded_cents ?? 0)}</strong></div><div><span>Account {state?.account.customer_id ?? 'C104'} · committed credit</span><strong>{money(state?.account.promo_credit_cents ?? 0)}</strong></div></div>
    </section>

    <section className="panel run-story-panel">
      <div className="panel-header"><div><h2>Live agent activity</h2><p className="tree-caption">{toolCalls.length} tool calls · {allowedCalls} allowed · {blockedCalls} blocked</p></div><span className="live-indicator"><i className="live-dot" />Polling · {lastUpdated ? `updated ${shortTime(lastUpdated.toISOString())}` : 'connecting'}</span></div>
      <ol className="run-timeline">{timeline.length === 0 ? <li className="empty-state">No activity yet. Start the live demo in a terminal with <code>python cli/agenttree.py demo</code>.</li> : timeline.map((item, index) => <li key={`${item.at}-${item.title}-${index}`} className={`timeline-${item.state}`}><span className="timeline-marker"/><time>{fullTime(item.at)}</time><div><strong>{item.title}</strong>{item.state === 'allowed' && <b className="call-decision allowed">ALLOWED</b>}{item.state === 'denied' && <b className="call-decision denied">BLOCKED</b>}{item.agent && <span className="timeline-agent">{item.agent}</span>}<p>{String(item.detail)}</p>{item.source && <small className="activity-source">{item.source === 'MODEL' ? 'Bedrock model' : item.source === 'CONTROLLED_TEST' ? 'Demo script' : item.source}</small>}</div></li>)}</ol>
    </section>
  </div>
}
export default App
