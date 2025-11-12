'use client';

import { useCallback } from 'react';

type LandingEventType = 'cta_click' | 'cta_error' | 'form_start' | 'form_submit' | 'form_error';

interface TrackLandingEventOptions {
  label?: string;
  email?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export function useLandingAnalytics(defaultSource = 'landing_page') {
  return useCallback(
    async (eventType: LandingEventType, options: TrackLandingEventOptions = {}) => {
      if (typeof window === 'undefined' || typeof navigator === 'undefined') {
        return false;
      }

      const payload = {
        event_type: eventType,
        label: options.label,
        email: options.email,
        source: options.source ?? defaultSource,
        metadata: {
          ...options.metadata,
          timestamp: new Date().toISOString(),
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
          },
        },
      };

      try {
        const serialized = JSON.stringify(payload);
        if (navigator.sendBeacon) {
          const beaconBlob = new Blob([serialized], { type: 'application/json' });
          const queued = navigator.sendBeacon('/api/public/landing/event', beaconBlob);
          if (queued) {
            return true;
          }
        }

        const response = await fetch('/api/public/landing/event', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: serialized,
          keepalive: true,
        });

        return response.ok;
      } catch (error) {
        console.warn('Landing analytics event failed', error);
        return false;
      }
    },
    [defaultSource]
  );
}
