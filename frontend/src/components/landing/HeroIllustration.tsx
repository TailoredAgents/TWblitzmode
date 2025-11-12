'use client';

import React from 'react';
import { ShieldCheck, Sparkles, Users } from 'lucide-react';
import GlassCard from '../ui/GlassCard';

export function HeroIllustration() {
  return (
    <div className="relative isolate aspect-[4/3] w-full overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/60 via-slate-950 to-black/90 shadow-2xl shadow-primary/20">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(87,142,255,0.28),transparent_65%)]" />
      <div className="absolute -left-24 top-1/4 h-64 w-64 rounded-full bg-primary/30 blur-3xl" />
      <div className="absolute -right-24 bottom-10 h-72 w-72 rounded-full bg-emerald-400/20 blur-3xl" />

      <svg
        className="absolute inset-0 h-full w-full opacity-60 mix-blend-screen"
        viewBox="0 0 400 300"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="heroGrid" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#f472b6" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <g fill="none" stroke="url(#heroGrid)" strokeWidth="0.6">
          {Array.from({ length: 12 }).map((_, index) => (
            <circle key={index} cx="200" cy="150" r={30 + index * 15} />
          ))}
        </g>
        <g stroke="#38bdf8" strokeOpacity="0.3">
          <line x1="80" y1="220" x2="200" y2="90" />
          <line x1="200" y1="90" x2="320" y2="210" />
          <line x1="80" y1="220" x2="150" y2="260" />
          <line x1="320" y1="210" x2="250" y2="260" />
        </g>
      </svg>

      <GlassCard className="absolute left-6 top-6 w-52 gap-2 bg-white/10 p-4 text-slate-100 shadow-glass-strong">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Users className="h-4 w-4 text-primary" />
          Connector score
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-bold">97</span>
          <span className="text-xs text-slate-300">trusted overlap</span>
        </div>
        <p className="text-[10px] leading-relaxed text-slate-200">
          Tier-1 connector with verified mutual history across enterprise accounts.
        </p>
      </GlassCard>

      <GlassCard className="absolute right-8 top-8 w-48 space-y-2 bg-emerald-500/10 p-4 text-emerald-100">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ShieldCheck className="h-4 w-4 text-emerald-300" />
          Vault status
        </div>
        <p className="text-xs leading-relaxed">
          Cookies encrypted and rolling health checks green across US & EU clusters.
        </p>
      </GlassCard>

      <GlassCard className="absolute bottom-12 left-12 w-60 bg-slate-900/80 p-5 text-sm text-slate-200">
        <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-primary">
          <Sparkles className="h-3 w-3" />
          Link agent brief
        </div>
        <p className="mt-3 text-xs leading-relaxed">
          “Recommending James Patel via mutual board experience. Approval queued for COO review.”
        </p>
      </GlassCard>

      <div className="absolute bottom-6 right-6 flex items-center gap-2 rounded-full bg-black/70 px-4 py-2 text-xs text-slate-200 backdrop-blur">
        <span className="inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        SOC2 controls live · 99.95% queue uptime
      </div>
    </div>
  );
}
