const ADMIN_ALIASES = new Set([
  'admin',
  'org_admin',
  'organization_admin',
  'super_admin',
  'platform_admin',
  'owner',
  'ops',
  'support',
  'team_admin',
  'manager_admin',
]);

const USER_ALIASES = new Set([
  'user',
  'member',
  'viewer',
  'operator',
  'contributor',
  'readonly',
  'read_only',
  'observer',
  'guest',
  'analyst',
  'approver',
]);

export type NormalizedRole = 'admin' | 'user';

export function normalizeRole(role?: string | null): NormalizedRole {
  if (!role) {
    return 'user';
  }

  const lowered = role.trim().toLowerCase();
  if (ADMIN_ALIASES.has(lowered)) {
    return 'admin';
  }
  if (USER_ALIASES.has(lowered)) {
    return 'user';
  }

  return 'user';
}

export function isAdminRole(role?: string | null): boolean {
  return normalizeRole(role) === 'admin';
}
