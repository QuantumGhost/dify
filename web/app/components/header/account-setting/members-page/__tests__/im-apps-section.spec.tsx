import { ToastHost } from '@langgenius/dify-ui/toast'
import { QueryClient, QueryClientProvider, queryOptions } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import IMAppsSection from '../im-apps-section'

const {
  mockUpsertSelfBuiltConfig,
  mockDeleteSelfBuiltConfig,
  mockUpsertInstallation,
  mockDeleteInstallation,
} = vi.hoisted(() => ({
  mockUpsertSelfBuiltConfig: vi.fn(),
  mockDeleteSelfBuiltConfig: vi.fn(),
  mockUpsertInstallation: vi.fn(),
  mockDeleteInstallation: vi.fn(),
}))

vi.mock('@/features/workspace-im-apps/client', () => {
  const contexts = {
    feishu: {
      provider: 'feishu',
      install_mode: 'self_built',
      scope_type: 'tenant',
      scope_id: 'tenant-1',
      status: 'configured',
      token_status: 'not_applicable',
      install_status: 'not_applicable',
      event_mode: 'long_connection',
      app_id_configured: true,
      app_secret_configured: true,
      errors: [],
    },
    dingtalk: {
      provider: 'dingtalk',
      install_mode: 'self_built',
      scope_type: 'tenant',
      scope_id: 'tenant-1',
      status: 'missing',
      token_status: 'not_applicable',
      install_status: 'not_applicable',
      event_mode: null,
      app_id_configured: false,
      app_secret_configured: false,
      errors: ['missing tenant self-built config'],
    },
    slack: {
      provider: 'slack',
      install_mode: 'isv',
      scope_type: 'tenant',
      scope_id: 'tenant-1',
      status: 'configured',
      token_status: 'valid',
      install_status: 'installed',
      event_mode: null,
      app_id_configured: false,
      app_secret_configured: false,
      errors: [],
    },
  } as const

  const selfBuiltConfigs = {
    feishu: {
      id: 'cfg-1',
      tenant_id: 'tenant-1',
      provider: 'feishu',
      scope_type: 'tenant',
      scope_id: 'tenant-1',
      provider_workspace_id: 'ws-1',
      app_id: 'cli_a',
      app_secret_configured: true,
      verification_token_configured: true,
      encrypt_key_configured: true,
      event_mode: 'long_connection',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    dingtalk: null,
  } as const

  const installation = {
    id: 'inst-1',
    tenant_id: 'tenant-1',
    provider: 'slack',
    install_mode: 'isv',
    scope_type: 'tenant',
    scope_id: 'tenant-1',
    install_status: 'installed',
    token_status: 'valid',
    provider_workspace_id: 'team-1',
    access_token_configured: true,
    refresh_token_configured: true,
    access_token_expires_at: null,
    token_refreshed_at: null,
    token_refresh_error: null,
    installed_at: null,
    uninstalled_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  } as const

  const resolveContext = (provider: 'feishu' | 'dingtalk' | 'slack') => contexts[provider]
  const resolveSelfBuiltConfig = (provider: 'feishu' | 'dingtalk') => selfBuiltConfigs[provider]
  const resolveInstallation = () => installation

  return {
    // eslint-disable-next-line @tanstack/query/exhaustive-deps
    imAppContextQueryOptions: (provider: 'feishu' | 'dingtalk' | 'slack') => queryOptions({
      queryKey: ['workspace-im-apps', provider, 'context', contexts[provider].status],
      queryFn: async () => resolveContext(provider),
    }),
    // eslint-disable-next-line @tanstack/query/exhaustive-deps
    selfBuiltConfigQueryOptions: (provider: 'feishu' | 'dingtalk') => queryOptions({
      queryKey: ['workspace-im-apps', provider, 'self-built-config', selfBuiltConfigs[provider]?.id ?? 'none'],
      queryFn: async () => resolveSelfBuiltConfig(provider),
    }),
    // eslint-disable-next-line @tanstack/query/exhaustive-deps
    installationQueryOptions: () => queryOptions({
      queryKey: ['workspace-im-apps', 'slack', 'installations', 'isv', installation.id],
      queryFn: async () => resolveInstallation(),
    }),
    upsertSelfBuiltConfig: mockUpsertSelfBuiltConfig,
    deleteSelfBuiltConfig: mockDeleteSelfBuiltConfig,
    upsertInstallation: mockUpsertInstallation,
    deleteInstallation: mockDeleteInstallation,
  }
})

const renderSection = (canEdit = true) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  render(
    <QueryClientProvider client={queryClient}>
      <IMAppsSection canEdit={canEdit} />
      <ToastHost />
    </QueryClientProvider>,
  )
}

describe('IMAppsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpsertSelfBuiltConfig.mockResolvedValue({})
    mockDeleteSelfBuiltConfig.mockResolvedValue({})
    mockUpsertInstallation.mockResolvedValue({})
    mockDeleteInstallation.mockResolvedValue({})
  })

  it('renders provider cards with current effective status', async () => {
    renderSection()

    expect(await screen.findByText('Feishu')).toBeInTheDocument()
    expect(screen.getByText('DingTalk')).toBeInTheDocument()
    expect(screen.getByText('Slack')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText('Configured').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('Missing').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Valid').length).toBeGreaterThan(0)
  })

  it('saves Feishu self-built config through the configure dialog', async () => {
    renderSection()

    fireEvent.click((await screen.findAllByRole('button', { name: 'common.operation.edit' }))[0]!)
    const dialog = await screen.findByRole('dialog', {
      name: 'Feishu',
    })
    const inputs = dialog.querySelectorAll('input')
    fireEvent.change(inputs[0]!, { target: { value: 'ws-2' } })
    fireEvent.change(inputs[1]!, { target: { value: 'cli_b' } })
    fireEvent.change(inputs[2]!, { target: { value: 'secret' } })
    fireEvent.change(inputs[3]!, { target: { value: 'token' } })
    fireEvent.change(inputs[4]!, { target: { value: 'encrypt' } })
    fireEvent.click(screen.getByRole('button', { name: 'common.operation.save' }))

    await waitFor(() => {
      expect(mockUpsertSelfBuiltConfig).toHaveBeenCalledWith('feishu', expect.objectContaining({
        provider_workspace_id: 'ws-2',
        app_id: 'cli_b',
        app_secret: 'secret',
        verification_token: 'token',
        encrypt_key: 'encrypt',
      }))
    })
  })

  it('removes the Slack installation from the confirmation dialog', async () => {
    renderSection()

    fireEvent.click((await screen.findAllByRole('button', { name: 'common.operation.edit' }))[2]!)
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Slack' })).getByRole('button', { name: 'common.operation.delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'common.operation.confirm' }))

    await waitFor(() => {
      expect(mockDeleteInstallation).toHaveBeenCalledWith('slack', 'isv')
    })
  })
})
