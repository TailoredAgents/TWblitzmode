'use client';

import React, { type JSX } from 'react';
import Link from 'next/link';

import GlassCard from '../../../../components/ui/GlassCard';

interface RegistrationKeyParams {
  params: {
    token: string;
  };
}

export default function RegistrationKeysLegacyPage({ params }: RegistrationKeyParams): JSX.Element {
  const { token } = params;
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-12">
      <GlassCard className="w-full max-w-2xl p-10 space-y-6 text-center">
        <div className="space-y-3">
          <p className="text-sm font-semibold uppercase tracking-wide text-primary/70">
            Registration Link Retired
          </p>
          <h1 className="text-3xl font-bold text-primary">Registration Keys No Longer Required</h1>
          <p className="text-base text-muted-foreground">
            Tallwave now provisions seats directly and no longer issues registration keys. The link
            you followed ({token}) is no longer valid.
          </p>
        </div>
        <div className="rounded-xl border border-border/30 bg-muted/10 p-6 text-left text-sm text-muted-foreground space-y-3">
          <p>
            Need to onboard a teammate? Send the request to{' '}
            <Link href="mailto:introducer@tallwave.com" className="text-primary hover:underline">
              introducer@tallwave.com
            </Link>
            . Include their Tallwave email and we&rsquo;ll confirm once the profile is ready.
          </p>
          <p>
            Already have access?{' '}
            <Link href="/login" className="text-primary hover:underline">
              Return to login
            </Link>{' '}
            to choose your profile and sign in.
          </p>
        </div>
      </GlassCard>
    </div>
  );
}
