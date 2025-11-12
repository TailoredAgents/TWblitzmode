'use client';

import React, { type JSX } from 'react';
import Link from 'next/link';

import GlassCard from '../../components/ui/GlassCard';

export default function CompanyPortalPage(): JSX.Element {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-12">
      <GlassCard className="w-full max-w-2xl p-10 space-y-6 text-center">
        <div className="space-y-3">
          <p className="text-sm font-semibold uppercase tracking-wide text-primary/70">
            Tallwave Company Portal
          </p>
          <h1 className="text-3xl font-bold text-primary">Company Portal Retired</h1>
          <p className="text-base text-muted-foreground">
            The Tallwave company portal has been sunset. All onboarding and account management now
            happens directly through the Tallwave operations team.
          </p>
        </div>
        <div className="rounded-xl border border-border/30 bg-muted/10 p-6 text-left text-sm text-muted-foreground space-y-3">
          <p>
            If you need to add teammates, update seats, or request access, please email{' '}
            <Link href="mailto:introducer@tallwave.com" className="text-primary hover:underline">
              introducer@tallwave.com
            </Link>
            . We&rsquo;ll coordinate setup and confirm once the profile is ready.
          </p>
          <p>
            Ready to get back to work?{' '}
            <Link href="/login" className="text-primary hover:underline">
              Return to the login page
            </Link>{' '}
            to choose your Tallwave profile and sign in.
          </p>
        </div>
      </GlassCard>
    </div>
  );
}
