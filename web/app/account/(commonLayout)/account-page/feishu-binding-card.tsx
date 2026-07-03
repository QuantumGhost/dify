'use client'

import { Button } from '@langgenius/dify-ui/button'
import { Input } from '@langgenius/dify-ui/input'
import { toast } from '@langgenius/dify-ui/toast'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_PREFIX } from '@/config'
import { openOAuthPopup } from '@/hooks/use-oauth'
import {
  getAccountIMBindings,
  updateAccountIMBinding,
} from './client'

const titleClassName = `
  system-sm-semibold text-text-secondary
`
const descriptionClassName = `
  mt-1 body-xs-regular text-text-tertiary
`
const FEISHU_BINDING_QUERY_KEY = ['account', 'im-bindings', 'feishu']

type OAuthCallbackPayload = {
  success?: boolean
  error?: string
  errorDescription?: string
}

type FeishuBindingFormProps = {
  initialOpenId: string
  initialUserId: string
  isSubmitting: boolean
  onSave: (payload: { open_id?: string, user_id?: string }) => Promise<void>
}

function FeishuBindingForm({
  initialOpenId,
  initialUserId,
  isSubmitting,
  onSave,
}: FeishuBindingFormProps) {
  const { t } = useTranslation()
  const [openId, setOpenId] = useState(initialOpenId)
  const [userId, setUserId] = useState(initialUserId)

  return (
    <div className="mt-4 space-y-4">
      <div>
        <label className={titleClassName} htmlFor="feishu-binding-open-id">
          {t('account.feishuBindingOpenId', { ns: 'common' })}
        </label>
        <Input
          id="feishu-binding-open-id"
          aria-label={t('account.feishuBindingOpenId', { ns: 'common' })}
          className="mt-2"
          value={openId}
          onChange={event => setOpenId(event.target.value)}
        />
      </div>
      <div>
        <label className={titleClassName} htmlFor="feishu-binding-user-id">
          {t('account.feishuBindingUserId', { ns: 'common' })}
        </label>
        <Input
          id="feishu-binding-user-id"
          aria-label={t('account.feishuBindingUserId', { ns: 'common' })}
          className="mt-2"
          value={userId}
          onChange={event => setUserId(event.target.value)}
        />
      </div>
      <div className="flex justify-end">
        <Button
          disabled={isSubmitting || (!openId.trim() && !userId.trim())}
          onClick={() => onSave({ open_id: openId.trim() || undefined, user_id: userId.trim() || undefined })}
        >
          {t('operation.save', { ns: 'common' })}
        </Button>
      </div>
    </div>
  )
}

export default function FeishuBindingCard() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [isSaving, setIsSaving] = useState(false)
  const [isBindingWithOAuth, setIsBindingWithOAuth] = useState(false)

  const bindingQuery = useQuery({
    queryKey: FEISHU_BINDING_QUERY_KEY,
    queryFn: getAccountIMBindings,
    retry: false,
  })
  const binding = bindingQuery.data?.data.find(item => item.provider === 'feishu')
  const formKey = `${binding?.open_id || ''}:${binding?.user_id || ''}`

  const saveBinding = async (payload: { open_id?: string, user_id?: string }) => {
    try {
      setIsSaving(true)
      await updateAccountIMBinding({
        provider: 'feishu',
        open_id: payload.open_id,
        user_id: payload.user_id,
      })
      await queryClient.invalidateQueries({ queryKey: FEISHU_BINDING_QUERY_KEY })
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
    }
    catch (error) {
      toast.error((error as Error).message)
    }
    finally {
      setIsSaving(false)
    }
  }

  const bindWithOAuth = () => {
    setIsBindingWithOAuth(true)

    try {
      openOAuthPopup(`${API_PREFIX}/account/im-bindings/feishu/oauth-link`, async (callbackData?: OAuthCallbackPayload) => {
        setIsBindingWithOAuth(false)

        if (!callbackData)
          return

        if (callbackData.success === false) {
          toast.error(callbackData.errorDescription || callbackData.error || t('account.feishuBindingOAuthTip', { ns: 'common' }))
          return
        }

        await queryClient.invalidateQueries({ queryKey: FEISHU_BINDING_QUERY_KEY })
        toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      })
    }
    catch (error) {
      setIsBindingWithOAuth(false)
      toast.error((error as Error).message)
    }
  }

  return (
    <div className="mb-8">
      <div className={titleClassName}>{t('account.feishuBindingTitle', { ns: 'common' })}</div>
      <div className={descriptionClassName}>{t('account.feishuBindingTip', { ns: 'common' })}</div>
      <div className="mt-2">
        <Button disabled={isBindingWithOAuth} onClick={bindWithOAuth}>
          {t('account.feishuBindingOAuth', { ns: 'common' })}
        </Button>
      </div>
      <div className="mt-2 body-xs-regular text-text-tertiary">
        {t('account.feishuBindingOAuthTip', { ns: 'common' })}
      </div>
      <FeishuBindingForm
        key={formKey}
        initialOpenId={binding?.open_id || ''}
        initialUserId={binding?.user_id || ''}
        isSubmitting={isSaving}
        onSave={saveBinding}
      />
    </div>
  )
}
