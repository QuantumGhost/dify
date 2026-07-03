// eslint-disable-next-line no-restricted-imports
import { get, put } from '@/service/base'

export type AccountIMBinding = {
  provider: string
  open_id?: string | null
  user_id?: string | null
}

export type AccountIMBindingListResponse = {
  data: AccountIMBinding[]
}

export const getAccountIMBindings = (): Promise<AccountIMBindingListResponse> => {
  return get<AccountIMBindingListResponse>('/account/im-bindings')
}

export const updateAccountIMBinding = (body: {
  provider: string
  open_id?: string
  user_id?: string
}): Promise<AccountIMBinding> => {
  return put<AccountIMBinding>(`/account/im-bindings/${body.provider}`, {
    body: {
      open_id: body.open_id || undefined,
      user_id: body.user_id || undefined,
    },
  })
}
