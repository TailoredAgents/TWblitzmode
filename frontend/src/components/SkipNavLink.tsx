'use client';

import React from 'react';
import { useI18n } from '../contexts/I18nContext';
import { cn } from '../lib/utils';

interface SkipNavLinkProps {
  targetId?: string;
  className?: string;
}

const SkipNavLink: React.FC<SkipNavLinkProps> = ({ targetId = 'main-content', className }) => {
  const { t } = useI18n();

  return (
    <a href={`#${targetId}`} className={cn('skip-nav-link', className)}>
      {t('accessibility.skipToContent')}
    </a>
  );
};

export default SkipNavLink;

