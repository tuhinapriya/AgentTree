import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

let fetchMock: ReturnType<typeof vi.fn>

const mockDashboard = {
  run_id: 'run-demo-verify',
  hierarchy: {
    run_id: 'run-demo-verify',
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
    expect.stringContaining('/runs/agenttree-live-demo/dashboard'),
    expect.any(Object),
  )
})

test('renders dashboard panels and agent list', async () => {
  render(<App />)

  expect(await screen.findByRole('heading', { name: /execution control/i })).toBeInTheDocument()
  expect(screen.getByText(/agent hierarchy/i)).toBeInTheDocument()
  expect(screen.getByText(/authorization events/i)).toBeInTheDocument()
  expect(screen.getAllByText(/parent-agent/i).length).toBeGreaterThan(0)
})

test('shows the agent tree and removes redundant operator controls', async () => {
  render(<App />)

  await screen.findAllByText(/parent-agent/i)
  expect(screen.getByText(/live · updates automatically/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /refresh|reset demo|contain branch/i })).not.toBeInTheDocument()
})
