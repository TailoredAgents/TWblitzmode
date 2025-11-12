import React from 'react';
import GlassCard from '../../../components/ui/GlassCard';
import type { TeamMember } from '../../../types';
import { TeamMemberRow } from './TeamMemberRow';

type TeamStatusFilter = 'all' | 'active' | 'deactivated';

interface TeamMembersTabProps {
  members: TeamMember[];
  filteredMembers: TeamMember[];
  statusFilter: TeamStatusFilter;
  onStatusFilterChange: (filter: TeamStatusFilter) => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
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

export function TeamMembersTab(props: TeamMembersTabProps) {
  const {
    members,
    filteredMembers,
    statusFilter,
    onStatusFilterChange,
    searchQuery,
    onSearchChange,
    ...tableProps
  } = props;

  return (
    <GlassCard className="p-6 space-y-4">
      <TeamMembersHeader />
      <TeamMembersFilters
        statusFilter={statusFilter}
        onStatusFilterChange={onStatusFilterChange}
        searchQuery={searchQuery}
        onSearchChange={onSearchChange}
      />
      <TeamMembersTable filteredMembers={filteredMembers} members={members} {...tableProps} />
    </GlassCard>
  );
}

function TeamMembersHeader() {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-lg font-semibold text-foreground">Team Members</h2>
      <p className="text-xs text-muted-foreground">
        Manage member status and monitor cookie compliance across your organization.
      </p>
    </div>
  );
}

interface TeamMembersFiltersProps {
  statusFilter: TeamStatusFilter;
  onStatusFilterChange: (filter: TeamStatusFilter) => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
}

function TeamMembersFilters({ statusFilter, onStatusFilterChange, searchQuery, onSearchChange }: TeamMembersFiltersProps) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <input
        type="text"
        value={searchQuery}
        onChange={(event) => onSearchChange(event.target.value)}
        placeholder="Search by name or email"
        className="w-full md:w-72 rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
      />
      <select
        value={statusFilter}
        onChange={(event) => onStatusFilterChange(event.target.value as TeamStatusFilter)}
        className="w-full md:w-48 rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="deactivated">Deactivated</option>
      </select>
    </div>
  );
}

type TeamMembersTableProps = Pick<
  TeamMembersTabProps,
  |
    'roleOptions'
    | 'formatRoleLabel'
    | 'statusBadgeClasses'
    | 'memberActionId'
    | 'resettingMemberId'
    | 'onRoleChange'
    | 'onToggleStatus'
    | 'onResetPassword'
    | 'formatDate'
> & {
  filteredMembers: TeamMember[];
  members: TeamMember[];
};

function TeamMembersTable({ filteredMembers, members, ...rowProps }: TeamMembersTableProps) {
  const hasMembers = filteredMembers.length > 0;

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <TeamMembersTableHeader />
          <tbody className="divide-y divide-border/20">
            {filteredMembers.map((member) => (
              <TeamMemberRow key={member.id} member={member} {...rowProps} />
            ))}
          </tbody>
        </table>
        {!hasMembers && <NoTeamMembersMessage />}
      </div>
      <TeamMembersSummary visibleCount={filteredMembers.length} totalCount={members.length} />
    </>
  );
}

function TeamMembersTableHeader() {
  return (
    <thead className="text-left text-xs uppercase text-muted-foreground border-b border-border/20">
      <tr>
        <th className="py-2 pr-4">Name</th>
        <th className="py-2 pr-4">Email</th>
        <th className="py-2 pr-4">Role</th>
        <th className="py-2 pr-4">Status</th>
        <th className="py-2">Cookie Status</th>
        <th className="py-2 pr-4">Last Login</th>
        <th className="py-2 pl-4 text-right">Actions</th>
      </tr>
    </thead>
  );
}

function NoTeamMembersMessage() {
  return (
    <div className="py-6 text-center text-sm text-muted-foreground">
      No team members found. Teammates can self‑seat: click Login → enter
      <span className="mx-1 font-mono">Tallwave123</span>→ click “+ Team member”.
    </div>
  );
}

interface TeamMembersSummaryProps {
  visibleCount: number;
  totalCount: number;
}

function TeamMembersSummary({ visibleCount, totalCount }: TeamMembersSummaryProps) {
  return (
    <p className="text-xs text-muted-foreground">
      Showing {visibleCount} of {totalCount} team members.
    </p>
  );
}
