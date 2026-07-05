'use client'

import {
  AlertDialog,
  AlertDialogActions,
  AlertDialogCancelButton,
  AlertDialogConfirmButton,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from '@langgenius/dify-ui/alert-dialog'
import { Button } from '@langgenius/dify-ui/button'
import { cn } from '@langgenius/dify-ui/cn'
import { Dialog, DialogCloseButton, DialogContent, DialogTitle } from '@langgenius/dify-ui/dialog'
import { Input } from '@langgenius/dify-ui/input'
import { Select, SelectContent, SelectItem, SelectItemIndicator, SelectItemText, SelectTrigger } from '@langgenius/dify-ui/select'
import { toast } from '@langgenius/dify-ui/toast'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  deleteInstallation,
  deleteSelfBuiltConfig,
  imAppContextQueryOptions,
  installationQueryOptions,
  selfBuiltConfigQueryOptions,
  upsertInstallation,
  upsertSelfBuiltConfig,
} from '@/features/workspace-im-apps/client'

const badgeBaseClassName = 'inline-flex rounded-md px-2 py-1 system-2xs-medium-uppercase'

type Props = {
  canEdit: boolean
}

type SelfBuiltProvider = 'feishu' | 'dingtalk'

type SelfBuiltDraft = {
  provider_workspace_id: string
  app_id: string
  app_secret: string
  verification_token: string
  encrypt_key: string
  event_mode: 'long_connection' | 'webhook'
}

type InstallationDraft = {
  provider_workspace_id: string
  install_status: 'pending' | 'installed' | 'uninstalled'
  access_token: string
  refresh_token: string
}

const formatProviderLabel = (provider: string) => {
  if (provider === 'dingtalk')
    return 'DingTalk'
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

const formatEnumLabel = (value: string | null | undefined) => {
  if (!value)
    return '-'
  return value
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const getStatusBadgeClassName = (value: string) => {
  if (value === 'configured' || value === 'installed' || value === 'valid')
    return 'bg-state-success-hover text-text-success'
  if (value === 'invalid' || value === 'expired' || value === 'refresh_failed' || value === 'unsupported')
    return 'bg-state-warning-hover text-text-warning'
  return 'bg-state-base-hover text-text-tertiary'
}

const buildSelfBuiltDraft = (config?: {
  provider_workspace_id: string | null
  app_id: string | null
  event_mode: 'long_connection' | 'webhook' | null
}) => ({
  provider_workspace_id: config?.provider_workspace_id ?? '',
  app_id: config?.app_id ?? '',
  app_secret: '',
  verification_token: '',
  encrypt_key: '',
  event_mode: config?.event_mode ?? 'long_connection',
} satisfies SelfBuiltDraft)

const buildInstallationDraft = (record?: {
  provider_workspace_id: string | null
  install_status: 'pending' | 'installed' | 'uninstalled' | 'not_applicable'
}) => ({
  provider_workspace_id: record?.provider_workspace_id ?? '',
  install_status: record?.install_status === 'not_applicable' ? 'pending' : record?.install_status ?? 'pending',
  access_token: '',
  refresh_token: '',
} satisfies InstallationDraft)

function FieldItem({ label, value }: { label: string, value: string }) {
  return (
    <div>
      <div className="system-2xs-medium-uppercase text-text-tertiary">{label}</div>
      <div className="mt-1 system-sm-medium break-all text-text-secondary">{value || '-'}</div>
    </div>
  )
}

function SelfBuiltCard({ provider, canEdit }: { provider: SelfBuiltProvider, canEdit: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)
  const { data: context, isPending: isContextPending, refetch: refetchContext } = useQuery(imAppContextQueryOptions(provider))
  const { data: config, isPending: isConfigPending } = useQuery(selfBuiltConfigQueryOptions(provider))
  const [draft, setDraft] = useState<SelfBuiltDraft>(() => buildSelfBuiltDraft())
  const saveMutation = useMutation({
    mutationFn: () => upsertSelfBuiltConfig(provider, draft),
    onSuccess: async () => {
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      setIsDialogOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: imAppContextQueryOptions(provider).queryKey }),
        queryClient.invalidateQueries({ queryKey: selfBuiltConfigQueryOptions(provider).queryKey }),
      ])
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    },
  })
  const removeMutation = useMutation({
    mutationFn: () => deleteSelfBuiltConfig(provider),
    onSuccess: async () => {
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      setShowRemoveConfirm(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: imAppContextQueryOptions(provider).queryKey }),
        queryClient.invalidateQueries({ queryKey: selfBuiltConfigQueryOptions(provider).queryKey }),
      ])
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    },
  })

  const openDialog = () => {
    setDraft(buildSelfBuiltDraft(config ?? undefined))
    setIsDialogOpen(true)
  }

  const isSaveDisabled
    = !draft.app_id.trim()
      || !draft.app_secret.trim()
      || (Boolean(config?.verification_token_configured) && !draft.verification_token.trim())
      || (Boolean(config?.encrypt_key_configured) && !draft.encrypt_key.trim())
      || saveMutation.isPending
  const contextStatus = context?.status ?? 'missing'

  return (
    <>
      <div className="rounded-xl border-[0.5px] border-components-card-border bg-components-card-bg p-4 shadow-xs">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="system-md-semibold text-text-primary">
              {formatProviderLabel(provider)}
            </div>
            <div className="mt-1 body-xs-regular text-text-tertiary">
              {formatEnumLabel(context?.install_mode)}
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="small"
              onClick={() => refetchContext()}
            >
              {t('operation.refresh', { ns: 'common' })}
            </Button>
            {canEdit && (
              <Button
                variant="secondary"
                size="small"
                onClick={openDialog}
              >
                {t('operation.edit', { ns: 'common' })}
              </Button>
            )}
          </div>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <FieldItem
            label={t('members.imApps.effectiveStatus', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(context?.status)}
          />
          <FieldItem
            label={t('account.imBinding.scope', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : context ? `${formatEnumLabel(context.scope_type)} · ${context.scope_id}` : '-'}
          />
          <FieldItem
            label={t('members.imApps.tenantConfig', { ns: 'common' })}
            value={isConfigPending ? t('loading', { ns: 'common' }) : config ? t('account.imBinding.status.bound', { ns: 'common' }) : t('account.imBinding.status.unbound', { ns: 'common' })}
          />
          <FieldItem
            label={t('members.imApps.eventMode', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(context?.event_mode)}
          />
          <FieldItem
            label={t('members.imApps.providerWorkspace', { ns: 'common' })}
            value={config?.provider_workspace_id ?? '-'}
          />
          <div>
            <div className="system-2xs-medium-uppercase text-text-tertiary">
              {t('members.imApps.effectiveStatus', { ns: 'common' })}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  badgeBaseClassName,
                  getStatusBadgeClassName(contextStatus),
                )}
              >
                {isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(contextStatus)}
              </span>
            </div>
          </div>
        </div>
        {context?.errors?.length
          ? (
              <div className="mt-4 rounded-lg bg-state-warning-hover px-3 py-2">
                <div className="system-xs-medium text-text-warning">{t('error', { ns: 'common' })}</div>
                <div className="mt-1 space-y-1">
                  {context.errors.map(error => (
                    <div key={error} className="body-xs-regular break-all text-text-warning">
                      {error}
                    </div>
                  ))}
                </div>
              </div>
            )
          : null}
      </div>
      <Dialog open={isDialogOpen} onOpenChange={open => !open && !saveMutation.isPending && setIsDialogOpen(false)}>
        <DialogContent className="w-160 max-w-160 p-0">
          <DialogCloseButton />
          <div className="px-6 pt-6 pb-3">
            <DialogTitle className="title-2xl-semi-bold text-text-primary">
              {formatProviderLabel(provider)}
            </DialogTitle>
            <div className="mt-2 body-xs-regular text-text-tertiary">
              {t('members.imApps.secretReplaceHint', { ns: 'common' })}
            </div>
          </div>
          <div className="grid gap-4 px-6 py-2">
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.providerWorkspace', { ns: 'common' })}</div>
              <Input
                value={draft.provider_workspace_id}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, provider_workspace_id: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.appId', { ns: 'common' })}</div>
              <Input
                value={draft.app_id}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, app_id: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.appSecret', { ns: 'common' })}</div>
              <Input
                type="password"
                value={draft.app_secret}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, app_secret: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.verificationToken', { ns: 'common' })}</div>
              <Input
                type="password"
                value={draft.verification_token}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, verification_token: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.encryptKey', { ns: 'common' })}</div>
              <Input
                type="password"
                value={draft.encrypt_key}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, encrypt_key: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.eventMode', { ns: 'common' })}</div>
              <Select
                value={draft.event_mode}
                disabled={saveMutation.isPending}
                onValueChange={(eventMode) => {
                  if (!eventMode)
                    return
                  setDraft(prev => ({ ...prev, event_mode: eventMode as SelfBuiltDraft['event_mode'] }))
                }}
              >
                <SelectTrigger size="medium">
                  {formatEnumLabel(draft.event_mode)}
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="long_connection">
                    <SelectItemText>{formatEnumLabel('long_connection')}</SelectItemText>
                    <SelectItemIndicator />
                  </SelectItem>
                  <SelectItem value="webhook">
                    <SelectItemText>{formatEnumLabel('webhook')}</SelectItemText>
                    <SelectItemIndicator />
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 px-6 pt-4 pb-6">
            <div>
              {config && canEdit && (
                <Button
                  variant="ghost"
                  disabled={removeMutation.isPending || saveMutation.isPending}
                  onClick={() => setShowRemoveConfirm(true)}
                >
                  {t('operation.delete', { ns: 'common' })}
                </Button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                disabled={saveMutation.isPending}
                onClick={() => setIsDialogOpen(false)}
              >
                {t('operation.cancel', { ns: 'common' })}
              </Button>
              <Button
                variant="primary"
                loading={saveMutation.isPending}
                disabled={isSaveDisabled}
                onClick={() => saveMutation.mutate()}
              >
                {t('operation.save', { ns: 'common' })}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={showRemoveConfirm} onOpenChange={open => !open && setShowRemoveConfirm(false)}>
        <AlertDialogContent backdropProps={{ forceRender: true }}>
          <div className="flex flex-col gap-2 px-6 pt-6 pb-4">
            <AlertDialogTitle className="title-2xl-semi-bold text-text-primary">
              {t('members.imApps.removeSelfBuilt', { ns: 'common' })}
            </AlertDialogTitle>
            <AlertDialogDescription className="system-md-regular whitespace-pre-wrap text-text-tertiary">
              {t('members.imApps.removeSelfBuiltConfirm', { ns: 'common' })}
            </AlertDialogDescription>
          </div>
          <AlertDialogActions>
            <AlertDialogCancelButton>{t('operation.cancel', { ns: 'common' })}</AlertDialogCancelButton>
            <AlertDialogConfirmButton
              disabled={removeMutation.isPending}
              onClick={() => removeMutation.mutate()}
            >
              {t('operation.confirm', { ns: 'common' })}
            </AlertDialogConfirmButton>
          </AlertDialogActions>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function SlackInstallationCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)
  const { data: context, isPending: isContextPending, refetch: refetchContext } = useQuery(imAppContextQueryOptions('slack'))
  const { data: installation, isPending: isInstallationPending } = useQuery(installationQueryOptions('slack', 'isv'))
  const [draft, setDraft] = useState<InstallationDraft>(() => buildInstallationDraft())
  const saveMutation = useMutation({
    mutationFn: () => upsertInstallation('slack', 'isv', draft),
    onSuccess: async () => {
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      setIsDialogOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: imAppContextQueryOptions('slack').queryKey }),
        queryClient.invalidateQueries({ queryKey: installationQueryOptions('slack', 'isv').queryKey }),
      ])
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    },
  })
  const removeMutation = useMutation({
    mutationFn: () => deleteInstallation('slack', 'isv'),
    onSuccess: async () => {
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      setShowRemoveConfirm(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: imAppContextQueryOptions('slack').queryKey }),
        queryClient.invalidateQueries({ queryKey: installationQueryOptions('slack', 'isv').queryKey }),
      ])
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    },
  })

  const openDialog = () => {
    setDraft(buildInstallationDraft(installation ?? undefined))
    setIsDialogOpen(true)
  }

  const isSaveDisabled
    = !draft.install_status
      || (draft.install_status === 'installed' && !draft.access_token.trim())
      || (Boolean(installation?.access_token_configured) && !draft.access_token.trim())
      || (Boolean(installation?.refresh_token_configured) && !draft.refresh_token.trim())
      || saveMutation.isPending

  return (
    <>
      <div className="rounded-xl border-[0.5px] border-components-card-border bg-components-card-bg p-4 shadow-xs">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="system-md-semibold text-text-primary">Slack</div>
            <div className="mt-1 body-xs-regular text-text-tertiary">
              {formatEnumLabel(context?.install_mode)}
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="small"
              onClick={() => refetchContext()}
            >
              {t('operation.refresh', { ns: 'common' })}
            </Button>
            {canEdit && (
              <Button
                variant="secondary"
                size="small"
                onClick={openDialog}
              >
                {t('operation.edit', { ns: 'common' })}
              </Button>
            )}
          </div>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <FieldItem
            label={t('members.imApps.effectiveStatus', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(context?.status)}
          />
          <FieldItem
            label={t('account.imBinding.scope', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : context ? `${formatEnumLabel(context.scope_type)} · ${context.scope_id}` : '-'}
          />
          <FieldItem
            label={t('members.imApps.installation', { ns: 'common' })}
            value={isInstallationPending ? t('loading', { ns: 'common' }) : installation ? t('account.imBinding.status.bound', { ns: 'common' }) : t('account.imBinding.status.unbound', { ns: 'common' })}
          />
          <FieldItem
            label={t('members.imApps.installStatus', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(context?.install_status)}
          />
          <FieldItem
            label={t('members.imApps.tokenStatus', { ns: 'common' })}
            value={isContextPending ? t('loading', { ns: 'common' }) : formatEnumLabel(context?.token_status)}
          />
          <FieldItem
            label={t('members.imApps.providerWorkspace', { ns: 'common' })}
            value={installation?.provider_workspace_id ?? '-'}
          />
        </div>
        {context?.errors?.length
          ? (
              <div className="mt-4 rounded-lg bg-state-warning-hover px-3 py-2">
                <div className="system-xs-medium text-text-warning">{t('error', { ns: 'common' })}</div>
                <div className="mt-1 space-y-1">
                  {context.errors.map(error => (
                    <div key={error} className="body-xs-regular break-all text-text-warning">
                      {error}
                    </div>
                  ))}
                </div>
              </div>
            )
          : null}
      </div>
      <Dialog open={isDialogOpen} onOpenChange={open => !open && !saveMutation.isPending && setIsDialogOpen(false)}>
        <DialogContent className="w-160 max-w-160 p-0">
          <DialogCloseButton />
          <div className="px-6 pt-6 pb-3">
            <DialogTitle className="title-2xl-semi-bold text-text-primary">Slack</DialogTitle>
            <div className="mt-2 body-xs-regular text-text-tertiary">
              {t('members.imApps.secretReplaceHint', { ns: 'common' })}
            </div>
          </div>
          <div className="grid gap-4 px-6 py-2">
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.providerWorkspace', { ns: 'common' })}</div>
              <Input
                value={draft.provider_workspace_id}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, provider_workspace_id: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.installStatus', { ns: 'common' })}</div>
              <Select
                value={draft.install_status}
                disabled={saveMutation.isPending}
                onValueChange={(installStatus) => {
                  if (!installStatus)
                    return
                  setDraft(prev => ({ ...prev, install_status: installStatus as InstallationDraft['install_status'] }))
                }}
              >
                <SelectTrigger size="medium">
                  {formatEnumLabel(draft.install_status)}
                </SelectTrigger>
                <SelectContent>
                  {['pending', 'installed', 'uninstalled'].map(value => (
                    <SelectItem key={value} value={value}>
                      <SelectItemText>{formatEnumLabel(value)}</SelectItemText>
                      <SelectItemIndicator />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.accessToken', { ns: 'common' })}</div>
              <Input
                type="password"
                value={draft.access_token}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, access_token: event.target.value }))}
              />
            </div>
            <div>
              <div className="mb-1 system-sm-medium text-text-secondary">{t('members.imApps.refreshToken', { ns: 'common' })}</div>
              <Input
                type="password"
                value={draft.refresh_token}
                disabled={saveMutation.isPending}
                onChange={event => setDraft(prev => ({ ...prev, refresh_token: event.target.value }))}
              />
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 px-6 pt-4 pb-6">
            <div>
              {installation && canEdit && (
                <Button
                  variant="ghost"
                  disabled={removeMutation.isPending || saveMutation.isPending}
                  onClick={() => setShowRemoveConfirm(true)}
                >
                  {t('operation.delete', { ns: 'common' })}
                </Button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                disabled={saveMutation.isPending}
                onClick={() => setIsDialogOpen(false)}
              >
                {t('operation.cancel', { ns: 'common' })}
              </Button>
              <Button
                variant="primary"
                loading={saveMutation.isPending}
                disabled={isSaveDisabled}
                onClick={() => saveMutation.mutate()}
              >
                {t('operation.save', { ns: 'common' })}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={showRemoveConfirm} onOpenChange={open => !open && setShowRemoveConfirm(false)}>
        <AlertDialogContent backdropProps={{ forceRender: true }}>
          <div className="flex flex-col gap-2 px-6 pt-6 pb-4">
            <AlertDialogTitle className="title-2xl-semi-bold text-text-primary">
              {t('members.imApps.removeInstallation', { ns: 'common' })}
            </AlertDialogTitle>
            <AlertDialogDescription className="system-md-regular whitespace-pre-wrap text-text-tertiary">
              {t('members.imApps.removeInstallationConfirm', { ns: 'common' })}
            </AlertDialogDescription>
          </div>
          <AlertDialogActions>
            <AlertDialogCancelButton>{t('operation.cancel', { ns: 'common' })}</AlertDialogCancelButton>
            <AlertDialogConfirmButton
              disabled={removeMutation.isPending}
              onClick={() => removeMutation.mutate()}
            >
              {t('operation.confirm', { ns: 'common' })}
            </AlertDialogConfirmButton>
          </AlertDialogActions>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export default function IMAppsSection({ canEdit }: Props) {
  const { t } = useTranslation()

  return (
    <div className="mt-8">
      <div className="mb-3">
        <div className="system-md-semibold text-text-secondary">
          {t('members.imApps.title', { ns: 'common' })}
        </div>
        <div className="mt-1 body-xs-regular text-text-tertiary">
          {t('members.imApps.description', { ns: 'common' })}
        </div>
      </div>
      <div className="grid gap-4">
        <SelfBuiltCard provider="feishu" canEdit={canEdit} />
        <SelfBuiltCard provider="dingtalk" canEdit={canEdit} />
        <SlackInstallationCard canEdit={canEdit} />
      </div>
    </div>
  )
}
