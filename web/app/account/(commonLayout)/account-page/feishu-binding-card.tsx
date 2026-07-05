'use client'
import type { GetAccountIntegratesResponse } from '@dify/contracts/api/console/account/types.gen'
import { Button } from '@langgenius/dify-ui/button'
import { useTranslation } from 'react-i18next'

type AccountIntegrate = GetAccountIntegratesResponse['data'][number]

type FeishuBindingCardProps = {
  integrate: AccountIntegrate | null
  onBind: () => void
}

export default function FeishuBindingCard({
  integrate,
  onBind,
}: FeishuBindingCardProps) {
  const { t } = useTranslation()

  if (!integrate)
    return null

  const isBound = integrate.is_bound
  const canBind = !isBound && Boolean(integrate.link)

  return (
    <div className="mb-8">
      <div className="mb-1 system-sm-semibold text-text-secondary">{t('account.feishuBinding', { ns: 'common' })}</div>
      <div className="mb-2 body-xs-regular text-text-tertiary">{t('account.feishuBindingTip', { ns: 'common' })}</div>
      <div className="flex items-center justify-between gap-2 rounded-lg bg-components-input-bg-normal p-3">
        <div className="system-sm-regular text-components-input-text-filled">
          {isBound
            ? t('dataSource.notion.connected', { ns: 'common' })
            : canBind
              ? t('integrations.connect', { ns: 'common' })
              : t('modelProvider.toBeConfigured', { ns: 'common' })}
        </div>
        {canBind && (
          <Button onClick={onBind}>
            {t('integrations.connect', { ns: 'common' })}
          </Button>
        )}
      </div>
    </div>
  )
}
