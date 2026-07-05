import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FeishuBindingCard from '../feishu-binding-card'

describe('FeishuBindingCard', () => {
  it('should render connect action when integrate is unbound and link exists', () => {
    const onBind = vi.fn()

    render(
      <FeishuBindingCard
        integrate={{
          provider: 'feishu_im',
          created_at: null,
          is_bound: false,
          link: '/account/feishu-im/bind',
        }}
        onBind={onBind}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.integrations.connect' }))

    expect(onBind).toHaveBeenCalledTimes(1)
  })

  it('should show connected status when integrate is already bound', () => {
    render(
      <FeishuBindingCard
        integrate={{
          provider: 'feishu_im',
          created_at: 1,
          is_bound: true,
          link: null,
        }}
        onBind={vi.fn()}
      />,
    )

    expect(screen.getByText('common.dataSource.notion.connected')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('should show configuration required when integrate cannot provide a bind link', () => {
    render(
      <FeishuBindingCard
        integrate={{
          provider: 'feishu_im',
          created_at: null,
          is_bound: false,
          link: null,
        }}
        onBind={vi.fn()}
      />,
    )

    expect(screen.getByText('common.modelProvider.toBeConfigured')).toBeInTheDocument()
  })
})
