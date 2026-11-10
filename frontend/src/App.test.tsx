import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

let fetchMock: ReturnType<typeof vi.fn>

const mockDashboard = {
  run_id: 'run-demo-verify',
  demo_execution: { status: 'SUCCEEDED', mode: 'CONTROLLED_TEST' },
  events: [
    { event_seq: 1, type: 'TOOL_STAGED', branch_id: 'order-agent', agent_id: 'order-agent-agent', tool: 'stage_refund', payload: { amount_cents: 4500 } },
    { event_seq: 2, type: 'TOOL_STAGED', branch_id: 'account-agent', agent_id: 'account-agent-agent', tool: 'stage_promo_credit', payload: { amount_cents: 5000 } },
    { event_seq: 3, type: 'TOOL_DECISION', agent_id: 'account-agent', tool: 'modify_billing', decision: 'DENY' },
    { event_seq: 4, type: 'POLICY_VIOLATION_CONTAINED', branch_id: 'account-agent', agent_id: 'account-agent-agent' },
    { event_seq: 5, type: 'COMMIT_ELIGIBLE', branch_id: 'order-agent', agent_id: 'order-agent-agent' },
    { event_seq: 6, type: 'BRANCH_COMMITTED', branch_id: 'order-agent', agent_id: 'order-agent-agent' },
  ],
  effects: { effects: [] },
  business_state: {
    order: { order_id: 'ORD-882', refunded_cents: 4500 },
    account: { customer_id: 'C104', promo_credit_cents: 0 },
  },
}

beforeEach(() => {
  fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    if (url.includes('/dashboard')) return { ok: true, json: async () => mockDashboard } as Response
    if (url.includes('/demo/live')) return { ok: true, json: async () => ({ run_id: 'new-live-run' }) } as Response
    return { ok: true, json: async () => ({ ok: true }) } as Response
  })
  vi.stubGlobal('fetch', fetchMock)
})

test('starts on a compact parent-to-two-branch transaction view', async () => {
  render(<App />)
  expect(await screen.findByRole('heading', { name: /one request\. two isolated transactions/i })).toBeInTheDocument()
  expect(screen.getByText('DEMO REQUEST')).toBeInTheDocument()
  expect(screen.queryByText('Parent agent')).not.toBeInTheDocument()
  expect(screen.queryByText('ORDER AGENT')).not.toBeInTheDocument()
  expect(screen.queryByText('ACCOUNT AGENT')).not.toBeInTheDocument()
  expect(screen.getByText('CONTROLLED_TEST')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /run demo/i })).toBeInTheDocument()
})

test('reveals staged, blocked, rolled-back, and committed outcomes in sequence', async () => {
  render(<App />)

  expect(await screen.findByText('Refund committed', {}, { timeout: 15000 })).toBeInTheDocument()
  expect(screen.getByText('Parent agent')).toBeInTheDocument()
  expect(screen.getByText('ORDER AGENT')).toBeInTheDocument()
  expect(screen.getByText('ACCOUNT AGENT')).toBeInTheDocument()
  expect(screen.getByText('2 APPROVED')).toBeInTheDocument()
  expect(screen.getByText('1 REJECTED')).toBeInTheDocument()
  expect(screen.getAllByText('COMMITTED').length).toBeGreaterThan(0)
  expect(screen.getAllByText('ROLLED BACK').length).toBeGreaterThan(0)
  expect(screen.getByText('Modify billing')).toBeInTheDocument()
  expect(screen.getByText('+$45.00 applied')).toBeInTheDocument()
  expect(screen.getByText('$50.00 discarded')).toBeInTheDocument()
  expect(screen.getByText('DATABASE UPDATED')).toBeInTheDocument()
}, 20000)

test('run demo starts a fresh live run', async () => {
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: /run demo/i }))
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/demo/live'), expect.objectContaining({ method: 'POST' }))
})
