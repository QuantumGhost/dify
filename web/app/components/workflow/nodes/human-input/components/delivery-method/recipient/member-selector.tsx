'use client'
import type { FC } from 'react'
import type { Recipient } from '@/app/components/workflow/nodes/human-input/types'
import type { Member } from '@/models/common'
import { Button } from '@langgenius/dify-ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@langgenius/dify-ui/popover'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ACCOUNT_SETTING_TAB } from '@/app/components/header/account-setting/constants'
import { useModalContextSelector } from '@/context/modal-context'
import MemberList from './member-list'

const i18nPrefix = 'nodes.humanInput'

type Props = Readonly<{
  value: Recipient[]
  email: string
  onSelect: (value: string) => void
  list: Member[]
}>

const MemberSelector: FC<Props> = ({
  value,
  email,
  onSelect,
  list = [],
}) => {
  const { t } = useTranslation()
  const setShowAccountSettingModal = useModalContextSelector(state => state.setShowAccountSettingModal)
  const [open, setOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')

  const handleSelect = useCallback((memberId: string) => {
    onSelect(memberId)
    setOpen(false)
  }, [onSelect])

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={(
            <Button
              className="w-full justify-between data-popup-open:bg-state-accent-hover"
              variant="ghost-accent"
            >
              <span aria-hidden className="mr-1 i-ri-contacts-book-line size-4" />
              <div>{t(`${i18nPrefix}.deliveryMethod.emailConfigure.memberSelector.trigger`, { ns: 'workflow' })}</div>
            </Button>
          )}
        />
        <PopoverContent
          placement="bottom-end"
          sideOffset={4}
          alignOffset={35}
          popupClassName="border-none bg-transparent p-0 shadow-none backdrop-blur-none"
        >
          <MemberList
            searchValue={searchValue}
            list={list}
            value={value}
            onSearchChange={setSearchValue}
            onSelect={handleSelect}
            email={email}
          />
        </PopoverContent>
      </Popover>
      <div className="flex justify-end">
        <Button
          variant="ghost"
          size="small"
          onClick={() => setShowAccountSettingModal({ payload: ACCOUNT_SETTING_TAB.MEMBERS })}
        >
          {t('settings.members', { ns: 'common' })}
        </Button>
      </div>
    </div>
  )
}

export default MemberSelector
