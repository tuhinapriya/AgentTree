import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

let fetchMock: ReturnType<typeof vi.fn>

const mockDashboard = {
  run_id: 'run-demo-verify',
  hierarchy: {
    run_id: 'run-demo-verify',
    tree: [
      {
        agent_id: 'parent-agent', role: 'parent', status: 'RUNNING', parent_agent_id: null,
        children: [
          { agent_id: 'order-agent', role: 'order', status: 'READY', parent_agent_id: 'parent-agent', children: [] },
          { agent_id: 'account-agent', role: 'account', status: 'BLOCKED', parent_agent_id: 'parent-agent', children: [] },
        ],
      },
    ],
    nodes: [
      {
        agent_id: 'parent-agent',
        role: 'parent',
        status: 'RUNNING',
        parent_agent_id: null,
        allowed_tools: ['read_orders', 'process_order'],
      },
      {
        agent_id: 'order-agent',
        role: 'order',
        status: 'READY',
        parent_agent_id: 'parent-agent',
        allowed_tools: ['read_orders', 'process_order'],
      },
      {
        agent_id: 'account-agent',
        role: 'account',
        status: 'BLOCKED',
        parent_agent_id: 'parent-agent',
        allowed_tools: ['read_account'],
        policy: {
          role: 'account',
          allowed_tools: ['read_account', 'stage_promo_credit'],
          customer_id: 'C104',
          max_amount_cents: 5000,
          commit_on_verified_completion: true,
          abort_on_scope_violation: true,
        },
      },
    ],
    edges: [
      { source: 'parent-agent', target: 'order-agent' },
      { source: 'parent-agent', target: 'account-agent' },
    ],
  },
  events: [
    {
      agent_id: 'account-agent',
      decision: 'DENY',
      tool: 'modify_billing',
      detail: 'Permission denied for modify_billing.',
      timestamp: '2026-11-07T10:22:00Z',
      type: 'authorization',
    },
  ],
}

beforeEach(() => {
  fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input)

    if (url.includes('/dashboard')) {
      return {
        ok: true,
        json: async () => mockDashboard,
      } as Response
    }

    if (url.includes('/branches/')) {
      return {
        ok: true,
        json: async () => ({ run_id: 'run-demo', branch_id: 'account-agent', status: 'STOPPED' }),
      } as Response
    }

    if (url.includes('/demo/reset')) {
      return {
        ok: true,
        json: async () => ({ run_id: 'run-demo', status: 'RESET' }),
      } as Response
    }

    return {
      ok: true,
      json: async () => ({ ok: true }),
    } as Response
  })

  vi.stubGlobal('fetch', fetchMock)
})

test('loads the transactional demo run by default', async () => {
  render(<App />)

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/runs/agenttree-transactional-demo/dashboard'),
    expect.any(Object),
  )
})

test('renders the tree, database result, and timeline', async () => {
  render(<App />)

  expect(await screen.findByRole('heading', { name: /customer transaction demo/i })).toBeInTheDocument()
  expect(screen.getByText(/3 registered · 1 parent · 2 child agents/i)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /final database state/i })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /live agent activity/i })).toBeInTheDocument()
})

test('selecting an agent shows its effective permissions', async () => {
  const user = userEvent.setup()
  render(<App />)

  await screen.findByRole('heading', { name: /customer transaction demo/i })
  await user.click(screen.getByRole('button', { name: /account agent/i }))
  expect(screen.getByRole('heading', { name: /account agent permissions/i })).toBeInTheDocument()
  expect(screen.getByText(/customer c104/i)).toBeInTheDocument()
  expect(screen.getByText(/stage promo credit/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /refresh|reset demo|contain branch/i })).not.toBeInTheDocument()
})
