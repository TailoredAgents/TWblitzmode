import React from 'react';
import { useI18n } from '../../contexts/I18nContext';
import { cn } from '../../lib/utils';

interface LanguageSwitcherProps {
  className?: string;
}

const LanguageSwitcher: React.FC<LanguageSwitcherProps> = ({ className }) => {
  const { availableLocales, locale, setLocale, t } = useI18n();

  const getLabelForLocale = React.useCallback(
    (code: string) => {
      if (typeof Intl !== 'undefined' && typeof Intl.DisplayNames === 'function') {
        try {
          const formatter = new Intl.DisplayNames([locale], { type: 'language' });
          const label = formatter.of(code);
          if (label) {
            return label;
          }
        } catch {
          // fallback below
        }
      }
      switch (code) {
        case 'en':
          return 'English';
        case 'es':
          return 'Español';
        default:
          return code;
      }
    },
    [locale],
  );

  return (
    <label className={cn('inline-flex items-center gap-2 text-xs text-muted-foreground', className)}>
      <span className="font-medium">{t('nav.language')}</span>
      <select
        aria-label="Select interface language"
        className="rounded-md border border-border bg-background/60 px-2 py-1 text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
        value={locale}
        onChange={(event) => setLocale(event.target.value as typeof locale)}
      >
        {availableLocales.map((code) => (
          <option key={code} value={code}>
            {getLabelForLocale(code)}
          </option>
        ))}
      </select>
    </label>
  );
};

export default LanguageSwitcher;
