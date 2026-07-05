import { queryOptions } from '@tanstack/react-query'
// eslint-disable-next-line no-restricted-imports
import { del, get, put } from '@/service/base'

export type IMProvider = 'feishu' | 'dingtalk' | 'slack'
export type IMInstallMode = 'self_built' | 'isv'
export type IMScopeType = 'deployment' | 'tenant'
export type IMAppConfigStatus = 'configured' | 'missing' | 'invalid' | 'unsupported'
export type IMTokenStatus = 'not_applicable' | 'unknown' | 'valid' | 'expiring' | 'expired' | 'refresh_failed'
export type IMInstallStatus = 'not_applicable' | 'pending' | 'installed' | 'uninstalled'
export type IMEventMode = 'long_connection' | 'webhook'

export type IMAppContext = {
  provider: IMProvider
  install_mode: IMInstallMode
  scope_type: IMScopeType
  scope_id: string
  status: IMAppConfigStatus
  token_status: IMTokenStatus
  install_status: IMInstallStatus
  event_mode: IMEventMode | null
  app_id_configured: boolean
  app_secret_configured: boolean
  errors: string[]
}

export type IMSelfBuiltConfigRecord = {
  id: string
  tenant_id: string
  provider: IMProvider
  scope_type: IMScopeType
  scope_id: string
  provider_workspace_id: string | null
  app_id: string | null
  app_secret_configured: boolean
  verification_token_configured: boolean
  encrypt_key_configured: boolean
  event_mode: IMEventMode | null
  created_at: string
  updated_at: string
}

export type IMInstallationRecord = {
  id: string
  tenant_id: string
  provider: IMProvider
  install_mode: IMInstallMode
  scope_type: IMScopeType
  scope_id: string
  install_status: IMInstallStatus
  token_status: IMTokenStatus
  provider_workspace_id: string | null
  access_token_configured: boolean
  refresh_token_configured: boolean
  access_token_expires_at: string | null
  token_refreshed_at: string | null
  token_refresh_error: string | null
  installed_at: string | null
  uninstalled_at: string | null
  created_at: string
  updated_at: string
}

type SelfBuiltConfigEnvelope = {
  data: IMSelfBuiltConfigRecord | null
}

type InstallationEnvelope = {
  data: IMInstallationRecord | null
}

export type UpsertSelfBuiltConfigPayload = {
  provider_workspace_id?: string
  app_id?: string
  app_secret?: string
  verification_token?: string
  encrypt_key?: string
  event_mode?: IMEventMode
}

export type UpsertInstallationPayload = {
  provider_workspace_id?: string
  install_status?: IMInstallStatus
  access_token?: string
  refresh_token?: string
}

export const imAppContextQueryOptions = (provider: IMProvider) =>
  queryOptions<IMAppContext>({
    queryKey: ['workspace-im-apps', provider, 'context'],
    queryFn: () => get<IMAppContext>(`/workspaces/current/im-apps/${provider}`),
  })

export const selfBuiltConfigQueryOptions = (provider: Extract<IMProvider, 'feishu' | 'dingtalk'>) =>
  queryOptions<IMSelfBuiltConfigRecord | null>({
    queryKey: ['workspace-im-apps', provider, 'self-built-config'],
    queryFn: async () => {
      const response = await get<SelfBuiltConfigEnvelope>(`/workspaces/current/im-apps/${provider}/self-built-config`)
      return response.data
    },
  })

export const installationQueryOptions = (provider: Extract<IMProvider, 'slack'>, installMode: Extract<IMInstallMode, 'isv'>) =>
  queryOptions<IMInstallationRecord | null>({
    queryKey: ['workspace-im-apps', provider, 'installations', installMode],
    queryFn: async () => {
      const response = await get<InstallationEnvelope>(`/workspaces/current/im-apps/${provider}/installations/${installMode}`)
      return response.data
    },
  })

export const upsertSelfBuiltConfig = (
  provider: Extract<IMProvider, 'feishu' | 'dingtalk'>,
  body: UpsertSelfBuiltConfigPayload,
) => {
  return put<IMSelfBuiltConfigRecord>(`/workspaces/current/im-apps/${provider}/self-built-config`, { body })
}

export const deleteSelfBuiltConfig = (provider: Extract<IMProvider, 'feishu' | 'dingtalk'>) => {
  return del(`/workspaces/current/im-apps/${provider}/self-built-config`)
}

export const upsertInstallation = (
  provider: Extract<IMProvider, 'slack'>,
  installMode: Extract<IMInstallMode, 'isv'>,
  body: UpsertInstallationPayload,
) => {
  return put<IMInstallationRecord>(`/workspaces/current/im-apps/${provider}/installations/${installMode}`, { body })
}

export const deleteInstallation = (
  provider: Extract<IMProvider, 'slack'>,
  installMode: Extract<IMInstallMode, 'isv'>,
) => {
  return del(`/workspaces/current/im-apps/${provider}/installations/${installMode}`)
}
