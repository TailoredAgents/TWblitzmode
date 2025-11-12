'use client';

import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertCircle, Check, Loader2 } from 'lucide-react';
import GlassCard from '../ui/GlassCard';
import { useLandingAnalytics } from '../../hooks/useLandingAnalytics';

const optionalShortText = z
  .string()
  .trim()
  .max(120, 'Keep responses under 120 characters.')
  .transform((value) => (value ? value : undefined))
  .optional();

const formSchema = z.object({
  fullName: z
    .string()
    .trim()
    .min(2, 'Please enter your full name.')
    .max(120, 'Name is too long for the form.'),
  email: z
    .string()
    .trim()
    .email('Enter a valid business email address.')
    .max(160, 'Email length exceeds the limit.'),
  company: optionalShortText,
  jobTitle: optionalShortText,
  teamSize: z
    .string()
    .trim()
    .max(60, 'Keep team size descriptions concise.')
    .transform((value) => (value ? value : undefined))
    .optional(),
  useCase: optionalShortText,
  message: z
    .string()
    .trim()
    .max(1000, 'Message limit is 1000 characters.')
    .transform((value) => (value ? value : undefined))
    .optional(),
  consent: z
    .boolean()
    .refine((val) => val === true, {
      message: 'You must consent in order for us to reach out.',
    }),
  // Honeypot field for bot detection
  website: z.string().max(0, 'This field should be empty').optional(),
});

type LandingContactFormValues = z.infer<typeof formSchema>;

type LandingContactFormProps = {
  defaultSource?: string;
  utm?: Record<string, string>;
};

const inputClasses =
  'w-full rounded-lg border border-[#DCDCDC] bg-white px-4 py-3 text-sm text-[#111111] placeholder:text-[#777777] focus:border-[#FFD400] focus:outline-none focus:ring-2 focus:ring-[#FFD400]/40 transition-shadow';
const labelClasses = 'text-xs font-medium uppercase tracking-widest text-[#111111]';
const errorClasses = 'mt-1 text-xs text-[#B3261E]';

export function LandingContactForm({ defaultSource = 'landing_page', utm }: LandingContactFormProps) {
  const trackEvent = useLandingAnalytics(defaultSource);
  const [status, setStatus] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [leadId, setLeadId] = useState<number | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<LandingContactFormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      fullName: '',
      email: '',
      company: '',
      jobTitle: '',
      teamSize: '',
      useCase: '',
      message: '',
      consent: false,
      website: '', // Honeypot field
    },
  });

  const onSubmit = async (values: LandingContactFormValues) => {
    setStatus('submitting');
    setLeadId(null);
    setErrorMessage(null);

    // Honeypot field check - reject if filled (indicates bot)
    if (values.website && values.website.trim() !== '') {
      console.warn('Bot submission detected via honeypot field');
      setErrorMessage('Submission rejected - please try again');
      setStatus('error');
      return;
    }

    void trackEvent('form_start', { label: 'landing_contact' });

    const utmPayload = utm && Object.keys(utm).length > 0 ? utm : undefined;

    const payload = {
      full_name: values.fullName.trim(),
      email: values.email.trim(),
      company: values.company,
      job_title: values.jobTitle,
      team_size: values.teamSize,
      use_case: values.useCase,
      message: values.message,
      consent: values.consent === true,
      source: defaultSource,
      utm: utmPayload,
      metadata: {
        locale: typeof window !== 'undefined' ? window.navigator.language : undefined,
      },
    };

    try {
      const response = await fetch('/api/public/landing/contact', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = body?.detail || body?.message || 'We could not submit your request.';
        throw new Error(detail);
      }

      const leadIdentifier = body?.data?.lead_id ?? null;
      setLeadId(leadIdentifier);
      setStatus('success');
      void trackEvent('form_submit', {
        label: 'landing_contact',
        email: values.email.trim(),
        metadata: { leadId: leadIdentifier },
      });

      reset({
        fullName: '',
        email: '',
        company: '',
        jobTitle: '',
        teamSize: '',
        useCase: '',
        message: '',
        consent: false,
        website: '', // Reset honeypot field
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'The request did not complete. Please try again.';
      setErrorMessage(message);
      setStatus('error');
      void trackEvent('form_error', {
        label: 'landing_contact',
        email: values.email.trim(),
        metadata: { message },
      });
    }
  };

  return (
    <GlassCard className="w-full border border-[#E4E4E4] bg-white p-6 shadow-sm sm:p-8">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6" noValidate>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-[#FFD400]">Request a demo</p>
          <h2 className="mt-2 text-2xl font-semibold text-[#111111] md:text-3xl">
            Show us your connector goals and we’ll spin up a tailored warm-intro plan.
          </h2>
          <p className="mt-3 text-sm text-[#2C2C2C]">
            Share your team’s focus and the Link agent will prepare baseline network analysis before
            the call.
          </p>
        </div>

        {status === 'success' && (
          <div className="flex items-start gap-3 rounded-lg border border-[#FFD400]/40 bg-[#FFF7CC] px-4 py-3 text-sm text-[#111111]">
            <Check className="mt-0.5 h-4 w-4 text-[#FFD400]" />
            <div>
              <p>Thanks! We’ve logged your request and a team member will reach out shortly.</p>
              {leadId && <p className="mt-1 text-xs text-[#5F4B00]/80">Reference ID: {leadId}</p>}
            </div>
          </div>
        )}

        {status === 'error' && errorMessage && (
          <div className="flex items-start gap-3 rounded-lg border border-[#B3261E]/30 bg-[#B3261E]/10 px-4 py-3 text-sm text-[#7c1a14]">
            <AlertCircle className="mt-0.5 h-4 w-4 text-[#B3261E]" />
            <div>
              <p>{errorMessage}</p>
              <p className="mt-1 text-xs text-rose-200/80">
                You can also email{' '}
                <a className="underline hover:text-[#B3261E]" href="mailto:intros@vouchlink.ai">
                  intros@vouchlink.ai
                </a>{' '}
                and we’ll take it from there.
              </p>
            </div>
          </div>
        )}

        {/* Honeypot field - hidden from users but visible to bots */}
        <input
          type="text"
          {...register('website')}
          style={{ display: 'none' }}
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Full name</span>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              {...register('fullName')}
              className={inputClasses}
              placeholder="Jordan Alvarez"
            />
            {errors.fullName && <p className={errorClasses}>{errors.fullName.message}</p>}
          </label>

          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Work email</span>
            <input
              id="email"
              type="email"
              autoComplete="email"
              {...register('email')}
              className={inputClasses}
              placeholder="jordan@vouchlink.ai"
            />
            {errors.email && <p className={errorClasses}>{errors.email.message}</p>}
          </label>

          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Company</span>
            <input
              id="company"
              type="text"
              {...register('company')}
              className={inputClasses}
              placeholder="Tallwave"
            />
            {errors.company && <p className={errorClasses}>{errors.company.message}</p>}
          </label>

          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Role or title</span>
            <input
              id="jobTitle"
              type="text"
              {...register('jobTitle')}
              className={inputClasses}
              placeholder="Head of Business Development"
            />
            {errors.jobTitle && <p className={errorClasses}>{errors.jobTitle.message}</p>}
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Team size / region focus</span>
            <input
              id="teamSize"
              type="text"
              {...register('teamSize')}
              className={inputClasses}
              placeholder="7-person GTM team (NA & EMEA)"
            />
            {errors.teamSize && <p className={errorClasses}>{errors.teamSize.message}</p>}
          </label>

          <label className="flex flex-col gap-2">
            <span className={labelClasses}>Primary use case</span>
            <input
              id="useCase"
              type="text"
              {...register('useCase')}
              className={inputClasses}
              placeholder="Investor intros, partner expansion, recruitment"
            />
            {errors.useCase && <p className={errorClasses}>{errors.useCase.message}</p>}
          </label>
        </div>

        <label className="flex flex-col gap-2">
          <span className={labelClasses}>What should we prepare?</span>
          <textarea
            id="message"
            rows={4}
            {...register('message')}
            className={`${inputClasses} min-h-[120px] resize-y`}
            placeholder="Share any target accounts, connector intel, or current intro workflows you’d like to automate."
          />
          {errors.message && <p className={errorClasses}>{errors.message.message}</p>}
        </label>

        <label className="flex items-start gap-3 text-xs text-[#2C2C2C]">
          <input
            id="consent"
            type="checkbox"
            {...register('consent')}
            className="mt-0.5 h-4 w-4 rounded border border-[#DCDCDC] bg-white text-[#FFD400] focus:ring-[#FFD400]"
          />
          <span>
            I agree to have Tallwave contact me about enterprise warm-introduction workflows and
            understand my data will be processed in line with the{' '}
            <a className="underline text-[#111111] hover:text-[#FFD400]" href="/privacy">
              privacy policy
            </a>
            .
          </span>
        </label>
        {errors.consent && <p className={errorClasses}>{errors.consent.message}</p>}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="submit"
            disabled={isSubmitting || status === 'submitting'}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-slate-950 shadow-lg shadow-primary/40 transition-transform hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-slate-900 disabled:pointer-events-none disabled:opacity-70"
          >
            {(isSubmitting || status === 'submitting') && <Loader2 className="h-4 w-4 animate-spin" />}
            {status === 'success' ? 'Request received' : 'Book a discovery call'}
          </button>

        <p className="text-xs text-[#2C2C2C]">
            Typical response time: under 4 business hours. No auto-enrolment or marketing blasts.
          </p>
        </div>
      </form>
    </GlassCard>
  );
}
