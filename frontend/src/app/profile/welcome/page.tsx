'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  ArrowRight,
  CheckCircle2,
  Cookie as CookieIcon,
  Info,
  Loader2,
  ShieldCheck,
  LogOut,
} from 'lucide-react';

import GlassCard from '../../../components/ui/GlassCard';
import { useToastActions } from '../../../components/ui/ToastContainer';
import { apiService } from '../../../services/api';
import type { OnboardingChecklist } from '../../../types';
import { useI18n } from '../../../contexts/I18nContext';
import { getAccessToken } from '../../../lib/authToken';
import { performLogout } from '../../../lib/logout';

function parseJwt(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split('.');
    if (!payload) return null;
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    if (typeof window === 'undefined') {
      return null;
    }
    const decoded = atob(normalized);
    return JSON.parse(decoded);
  } catch (err) {
    console.warn('Failed to parse JWT payload', err);
    return null;
  }
}

const cookieTips = [
  'Use an incognito/private window to copy your LinkedIn session cookie (li_at).',
  'Keep your LinkedIn session active in the background to avoid expirations.',
  'Upload optional JSESSIONID and User-Agent values for greater stability.',
];

function WelcomePageContent() {
  const params = useSearchParams();
  const { success, error } = useToastActions();
  const errorRef = useRef(error);
  useEffect(() => {
    errorRef.current = error;
  }, [error]);
  const { t } = useI18n();
  const [acceptedAt, setAcceptedAt] = useState<string | null>(null);
  const [cookieStatus, setCookieStatus] = useState<string>('missing');
  const [onboardingFlags, setOnboardingFlags] = useState<OnboardingChecklist | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let isActive = true;
    const initializeOnboarding = async () => {
      try {
        // Safely parse JWT token
        const token = getAccessToken();
        const claims = token ? parseJwt(token) : null;

        if (claims) {
          try {
            const accepted = claims.accepted_terms === true || claims.accepted_terms === 'true';
            const acceptedAt = accepted ? (claims.accepted_terms_at as string | null | undefined) ?? 'accepted' : null;
            const status = (claims.cookie_status as string | undefined) ?? 'missing';

            if (!isActive) {
              return;
            }
            setAcceptedAt(acceptedAt);
            setCookieStatus(status);
            setOnboardingFlags({
              accept_terms: !accepted,
              cookie_required: status !== 'valid',
            });
          } catch (claimsError) {
            console.warn('Failed to process JWT claims', claimsError);
            // Set default onboarding state if claims parsing fails
            if (!isActive) {
              return;
            }
            setOnboardingFlags({
              accept_terms: true,
              cookie_required: true,
            });
          }
        } else {
          // No valid token, set default onboarding state
          if (!isActive) {
            return;
          }
          setOnboardingFlags({
            accept_terms: true,
            cookie_required: true,
          });
        }

        // Load user state from API
        try {
          const userResponse = await apiService.getCurrentUser();
          if (!isActive) {
            return;
          }
          if (userResponse.data?.accepted_terms_at) {
            setAcceptedAt(userResponse.data.accepted_terms_at);
          }
        } catch (apiError) {
          console.error('Failed to load user context', apiError);
          // Don't show error toast for initial load failures - user might not be authenticated yet
        }
      } catch (err) {
        console.error('Failed to initialize onboarding', err);
        if (isActive) {
          errorRef.current('Unable to load onboarding status', 'Please refresh the page to try again.');
        }

        // Set fallback state to prevent crashes
        if (isActive) {
          setOnboardingFlags({
            accept_terms: true,
            cookie_required: true,
          });
        }
      } finally {
        if (isActive) {
          setLoading(false);
        }
      }
    };

    void initializeOnboarding();

    return () => {
      isActive = false;
    };
  }, []);

  const needsTerms = useMemo(() => {
    if (onboardingFlags) {
      return onboardingFlags.accept_terms;
    }
    return !acceptedAt;
  }, [acceptedAt, onboardingFlags]);

  const cookieRequired = useMemo(() => {
    if (onboardingFlags) {
      return onboardingFlags.cookie_required;
    }
    return cookieStatus !== 'valid';
  }, [cookieStatus, onboardingFlags]);

  const handleAcceptTerms = async () => {
    setAccepting(true);
    try {
      const response = await apiService.acceptTerms();
      if (response.data?.accepted_at) {
        setAcceptedAt(response.data.accepted_at);

        // Safely update onboarding flags
        setOnboardingFlags((prev) => {
          const currentFlags = prev ?? {
            cookie_required: cookieRequired,
            accept_terms: true,
          };
          return {
            ...currentFlags,
            accept_terms: false,
          };
        });

        success('Terms accepted', 'Thanks for confirming compliance.');
      } else {
        const errorMessage = response.error ?? 'No confirmation returned from server.';
        error('Unable to confirm acceptance', errorMessage);
      }
    } catch (err) {
      console.error('Accept terms failed', err);
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred.';
      error('Unable to record acceptance', `Please try again. ${errorMessage}`);
    } finally {
      setAccepting(false);
    }
  };

  const handleOpenCookieJar = async () => {
    try {
      await apiService.setUserPreference('preferredDashboardView', 'settings-cookie-jar');
      await apiService.setUserPreference('preferredSettingsTab', 'cookie-jar');
    } catch (preferencesError) {
      console.warn('Failed to set user preferences', preferencesError);
      // Fallback to sessionStorage for immediate redirect
      try {
        if (typeof window !== 'undefined') {
          const sessionStorageRef = window.sessionStorage;
          if (sessionStorageRef) {
            sessionStorageRef.setItem('preferredDashboardView', 'settings-cookie-jar');
            sessionStorageRef.setItem('preferredSettingsTab', 'cookie-jar');
          }
        }
      } catch (storageError) {
        console.warn('Failed to set session storage preferences', storageError);
        // Continue navigation even if storage fails
      }
    }

    // Use window.location.replace for immediate, forceful navigation
    if (typeof window !== 'undefined') {
      window.location.replace('/dashboard');
    }
  };

  const handleSkip = () => {
    // Use window.location.replace for immediate, forceful navigation
    if (typeof window !== 'undefined') {
      window.location.replace('/dashboard');
    }
  };

  const handleLogout = useCallback(async () => {
    if (loggingOut) {
      return;
    }
    setLoggingOut(true);
    try {
      await performLogout();
    } finally {
      setLoggingOut(false);
    }
  }, [loggingOut]);

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <GlassCard className="px-8 py-6 flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Preparing your onboarding checklist…</span>
        </GlassCard>
      </div>
    );
  }

  const highlightCookie = params?.get('focus') === 'cookie' || cookieRequired;

  return (
    <div className="min-h-screen bg-background px-4 py-12">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={() => { void handleLogout(); }}
            data-testid="logout-button"
            className="inline-flex items-center gap-2 rounded-lg border border-border/40 bg-background/60 px-3 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10 hover:text-destructive-foreground disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={t('nav.logout', 'Log out')}
            disabled={loggingOut}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            <span>{loggingOut ? t('profile.loggingOut', 'Logging out…') : t('nav.logout', 'Log out')}</span>
          </button>
        </div>

        <GlassCard className="p-6 space-y-3">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-6 h-6 text-primary" />
            <div>
              <h1 className="text-xl font-semibold text-primary">{t('profile.welcomeTitle')}</h1>
              <p className="text-sm text-muted-foreground">Complete these quick steps to unlock outreach tooling for your team.</p>
            </div>
          </div>
        </GlassCard>

        <GlassCard className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CheckCircle2 className={`w-5 h-5 ${needsTerms ? 'text-muted-foreground' : 'text-emerald-500'}`} />
              <div>
                <h2 className="text-lg font-semibold text-foreground">Step 1 – Accept Terms of Service</h2>
                <p className="text-sm text-muted-foreground">{t('profile.complianceNote')}</p>
              </div>
            </div>
            {!needsTerms && (
              <span className="text-xs uppercase tracking-wide text-emerald-500">Completed</span>
            )}
          </div>

          {needsTerms ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                We require every team member to acknowledge our responsible-AI guidelines before accessing prospect data. Review the policy and confirm below.
              </p>
              <button
                type="button"
                onClick={handleAcceptTerms}
                disabled={accepting}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-60"
              >
                {accepting ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                {accepting ? 'Recording…' : 'I agree to the terms'}
              </button>
            </div>
          ) : (
            <div className="rounded-lg border border-border/20 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
              Terms accepted {acceptedAt && acceptedAt !== 'accepted' ? `on ${new Date(acceptedAt).toLocaleString()}` : ''}. You can revisit the policy in Settings → Security at any time.
            </div>
          )}
        </GlassCard>

        <GlassCard className={`p-6 space-y-4 ${highlightCookie ? 'ring-2 ring-primary/40' : ''}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CookieIcon className={`w-5 h-5 ${cookieRequired ? 'text-primary' : 'text-emerald-500'}`} />
              <div>
                <h2 className="text-lg font-semibold text-foreground">Step 2 – Upload a valid LinkedIn Cookie Jar</h2>
                <p className="text-sm text-muted-foreground">Securely store your session so PhantomBuster and outreach automations stay authorized.</p>
              </div>
            </div>
            {!cookieRequired && <span className="text-xs uppercase tracking-wide text-emerald-500">Ready</span>}
          </div>

          {cookieRequired ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                We detected that your current LinkedIn session is <strong className="text-foreground">{cookieStatus}</strong>. Follow the guided upload to refresh your cookie jar before continuing.
              </p>
              <ul className="space-y-2 text-sm text-muted-foreground">
                {cookieTips.map((tip) => (
                  <li key={tip} className="flex items-start gap-2">
                    <Info className="w-4 h-4 mt-0.5 text-primary" />
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleOpenCookieJar}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
                >
                  Open Cookie Jar
                  <ArrowRight className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={handleSkip}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border/40 text-sm font-medium text-muted-foreground hover:text-foreground"
                >
                  Skip for now
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-border/20 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
              Cookie jar is current. If you encounter 401 errors later, you can re-upload in Settings → Cookie Jar.
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}

export default function WelcomePage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center">
      <GlassCard className="px-8 py-6 flex items-center gap-3">
        <div className="w-5 h-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm text-muted-foreground">Loading onboarding...</span>
      </GlassCard>
    </div>}>
      <WelcomePageContent />
    </Suspense>
  );
}
