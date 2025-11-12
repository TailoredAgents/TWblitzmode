'use client';

import React, { useCallback, useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Loader2, ShieldAlert } from 'lucide-react';

const DEV_CODE_LENGTH = 4;
const API_BASE = '';

const ensureFingerprint = (): string => {
  if (typeof window === 'undefined') {
    return '';
  }

  const storageKey = 'vl_dev_fp';
  let existing = window.localStorage.getItem(storageKey);
  if (existing && existing.length >= 8) {
    return existing;
  }

  if (window.crypto?.randomUUID) {
    existing = window.crypto.randomUUID();
  } else {
    existing = `fp-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
  }
  window.localStorage.setItem(storageKey, existing);
  return existing;
};

export default function MaintenanceAccessPage(): React.ReactElement {
  const router = useRouter();
  const [deviceFingerprint, setDeviceFingerprint] = useState<string>('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setDeviceFingerprint(ensureFingerprint());
    }
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setError('');
      setStatusMessage('');
      setSubmitting(true);
      try {
        setStatusMessage('The Developer Portal has been retired.');
        setTimeout(() => router.replace('/'), 800);
      } finally {
        setSubmitting(false);
      }
    },
    [router]
  );

  return (
    <div className="flex min-h-screen flex-col bg-[#0E1A2A] text-white">
      <header className="flex items-center justify-between px-6 py-4">
        <button
          type="button"
          onClick={() => router.back()}
          className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
        <Link href="/" className="text-xs font-semibold uppercase tracking-widest text-white/60 hover:text-white">
          Tallwave
        </Link>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-12 sm:px-6">
        <div className="w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur">
          <div className="mb-6 flex items-center gap-3 text-white">
            <ShieldAlert className="h-6 w-6 text-[#FFD400]" />
            <div>
              <p className="text-sm font-semibold uppercase tracking-widest text-white/80">Restricted</p>
              <h1 className="text-2xl font-semibold text-white">Developer Portal retired</h1>
            </div>
          </div>
          <p className="mb-6 text-sm text-white/70">
            This portal has been retired and is no longer accessible. Continue to the main dashboard.
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <label className="block">
              <span className="text-xs uppercase tracking-widest text-white/60">Access code</span>
              <input
                autoFocus
                inputMode="numeric"
                maxLength={DEV_CODE_LENGTH}
                value={code}
                onChange={(event) => {
                  const nextValue = event.target.value.replace(/\D/g, '').slice(0, DEV_CODE_LENGTH);
                  setCode(nextValue);
                  if (error) {
                    setError('');
                  }
                  if (statusMessage) {
                    setStatusMessage('');
                  }
                }}
                className="mt-2 w-full rounded-xl border border-white/20 bg-white/10 px-4 py-3 text-lg tracking-[0.5rem] text-white outline-none transition focus:border-[#FFD400] focus:bg-white/15 focus:ring-2 focus:ring-[#FFD400]/40"
                placeholder="••••"
                aria-label="Developer maintenance access code"
              />
            </label>

            {error ? (
              <p className="text-sm text-[#FF8A80]" role="alert">
                {error}
              </p>
            ) : statusMessage ? (
              <p className="text-sm text-[#8BF6D4]">{statusMessage}</p>
            ) : null}

            <button
              type="submit"
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#FFD400] px-4 py-3 text-sm font-semibold uppercase tracking-widest text-[#0E1A2A] transition hover:bg-[#C9A700] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0E1A2A] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              <span>{submitting ? 'Redirecting…' : 'Return to Dashboard'}</span>
            </button>
          </form>

          <div className="mt-6 text-xs text-white/50">
            <p>Need help? Contact operations for assistance.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
