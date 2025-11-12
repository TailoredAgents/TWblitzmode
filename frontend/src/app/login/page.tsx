'use client';

import React, { useCallback, useEffect, useMemo, useState, type JSX } from 'react';
import { useRouter } from 'next/navigation';
import {
  AlertTriangle,
  Clock3,
  Cookie as CookieIcon,
  Loader2,
  Lock,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import { useToastActions } from '../../components/ui/ToastContainer';
import { useI18n } from '../../contexts/I18nContext';
import { apiService } from '../../services/api';
import type { LoginForm, LoginRosterUser, MasterAddTeamMemberPayload } from '../../types';
import { getAccessToken, setAccessToken } from '../../lib/authToken';

function parseJwt(token: string): Record<string, unknown> | null {
  try {
    const [, payload] = token.split('.');
    if (!payload) return null;
    if (typeof window === 'undefined') {
      return null;
    }
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const decoded = atob(normalized);
    return JSON.parse(decoded);
  } catch (err) {
    console.warn('Failed to parse JWT payload', err);
    return null;
  }
}

const MASTER_LOGIN_PASSWORD = process.env.NEXT_PUBLIC_MASTER_LOGIN_PASSWORD ?? 'Tallwave123';
const DEFAULT_AVATAR_BACKGROUND = '#E0ECFF';
const DEFAULT_AVATAR_FOREGROUND = '#1D4ED8';
const avatarBackgrounds = [
  DEFAULT_AVATAR_BACKGROUND,
  '#FFE6D9',
  '#E6F4EA',
  '#F3E8FF',
  '#FFF5CC',
  '#E5F6FF',
];
const avatarForegrounds = [
  DEFAULT_AVATAR_FOREGROUND,
  '#C2410C',
  '#047857',
  '#7C3AED',
  '#B45309',
  '#0C4A6E',
];

function avatarColors(userId: number): { background: string; foreground: string } {
  const index = Math.abs(userId) % avatarBackgrounds.length;
  // eslint-disable-next-line security/detect-object-injection
  const background = avatarBackgrounds[index] ?? DEFAULT_AVATAR_BACKGROUND;
  // eslint-disable-next-line security/detect-object-injection
  const foreground = avatarForegrounds[index] ?? DEFAULT_AVATAR_FOREGROUND;
  return { background, foreground };
}

function initialsFromName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) {
    return 'TT';
  }
  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) {
    return (parts[0]?.slice(0, 2) ?? 'TT').toUpperCase();
  }
  const first = parts[0]?.[0] ?? 'T';
  const lastSource = parts[parts.length - 1] ?? parts[0];
  const last = lastSource?.[0] ?? first;
  return `${first}${last}`.toUpperCase();
}

function formatLastSeen(value?: string | null): string {
  if (!value) {
    return 'Never signed in';
  }
  try {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return 'Active recently';
    }
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(parsed);
  } catch {
    return 'Active recently';
  }
}

const loginStyles = `
  .login-grid-mask {
    position: absolute;
    inset: -45%;
    background-image: linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
    background-size: 160px 160px;
    opacity: 0.12;
    transform: rotate(2deg);
    animation: loginGridDrift 36s ease-in-out infinite;
  }

  .login-diagonal-shine {
    position: absolute;
    inset: -20%;
    background: radial-gradient(ellipse at top, rgba(255, 255, 255, 0.16), transparent 60%) no-repeat;
    transform: rotate(-18deg);
    opacity: 0.35;
    animation: loginShine 16s ease-in-out infinite;
  }

  .login-orb {
    position: absolute;
    border-radius: 9999px;
    filter: blur(140px);
    mix-blend-mode: screen;
    opacity: 0.55;
    animation: loginOrbPulse 24s ease-in-out infinite;
  }

  .login-orb.orb-1 {
    top: -22%;
    left: 18%;
    width: 540px;
    height: 540px;
    background: rgba(255, 212, 0, 0.18);
  }

  .login-orb.orb-2 {
    bottom: -36%;
    right: 14%;
    width: 620px;
    height: 620px;
    background: rgba(103, 172, 255, 0.18);
    animation-delay: 4s;
  }

  .login-orb.orb-3 {
    top: 32%;
    right: -24%;
    width: 420px;
    height: 420px;
    background: rgba(255, 255, 255, 0.14);
    animation-delay: 8s;
  }

  .login-card-grid {
    position: absolute;
    inset: -220%;
    background-image: linear-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.08) 1px, transparent 1px);
    background-size: 120px 120px;
    opacity: 0.08;
    animation: loginInnerDrift 48s linear infinite;
  }

  .login-card-shimmer {
    position: absolute;
    inset: -220%;
    background: linear-gradient(120deg, transparent 40%, rgba(255, 255, 255, 0.16) 50%, transparent 60%);
    animation: loginShimmer 24s linear infinite;
    mix-blend-mode: screen;
  }

  .login-card-glow {
    position: absolute;
    inset: -1px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: inherit;
    box-shadow: inset 0 0 60px rgba(255, 255, 255, 0.05);
  }

  .login-inner-grid {
    position: absolute;
    inset: -140%;
    background-image: linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
    background-size: 56px 56px;
    opacity: 0.2;
    animation: loginInnerDrift 60s linear infinite;
  }

  @keyframes loginGridDrift {
    0% {
      transform: rotate(2deg) translate3d(0, 0, 0);
    }
    50% {
      transform: rotate(2deg) translate3d(60px, -45px, 0);
    }
    100% {
      transform: rotate(2deg) translate3d(-30px, 30px, 0);
    }
  }

  @keyframes loginOrbPulse {
    0%,
    100% {
      transform: scale(0.95);
      opacity: 0.4;
    }
    50% {
      transform: scale(1.12);
      opacity: 0.7;
    }
  }

  @keyframes loginShimmer {
    0% {
      transform: translate3d(-40%, 0, 0);
    }
    50% {
      transform: translate3d(40%, 0, 0);
    }
    100% {
      transform: translate3d(-40%, 0, 0);
    }
  }

  @keyframes loginShine {
    0%,
    100% {
      opacity: 0.25;
    }
    50% {
      opacity: 0.45;
    }
  }

  @keyframes loginInnerDrift {
    0% {
      transform: translate3d(0, 0, 0);
    }
    50% {
      transform: translate3d(-60px, 30px, 0);
    }
    100% {
      transform: translate3d(40px, -20px, 0);
    }
  }
`;

const loginGlobalStyles = `
  .animate-slow-pulse {
    animation: slowPulse 6s ease-in-out infinite;
  }

  @keyframes slowPulse {
    0%,
    100% {
      opacity: 0.5;
      transform: scale(1);
    }
    50% {
      opacity: 1;
      transform: scale(1.3);
    }
  }
`;
export default function LoginPage(): JSX.Element {
  const router = useRouter();
  const { success, error } = useToastActions();
  const { t } = useI18n();
  const translate = React.useCallback(
    (key: string, fallback: string) => t(`login.${key}`, fallback),
    [t],
  );

  const [roster, setRoster] = useState<LoginRosterUser[]>([]);
  const [rosterLoading, setRosterLoading] = useState(true);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [isUnlocked, setIsUnlocked] = useState(false);
  const [unlockInput, setUnlockInput] = useState('');
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [authenticatingUserId, setAuthenticatingUserId] = useState<number | null>(null);
  const [cookieBannerStatus, setCookieBannerStatus] = useState<string | null>(null);
  const [bannerOrganizationSlug, setBannerOrganizationSlug] = useState<string | null>(null);
  const [isAddMemberOpen, setIsAddMemberOpen] = useState(false);
  const [addMemberLoading, setAddMemberLoading] = useState(false);
  const [addMemberError, setAddMemberError] = useState<string | null>(null);
  const [newMemberForm, setNewMemberForm] = useState({
    name: '',
    email: '',
    li_at: '',
    jsessionid: '',
    cookie_label: '',
  });

  const loadRoster = useCallback(async () => {
    setRosterLoading(true);
    try {
      const response = await apiService.getLoginRoster();
      setRoster(response.data ?? []);
      setRosterError(null);
    } catch (err) {
      console.error('Failed to load login roster', err);
      setRoster([]);
      setRosterError('Unable to load Tallwave teammates. Please try again shortly.');
    } finally {
      setRosterLoading(false);
    }
  }, []);

  const resetNewMemberForm = useCallback(() => {
    setNewMemberForm({
      name: '',
      email: '',
      li_at: '',
      jsessionid: '',
      cookie_label: '',
    });
    setAddMemberError(null);
  }, []);

  useEffect(() => {
    if (isUnlocked) {
      void loadRoster();
    }
  }, [loadRoster, isUnlocked]);

  useEffect(() => {
    const token = getAccessToken();
    const claims = token ? parseJwt(token) : null;
    if (claims) {
      const status = claims.cookie_status as string | undefined;
      if (status && status !== 'valid') {
        setCookieBannerStatus(status);
        const slugClaim = claims.organization_slug as string | undefined;
        if (slugClaim) {
          setBannerOrganizationSlug(slugClaim);
        }
      }
    }
  }, []);

  const handleAddMemberFieldChange =
    (field: keyof typeof newMemberForm) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setNewMemberForm((prev) => ({
        ...prev,
        [field]: event.target.value,
      }));
      if (addMemberError) {
        setAddMemberError(null);
      }
    };

  const handleAddMemberSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = newMemberForm.name.trim();
    const trimmedEmail = newMemberForm.email.trim();
    const trimmedLiAt = newMemberForm.li_at.trim();
    const trimmedSession = newMemberForm.jsessionid.trim();
    const trimmedLabel = newMemberForm.cookie_label.trim();

    if (!trimmedName || !trimmedEmail) {
      const message = translate(
        'errors.addMemberRequired',
        'Name and email are required. Cookies can be added later in Settings → Cookie Jar.',
      );
      setAddMemberError(message);
      error(message, translate('errors.addMemberHint', 'Fill in the required details and try again.'));
      return;
    }

    setAddMemberLoading(true);
    try {
      const payload: MasterAddTeamMemberPayload = {
        master_password: MASTER_LOGIN_PASSWORD,
        name: trimmedName,
        email: trimmedEmail,
        user_agent: 'self-service-login',
      };
      if (trimmedLiAt) {
        payload.li_at = trimmedLiAt;
      }
      if (trimmedSession) {
        payload.jsessionid = trimmedSession;
      }
      if (trimmedLabel) {
        payload.cookie_label = trimmedLabel;
      }

      if (trimmedSession) {
        payload.jsessionid = trimmedSession;
      }

      if (trimmedLabel) {
        payload.cookie_label = trimmedLabel;
      }

      await apiService.addTeamMemberWithMaster(payload);

      success(
        translate('messages.memberAddedTitle', 'Tallwave teammate added!'),
        translate('messages.memberAddedBody', 'Their profile is now available in the roster.'),
      );
      setIsAddMemberOpen(false);
      resetNewMemberForm();
      await loadRoster();
    } catch (err) {
      console.error('Failed to add team member', err);
      const message = translate('errors.addMemberFailed', 'Unable to add the team member. Please try again.');
      setAddMemberError(message);
      error(message, translate('errors.tryAgain', 'Please try again later.'));
    } finally {
      setAddMemberLoading(false);
    }
  };

  const handleOpenAddMember = () => {
    resetNewMemberForm();
    setIsAddMemberOpen(true);
  };

  const handleCloseAddMember = () => {
    if (!addMemberLoading) {
      setIsAddMemberOpen(false);
    }
  };

  const filteredRoster = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) {
      return roster;
    }
    return roster.filter((user) => user.displayName.toLowerCase().includes(term));
  }, [roster, searchTerm]);

  const handleUnlockSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const normalized = unlockInput.trim();
    if (normalized === MASTER_LOGIN_PASSWORD) {
      setIsUnlocked(true);
      setUnlockError(null);
      setUnlockInput('');
      return;
    }

    const message = translate('errors.invalidMasterPassword', 'Incorrect password. Please try again.');
    setUnlockError(message);
    error(message, translate('errors.masterPasswordHint', 'Double-check the Tallwave access password.'));
  };

  const redirectTo = useCallback(
    (url: string) => {
      if (typeof window !== 'undefined') {
        window.location.replace(url);
      } else {
        router.replace(url);
      }
    },
    [router],
  );

  const handleUserLogin = async (user: LoginRosterUser) => {
    if (loading || authenticatingUserId !== null) {
      return;
    }
    setLoading(true);
    setAuthenticatingUserId(user.id);
    try {
      const loginPayload: LoginForm = {
        userId: user.id,
        password: MASTER_LOGIN_PASSWORD,
      };

      const response = await apiService.login(loginPayload);
      const token = response?.data?.access_token;

      if (token) {
        setAccessToken(token);

        const claims = parseJwt(token) ?? {};
        const acceptedTermsFromToken =
          claims.accepted_terms === true ||
          claims.accepted_terms === 'true' ||
          response.data?.accepted_terms === true;
        const cookieStatusFromToken =
          (claims.cookie_status as string | undefined) ??
          response.data?.cookie_status ??
          'missing';
        const slugFromClaims =
          typeof claims.organization_slug === 'string'
            ? (claims.organization_slug as string)
            : null;
        const responseSlug =
          typeof response.data?.organization_slug === 'string'
            ? (response.data?.organization_slug as string)
            : undefined;

        const derivedSlug = responseSlug ?? slugFromClaims ?? null;

        setCookieBannerStatus(null);
        setBannerOrganizationSlug(derivedSlug);

        success(translate('messages.loginSuccess', 'Welcome back to Tallwave!'));

        if (!acceptedTermsFromToken) {
          redirectTo('/profile/welcome');
          return;
        }

        if (cookieStatusFromToken && cookieStatusFromToken !== 'valid') {
          if (typeof window !== 'undefined') {
            try {
              await apiService.setUserPreference('preferredDashboardView', 'settings-cookie-jar');
              await apiService.setUserPreference('preferredSettingsTab', 'cookie-jar');
            } catch {
              sessionStorage.setItem('preferredDashboardView', 'settings-cookie-jar');
              sessionStorage.setItem('preferredSettingsTab', 'cookie-jar');
            }
          }
          redirectTo('/profile/welcome?focus=cookie');
          return;
        }

        redirectTo('/dashboard');
      } else {
        error(
          translate('errors.loginFailed', 'Login failed'),
          response.error ?? translate('errors.tryAgain', 'Please try again.'),
        );
      }
    } catch (err) {
      console.error('Login error:', err);
      error(
        translate('errors.loginFailed', 'Login failed'),
        translate('errors.tryAgain', 'Please try again later.'),
      );
    } finally {
      setLoading(false);
      setAuthenticatingUserId(null);
    }
  };

  const handleCookieBannerOpen = async () => {
    setCookieBannerStatus(null);
    if (typeof window !== 'undefined') {
      try {
        await apiService.setUserPreference('preferredDashboardView', 'settings-cookie-jar');
        await apiService.setUserPreference('preferredSettingsTab', 'cookie-jar');
      } catch {
        sessionStorage.setItem('preferredDashboardView', 'settings-cookie-jar');
        sessionStorage.setItem('preferredSettingsTab', 'cookie-jar');
      }
    }
    router.push('/profile/welcome?focus=cookie');
  };

  const handleCookieBannerDismiss = () => {
    setCookieBannerStatus(null);
    router.push('/dashboard');
  };

  return (
    <>
      <main
        id="login-main"
        role="main"
        className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#040404] px-4 py-12 sm:px-6"
      >
        <div aria-hidden="true" className="absolute inset-0 -z-30 bg-[#020202]" />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-20 bg-[radial-gradient(circle_at_top,#FFD40014,transparent_55%),radial-gradient(circle_at_bottom,#ffffff12,transparent_62%)]"
        />
        <div aria-hidden="true" className="absolute inset-0 -z-10 overflow-hidden">
          <div className="login-grid-mask" />
          <div className="login-diagonal-shine" />
          <div className="login-orb orb-1" />
          <div className="login-orb orb-2" />
          <div className="login-orb orb-3" />
        </div>

        <div className="relative z-10 w-full max-w-6xl">
          <div className="relative overflow-hidden rounded-[2.75rem] border border-white/12 bg-white/[0.04] shadow-[0_80px_200px_-80px_rgba(0,0,0,0.85)] backdrop-blur-[60px]">
            <div className="pointer-events-none absolute inset-0">
              <div className="login-card-grid" />
              <div className="login-card-shimmer" />
              <div className="login-card-glow" />
            </div>

            <div className="relative flex flex-col gap-10 px-8 pb-12 pt-14 text-center sm:px-12 sm:text-left">
              <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex flex-col items-center gap-4 text-center lg:items-start lg:text-left">
                  <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-1 text-[11px] font-semibold uppercase tracking-[0.45em] text-white/80">
                    Team Access
                  </span>
                  <div className="space-y-3">
                    <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-5xl">
                      {translate('headline', 'Sign In')}
                    </h1>
                    <p className="text-sm text-white/70 sm:text-base lg:max-w-xl">
                      {translate(
                        'subheadline',
                        'Find your account below and sign in. Contact your admin if you need any help.',
                      )}
                    </p>
                  </div>
                </div>

                <div className="grid w-full max-w-sm gap-3 rounded-3xl border border-white/15 bg-white/10 px-6 py-5 text-left text-xs text-white/70 shadow-[0_20px_80px_-60px_rgba(0,0,0,0.9)]">
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#7CFC9A] animate-slow-pulse" />
                    Systems nominal
                  </div>
                  <p className="flex items-center gap-2 text-white/65">
                    <Sparkles className="h-4 w-4 text-[#FFD400]" />
                    Link agent calibrated with Tallwave context
                  </p>
                  <p className="flex items-center gap-2 text-white/65">
                    <ShieldCheck className="h-4 w-4 text-[#8BF6D4]" />
                    Vault guardrails verified moments ago
                  </p>
                  <p className="flex items-center gap-2 text-white/65">
                    <Clock3 className="h-4 w-4 text-white/60" />
                    Last sync <span className="font-mono text-white/80">2m ago</span>
                  </p>
                </div>
              </div>

              <div className="relative overflow-hidden rounded-3xl border border-white/12 bg-black/60 px-6 py-6 shadow-[inset_0_0_60px_rgba(0,0,0,0.45)] sm:px-8">
                <div className="login-inner-grid" />
                <div className="relative space-y-8">
                  {cookieBannerStatus && (
                    <div
                      role="status"
                      aria-live="polite"
                      className="relative overflow-hidden rounded-2xl border border-amber-300/60 bg-amber-500/10 px-5 py-4 text-sm text-amber-100 shadow-[0_20px_60px_-40px_rgba(0,0,0,0.8)] sm:px-6"
                    >
                      <div className="pointer-events-none absolute inset-0 brightness-125 mix-blend-screen opacity-40" />
                      <div className="relative flex items-start gap-3">
                        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-200" />
                        <div className="space-y-2">
                          <div>
                            <p className="text-sm font-medium text-amber-100">
                              {translate('cookieBanner.title', 'LinkedIn session required')}
                            </p>
                            <p className="text-xs text-amber-100/90">
                              {translate('cookieBanner.detectedPrefix', 'We detected a')}{' '}
                              <strong>{cookieBannerStatus}</strong>{' '}
                              {translate('cookieBanner.cookieJar', 'cookie jar for')}{' '}
                              {bannerOrganizationSlug ? (
                                <span className="font-mono text-xs text-amber-100">{bannerOrganizationSlug}</span>
                              ) : (
                                translate('cookieBanner.thisOrganization', 'this organization')
                              )}
                              .{' '}
                              {translate(
                                'cookieBanner.callToAction',
                                'Upload a fresh LinkedIn cookie to activate outreach features.',
                              )}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-3">
                            <button
                              type="button"
                              onClick={handleCookieBannerOpen}
                              className="inline-flex items-center gap-2 rounded-full border border-amber-200/40 bg-amber-300/20 px-3 py-1.5 text-xs font-medium text-amber-50 transition hover:border-amber-100 hover:bg-amber-200/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#040404]"
                            >
                              <CookieIcon className="h-3 w-3" />
                              {translate('cookieBanner.reviewAction', 'Go to Cookie Jar')}
                            </button>
                            <button
                              type="button"
                              onClick={handleCookieBannerDismiss}
                              className="inline-flex items-center gap-2 rounded-full border border-amber-200/40 px-3 py-1.5 text-xs font-medium text-amber-100 transition hover:border-amber-100 hover:bg-amber-100/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#040404]"
                            >
                              {translate('cookieBanner.dismissAction', 'Continue without updating')}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {!isUnlocked ? (
                    <form onSubmit={handleUnlockSubmit} className="space-y-6 text-center">
                      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-white/10 shadow-[0_20px_80px_-60px_rgba(255,212,0,0.6)]">
                        <Lock className="h-7 w-7 text-[#FFD400]" />
                      </div>
                      <div className="space-y-2">
                        <h2 className="text-2xl font-semibold text-white">
                          {translate('unlock.title', 'Enter Password')}
                        </h2>
                        <p className="text-sm text-white/60">
                          {translate('unlock.subtitle', 'Unlock the Tallwave workspace with the shared access code.')}
                        </p>
                      </div>
                      <div className="relative mx-auto max-w-sm">
                        <Lock className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" />
                        <input
                          data-testid="unlock-password-input"
                          type="password"
                          value={unlockInput}
                          onChange={(event) => {
                            setUnlockInput(event.target.value);
                            if (unlockError) {
                              setUnlockError(null);
                            }
                          }}
                          placeholder={translate('unlock.placeholder', 'Tallwave access password')}
                          className="w-full rounded-2xl border border-white/12 bg-white/10 pl-11 pr-4 py-3 text-sm text-white placeholder:text-white/40 shadow-[0_20px_80px_-60px_rgba(255,255,255,0.8)] transition focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                          aria-label={translate('unlock.ariaLabel', 'Enter the Tallwave access password')}
                          required
                        />
                      </div>
                      {unlockError ? (
                        <p role="alert" className="text-xs text-red-300">
                          {unlockError}
                        </p>
                      ) : null}
                      <button
                        data-testid="unlock-submit"
                        type="submit"
                        className="inline-flex w-full max-w-sm items-center justify-center gap-2 rounded-2xl border border-[#FFD400]/60 bg-[#FFD400] px-4 py-3 font-medium text-black shadow-[0_20px_80px_-60px_rgba(255,212,0,0.9)] transition hover:border-[#FFE45E] hover:bg-[#FFE45E] focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40 disabled:cursor-not-allowed disabled:opacity-60 mx-auto"
                      >
                        {translate('unlock.cta', 'Unlock workspace')}
                      </button>
                      <p className="text-xs text-white/40">
                        {translate('unlock.helper', 'Need help? Reach your Tallwave admin for the access password.')}
                      </p>
                    </form>
                  ) : (
                    <div className="space-y-6">
                      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                        <div className="relative w-full sm:max-w-xs">
                          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                          <input
                            type="search"
                            value={searchTerm}
                            onChange={(event) => setSearchTerm(event.target.value)}
                            placeholder={translate('searchPlaceholder', 'Search Tallwave teammates')}
                            className="w-full rounded-2xl border border-white/12 bg-white/10 pl-11 pr-4 py-3 text-sm text-white placeholder:text-white/40 shadow-[0_20px_80px_-60px_rgba(255,255,255,0.8)] transition focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                            aria-label={translate('searchAriaLabel', 'Search teammates by name')}
                          />
                        </div>
                        <button
                          data-testid="open-add-member"
                          type="button"
                          onClick={handleOpenAddMember}
                          aria-haspopup="dialog"
                          aria-expanded={isAddMemberOpen}
                          className="group inline-flex items-center justify-center gap-2 rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm font-semibold text-white transition hover:border-[#FFD400]/60 hover:bg-[#FFD400]/10 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                        >
                          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#FFD400]/20 text-[#FFD400] shadow-[0_0_20px_rgba(255,212,0,0.35)] transition group-hover:bg-[#FFD400]/30 group-hover:text-black">
                            +
                          </span>
                          <span className="text-left leading-tight">
                            <span className="block text-xs uppercase tracking-[0.35em] text-white/55">
                              Tallwave roster
                            </span>
                            <span className="block text-sm font-semibold">Add team member</span>
                          </span>
                        </button>
                      </div>

                      <div aria-live="polite" aria-busy={rosterLoading}>
                        {rosterLoading ? (
                          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                            {Array.from({ length: 6 }).map((_, index) => (
                              // eslint-disable-next-line react/no-array-index-key
                              <div key={index} className="h-24 rounded-3xl border border-white/10 bg-white/10 animate-pulse" />
                            ))}
                          </div>
                        ) : rosterError ? (
                          <div
                            role="alert"
                            className="rounded-3xl border border-red-500/40 bg-red-500/10 px-5 py-12 text-center text-sm text-red-200"
                          >
                            {rosterError}
                          </div>
                        ) : filteredRoster.length === 0 ? (
                          <div className="rounded-3xl border border-white/12 bg-white/10 px-5 py-12 text-center text-sm text-white/60">
                            {translate('roster.empty', 'No teammates found. Try a different search term.')}
                          </div>
                        ) : (
                          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                            {filteredRoster.map((user) => {
                              const colors = avatarColors(user.id);
                              const initials = initialsFromName(user.displayName);
                              const isAuthenticating = authenticatingUserId === user.id && loading;
                              return (
                                <button
                                  data-testid="login-roster-card"
                                  data-user-id={user.id}
                                  data-user-name={user.displayName}
                                  key={user.id}
                                  type="button"
                                  onClick={() => handleUserLogin(user)}
                                  disabled={loading}
                                  className="group relative overflow-hidden rounded-3xl border border-white/12 bg-white/10 p-5 text-left transition-all duration-300 hover:-translate-y-1 hover:border-[#FFD400]/60 hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFD400]/40 disabled:cursor-not-allowed disabled:opacity-70"
                                >
                                  <span
                                    aria-hidden
                                    className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
                                    style={{
                                      background:
                                        'linear-gradient(135deg, rgba(255,212,0,0.25), rgba(255,255,255,0))',
                                      mixBlendMode: 'screen',
                                    }}
                                  />
                                  <span
                                    aria-hidden
                                    className="pointer-events-none absolute -inset-px rounded-[inherit] border border-white/10 opacity-60"
                                  />
                                  <div className="relative z-10 flex items-center gap-4">
                                    <div
                                      className="flex h-12 w-12 items-center justify-center rounded-full font-semibold shadow-[0_10px_30px_-15px_rgba(0,0,0,0.6)]"
                                      style={{
                                        backgroundColor: colors.background,
                                        color: colors.foreground,
                                      }}
                                      aria-hidden
                                    >
                                      {initials}
                                    </div>
                                    <div className="space-y-1">
                                      <p className="text-base font-semibold text-white transition-colors duration-300 group-hover:text-[#FFD400]">
                                        {user.displayName}
                                      </p>
                                      <p className="text-xs text-white/60">{formatLastSeen(user.lastLoginAt)}</p>
                                    </div>
                                  </div>
                                  {isAuthenticating ? (
                                    <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                                      <Loader2 className="h-5 w-5 animate-spin text-[#FFD400]" />
                                    </div>
                                  ) : null}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <footer className="relative mt-6 flex flex-wrap items-center justify-between gap-3 rounded-[1.75rem] border border-white/12 bg-white/[0.04] px-6 py-5 text-xs text-white/70 shadow-[0_40px_120px_-80px_rgba(0,0,0,0.9)] backdrop-blur-xl">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.4em] text-white/70">
                Need Assistance?
              </span>
              <span className="text-white/60">
                Reach your admin or continue to onboarding once you’re inside the workspace.
              </span>
            </div>
            <div className="text-white/55">introducer@tallwave.com</div>
          </footer>
        </div>
      </main>

      <style dangerouslySetInnerHTML={{ __html: loginStyles }} />
      <style dangerouslySetInnerHTML={{ __html: loginGlobalStyles }} />

      {isAddMemberOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-6 backdrop-blur">
          <div
            data-testid="add-member-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-member-title"
            aria-describedby="add-member-description"
            className="relative w-full max-w-xl overflow-hidden rounded-3xl border border-white/15 bg-[#060606] shadow-[0_60px_180px_-80px_rgba(0,0,0,0.9)]"
          >
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,#FFD4001a,transparent_60%),radial-gradient(circle_at_bottom,#ffffff12,transparent_65%)]" />
            <div className="relative flex flex-col gap-6 px-6 pb-8 pt-6 sm:px-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.4em] text-[#FFD400]/80">
                    Tallwave Roster
                  </p>
                  <h2 id="add-member-title" className="mt-2 text-2xl font-semibold text-white">
                    Add a new teammate
                  </h2>
                  <p id="add-member-description" className="mt-1 text-sm text-white/60">
                    Capture their name, contact email, and LinkedIn cookies to activate the agent instantly.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleCloseAddMember}
                  className="rounded-full border border-white/15 bg-white/10 p-2 text-white/70 transition hover:border-white/30 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFD400]/40 focus-visible:ring-offset-2 focus-visible:ring-offset-[#060606]"
                  aria-label={translate('actions.closeModal', 'Close dialog')}
                >
                  ✕
                </button>
              </div>

              <form onSubmit={handleAddMemberSubmit} className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="flex flex-col gap-2 text-sm text-white/80">
                    {translate('addMember.nameLabel', 'Full name')}
                    <input
                      data-testid="add-member-name"
                      type="text"
                      value={newMemberForm.name}
                      onChange={handleAddMemberFieldChange('name')}
                      className="w-full rounded-xl border border-white/12 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                      placeholder={translate('addMember.namePlaceholder', 'Jordan Carter')}
                      disabled={addMemberLoading}
                      required
                    />
                  </label>
                  <label className="flex flex-col gap-2 text-sm text-white/80">
                    {translate('addMember.emailLabel', 'Work email')}
                    <input
                      data-testid="add-member-email"
                      type="email"
                      value={newMemberForm.email}
                      onChange={handleAddMemberFieldChange('email')}
                      className="w-full rounded-xl border border-white/12 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                      placeholder="teammate@tallwave.com"
                      disabled={addMemberLoading}
                      required
                    />
                  </label>
                </div>
                <label className="flex flex-col gap-2 text-sm text-white/80">
                  {translate('addMember.li_atLabel', 'LinkedIn li_at cookie (optional)')}
                  <textarea
                    data-testid="add-member-liat"
                    value={newMemberForm.li_at}
                    onChange={handleAddMemberFieldChange('li_at')}
                    className="min-h-[96px] w-full rounded-xl border border-white/12 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                    placeholder={translate('addMember.li_atPlaceholder', 'Paste the li_at value...')}
                    disabled={addMemberLoading}
                  />
                </label>
                <label className="flex flex-col gap-2 text-sm text-white/80">
                  {translate('addMember.jsessionidLabel', 'LinkedIn JSESSIONID (optional)')}
                  <textarea
                    data-testid="add-member-jsessionid"
                    value={newMemberForm.jsessionid}
                    onChange={handleAddMemberFieldChange('jsessionid')}
                    className="min-h-[72px] w-full rounded-xl border border-white/12 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                    placeholder={translate('addMember.jsessionidPlaceholder', 'Paste the JSESSIONID value...')}
                    disabled={addMemberLoading}
                  />
                </label>
                <label className="flex flex-col gap-2 text-sm text-white/80">
                  {translate('addMember.label', 'Cookie label (optional)')}
                  <input
                    data-testid="add-member-label"
                    type="text"
                    value={newMemberForm.cookie_label}
                    onChange={handleAddMemberFieldChange('cookie_label')}
                    className="w-full rounded-xl border border-white/12 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-[#FFD400]/60 focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40"
                    placeholder={translate('addMember.labelPlaceholder', 'e.g. Primary LinkedIn session')}
                    disabled={addMemberLoading}
                  />
                </label>
                {addMemberError ? (
                  <p role="alert" className="text-sm text-red-300">
                    {addMemberError}
                  </p>
                ) : null}
                <button
                  data-testid="add-member-submit"
                  type="submit"
                  disabled={addMemberLoading}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-[#FFD400]/60 bg-[#FFD400] px-4 py-3 font-medium text-black shadow-[0_20px_80px_-60px_rgba(255,212,0,0.9)] transition hover:border-[#FFE45E] hover:bg-[#FFE45E] focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {addMemberLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                  {translate('addMember.submit', 'Add Tallwave teammate')}
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
