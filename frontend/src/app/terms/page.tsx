import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: 'The terms and conditions governing use of the Tallwave platform.',
};

export default function TermsOfServicePage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-16 text-slate-200">
      <h1 className="text-3xl font-semibold text-white">Terms of Service</h1>
      <p className="mt-4 text-sm text-slate-300">Effective as of October 2025</p>

      <section className="mt-10 space-y-6 text-sm leading-relaxed text-slate-200">
        <p>
          These Terms of Service (&quot;Terms&quot;) form a binding agreement between Tallwave (&quot;Tallwave&quot;,
          &quot;we&quot;, &quot;our&quot;) and the organisation or individual that creates an account (&quot;Customer&quot;,
          &quot;you&quot;). By accessing or using the Tallwave platform, Link agent, or related services, you agree to these
          Terms.
        </p>

        <div>
          <h2 className="text-xl font-semibold text-white">1. Platform Access</h2>
          <p className="mt-3">
            We provide authorised users access to the Tallwave web application, API, and automation services for managing warm
            introductions. Access requires valid credentials issued to your organisation. You are responsible for safeguarding
            accounts and ensuring only permitted users access the platform.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">2. Acceptable Use</h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>Do not misuse connector or prospect data or violate LinkedIn terms while using Link automations.</li>
            <li>Do not attempt to disable or circumvent guardrails, queue telemetry, or approval workflows.</li>
            <li>
              Use the platform solely for legitimate business introductions; unsolicited marketing or spam behaviour is prohibited.
            </li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">3. Data Ownership</h2>
          <p className="mt-3">
            Customer retains ownership of uploaded data. Tallwave acts as a processor and uses the data only to deliver the
            contracted services, provide support, and improve reliability in an aggregated and anonymised manner.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">4. Confidentiality &amp; Security</h2>
          <p className="mt-3">
            We implement administrative, technical, and physical safeguards aligned with SOC 2 Type II requirements. You agree to
            maintain confidentiality of platform information and notify us promptly of any suspected breach.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">5. Payment &amp; Billing</h2>
          <p className="mt-3">
            Paid plans require timely payment of subscription fees. Delinquent accounts may be suspended. If the platform cannot
            process payments via Stripe due to configuration errors, we may request alternative arrangements while access remains
            active.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">6. Termination</h2>
          <p className="mt-3">
            Either party may terminate services with written notice if the other party materially breaches these Terms and fails to
            cure within 30 days. Upon termination, we will provide a secure export of customer data and delete production copies
            per our retention schedule.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">7. Warranties &amp; Disclaimers</h2>
          <p className="mt-3">
            We warrant that we will provide the services in a professional manner using industry-standard safeguards. Except for
            the warranties expressly stated herein, the services are provided &quot;as is&quot; without further warranty.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">8. Liability</h2>
          <p className="mt-3">
            To the maximum extent permitted by law, neither party shall be liable for indirect or consequential damages. Our total
            liability for claims arising out of these Terms is limited to the fees paid by you during the twelve (12) months
            preceding the event giving rise to liability.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">9. Updates</h2>
          <p className="mt-3">
            We may update these Terms when product or regulatory changes occur. Material updates will be communicated to Customer
            administrators at least 30 days before they take effect. Continued use of the platform after changes become effective
            constitutes acceptance.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">10. Contact</h2>
          <p className="mt-3">
            For contractual or legal matters, contact <a className="underline hover:text-white" href="mailto:legal@vouchlink.ai">legal@vouchlink.ai</a>. For billing questions, email{' '}
            <a className="underline hover:text-white" href="mailto:billing@vouchlink.ai">billing@vouchlink.ai</a>.
          </p>
        </div>
      </section>
    </main>
  );
}
