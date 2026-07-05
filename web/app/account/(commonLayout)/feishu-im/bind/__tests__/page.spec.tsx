import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Page from '../page'

const mockAssign = vi.fn()
const mockCookieGet = vi.fn()

vi.mock('js-cookie', () => ({
  default: {
    get: (...args: unknown[]) => mockCookieGet(...args),
  },
}))

describe('FeishuBindPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAssign.mockReset()
    mockCookieGet.mockReturnValue('csrf-token')
    vi.spyOn(window.location, 'assign').mockImplementation(mockAssign)
  })

  it('should redirect to Feishu authorization url after loading the bind endpoint', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      authorization_url: 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=abc',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    render(<Page />)

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled()
      expect(mockAssign).toHaveBeenCalledWith('https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=abc')
    })
  })

  it('should show retry action when loading the bind endpoint fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('failed'))

    render(<Page />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'common.operation.retry' })).toBeInTheDocument()
    })
  })
})
