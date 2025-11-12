import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Filter, SlidersHorizontal, RefreshCw } from 'lucide-react';
import ProspectsGrid from './ui/ProspectsGrid';
import GlassCard from './ui/GlassCard';
import { useToastActions } from './ui/ToastContainer';
import { cn, debounce } from '../lib/utils';
import { apiService } from '../services/api';
import type { ProspectWithConnectors, ConnectorWithContext, ProspectFilters } from '../types';

const STATUS_WHITELIST = new Set<ProspectWithConnectors['status']>([
  'pending_lookup',
  'lookup_complete',
  'mutuals_found',
  'enriched',
  'scheduled',
  'contacted',
]);

const PRIORITY_WHITELIST = new Set<ProspectWithConnectors['priority']>(['low', 'medium', 'high', 'urgent']);

export const toNumber = (value: unknown, fallback?: number): number => {
  if (value === null || value === undefined) {
    return fallback ?? 0;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback ?? 0;
};

export interface ProspectNormalizationContext {
  organizationKey?: string | null;
  organizationId?: string | number | null;
}

/* eslint-disable security/detect-object-injection */
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const pickString = (record: Record<string, unknown>, ...keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string') {
      return value;
    }
  }
  return undefined;
};

const pickBoolean = (record: Record<string, unknown>, key: string, fallback = false): boolean =>
  typeof record[key] === 'boolean' ? (record[key] as boolean) : fallback;
/* eslint-enable security/detect-object-injection */

export const normalizeConnector = (input: unknown, index: number): ConnectorWithContext => {
  const connector = isRecord(input) ? input : {};

  const id = toNumber(connector['id'], index + 1);
  const rankingRaw = connector['ranking_score'];
  const rankingScore =
    typeof rankingRaw === 'number' && Number.isFinite(rankingRaw)
      ? rankingRaw
      : Number.isFinite(Number(rankingRaw))
        ? Number(rankingRaw)
        : 0;

  const emailStatusRaw = pickString(connector, 'email_status');
  const emailStatusValues: ReadonlyArray<ConnectorWithContext['email_status']> = [
    'pending',
    'available',
    'unavailable',
    'bounced',
  ];
  const emailStatus =
    emailStatusRaw && emailStatusValues.includes(emailStatusRaw as ConnectorWithContext['email_status'])
      ? (emailStatusRaw as ConnectorWithContext['email_status'])
      : 'pending';

  const reasonCodesSource = connector['reason_codes'];
  const reasonCodes = Array.isArray(reasonCodesSource)
    ? reasonCodesSource.map((code) => String(code))
    : undefined;

  const companyValue = pickString(connector, 'company', 'organization');
  const company = companyValue && companyValue.trim().length > 0 ? companyValue : undefined;

  const connectionDegreeValue = connector['connection_degree'] ?? connector['degree'];
  const connectionDegree =
    typeof connectionDegreeValue === 'number' && Number.isFinite(connectionDegreeValue)
      ? connectionDegreeValue
      : Number.isFinite(Number(connectionDegreeValue))
        ? Number(connectionDegreeValue)
        : undefined;

  const relationshipStrengthValue = connector['relationship_strength'] ?? connector['score'];
  const relationshipStrength =
    typeof relationshipStrengthValue === 'number' && Number.isFinite(relationshipStrengthValue)
      ? relationshipStrengthValue
      : Number.isFinite(Number(relationshipStrengthValue))
        ? Number(relationshipStrengthValue)
        : undefined;

  const sharedExperiencesSource = connector['shared_experiences'] ?? connector['shared_roles'];
  const sharedExperiences = Array.isArray(sharedExperiencesSource)
    ? sharedExperiencesSource.map((experience) => String(experience))
    : typeof sharedExperiencesSource === 'string'
      ? [sharedExperiencesSource]
      : undefined;

  const connectorWithContext: ConnectorWithContext = {
    id,
    full_name: pickString(connector, 'full_name', 'name') ?? '',
    ranking_score: rankingScore,
    rank: toNumber(connector['rank'], index + 1),
    email_status: emailStatus,
  };

  if (company) {
    connectorWithContext.company = company;
  }
  const headlineValue = pickString(connector, 'headline', 'title', 'role');
  if (headlineValue) {
    connectorWithContext.headline = headlineValue;
  }
  const emailValue = pickString(connector, 'email', 'contact_email');
  if (emailValue) {
    connectorWithContext.email = emailValue;
  }
  const linkedinValue = pickString(connector, 'linkedin_url', 'profile_url');
  if (linkedinValue) {
    connectorWithContext.linkedin_url = linkedinValue;
  }
  if (connector['team_member_id'] !== undefined) {
    connectorWithContext.team_member_id = toNumber(connector['team_member_id'], 0);
  }
  if (connectionDegree !== undefined) {
    connectorWithContext.connection_degree = connectionDegree;
  }
  if (relationshipStrength !== undefined) {
    connectorWithContext.relationship_strength = relationshipStrength;
  }
  const mutualContextValue = pickString(connector, 'mutual_context', 'shared_context');
  if (mutualContextValue) {
    connectorWithContext.mutual_context = mutualContextValue;
  }
  if (sharedExperiences) {
    connectorWithContext.shared_experiences = sharedExperiences;
  }
  if (reasonCodes) {
    connectorWithContext.reason_codes = reasonCodes;
  }
  const profilePictureValue = pickString(connector, 'profile_picture_url', 'avatar_url');
  if (profilePictureValue) {
    connectorWithContext.profile_picture_url = profilePictureValue;
  }
  if (pickBoolean(connector, 'is_team_member', false)) {
    connectorWithContext.is_team_member = true;
  }

  return connectorWithContext;
};

export const normalizeProspect = (
  input: unknown,
  index: number,
  context: ProspectNormalizationContext = {}
): ProspectWithConnectors => {
  const raw = isRecord(input) ? input : {};
  const id = toNumber(raw['id'], index + 1);

  const statusCandidate = (pickString(raw, 'status') ?? '').toLowerCase();
  const normalizedStatus = STATUS_WHITELIST.has(statusCandidate as ProspectWithConnectors['status'])
    ? (statusCandidate as ProspectWithConnectors['status'])
    : 'pending_lookup';

  const priorityCandidate = (pickString(raw, 'priority') ?? '').toLowerCase();
  const normalizedPriority = PRIORITY_WHITELIST.has(priorityCandidate as ProspectWithConnectors['priority'])
    ? (priorityCandidate as ProspectWithConnectors['priority'])
    : 'medium';

  let connectorsSource: unknown[] = [];
  if (Array.isArray(raw['top_connectors']) && raw['top_connectors'].length > 0) {
    connectorsSource = raw['top_connectors'];
  } else if (Array.isArray(raw['connectors'])) {
    connectorsSource = raw['connectors'];
  }

  const normalizedConnectors = connectorsSource
    .filter((connector): connector is Record<string, unknown> => isRecord(connector))
    .map((connector, connectorIndex) => normalizeConnector(connector, connectorIndex));

  const organizationCandidate =
    raw['organization_id'] ??
    raw['tenant_id'] ??
    context.organizationKey ??
    (context.organizationId ?? '');

  let organization_id: string | number = '';
  if (typeof organizationCandidate === 'number' && Number.isFinite(organizationCandidate)) {
    organization_id = organizationCandidate;
  } else {
    const candidateString = String(organizationCandidate ?? '').trim();
    if (candidateString.length > 0) {
      const parsed = Number(candidateString);
      organization_id = Number.isFinite(parsed) ? parsed : candidateString;
    }
  }

  const tagsValue = raw['tags'];

  const createdAt = pickString(raw, 'created_at') ?? new Date().toISOString();
  const updatedAt = pickString(raw, 'updated_at') ?? createdAt;

  const prospect: ProspectWithConnectors = {
    id,
    organization_id,
    company: pickString(raw, 'company', 'company_name') ?? '',
    full_name: pickString(raw, 'full_name', 'name') ?? '',
    status: normalizedStatus,
    priority: normalizedPriority,
    created_at: createdAt,
    updated_at: updatedAt,
    connectors_count: toNumber(raw['connectors_count'], normalizedConnectors.length),
    top_connectors: normalizedConnectors,
  };

  const roleValue = pickString(raw, 'role', 'title', 'headline');
  if (roleValue) {
    prospect.role = roleValue;
  }

  const emailValue = pickString(raw, 'email', 'work_email');
  if (emailValue) {
    prospect.email = emailValue;
  }

  const linkedinValue = pickString(raw, 'linkedin_url', 'profile_url');
  if (linkedinValue) {
    prospect.linkedin_url = linkedinValue;
  }

  const locationValue = pickString(raw, 'location', 'city');
  if (locationValue) {
    prospect.location = locationValue;
  }

  const headlineValue = pickString(raw, 'headline', 'bio');
  if (headlineValue) {
    prospect.headline = headlineValue;
  }

  const companySizeValue = pickString(raw, 'company_size', 'size');
  if (companySizeValue) {
    prospect.company_size = companySizeValue;
  }

  const industryValue = pickString(raw, 'industry', 'sector');
  if (industryValue) {
    prospect.industry = industryValue;
  }

  const aboutValue = pickString(raw, 'about', 'summary');
  if (aboutValue) {
    prospect.about = aboutValue;
  }

  if (Array.isArray(tagsValue)) {
    prospect.tags = tagsValue.map((tag) => String(tag));
  }

  const notesValue = pickString(raw, 'notes');
  if (notesValue) {
    prospect.notes = notesValue;
  }

  const profilePictureValue = pickString(raw, 'profile_picture_url', 'avatar_url');
  if (profilePictureValue) {
    prospect.profile_picture_url = profilePictureValue;
  }

  const lastContactValue = pickString(raw, 'last_contact_date', 'last_contacted_at');
  if (lastContactValue) {
    prospect.last_contact_date = lastContactValue;
  }

  const responseRate = raw['response_rate'];
  if (typeof responseRate === 'number' && Number.isFinite(responseRate)) {
    prospect.response_rate = responseRate;
  }

  return prospect;
};

interface ProspectsViewProps {
  organizationId: string | number;
  className?: string;
}

const ProspectsView: React.FC<ProspectsViewProps> = ({ organizationId, className }) => {
  const [prospects, setProspects] = useState<ProspectWithConnectors[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState<ProspectFilters>({});
  const [showFilters, setShowFilters] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { error, success } = useToastActions();

  // Status and priority options for filtering
  const statusOptions = [
    'pending_lookup',
    'lookup_complete',
    'mutuals_found',
    'enriched',
    'scheduled',
    'contacted'
  ];

  const priorityOptions = ['low', 'medium', 'high', 'urgent'];

  const organizationKey = useMemo(() => {
    if (organizationId === null || organizationId === undefined) {
      return null;
    }
    const value =
      typeof organizationId === 'string'
        ? organizationId.trim()
        : Number.isFinite(organizationId)
          ? organizationId.toString()
          : '';
    return value.length > 0 ? value : null;
  }, [organizationId]);
  // Debounced search
  const debouncedSearch = useMemo(
    () => debounce((query: string) => {
      setFilters(prev => {
        if (query) {
          return { ...prev, search: query };
        } else {
          const { search, ...rest } = prev;
          return rest as ProspectFilters;
        }
      });
    }, 300),
    []
  );

  useEffect(() => {
    debouncedSearch(searchQuery);
  }, [searchQuery, debouncedSearch]);



  const loadProspects = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setLoadError(null);

    try {
      const enrichedFilters: ProspectFilters = {
        ...filters,
      };

      const response = await apiService.getProspects(enrichedFilters, organizationKey ?? undefined);
      const normalized = (response ?? []).map((prospect, index) =>
        normalizeProspect(prospect, index, { organizationKey, organizationId })
      );
      setProspects(normalized);
    } catch (err) {
      console.error('Error loading prospects:', err);
      error(
        'Failed to load prospects',
        'Please try refreshing the page or contact support if the issue persists.'
      );
      setLoadError('We hit a snag loading prospects. Try refreshing or adjust your filters.');
      setProspects([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filters, organizationKey, organizationId, error]);

  useEffect(() => {
    void loadProspects();
  }, [loadProspects]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadProspects(false);
  };

  const handleProspectSelect = (prospect: ProspectWithConnectors) => {
    const name = prospect.full_name?.trim()?.length ? prospect.full_name : 'Prospect';
    success(`Selected ${name}`, 'Prospect has been successfully selected for outreach.');
  };

  const handleConnectorSelect = (connector: ConnectorWithContext, prospect: ProspectWithConnectors) => {
    const connectorName = connector.full_name?.trim()?.length ? connector.full_name : 'Connector';
    const prospectName = prospect.full_name?.trim()?.length ? prospect.full_name : 'prospect';
    success(
      `Selected ${connectorName} for ${prospectName}`,
      'Connector relationship has been established.'
    );
  };

  const handleFilterChange = <K extends keyof ProspectFilters>(key: K, value: ProspectFilters[K] | undefined) => {
    setFilters((prev) => {
      if (value === undefined || (typeof value === 'string' && value.trim().length === 0) || (Array.isArray(value) && value.length === 0)) {
        const { [key]: _removed, ...rest } = prev;
        return rest as ProspectFilters;
      }
      return { ...prev, [key]: value } as ProspectFilters;
    });
  };

  const clearFilters = () => {
    setFilters({});
    setSearchQuery('');
  };

  const activeFilterCount = Object.values(filters).filter(value =>
    value !== undefined && value !== '' &&
    (Array.isArray(value) ? value.length > 0 : true)
  ).length;

  if (!organizationKey) {
    return (
      <GlassCard className="p-6">
        <div className="space-y-2">
          <h2 className="text-lg font-semibold text-primary">No organization selected</h2>
          <p className="text-sm text-muted-foreground">
            Join an organization or request access from an administrator to manage prospects.
          </p>
        </div>
      </GlassCard>
    );
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Prospects</h1>
            <p className="text-muted-foreground">
              Manage your prospect pipeline and connections
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn('w-4 h-4', refreshing && 'animate-spin')} />
              Refresh
            </button>
          </div>
        </div>

        {/* Search and Filters */}
        <GlassCard className="p-4">
          <div className="flex flex-col gap-4">
            {/* Search bar */}
            <div className="flex items-center gap-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search prospects by name, company, or role..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                />
              </div>

              <button
                onClick={() => setShowFilters(!showFilters)}
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-2 rounded-lg transition-colors',
                  showFilters
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:text-foreground'
                )}
              >
                <SlidersHorizontal className="w-4 h-4" />
                Filters
                {activeFilterCount > 0 && (
                  <span className="bg-destructive text-destructive-foreground text-xs px-1.5 py-0.5 rounded-full">
                    {activeFilterCount}
                  </span>
                )}
              </button>
            </div>

            {/* Expanded filters */}
            {showFilters && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 pt-4 border-t border-border">
                {/* Status filter */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Status
                  </label>
                  <select
                    multiple
                    value={filters.status ?? []}
                    onChange={(e) => {
                      const values = Array.from(e.target.selectedOptions, option => option.value);
                      handleFilterChange('status', values.length > 0 ? values : undefined);
                    }}
                    className="w-full bg-background border border-border rounded-lg p-2 text-sm"
                  >
                    {statusOptions.map(status => (
                      <option key={status} value={status}>
                        {status.replace('_', ' ')}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Priority filter */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Priority
                  </label>
                  <select
                    multiple
                    value={filters.priority ?? []}
                    onChange={(e) => {
                      const values = Array.from(e.target.selectedOptions, option => option.value);
                      handleFilterChange('priority', values.length > 0 ? values : undefined);
                    }}
                    className="w-full bg-background border border-border rounded-lg p-2 text-sm"
                  >
                    {priorityOptions.map(priority => (
                      <option key={priority} value={priority}>
                        {priority}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Company filter */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Company
                  </label>
                  <input
                    type="text"
                    placeholder="Filter by company"
                    value={filters.company ?? ''}
                    onChange={(e) => {
                      const nextValue = e.target.value;
                      handleFilterChange('company', nextValue.length > 0 ? nextValue : undefined);
                    }}
                    className="w-full bg-background border border-border rounded-lg p-2 text-sm"
                  />
                </div>

                {/* Has connectors filter */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Connections
                  </label>
                  <select
                    value={filters.hasConnectors === undefined ? '' : filters.hasConnectors.toString()}
                    onChange={(e) => {
                      const value = e.target.value;
                      handleFilterChange('hasConnectors',
                        value === '' ? undefined : value === 'true'
                      );
                    }}
                    className="w-full bg-background border border-border rounded-lg p-2 text-sm"
                  >
                    <option value="">All prospects</option>
                    <option value="true">Has connections</option>
                    <option value="false">No connections</option>
                  </select>
                </div>

                {/* Clear filters button */}
                {activeFilterCount > 0 && (
                  <div className="col-span-full">
                    <button
                      onClick={clearFilters}
                      className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-destructive/10 text-destructive hover:bg-destructive/20 rounded-lg transition-colors"
                    >
                      <Filter className="w-3 h-3" />
                      Clear {activeFilterCount} filter{activeFilterCount !== 1 ? 's' : ''}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </GlassCard>
      </div>

      {loadError && (
        <GlassCard className="border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {loadError}
        </GlassCard>
      )}

      {/* Prospects grid */}
      <ProspectsGrid
        prospects={prospects}
        loading={loading}
        onProspectSelect={handleProspectSelect}
        onConnectorSelect={handleConnectorSelect}
        filters={filters}
        onFiltersChange={setFilters}
        emptyStateTitle="No prospects found"
        emptyStateDescription="Start by importing prospects or adjust your search filters."
      />
    </div>
  );
};

export default ProspectsView;
