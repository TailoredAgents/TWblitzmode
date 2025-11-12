'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';

export interface MaintenanceAccessButtonProps {
  visible: boolean;
  className?: string;
}

/**
 * Renders a low-visibility maintenance access control for developers.
 * Button is deliberately subtle but still accessible for keyboard/screen readers.
 */
export const MaintenanceAccessButton: React.FC<MaintenanceAccessButtonProps> = ({ visible, className }) => {
  const router = useRouter();

  if (!visible) {
    return null;
  }

  return (
    <button
      type="button"
      aria-label="Open maintenance access"
      onClick={() => {
        router.push('/maintenance');
      }}
      className={`fixed bottom-4 right-4 z-50 inline-flex items-center gap-2 rounded-full border border-white/30 bg-[#0E1A2A]/80 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white opacity-40 shadow-lg shadow-black/20 transition hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#FFD400] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0E1A2A] ${
        className ?? ''
      }`}
    >
      <ShieldCheck className="h-3.5 w-3.5" />
      Maintenance
    </button>
  );
};
