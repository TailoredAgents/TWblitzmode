import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description: 'Understand how Tallwave protects customer data and connector intelligence.',
};

export default function PrivacyPolicyPage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-16 text-slate-200">
      <h1 className="text-3xl font-semibold text-white">Privacy Policy</h1>
      <p className="mt-4 text-sm text-slate-300">
        Last updated: {new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
      </p>

      <section className="mt-10 space-y-4 text-sm leading-relaxed text-slate-200">
        <p>
          Tallwave helps enterprise go-to-market teams deliver compliant warm introductions. Protecting the privacy of
          prospects, connectors, and customers is foundational to the platform. This policy explains what data we collect, how we
          use it, and the controls you have.
        </p>
        <p>
          By accessing our websites or using the Tallwave platform, you agree to the practices described below. If you have
          questions, contact <a className="underline hover:text-white" href="mailto:privacy@vouchlink.ai">privacy@vouchlink.ai</a>.
        </p>
      </section>

      <section className="mt-12 space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-white">Information We Collect</h2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-sm text-slate-200">
            <li>Account and organisation details supplied during onboarding or through the admin console.</li>
            <li>Connector, prospect, and workflow data that you upload or synchronise from approved providers.</li>
            <li>Autonomous agent telemetry, audit events, and approvals captured to maintain compliance.</li>
            <li>
              Limited website analytics and landing-page submissions used to improve the product and respond to enquiries.
            </li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">How We Use Data</h2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-sm text-slate-200">
            <li>Operate and secure the Tallwave platform, including queue health, vault management, and agent guardrails.</li>
            <li>Provide customer support, onboarding, and success services requested by your team.</li>
            <li>Improve Link’s matching intelligence and automation reliability without exposing tenant data to other customers.</li>
            <li>Meet legal, regulatory, or security obligations when requested by authorised parties.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">How We Protect Data</h2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-sm text-slate-200">
            <li>Deterministic tenant encryption keys with hardware-backed secrets and rotation policies.</li>
            <li>Network isolation between production, staging, and sandbox environments with audited access controls.</li>
            <li>SOC 2 Type II control set with continuous monitoring for vault health and cookie lifecycle events.</li>
            <li>Regional data storage options and GDPR-compliant data processing agreements for EU customers.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">Data Subject Rights</h2>
          <p className="mt-4 text-sm text-slate-200">
            If you reside in a region that provides privacy rights (including GDPR, UK GDPR, CCPA/CPRA), you may request access,
            correction, deletion, or restriction of your data. Email{' '}
            <a className="underline hover:text-white" href="mailto:privacy@vouchlink.ai">
              privacy@vouchlink.ai
            </a>{' '}
            with your request and authorised organisation details. We respond within the timelines required by local regulation.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">International Transfers</h2>
          <p className="mt-4 text-sm text-slate-200">
            Tallwave operates primarily from the United States with regional infrastructure options. When data is transferred
            internationally, we rely on appropriate safeguards such as Standard Contractual Clauses or intra-company agreements.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">Contact</h2>
          <p className="mt-4 text-sm text-slate-200">
            Privacy enquiries:{' '}
            <a className="underline hover:text-white" href="mailto:privacy@vouchlink.ai">
              privacy@vouchlink.ai
            </a>
            . Security concerns:{' '}
            <a className="underline hover:text-white" href="mailto:security@vouchlink.ai">
              security@vouchlink.ai
            </a>
            . Mailing address: Tallwave, 548 Market Street PMB 62476, San Francisco, CA 94104.
          </p>
        </div>
      </section>
    </main>
  );
}
