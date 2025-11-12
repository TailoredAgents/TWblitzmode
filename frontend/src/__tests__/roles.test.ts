import { isAdminRole, normalizeRole } from '../lib/roles';

describe('role normalization utilities', () => {
  it('normalizes admin aliases', () => {
    expect(normalizeRole('owner')).toBe('admin');
    expect(normalizeRole('team_admin')).toBe('admin');
    expect(isAdminRole('manager_admin')).toBe(true);
  });

  it('normalizes user aliases and defaults', () => {
    expect(normalizeRole('viewer')).toBe('user');
    expect(normalizeRole('readonly')).toBe('user');
    expect(normalizeRole(undefined)).toBe('user');
  });

  it('falls back to user for unknown roles', () => {
    expect(normalizeRole('enterprise_champion')).toBe('user');
    expect(isAdminRole('enterprise_champion')).toBe(false);
  });
});
