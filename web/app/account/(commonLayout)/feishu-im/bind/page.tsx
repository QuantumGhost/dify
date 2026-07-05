'use client'
import { Button } from '@langgenius/dify-ui/button'
import Cookies from 'js-cookie'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_PREFIX, CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from '@/config'

export default function FeishuBindPage() {
  const { t } = useTranslation()
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false)

  const startBinding = useCallback(async () => {
    setIsLoading(true)
    setHasError(false)
    try {
      const response = await fetch(`${API_PREFIX}/oauth/feishu-im/bind`, {
        method: 'GET',
        credentials: 'include',
        headers: {
          [CSRF_HEADER_NAME]: Cookies.get(CSRF_COOKIE_NAME()) || '',
        },
      })
      if (!response.ok)
        throw new Error('failed')
      const payload = await response.json() as { authorization_url: string }
      window.location.assign(payload.authorization_url)
    }
    catch {
      setHasError(true)
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void startBinding()
  }, [startBinding])

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-[640px] flex-col justify-center px-6">
      <div className="rounded-xl border border-divider-subtle bg-background-default p-6">
        <div className="mb-1 title-xl-semi-bold text-text-primary">{t('account.feishuBinding', { ns: 'common' })}</div>
        <div className="body-sm-regular text-text-tertiary">{t('account.feishuBindingTip', { ns: 'common' })}</div>
        {hasError && (
          <div className="mt-4">
            <Button onClick={startBinding}>
              {t('operation.retry', { ns: 'common' })}
            </Button>
          </div>
        )}
        {isLoading && !hasError && (
          <div className="mt-4 body-sm-regular text-text-tertiary">{t('integrations.connect', { ns: 'common' })}</div>
        )}
      </div>
    </div>
  )
}
