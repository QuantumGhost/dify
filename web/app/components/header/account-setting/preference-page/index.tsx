'use client'
import type { Locale } from '@/i18n-config'
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
import { Select, SelectContent, SelectItem, SelectItemIndicator, SelectItemText, SelectTrigger } from '@langgenius/dify-ui/select'
import { toast } from '@langgenius/dify-ui/toast'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTheme } from 'next-themes'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SkeletonContainer, SkeletonRectangle, SkeletonRow } from '@/app/components/base/skeleton'
import { useAppContext } from '@/context/app-context'
import { useLocale } from '@/context/i18n'
import { currentIMBindingQueryOptions, revokeCurrentIMBinding } from '@/features/account-profile/client'
import { setLocaleOnClient } from '@/i18n-config'
import { languages } from '@/i18n-config/language'
import { useRouter } from '@/next/navigation'
import { updateUserProfile } from '@/service/common'
import { timezones } from '@/utils/timezone'

type SelectOption = {
  value: string
  name: string
}

type TimezoneOption = {
  value: string | number
  name: string
}

const titleClassName = `
  mb-1 system-sm-medium text-text-secondary
`
const themes = ['system', 'light', 'dark'] as const
type ThemeOption = typeof themes[number]

const isThemeOption = (value: string): value is ThemeOption => {
  return (themes as readonly string[]).includes(value)
}

const formatProviderLabel = (provider: string) => {
  if (provider === 'dingtalk')
    return 'DingTalk'

  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

const formatScopeValue = (scopeType: string, scopeId: string) => {
  return `${scopeType.replaceAll('_', ' ')} · ${scopeId}`
}

function IMBindingSkeleton() {
  const { t } = useTranslation()

  return (
    <div
      role="status"
      aria-label={t('loading', { ns: 'common' })}
      className="rounded-xl border-[0.5px] border-components-card-border bg-components-card-bg p-4 shadow-xs"
    >
      <SkeletonContainer className="h-28">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 space-y-2">
            <SkeletonRectangle className="h-4 w-28 animate-pulse" />
            <SkeletonRectangle className="h-3 w-2/3 animate-pulse" />
          </div>
          <SkeletonRectangle className="h-6 w-18 animate-pulse rounded-md" />
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, index) => (
            <SkeletonRow key={index}>
              <div className="flex flex-1 flex-col gap-1">
                <SkeletonRectangle className="h-3 w-20 animate-pulse" />
                <SkeletonRectangle className="h-4 w-full animate-pulse" />
              </div>
            </SkeletonRow>
          ))}
        </div>
      </SkeletonContainer>
    </div>
  )
}

export default function PreferencePage() {
  const locale = useLocale()
  const { userProfile, mutateUserProfile } = useAppContext()
  const [editing, setEditing] = useState(false)
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const { theme, setTheme } = useTheme()
  const {
    data: currentIMBinding,
    isPending: isCurrentIMBindingLoading,
    isError: isCurrentIMBindingError,
    refetch: refetchCurrentIMBinding,
  } = useQuery(currentIMBindingQueryOptions())
  const languageOptions: SelectOption[] = languages.filter(item => item.supported)
  const themeOptions: SelectOption[] = [
    { value: 'system', name: t('account.appearanceFollowSystem', { ns: 'common' }) },
    { value: 'light', name: t('account.appearanceLight', { ns: 'common' }) },
    { value: 'dark', name: t('account.appearanceDark', { ns: 'common' }) },
  ]
  const revokeCurrentIMBindingMutation = useMutation({
    mutationFn: revokeCurrentIMBinding,
    onSuccess: async () => {
      setShowRevokeConfirm(false)
      queryClient.setQueryData(currentIMBindingQueryOptions().queryKey, null)
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      await queryClient.invalidateQueries({ queryKey: currentIMBindingQueryOptions().queryKey })
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    },
  })
  const selectedLanguage = languageOptions.find(item => item.value === (locale || userProfile.interface_language))
  const selectedTheme = themeOptions.find(item => item.value === (theme || 'system'))
  const selectedTimezone = timezones.find(item => item.value === userProfile.timezone)
  const handleSelectTheme = (item: SelectOption) => {
    if (isThemeOption(item.value))
      setTheme(item.value)
  }
  const handleSelectLanguage = async (item: SelectOption) => {
    const url = '/account/interface-language'
    const bodyKey = 'interface_language'
    setEditing(true)
    try {
      await updateUserProfile({ url, body: { [bodyKey]: item.value } })
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      setLocaleOnClient(item.value.toString() as Locale, false)
      router.refresh()
    }
    catch (e) {
      toast.error((e as Error).message)
    }
    finally {
      setEditing(false)
    }
  }
  const handleSelectTimezone = async (item: TimezoneOption) => {
    const url = '/account/timezone'
    const bodyKey = 'timezone'
    setEditing(true)
    try {
      await updateUserProfile({ url, body: { [bodyKey]: item.value } })
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      mutateUserProfile()
    }
    catch (e) {
      toast.error((e as Error).message)
    }
    finally {
      setEditing(false)
    }
  }
  return (
    <>
      <div className="mb-6">
        <div className={titleClassName}>{t('account.appearanceLabel', { ns: 'common' })}</div>
        <Select
          value={selectedTheme?.value ?? 'system'}
          onValueChange={(nextValue) => {
            if (!nextValue)
              return
            const nextItem = themeOptions.find(item => item.value === nextValue)
            if (nextItem)
              handleSelectTheme(nextItem)
          }}
        >
          <SelectTrigger size="medium">
            {selectedTheme?.name ?? t('account.appearanceFollowSystem', { ns: 'common' })}
          </SelectTrigger>
          <SelectContent>
            {themeOptions.map(item => (
              <SelectItem key={item.value} value={item.value}>
                <SelectItemText>{item.name}</SelectItemText>
                <SelectItemIndicator />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mb-6">
        <div className={titleClassName}>{t('language.displayLanguage', { ns: 'common' })}</div>
        <Select
          value={selectedLanguage?.value ?? null}
          disabled={editing}
          onValueChange={(nextValue) => {
            if (!nextValue)
              return
            const nextItem = languageOptions.find(item => item.value === nextValue)
            if (nextItem)
              handleSelectLanguage(nextItem)
          }}
        >
          <SelectTrigger size="medium">
            {selectedLanguage?.name ?? t('placeholder.select', { ns: 'common' })}
          </SelectTrigger>
          <SelectContent>
            {languageOptions.map(item => (
              <SelectItem key={item.value} value={item.value}>
                <SelectItemText>{item.name}</SelectItemText>
                <SelectItemIndicator />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mb-6">
        <div className={titleClassName}>{t('language.timezone', { ns: 'common' })}</div>
        <Select
          value={selectedTimezone ? String(selectedTimezone.value) : null}
          disabled={editing}
          onValueChange={(nextValue) => {
            if (!nextValue)
              return
            const nextItem = timezones.find(item => String(item.value) === nextValue)
            if (nextItem)
              handleSelectTimezone(nextItem)
          }}
        >
          <SelectTrigger size="medium">
            {selectedTimezone?.name ?? t('placeholder.select', { ns: 'common' })}
          </SelectTrigger>
          <SelectContent>
            {timezones.map(item => (
              <SelectItem key={item.value} value={String(item.value)}>
                <SelectItemText>{item.name}</SelectItemText>
                <SelectItemIndicator />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mb-6">
        <div className={titleClassName}>{t('account.imBinding.title', { ns: 'common' })}</div>
        <div className="mb-2 body-xs-regular text-text-tertiary">
          {t('account.imBinding.description', { ns: 'common' })}
        </div>
        {isCurrentIMBindingLoading && (
          <IMBindingSkeleton />
        )}
        {!isCurrentIMBindingLoading && isCurrentIMBindingError && (
          <div className="rounded-xl border-[0.5px] border-components-card-border bg-components-card-bg p-4 shadow-xs">
            <div className="system-sm-medium text-text-secondary">
              {t('account.imBinding.loadFailed', { ns: 'common' })}
            </div>
            <div className="mt-3">
              <Button
                variant="secondary"
                onClick={() => refetchCurrentIMBinding()}
              >
                {t('operation.refresh', { ns: 'common' })}
              </Button>
            </div>
          </div>
        )}
        {!isCurrentIMBindingLoading && !isCurrentIMBindingError && (
          <div className="rounded-xl border-[0.5px] border-components-card-border bg-components-card-bg p-4 shadow-xs">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="i-ri-message-3-line size-4 text-text-secondary" aria-hidden="true" />
                  <div className="system-sm-semibold text-text-primary">
                    {currentIMBinding
                      ? formatProviderLabel(currentIMBinding.provider)
                      : t('account.imBinding.status.unbound', { ns: 'common' })}
                  </div>
                </div>
                <div className="mt-1 body-xs-regular text-text-tertiary">
                  {currentIMBinding
                    ? currentIMBinding.provider_user_display_name || currentIMBinding.provider_user_id
                    : t('account.imBinding.emptyDescription', { ns: 'common' })}
                </div>
              </div>
              <span
                className={cn(
                  'inline-flex w-fit rounded-md px-2 py-1 system-2xs-medium-uppercase',
                  currentIMBinding
                    ? 'bg-state-success-hover text-text-success'
                    : 'bg-state-base-hover text-text-tertiary',
                )}
              >
                {currentIMBinding
                  ? t('account.imBinding.status.bound', { ns: 'common' })
                  : t('account.imBinding.status.unbound', { ns: 'common' })}
              </span>
            </div>
            {currentIMBinding && (
              <>
                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <div>
                    <div className="system-2xs-medium-uppercase text-text-tertiary">
                      {t('account.imBinding.provider', { ns: 'common' })}
                    </div>
                    <div className="mt-1 system-sm-medium text-text-secondary">
                      {formatProviderLabel(currentIMBinding.provider)}
                    </div>
                  </div>
                  <div>
                    <div className="system-2xs-medium-uppercase text-text-tertiary">
                      {t('account.imBinding.linkedAccount', { ns: 'common' })}
                    </div>
                    <div className="mt-1 system-sm-medium text-text-secondary">
                      {currentIMBinding.provider_user_display_name || currentIMBinding.provider_user_id}
                    </div>
                  </div>
                  <div>
                    <div className="system-2xs-medium-uppercase text-text-tertiary">
                      {t('account.imBinding.scope', { ns: 'common' })}
                    </div>
                    <div className="mt-1 system-sm-medium break-all text-text-secondary">
                      {formatScopeValue(currentIMBinding.scope_type, currentIMBinding.scope_id)}
                    </div>
                  </div>
                  <div>
                    <div className="system-2xs-medium-uppercase text-text-tertiary">
                      {t('account.imBinding.workspace', { ns: 'common' })}
                    </div>
                    <div className="mt-1 system-sm-medium break-all text-text-secondary">
                      {currentIMBinding.provider_workspace_id}
                    </div>
                  </div>
                </div>
                <div className="mt-5">
                  <Button
                    variant="secondary"
                    disabled={revokeCurrentIMBindingMutation.isPending}
                    onClick={() => setShowRevokeConfirm(true)}
                  >
                    {t('account.imBinding.revokeAction', { ns: 'common' })}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
      <AlertDialog open={showRevokeConfirm} onOpenChange={open => !open && setShowRevokeConfirm(false)}>
        <AlertDialogContent backdropProps={{ forceRender: true }}>
          <div className="flex flex-col gap-2 px-6 pt-6 pb-4">
            <AlertDialogTitle className="w-full truncate title-2xl-semi-bold text-text-primary">
              {t('account.imBinding.revokeAction', { ns: 'common' })}
            </AlertDialogTitle>
            <AlertDialogDescription className="w-full system-md-regular wrap-break-word whitespace-pre-wrap text-text-tertiary">
              {t('account.imBinding.revokeConfirmDescription', { ns: 'common' })}
            </AlertDialogDescription>
          </div>
          <AlertDialogActions>
            <AlertDialogCancelButton>{t('operation.cancel', { ns: 'common' })}</AlertDialogCancelButton>
            <AlertDialogConfirmButton
              disabled={revokeCurrentIMBindingMutation.isPending}
              onClick={() => revokeCurrentIMBindingMutation.mutate()}
            >
              {t('operation.confirm', { ns: 'common' })}
            </AlertDialogConfirmButton>
          </AlertDialogActions>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
