import { normalizeConnector, normalizeProspect } from '../ProspectsView';

describe('ProspectsView normalization helpers', () => {
  it('normalizes missing connector fields without placeholder text', () => {
    const normalized = normalizeConnector({}, 0);
    expect(normalized.full_name).toBe('');
    expect(normalized.company).toBeUndefined();
    expect(normalized.email_status).toBe('pending');
    expect(normalized.rank).toBe(1);
  });

  it('normalizes prospect defaults without synthetic labels', () => {
    const normalized = normalizeProspect(
      {
        status: 'unknown_status',
        priority: 'not_a_priority',
      },
      0,
      { organizationKey: null, organizationId: null }
    );

    expect(normalized.full_name).toBe('');
    expect(normalized.company).toBe('');
    expect(normalized.status).toBe('pending_lookup');
    expect(normalized.priority).toBe('medium');
    expect(normalized.organization_id).toBe('');
  });

  it('prefers provided organization identifiers', () => {
    const normalized = normalizeProspect(
      {
        id: '42',
        status: 'enriched',
        priority: 'high',
        organization_id: 512,
      },
      0,
      { organizationKey: 'abc', organizationId: 'xyz' }
    );

    expect(normalized.id).toBe(42);
    expect(normalized.organization_id).toBe(512);
    expect(normalized.status).toBe('enriched');
    expect(normalized.priority).toBe('high');
  });
});
