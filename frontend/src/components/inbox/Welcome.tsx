import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Symbol, type SymbolName } from '../Symbol'

/** The empty inbox at the very start: what nexsift does, and the three steps to the first message. */
export function Welcome() {
  const { t } = useTranslation()
  const steps: { key: string; symbol: SymbolName; to: string }[] = [
    { key: 'source', symbol: 'plug', to: '/sources?add=1' },
    { key: 'test', symbol: 'play', to: '/sources' },
    { key: 'phone', symbol: 'phone', to: '/rules#targets' },
  ]
  return (
    <div className="ns-scroll flex flex-1 flex-col gap-5 overflow-y-auto p-5">
      <div>
        <h2 className="text-lg font-semibold text-mist-100">{t('welcome.title')}</h2>
        <p className="mt-1 text-sm text-mist-400">{t('welcome.lead')}</p>
      </div>
      <ol className="flex flex-col gap-2.5">
        {steps.map((step, index) => (
          <li key={step.key}>
            <Link to={step.to} className="flex items-start gap-3 rounded-xl border border-ink-700 bg-ink-850/70 p-3.5 transition-colors hover:border-accent-500/50 hover:bg-ink-800">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-500/15 text-sm font-semibold text-accent-400">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium text-mist-100">
                  <Symbol name={step.symbol} className="h-4 w-4 text-mist-500" />
                  {t(`welcome.${step.key}.title`)}
                </span>
                <span className="mt-0.5 block text-xs text-mist-500">{t(`welcome.${step.key}.text`)}</span>
              </span>
              <Symbol name="chevronRight" className="mt-1 h-4 w-4 text-mist-600" />
            </Link>
          </li>
        ))}
      </ol>
      <p className="text-xs text-mist-600">{t('welcome.keys')}</p>
    </div>
  )
}
