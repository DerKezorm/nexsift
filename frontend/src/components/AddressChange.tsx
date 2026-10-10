/**
 * The question a changed public address asks (`lib/addressQuestion.ts`): authentik still knows the old redirect
 * address of an entry the button made, and a provider entered by hand has to be changed by the operator. The page
 * shows this question, and only "Save" sends the same request again with the confirmation.
 */
import { useTranslation } from 'react-i18next'

import type { AddressQuestion } from '../lib/addressQuestion'
import { Button } from './ui'

export function AddressChangeQuestion({ question, busy = false, onCancel, onConfirm }: { question: AddressQuestion; busy?: boolean; onCancel: () => void; onConfirm: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-warn-500/40 bg-warn-500/10 p-3" role="alertdialog" aria-label={t('oidc.admin.address')} data-testid="address-change">
      {question.count > 0 && <p className="text-sm text-mist-200">{t('oidc.admin.addressChangeConfirm', { address: question.address })}</p>}
      {question.hand > 0 && <p className="text-sm text-mist-200">{t('oidc.admin.addressChangeHand', { count: question.hand })}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t('settings.providers.cancel')}
        </Button>
        <Button variant="danger" size="sm" loading={busy} onClick={onConfirm}>
          {t('common.save')}
        </Button>
      </div>
    </div>
  )
}
