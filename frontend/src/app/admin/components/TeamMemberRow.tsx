import React from 'react';
import type { TeamMember } from '../../../types';

interface TeamMemberRowProps {
  member: TeamMember;
  roleOptions: Array<'admin' | 'user'>;
  formatRoleLabel: (role: string) => string;
  statusBadgeClasses: Record<string, string>;
  memberActionId: number | null;
  resettingMemberId: number | null;
  onRoleChange: (memberId: number, role: 'admin' | 'user') => void;
  onToggleStatus: (member: TeamMember) => void;
  onResetPassword: (memberId: number) => void;
  formatDate: (value?: string | null | undefined) => string;
}

export function TeamMemberRow({
  member,
  roleOptions,
  formatRoleLabel,
  statusBadgeClasses,
  memberActionId,
  resettingMemberId,
  onRoleChange,
  onToggleStatus,
  onResetPassword,
  formatDate,
}: TeamMemberRowProps) {
  const statusKey = member.status ?? 'active';
  const cookieStatusKey = member.cookie_status ?? 'missing';
  const statusBadgeClass = resolveBadgeClass(statusBadgeClasses, statusKey);
  const cookieBadgeClass = resolveBadgeClass(statusBadgeClasses, cookieStatusKey);
  const isProcessing = memberActionId === member.id;
  const isResetting = resettingMemberId === member.id;
  const isActive = statusKey === 'active';

  return (
    <tr data-testid="team-member-row" data-member-id={member.id} data-member-name={member.name}>
      <TeamMemberNameCell member={member} />
      <TeamMemberEmailCell member={member} />
      <TeamMemberRoleCell
        memberId={member.id}
        currentRole={member.role ?? 'user'}
        roleOptions={roleOptions}
        formatRoleLabel={formatRoleLabel}
        disabled={isProcessing}
        onRoleChange={onRoleChange}
      />
      <TeamMemberStatusCell label={formatRoleLabel(statusKey)} badgeClass={statusBadgeClass} />
      <TeamMemberStatusCell label={cookieStatusKey} badgeClass={cookieBadgeClass} />
      <TeamMemberLoginCell value={member.last_login_at} formatDate={formatDate} />
      <TeamMemberActionsCell
        member={member}
        isActive={isActive}
        isProcessing={isProcessing}
        isResetting={isResetting}
        onRoleChange={onRoleChange}
        onToggleStatus={onToggleStatus}
        onResetPassword={onResetPassword}
      />
    </tr>
  );
}

function TeamMemberNameCell({ member }: { member: TeamMember }) {
  return <td className="py-2 pr-4">{member.name}</td>;
}

function TeamMemberEmailCell({ member }: { member: TeamMember }) {
  return <td className="py-2 pr-4 text-xs text-muted-foreground">{member.email ?? '—'}</td>;
}

interface TeamMemberRoleCellProps {
  memberId: number;
  currentRole: string;
  roleOptions: Array<'admin' | 'user'>;
  formatRoleLabel: (role: string) => string;
  disabled: boolean;
  onRoleChange: (memberId: number, role: 'admin' | 'user') => void;
}

function TeamMemberRoleCell({ memberId, currentRole, roleOptions, formatRoleLabel, disabled, onRoleChange }: TeamMemberRoleCellProps) {
  const safeRole = roleOptions.includes(currentRole as 'admin' | 'user') ? currentRole : 'user';

  return (
    <td className="py-2 pr-4 text-xs text-muted-foreground">
      <select
        value={safeRole}
        onChange={(event) => onRoleChange(memberId, event.target.value as 'admin' | 'user')}
        disabled={disabled}
        className="w-full rounded-lg border border-border/30 bg-muted/20 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        {roleOptions.map((option) => (
          <option key={option} value={option} className="text-foreground">
            {formatRoleLabel(option)}
          </option>
        ))}
      </select>
    </td>
  );
}

function TeamMemberStatusCell({ label, badgeClass }: { label: string; badgeClass: string }) {
  return (
    <td className="py-2 pr-4 text-xs">
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full ${badgeClass}`}>{label}</span>
    </td>
  );
}

function TeamMemberLoginCell({
  value,
  formatDate,
}: {
  value?: string | null | undefined;
  formatDate: (input?: string | null | undefined) => string;
}) {
  return <td className="py-2 pr-4 text-xs text-muted-foreground">{formatDate(value)}</td>;
}

interface TeamMemberActionsProps {
  member: TeamMember;
  isActive: boolean;
  isProcessing: boolean;
  isResetting: boolean;
  onToggleStatus: (member: TeamMember) => void;
  onResetPassword: (memberId: number) => void;
  onRoleChange: (memberId: number, role: 'admin' | 'user') => void;
}

function TeamMemberActionsCell({
  member,
  isActive,
  isProcessing,
  isResetting,
  onRoleChange,
  onToggleStatus,
  onResetPassword,
}: TeamMemberActionsProps) {
  const normalizedRole = (member.role ?? 'user') as 'admin' | 'user';
  const isAdmin = normalizedRole === 'admin';

  return (
    <td className="py-2 pl-4 text-right">
      <div className="flex items-center justify-end gap-2">
        <button
          data-testid="team-member-role-toggle"
          type="button"
          onClick={() => onRoleChange(member.id, isAdmin ? 'user' : 'admin')}
          disabled={isProcessing}
          className="px-3 py-1 text-xs rounded-lg border border-border/30 bg-muted/20 hover:bg-muted/30 disabled:opacity-50"
        >
          {isAdmin ? 'Make Standard' : 'Make Admin'}
        </button>
        <button
          type="button"
          onClick={() => onToggleStatus(member)}
          disabled={isProcessing}
          className="px-3 py-1 text-xs rounded-lg border border-border/30 bg-muted/20 hover:bg-muted/30 disabled:opacity-50"
        >
          {isActive ? 'Deactivate' : 'Activate'}
        </button>
        <button
          type="button"
          onClick={() => onResetPassword(member.id)}
          disabled={isResetting}
          className="px-3 py-1 text-xs rounded-lg border border-border/30 bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50"
        >
          {isResetting ? 'Generating…' : 'Reset Password'}
        </button>
      </div>
    </td>
  );
}

function resolveBadgeClass(map: Record<string, string>, key: string): string {
  const lookup = new Map(Object.entries(map));
  return lookup.get(key) ?? 'bg-slate-500/20 text-slate-600';
}
