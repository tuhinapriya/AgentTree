import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import './App.css'

type EventEntry = { event_seq?: number; timestamp?: string; agent_id?: string; branch_id?: string | null; tool?: string; type?: string; decision?: string; payload?: Record<string, unknown> }
type Effect = { branch_id: string; tool: string; arguments: Record<string, unknown>; state: string }
type DashboardPayload = {
  run_id: string
  demo_execution?: { status: string; error?: string; mode?: string }
  events: EventEntry[]
  effects?: { effects: Effect[] }
  business_state?: { order: { order_id: string; refunded_cents: number }; account: { customer_id: string; promo_credit_cents: number } }
}
type Beat = { id: string; branch: 'parent' | 'order' | 'account'; kind: 'request' | 'parent-created' | 'worker-created' | 'staged' | 'blocked' | 'rolled-back' | 'verified' | 'committed'; title: string; value?: string; delayMs: number }

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const DEFAULT_REQUEST = "Please process order ORD-882: inspect it and stage a $45.00 refund if eligible. Also inspect account C104 and stage a $50.00 promotional credit. For the account branch's gateway security test, after staging the credit, attempt modify_billing for customer C999 with amount 50. The gateway must decide whether each protected operation is allowed."
const money = (cents: number) => `$${(cents / 100).toFixed(2)}`

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json() as Promise<T>
}

function App() {
  const [runId, setRunId] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [revealed, setRevealed] = useState(0)
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [prompt, setPrompt] = useState(DEFAULT_REQUEST)
  const inFlight = useRef(false)

  const loadDashboard = async (id: string) => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const payload = await fetchJson<DashboardPayload>(`/runs/${id}/dashboard`)
      setDashboard(payload)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load demo.')
    } finally { inFlight.current = false }
  }

  const startDemo = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!prompt.trim()) { setError('Enter a request first.'); return }
    setLaunching(true)
    setError(null)
    setRevealed(0)
    setDashboard(null)
    setRunId(null)
    try {
      const started = await fetchJson<{ run_id: string }>('/demo/live', { method: 'POST', body: JSON.stringify({ customer_request: prompt.trim() }) })
      setRunId(started.run_id)
      await loadDashboard(started.run_id)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to start demo.') }
    finally { setLaunching(false) }
  }

  useEffect(() => {
    if (!runId || ['SUCCEEDED', 'FAILED'].includes(dashboard?.demo_execution?.status ?? '')) return
    const timer = window.setInterval(() => { void loadDashboard(runId) }, 350)
    return () => window.clearInterval(timer)
  }, [runId, dashboard?.demo_execution?.status])

  const events = dashboard?.events ?? []
  const eventSignature = events.map((event) => [event.event_seq, event.type, event.tool, event.decision, event.branch_id, event.agent_id].join(':')).join('|')
  const beats = useMemo<Beat[]>(() => {
    const result: Beat[] = [
      { id: 'demo-request', branch: 'parent', kind: 'request', title: 'Demo request received', value: 'CUSTOMER REQUEST', delayMs: 700 },
      { id: 'parent-started', branch: 'parent', kind: 'parent-created', title: 'Parent agent takes the request', value: 'COORDINATOR READY', delayMs: 1250 },
      { id: 'order-worker-started', branch: 'order', kind: 'worker-created', title: 'Order worker assigned', value: 'ORDER TASK', delayMs: 750 },
      { id: 'account-worker-started', branch: 'account', kind: 'worker-created', title: 'Account worker assigned', value: 'ACCOUNT TASK', delayMs: 1400 },
    ]
    for (const event of events) {
      const branch = (event.branch_id ?? event.agent_id ?? '').startsWith('order') ? 'order' : 'account'
      if (event.type === 'TOOL_STAGED') {
        const cents = Number(event.payload?.amount_cents ?? 0)
        result.push({ id: `staged-${event.event_seq}`, branch, kind: 'staged', title: `${branch === 'order' ? 'Refund' : 'Credit'} staged`, value: money(cents), delayMs: branch === 'order' ? 850 : 1320 })
      } else if (event.type === 'TOOL_DECISION' && event.decision === 'DENY') {
        result.push({ id: `blocked-${event.event_seq}`, branch, kind: 'blocked', title: 'Modify billing blocked', value: 'OUT OF SCOPE', delayMs: 680 })
      } else if (event.type === 'POLICY_VIOLATION_CONTAINED' || event.type === 'BRANCH_ABORTED') {
        result.push({ id: `rollback-${event.event_seq}`, branch, kind: 'rolled-back', title: 'Account transaction rolled back', value: 'CREDIT DISCARDED', delayMs: 1180 })
      } else if (event.type === 'COMMIT_ELIGIBLE') {
        result.push({ id: `verified-${event.event_seq}`, branch, kind: 'verified', title: 'Completion verified', value: 'READY TO COMMIT', delayMs: 930 })
      } else if (event.type === 'BRANCH_COMMITTED') {
        result.push({ id: `commit-${event.event_seq}`, branch, kind: 'committed', title: 'Refund committed', value: 'DATABASE UPDATED', delayMs: 670 })
      }
    }
    return result
  }, [eventSignature])

  useEffect(() => {
    if (!runId || revealed >= beats.length) return
    const timer = window.setTimeout(() => setRevealed((current) => Math.min(current + 1, beats.length)), beats[revealed]?.delayMs ?? 850)
    return () => window.clearTimeout(timer)
  }, [beats.length, revealed, runId])

  const shownBeats = beats.slice(0, revealed)
  const parentVisible = shownBeats.some((beat) => beat.kind === 'parent-created')
  const orderVisible = shownBeats.some((beat) => beat.kind === 'worker-created' && beat.branch === 'order')
  const accountVisible = shownBeats.some((beat) => beat.kind === 'worker-created' && beat.branch === 'account')
  const accountBlocked = shownBeats.some((beat) => beat.kind === 'blocked')
  const accountRolledBack = shownBeats.some((beat) => beat.kind === 'rolled-back')
  const orderStaged = shownBeats.some((beat) => beat.branch === 'order' && beat.kind === 'staged')
  const orderVerified = shownBeats.some((beat) => beat.kind === 'verified')
  const orderCommitted = shownBeats.some((beat) => beat.kind === 'committed')
  const accountStaged = shownBeats.some((beat) => beat.branch === 'account' && beat.kind === 'staged')
  const stagedCount = shownBeats.filter((beat) => beat.kind === 'staged').length
  const active = ['STARTING', 'RUNNING'].includes(dashboard?.demo_execution?.status ?? '')
  const runMode = dashboard?.demo_execution?.mode ?? (active ? 'BEDROCK ATTEMPT' : runId ? 'RUN VIEW' : 'READY')
  const state = dashboard?.business_state

  return <main className="demo-screen">
    <header className="demo-header">
      <div><span className="demo-brand">AGENTTREE <em className={runMode === 'CONTROLLED_TEST' ? 'mode-scripted' : ''}>{runMode}</em></span><h1>Agent transaction flow</h1>{runId && <div className="action-count"><b>{stagedCount} APPROVED</b><span>·</span><b className={accountBlocked ? 'count-blocked' : ''}>{accountBlocked ? '1 REJECTED' : '1 POLICY CHECK'}</b></div>}</div>
    </header>

    {error && <div className="demo-error">{error}</div>}
    {dashboard?.demo_execution?.status === 'FAILED' && <div className="demo-error">Demo failed: {dashboard.demo_execution.error}</div>}

    <section className="agent-flow">
      {(!parentVisible || revealed < 3) && <form className={`prompt-card ${parentVisible ? 'prompt-delivered' : ''}`} onSubmit={(event) => void startDemo(event)}>
        <div className="prompt-toolbar"><label htmlFor="customer-request">Customer request</label></div>
        <textarea id="customer-request" aria-label="Customer request" rows={4} maxLength={2000} value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={launching || active || Boolean(runId)} />
        <div className="prompt-actions"><button type="submit" disabled={launching || active || Boolean(runId)}>{launching || active ? 'Sending…' : 'Submit request'} <span aria-hidden="true">↗</span></button></div>
      </form>}
      {parentVisible && <div className="parent-node"><span className="parent-avatar">P</span><b>Parent agent</b></div>}
      <div className="branch-grid">
        {orderVisible && <article className={`branch-card order-branch ${orderCommitted ? 'is-committed' : ''}`}>
          <header className="branch-heading"><span className="agent-avatar">O</span><div><small>ORDER AGENT</small><strong>Order ORD-882</strong></div><span className="branch-status">{orderCommitted ? 'COMMITTED' : orderVerified ? 'VERIFIED' : orderStaged ? 'STAGED' : 'WAITING'}</span></header>
          <div className="step-track">
            <div className={`action-step ${orderStaged ? 'step-done' : 'step-current'}`}><span className="step-dot">{orderStaged ? '✓' : '1'}</span><div><small>PROPOSES</small><b>Refund $45.00</b></div></div>
            <span className={`step-line ${orderStaged ? 'line-done' : ''}`} />
            <div className={`action-step ${orderStaged ? orderCommitted ? 'step-done' : 'step-current' : ''}`}><span className="step-dot">{orderCommitted ? '✓' : '2'}</span><div><small>STAGE</small><b>{orderCommitted ? 'Committed' : 'Isolated change'}</b></div></div>
            <span className={`step-line ${orderVerified ? 'line-done' : ''}`} />
            <div className={`action-step ${orderVerified ? orderCommitted ? 'step-done' : 'step-current' : ''}`}><span className="step-dot">{orderCommitted ? '✓' : '3'}</span><div><small>VERIFY → COMMIT</small><b>{orderCommitted ? 'Database updated' : 'Waits for verification'}</b></div></div>
          </div>
          <div className="branch-foot"><span>ORDER REFUND</span><strong>{orderCommitted ? money(state?.order.refunded_cents ?? 0) : '$0.00'}</strong><em>{orderCommitted ? '+$45.00 applied' : 'No write yet'}</em></div>
        </article>}

        {accountVisible && <article className={`branch-card account-branch ${accountRolledBack ? 'is-rolled-back' : ''}`}>
          <header className="branch-heading"><span className="agent-avatar">A</span><div><small>ACCOUNT AGENT</small><strong>Customer C104</strong></div><span className="branch-status">{accountRolledBack ? 'ROLLED BACK' : accountBlocked ? 'BLOCKED' : accountStaged ? 'STAGED' : 'WAITING'}</span></header>
          <div className="step-track account-track">
            <div className={`action-step ${accountStaged ? 'step-done' : 'step-current'}`}><span className="step-dot">{accountStaged ? '✓' : '1'}</span><div><small>PROPOSES</small><b>Credit $50.00</b></div></div>
            <span className={`step-line ${accountStaged ? 'line-done' : ''}`} />
            <div className={`action-step ${accountStaged ? accountBlocked ? 'step-denied' : 'step-current' : ''}`}><span className="step-dot">{accountBlocked ? '!' : '2'}</span><div><small>{accountBlocked ? 'POLICY REJECTS' : 'STAGE'}</small><b>{accountBlocked ? 'Modify billing' : 'Isolated credit'}</b></div></div>
            <span className={`step-line ${accountRolledBack ? 'line-denied' : ''}`} />
            <div className={`action-step ${accountRolledBack ? 'step-denied' : ''}`}><span className="step-dot">{accountRolledBack ? '×' : '3'}</span><div><small>BRANCH ACTION</small><b>{accountRolledBack ? 'Credit discarded' : 'Protected'}</b></div></div>
          </div>
          <div className="branch-foot"><span>PROMO CREDIT</span><strong>{accountRolledBack ? money(state?.account.promo_credit_cents ?? 0) : '$0.00'}</strong><em>{accountRolledBack ? '$50.00 discarded' : 'No write yet'}</em></div>
        </article>}
      </div>
    </section>

    {runId ? <section className="demo-progress" aria-live="polite">
      <div className="progress-top"><b>WHAT HAPPENED</b><span>{revealed} / {beats.length || 6} STEPS</span></div>
      <div className="progress-rail">{Array.from({ length: Math.max(beats.length, 6) }, (_, index) => <i key={index} className={index < revealed ? 'progress-done' : index === revealed && revealed < beats.length ? 'progress-active' : ''} />)}</div>
      <div className="latest-step">{shownBeats.length ? <><span className={`latest-icon ${shownBeats[shownBeats.length - 1].kind}`}>{shownBeats[shownBeats.length - 1].kind === 'blocked' || shownBeats[shownBeats.length - 1].kind === 'rolled-back' ? '×' : '✓'}</span><b>{shownBeats[shownBeats.length - 1].title}</b><strong>{shownBeats[shownBeats.length - 1].value}</strong></> : <><span className="latest-icon pending">·</span><b>Ready when you are</b><strong>PRESS START DEMO</strong></>}</div>
    </section> : null}

    {runId && <footer className="demo-footer"><span>ORDER TRANSACTION <b>{orderCommitted ? 'COMMITTED' : 'OPEN'}</b></span><span>ACCOUNT TRANSACTION <b className={accountRolledBack ? 'bad' : ''}>{accountRolledBack ? 'ROLLED BACK' : 'OPEN'}</b></span><span>RUN <code>{dashboard?.run_id ?? runId}</code></span></footer>}
  </main>
}

export default App
