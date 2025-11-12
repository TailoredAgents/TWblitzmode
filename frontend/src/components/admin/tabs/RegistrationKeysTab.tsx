'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Clipboard, KeyRound, Loader2 } from 'lucide-react';

import GlassCard from '../../ui/GlassCard';
import { apiService } from '../../../services/api';
import type { RegistrationKeyListItem, RegistrationKeyResponse } from '../../../types';
import { useToastActions } from '../../ui/ToastContainer';
import { cn } from '../../../lib/utils';

interface RegistrationKeysTabProps {
  organizationId: number;
  onKeysUpdated?: () => void;
}

const RECENT_KEY_LIMIT = 6;

const statusStyles = new Map<string, string>([
  ['active', 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'],
  ['unused', 'bg-blue-500/15 text-blue-600 dark:text-blue-300'],
  ['released', 'bg-amber-500/15 text-amber-600 dark:text-amber-300'],
  ['expired', 'bg-rose-500/15 text-rose-600 dark:text-rose-300'],
]);

function buildShareUrl(path: string): string {
  if (!path) return '';
  try {
    if (typeof window === 'undefined') {
      return path;
    }
    return new URL(path, window.location.origin).toString();
  } catch (err) {
    console.error('Failed to construct registration key share URL', err);
    return path;
  }
}

function formatRegistrationExpiry(value?: string | null): string {
  if (!value) return 'Link deactivates after first download.';
  try {
    const formatted = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
    return `Link expires after first download or on ${formatted}.`;
  } catch (err) {
    console.error('Failed to format registration key expiry', err);
    return 'Link deactivates after first download.';
  }
}

async function copyToClipboard(value: string): Promise<void> {
  if (!navigator.clipboard) {
    throw new Error('Clipboard API not available');
  }
  await navigator.clipboard.writeText(value);
}

export function RegistrationKeysTab({ organizationId, onKeysUpdated }: RegistrationKeysTabProps) {
  const { success, error } = useToastActions();
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [generateCount, setGenerateCount] = useState(1);
  const [registrationKeys, setRegistrationKeys] = useState<RegistrationKeyListItem[]>([]);
  const [recentKeys, setRecentKeys] = useState<RegistrationKeyResponse[]>([]);
  const [searchTerm, setSearchTerm] = useState('');

  const loadKeys = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiService.getRegistrationKeys(organizationId);
      const payload = response.data ?? [];
      setRegistrationKeys(payload);
    } catch (err) {
      console.error('Failed to load registration keys', err);
      error('Unable to load registration keys');
    } finally {
      setLoading(false);
    }
  }, [organizationId, error]);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  const handleCopy = useCallback(
    async (value: string, message: string) => {
      try {
        await copyToClipboard(value);
        success(message);
      } catch (err) {
        console.error('Clipboard error', err);
        error('Unable to copy automatically', 'Please copy the highlighted value manually.');
      }
    },
    [success, error]
  );

  const handleGenerateKeys = useCallback(async () => {
    if (generateCount < 1) {
      error('Enter a valid key count');
      return;
    }

    setActionPending(true);
    try {
      const response = await apiService.generateRegistrationKeys(organizationId, generateCount);
      const generated = (response.data ?? []).slice(0, RECENT_KEY_LIMIT);
      setRecentKeys(generated);
      await loadKeys();
      onKeysUpdated?.();
      success(
        `Generated ${generated.length} registration ${generated.length === 1 ? 'key' : 'keys'}`,
        'Share these securely with your team.'
      );
    } catch (err) {
      console.error('Failed to generate registration keys', err);
      error('Unable to generate registration keys', 'Please try again later.');
    } finally {
      setActionPending(false);
    }
  }, [generateCount, organizationId, loadKeys, error, success, onKeysUpdated]);

  const handleReleaseKey = useCallback(
    async (keyId: number) => {
      setActionPending(true);
      try {
        await apiService.releaseRegistrationKey(organizationId, keyId);
        await loadKeys();
        onKeysUpdated?.();
        success('Seat released', 'The registration key is now available for reuse.');
      } catch (err) {
        console.error('Failed to release registration key', err);
        error('Unable to release key right now');
      } finally {
        setActionPending(false);
      }
    },
    [organizationId, loadKeys, onKeysUpdated, error, success]
  );

  const filteredKeys = useMemo(() => {
    if (!searchTerm.trim()) {
      return registrationKeys;
    }
    const term = searchTerm.trim().toLowerCase();
    return registrationKeys.filter((key) => {
      const assignedTo = key.assigned_to?.toLowerCase() ?? '';
      const email = key.assigned_email?.toLowerCase() ?? '';
      const keyValue = key.key?.toLowerCase() ?? key.masked_key.toLowerCase();
      return (
        keyValue.includes(term) ||
        assignedTo.includes(term) ||
        email.includes(term)
      );
    });
  }, [registrationKeys, searchTerm]);

  return (
    <div className="space-y-6">
      <GlassCard className="p-6 space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Registration Keys (Retired)</h2>
            <p className="text-sm text-muted-foreground">
              Tallwave now uses self‑service seating. Teammates can self‑seat: Login → enter
              <span className="mx-1 font-mono">Tallwave123</span>→ click “+ Team member”.
            </p>
          </div>
          <div className="text-xs text-muted-foreground">No action required.</div>
        </div>

              {recentKeys.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-primary">
                    <ArrowRight className="w-4 h-4" />
                    Legacy keys (archived):
                  </div>
            <div className="grid gap-3 md:grid-cols-2">
              {recentKeys.map((key) => {
                const shareUrl = key.download_url ? buildShareUrl(key.download_url) : '';
                return (
                  <div key={key.id} className="space-y-2 rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 space-y-1">
                        <span className="text-[11px] font-semibold uppercase text-muted-foreground">Key</span>
                        <div className="rounded-md border border-border/40 bg-background/80 px-2 py-1.5">
                          <span className="break-all font-mono text-xs text-foreground">{key.key}</span>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleCopy(key.key, 'Registration key copied')}
                        className="inline-flex items-center gap-1 rounded-md border border-primary/40 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10"
                      >
                        <Clipboard className="w-3 h-3" />
                        Copy
                      </button>
                    </div>
                    {shareUrl && (
                      <div className="flex flex-col gap-2 rounded-md border border-border/40 bg-background/50 px-2 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] font-semibold text-muted-foreground">Secure link</span>
                          <button
                            type="button"
                            onClick={() => handleCopy(shareUrl, 'Secure link copied')}
                            className="inline-flex items-center gap-1 rounded-md border border-primary/30 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10"
                          >
                            <Clipboard className="w-3 h-3" />
                            Copy link
                          </button>
                        </div>
                        <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                          <a
                            href={key.download_url ?? '#'}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-primary hover:text-primary/80"
                          >
                            <ArrowRight className="h-3 w-3" />
                            Open link
                          </a>
                          <span className="text-right">{formatRegistrationExpiry(key.expires_at)}</span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <input
              type="search"
              placeholder="Search keys or assignees"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              className="w-full md:w-72 px-3 py-2 rounded-lg border border-border/40 bg-background text-sm"
            />
            <span className="text-xs text-muted-foreground">
              {filteredKeys.length} of {registrationKeys.length} keys
            </span>
          </div>
        </div>

        <div className="overflow-x-auto rounded-lg border border-border/20">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground bg-muted/30">
              <tr>
                <th className="py-2 px-3">Key</th>
                <th className="py-2 px-3">Status</th>
                <th className="py-2 px-3">Assigned To</th>
                <th className="py-2 px-3">Created</th>
                <th className="py-2 px-3">Expires</th>
                <th className="py-2 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin mx-auto mb-2" />
                    Loading registration keys…
                  </td>
                </tr>
              ) : filteredKeys.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                    No registration keys match the current filters.
                  </td>
                </tr>
              ) : (
                filteredKeys.map((key) => {
                  const status = key.status?.toLowerCase() ?? 'unused';
                  const badgeClass = statusStyles.get(status) ?? 'bg-muted text-muted-foreground';
                  return (
                    <tr key={key.id} className="border-t border-border/10">
                      <td className="py-3 px-3">
                        <code className="break-all text-xs font-mono text-foreground/90">{key.key}</code>
                      </td>
                      <td className="py-3 px-3">
                        <span className={cn('inline-flex items-center rounded-full px-2 py-1 text-xs font-medium', badgeClass)}>
                          {status}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex flex-col text-xs text-muted-foreground">
                          <span className="text-foreground font-medium">{key.assigned_to ?? '—'}</span>
                          <span>{key.assigned_email ?? '—'}</span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-xs text-muted-foreground">{key.created_at_human ?? '—'}</td>
                      <td className="py-3 px-3 text-xs text-muted-foreground">{key.expires_at_human ?? '—'}</td>
                      <td className="py-3 px-3 text-right">
                        {status === 'active' ? (
                          <button
                            type="button"
                            onClick={() => handleReleaseKey(key.id)}
                            disabled={actionPending}
                            className="inline-flex items-center gap-1 rounded-md border border-border/40 px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                          >
                            Release
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleCopy(key.key ?? key.masked_key, 'Registration key copied')}
                            className="inline-flex items-center gap-1 rounded-md border border-border/40 px-3 py-1.5 text-xs font-medium hover:bg-muted"
                          >
                            Copy
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </div>
  );
}
