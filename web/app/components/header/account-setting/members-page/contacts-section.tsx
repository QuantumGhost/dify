'use client'

import { Button } from '@langgenius/dify-ui/button'
import { cn } from '@langgenius/dify-ui/cn'
import { Dialog, DialogCloseButton, DialogContent, DialogTitle } from '@langgenius/dify-ui/dialog'
import { Input } from '@langgenius/dify-ui/input'
import { toast } from '@langgenius/dify-ui/toast'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useContacts, useCreateExternalContact } from '@/features/workspace-contacts/client'

const badgeBaseClassName = 'inline-flex rounded-md px-2 py-1 system-2xs-medium-uppercase'

const formatProviderLabel = (provider: string | null) => {
  if (!provider)
    return null
  if (provider === 'dingtalk')
    return 'DingTalk'
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

export default function ContactsSection() {
  const { t } = useTranslation()
  const { data, isPending } = useContacts()
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const createExternalContactMutation = useCreateExternalContact()

  const contacts = data?.data ?? []

  const resetForm = () => {
    setName('')
    setEmail('')
  }

  const handleCloseDialog = () => {
    if (createExternalContactMutation.isPending)
      return
    resetForm()
    setIsDialogOpen(false)
  }

  const handleCreateExternalContact = async () => {
    try {
      await createExternalContactMutation.mutateAsync({
        name,
        email,
      })
      toast.success(t('actionMsg.modifiedSuccessfully', { ns: 'common' }))
      handleCloseDialog()
    }
    catch (error) {
      toast.error(error instanceof Error ? error.message : t('actionMsg.modifiedUnsuccessfully', { ns: 'common' }))
    }
  }

  return (
    <>
      <div className="mt-8">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="system-md-semibold text-text-secondary">
              {t('nodes.humanInput.deliveryMethod.emailConfigure.memberSelector.title', { ns: 'workflow' })}
            </div>
          </div>
          <Button
            variant="secondary"
            onClick={() => setIsDialogOpen(true)}
          >
            {t('operation.add', { ns: 'common' })}
          </Button>
        </div>
        <div className="overflow-visible lg:overflow-visible">
          <div className="flex min-w-120 items-center border-b border-divider-regular py-1.75">
            <div className="min-w-0 grow px-3 system-xs-medium-uppercase text-text-tertiary">{t('members.name', { ns: 'common' })}</div>
            <div className="w-48 shrink-0 px-3 system-xs-medium-uppercase text-text-tertiary">{t('account.email', { ns: 'common' })}</div>
            <div className="w-44 shrink-0 px-3 system-xs-medium-uppercase text-text-tertiary">{t('menus.status', { ns: 'common' })}</div>
          </div>
          {isPending && (
            <div className="border-b border-divider-subtle px-3 py-4 system-sm-regular text-text-tertiary">
              {t('loading', { ns: 'common' })}
            </div>
          )}
          {!isPending && contacts.length === 0 && (
            <div className="border-b border-divider-subtle px-3 py-4 system-sm-regular text-text-tertiary">
              {t('noData', { ns: 'common' })}
            </div>
          )}
          {!isPending && contacts.map((contact) => {
            const deliveryLabel = contact.delivery_status === 'im'
              ? t('account.imBinding.status.bound', { ns: 'common' })
              : contact.delivery_status === 'email'
                ? t('account.email', { ns: 'common' })
                : t('account.imBinding.status.unbound', { ns: 'common' })
            const providerLabel = formatProviderLabel(contact.delivery_provider)

            return (
              <div
                key={contact.id}
                className="flex min-w-120 items-center border-b border-divider-subtle px-3 py-3"
              >
                <div className="min-w-0 grow">
                  <div className="system-sm-medium text-text-secondary">{contact.name}</div>
                  {providerLabel && (
                    <div className="mt-0.5 system-xs-regular text-text-tertiary">{providerLabel}</div>
                  )}
                </div>
                <div className="w-48 shrink-0 px-3 system-sm-regular text-text-secondary">
                  {contact.email || '-'}
                </div>
                <div className="w-44 shrink-0 px-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        badgeBaseClassName,
                        contact.delivery_status === 'im'
                          ? 'bg-state-success-hover text-text-success'
                          : contact.delivery_status === 'email'
                            ? 'bg-state-accent-hover text-text-accent-secondary'
                            : 'bg-state-base-hover text-text-tertiary',
                      )}
                    >
                      {deliveryLabel}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <Dialog open={isDialogOpen} onOpenChange={open => !open && handleCloseDialog()}>
        <DialogContent className="w-120 max-w-120 p-0">
          <DialogCloseButton />
          <div className="px-6 pt-6 pb-3">
            <DialogTitle className="title-2xl-semi-bold text-text-primary">
              {t('nodes.humanInput.deliveryMethod.emailConfigure.memberSelector.title', { ns: 'workflow' })}
            </DialogTitle>
          </div>
          <div className="space-y-4 px-6 py-2">
            <div>
              <div className="mb-1 flex h-6 items-center system-sm-medium text-text-secondary">
                {t('account.name', { ns: 'common' })}
              </div>
              <Input
                value={name}
                onChange={event => setName(event.target.value)}
                disabled={createExternalContactMutation.isPending}
              />
            </div>
            <div>
              <div className="mb-1 flex h-6 items-center system-sm-medium text-text-secondary">
                {t('account.email', { ns: 'common' })}
              </div>
              <Input
                value={email}
                onChange={event => setEmail(event.target.value)}
                disabled={createExternalContactMutation.isPending}
              />
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 px-6 pb-6">
            <Button disabled={createExternalContactMutation.isPending} onClick={handleCloseDialog}>
              {t('operation.cancel', { ns: 'common' })}
            </Button>
            <Button
              variant="primary"
              disabled={!name.trim() || !email.trim() || createExternalContactMutation.isPending}
              loading={createExternalContactMutation.isPending}
              onClick={handleCreateExternalContact}
            >
              {t('operation.add', { ns: 'common' })}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
