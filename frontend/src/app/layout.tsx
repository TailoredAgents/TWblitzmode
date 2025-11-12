import type { Metadata } from 'next';
import { ToastProvider } from '../components/ui/ToastContainer';
import { ThemeProvider } from '../contexts/ThemeContext';
import { I18nProvider } from '../contexts/I18nContext';
import SkipNavLink from '../components/SkipNavLink';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'https://tallwave.ai'),
  title: {
    default: 'Tallwave Introducer | Warm Introduction Orchestration',
    template: '%s | Tallwave Introducer',
  },
  description:
    'Tallwave orchestrates compliant warm introductions for Tallwave teams with Link, the guardrailed autonomous agent built for regulated workflows.',
  keywords: [
    'Tallwave',
    'warm introductions',
    'enterprise prospecting',
    'connector intelligence',
    'LinkedIn automation',
  ],
  openGraph: {
    title: 'Tallwave Introducer | Warm Introduction Orchestration',
    description:
      'Deliver trustworthy Tallwave warm introductions with Link, the enterprise-grade agent that unifies network scans, approvals, and outreach.',
    url: 'https://tallwave.ai',
    siteName: 'Tallwave Introducer',
    locale: 'en_US',
    type: 'website',
    images: [
      {
        url: '/og/tallwave-hero.png',
        width: 1200,
        height: 630,
        alt: 'Tallwave dashboard preview',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Tallwave Introducer | Warm Introduction Orchestration',
    description:
      'Deliver trustworthy Tallwave warm introductions with Link, the enterprise-grade agent that unifies network scans, approvals, and outreach.',
    images: ['/og/tallwave-hero.png'],
  },
  alternates: {
    canonical: '/',
  },
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <I18nProvider>
          <ThemeProvider defaultTheme="system" storageKey="tallwave-theme">
            <ToastProvider position="top-right" maxToasts={5}>
              <SkipNavLink />
              <div className="min-h-screen bg-background text-foreground transition-colors duration-300">
                {children}
              </div>
            </ToastProvider>
          </ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
