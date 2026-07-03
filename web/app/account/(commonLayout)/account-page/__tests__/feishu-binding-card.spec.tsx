import type { ReactNode } from 'react'
import { toast } from '@langgenius/dify-ui/toast'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { API_PREFIX } from '@/config'
import { openOAuthPopup } from '@/hooks/use-oauth'
import {
  getAccountIMBindings,
  updateAccountIMBinding,
} from '../client'
import FeishuBindingCard from '../feishu-binding-card'

vi.mock('@/hooks/use-oauth', () => ({
  openOAuthPopup: vi.fn(),
}))

vi.mock('../client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../client')>()
  return {
    ...actual,
    getAccountIMBindings: vi.fn(),
    updateAccountIMBinding: vi.fn(),
  }
})

vi.mock('@langgenius/dify-ui/toast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

const mockGetAccountIMBindings = vi.mocked(getAccountIMBindings)
const mockUpdateAccountIMBinding = vi.mocked(updateAccountIMBinding)
const mockOpenOAuthPopup = vi.mocked(openOAuthPopup)

const createQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
})

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  )
}

const renderComponent = () => {
  const queryClient = createQueryClient()
  return render(<FeishuBindingCard />, {
    wrapper: createWrapper(queryClient),
  })
}

describe('FeishuBindingCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render the current Feishu binding values when they exist', async () => {
    mockGetAccountIMBindings.mockResolvedValue({
      data: [{
        provider: 'feishu',
        open_id: 'open-1',
        user_id: 'user-1',
      }],
    })

    renderComponent()

    expect(screen.getByText('common.account.feishuBindingTitle')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'common.account.feishuBindingOpenId' })).toHaveValue('open-1')
    })
    expect(screen.getByRole('textbox', { name: 'common.account.feishuBindingUserId' })).toHaveValue('user-1')
  })

  it('should save the manual Feishu binding and show a success toast', async () => {
    mockGetAccountIMBindings.mockResolvedValue({ data: [] })
    mockUpdateAccountIMBinding.mockResolvedValue({
      provider: 'feishu',
      open_id: 'open-2',
      user_id: 'user-2',
    })

    renderComponent()

    fireEvent.change(
      await screen.findByRole('textbox', { name: 'common.account.feishuBindingOpenId' }),
      { target: { value: 'open-2' } },
    )
    fireEvent.change(
      screen.getByRole('textbox', { name: 'common.account.feishuBindingUserId' }),
      { target: { value: 'user-2' } },
    )
    fireEvent.click(screen.getByRole('button', { name: 'common.operation.save' }))

    await waitFor(() => {
      expect(mockUpdateAccountIMBinding).toHaveBeenCalledWith({
        provider: 'feishu',
        open_id: 'open-2',
        user_id: 'user-2',
      })
    })
    expect(toast.success).toHaveBeenCalledWith('common.actionMsg.modifiedSuccessfully')
  })

  it('should open the OAuth popup and refresh bindings on callback success', async () => {
    mockGetAccountIMBindings
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: [{
          provider: 'feishu',
          open_id: 'oauth-open',
          user_id: 'oauth-user',
        }],
      })

    renderComponent()

    fireEvent.click(await screen.findByRole('button', { name: 'common.account.feishuBindingOAuth' }))

    expect(mockOpenOAuthPopup).toHaveBeenCalledWith(
      `${API_PREFIX}/account/im-bindings/feishu/oauth-link`,
      expect.any(Function),
    )

    const oauthCallback = mockOpenOAuthPopup.mock.calls[0]?.[1]
    oauthCallback?.({ type: 'oauth_callback' })

    await waitFor(() => {
      expect(mockGetAccountIMBindings).toHaveBeenCalledTimes(2)
    })
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'common.account.feishuBindingOpenId' })).toHaveValue('oauth-open')
    })
    expect(toast.success).toHaveBeenCalledWith('common.actionMsg.modifiedSuccessfully')
  })

  it('should show the OAuth callback error without updating the binding', async () => {
    mockGetAccountIMBindings.mockResolvedValue({ data: [] })

    renderComponent()

    fireEvent.click(await screen.findByRole('button', { name: 'common.account.feishuBindingOAuth' }))

    const oauthCallback = mockOpenOAuthPopup.mock.calls[0]?.[1]
    oauthCallback?.({ success: false, errorDescription: 'denied' })

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('denied')
    })
    expect(mockGetAccountIMBindings).toHaveBeenCalledTimes(1)
  })
})
