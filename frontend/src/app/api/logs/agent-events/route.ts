
import { NextResponse } from 'next/server';

type AgentEvent = {
  eventId?: string;
  eventType?: string;
  level?: string;
  message?: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
};

type AgentEventPayload = {
  events?: AgentEvent[];
  summary?: Record<string, unknown>;
};

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as AgentEventPayload | AgentEventPayload[];
    const eventsArray = Array.isArray(body) ? body : [body];
    const eventCount = eventsArray.reduce(
      (total, payload) => total + (Array.isArray(payload?.events) ? payload.events.length : 0),
      0,
    );

    console.debug('[agent-events] received payload', {
      envelopes: eventsArray.length,
      events: eventCount,
    });

    return NextResponse.json(
      {
        data: {
          status: 'accepted',
          envelopes: eventsArray.length,
          events: eventCount,
        },
      },
      { status: 200 },
    );
  } catch (error) {
    console.warn('[agent-events] failed to parse payload', error);
    return NextResponse.json(
      {
        error: 'invalid_payload',
        message: 'Unable to parse agent event payload. Logging disabled temporarily.',
      },
      { status: 400 },
    );
  }
}
