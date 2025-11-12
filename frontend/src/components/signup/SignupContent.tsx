import React, { type JSX } from 'react';
import Link from 'next/link';

import GlassCard from '../ui/GlassCard';

export function SignupContent(): JSX.Element {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-12">
      <GlassCard className="w-full max-w-2xl p-10 space-y-6 text-center">
        <div className="space-y-3">
          <p className="text-sm font-semibold uppercase tracking-wide text-primary/70">
            Tallwave Account Provisioning
          </p>
          <h1 className="text-3xl font-bold text-primary">Self-Serve Sign Up Disabled</h1>
          <p className="text-base text-muted-foreground">
            Tallwave manages Introducer access centrally. If you need an account or additional seats,
            contact the Tallwave operations team and we&rsquo;ll get you onboarded right away.
          </p>
        </div>
        <div className="rounded-xl border border-border/30 bg-muted/10 p-6 text-left text-sm text-muted-foreground space-y-3">
          <p>
            <strong className="text-foreground">Need help?</strong> Send a note to{' '}
            <Link href="mailto:introducer@tallwave.com" className="text-primary hover:underline">
              introducer@tallwave.com
            </Link>{' '}
            with the teammate&rsquo;s name, role, and Tallwave email address. Our team will confirm access
            within one business day.
          </p>
          <p>
            Looking to get started?{' '}
            <Link href="/login" className="text-primary hover:underline">
              Return to the login page
            </Link>{' '}
            to select your profile and sign in.
          </p>
        </div>
      </GlassCard>
    </div>
  );
}
