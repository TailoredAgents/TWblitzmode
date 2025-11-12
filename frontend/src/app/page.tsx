'use client';

import React, { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import Cookies from 'js-cookie';
import { Loader2 } from 'lucide-react';
import { apiService } from '../services/api';
import { MaintenanceAccessButton } from '../components/landing/MaintenanceAccessButton';
import { clearAccessToken, getAccessToken } from '../lib/authToken';

function LandingPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [showMaintenanceAccess, setShowMaintenanceAccess] = useState(false);

  useEffect(() => {
    let redirected = false;
    let isMounted = true;

    const bootstrapSession = async () => {
      try {
        if (getAccessToken()) {
          redirected = true;
          router.replace('/dashboard');
        } else {
          const refreshed = await apiService.refreshAccessToken();
          if (refreshed) {
            redirected = true;
            router.replace('/dashboard');
          }
        }
      } catch (error) {
        console.warn('Session bootstrap failed:', error);
      } finally {
        if (!redirected) {
          clearAccessToken();
          Cookies.remove('auth_token');
          Cookies.remove('tallwave_auth_token');
          if (typeof window !== 'undefined') {
            window.localStorage.removeItem('tallwave_auth_token');
          }
        }
        if (isMounted) {
          setCheckingAuth(false);
        }
      }
    };

    void bootstrapSession();

    return () => {
      isMounted = false;
    };
  }, [router]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    setShowMaintenanceAccess(searchParams?.get('dev') === '1');
  }, [searchParams]);

  if (checkingAuth) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-[#FFD400]" />
        <span className="sr-only">Preparing Tallwave workspace…</span>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-[#050505] text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-30 bg-[radial-gradient(circle_at_20%_20%,#FFD40026,transparent_45%),radial-gradient(circle_at_80%_10%,#FFED9A1a,transparent_40%),radial-gradient(circle_at_50%_120%,#000000f5,transparent_65%)]"
      />
      <div
        aria-hidden="true"
        className="absolute -left-32 top-24 -z-20 h-80 w-80 rounded-full border border-white/10 bg-white/5 blur-[120px]"
      />
      <div
        aria-hidden="true"
        className="absolute bottom-[-18rem] left-1/3 -z-20 h-[36rem] w-[36rem] rounded-full border border-[#FFD400]/20 bg-[#FFD400]/10 blur-[180px]"
      />
      <div
        aria-hidden="true"
        className="absolute -top-24 right-[-12rem] -z-20 h-[28rem] w-[28rem] rounded-full border border-[#FFD400]/15 bg-[#FFD400]/14 blur-[150px]"
      />
      <header className="mx-auto flex w-full justify-center px-6 pt-6">
        <div className="flex w-full max-w-6xl flex-col gap-4 rounded-3xl border border-white/10 bg-black/85 px-6 py-5 shadow-[0_20px_60px_-40px_rgba(0,0,0,0.9)] backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <Link href="/" className="flex items-center gap-3">
            <span className="relative flex items-center gap-3">
              <span className="absolute -left-4 -top-2 h-12 w-12 rounded-full bg-[#FFD400]/10 blur-xl" aria-hidden="true" />
              <Image
                src="/tallwave-logo.png"
                alt="Tallwave logo"
                width={148}
                height={40}
                priority
                className="h-10 w-auto"
              />
              <span className="hidden flex-col text-left leading-tight sm:flex">
                <span className="text-xs font-semibold uppercase tracking-[0.4em] text-white/80">Warm introduction ops</span>
                <span className="text-[11px] text-white/60">Tailored for Tallwave by Tailored Agents</span>
              </span>
            </span>
          </Link>
          <nav className="flex flex-wrap items-center gap-4 text-sm text-white/60">
            <Link href="/login" data-testid="landing-login-link" className="transition-colors hover:text-white">
              Log in
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative flex flex-1 items-center justify-center overflow-hidden px-6 pb-24">
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-20 bg-[radial-gradient(circle_at_top,#FFD4001f,transparent_55%),radial-gradient(circle_at_bottom,#000000e6,transparent_70%)]"
        />
        <div
          aria-hidden="true"
          className="absolute left-1/2 top-10 -z-10 h-80 w-80 -translate-x-1/2 rounded-full bg-[#FFD400]/15 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="absolute bottom-[-6rem] right-[-4rem] -z-10 h-96 w-96 rounded-full bg-black/70 blur-[120px]"
        />
        <section
          id="landing-hero"
          aria-labelledby="landing-hero-heading"
          className="relative isolate flex max-w-3xl flex-col items-center justify-center rounded-[2.75rem] border border-white/10 bg-black/70 px-12 py-20 text-center shadow-[0_40px_140px_-50px_rgba(0,0,0,0.85)] backdrop-blur-2xl"
        >
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 rounded-[2.75rem] border border-white/5 opacity-70"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -left-24 top-16 h-32 w-32 rounded-full border border-white/20 bg-white/10 blur-2xl"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-24 bottom-20 h-28 w-28 rounded-full border border-[#FFD400]/40 bg-[#FFD400]/20 blur-2xl"
          />
          <h1
            id="landing-hero-heading"
            className="relative text-4xl font-semibold leading-tight text-white sm:text-5xl lg:text-6xl"
          >
            <span className="bg-gradient-to-br from-white via-white to-[#FFD400] bg-clip-text text-transparent">
              Welcome To Your Warm Introduction Agent
            </span>
          </h1>
        </section>
      </main>

      <MaintenanceAccessButton visible={showMaintenanceAccess} />
    </div>
  );
}

export default function LandingPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <LandingPageContent />
    </Suspense>
  );
}
