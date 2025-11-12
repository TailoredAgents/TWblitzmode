import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Users,
  Bot,
  Mail,
  TrendingUp,
  AlertTriangle,
  CheckCircle,
  Clock,
  Activity,
  BarChart3,
  PieChart,
  RefreshCw,
  ArrowUpRight,
  Copy,
} from 'lucide-react';
import {
  LineChart,
  AreaChart,
  Area,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { AnalyticsOverview } from '../types';
import { apiService } from '../services/api';
import webSocketService from '../services/websocket';
import { useToastActions } from './ui/ToastContainer';
import GlassCard from './ui/GlassCard';
import { DashboardSkeleton } from './ui/LoadingSkeleton';
import { cn, stringifyId } from '../lib/utils';
import LinkChat from './LinkChat';
import { useI18n } from '../contexts/I18nContext';
import { getChartPalette } from '../lib/designTokens';
import { useFocusManagement, announceToScreenReader, generateAccessibleId, AccessibilityPatterns, useReducedMotion } from '../lib/accessibility';

interface DashboardOverviewProps {
  organizationId: string | number;
  userId: string | number;
}

const DashboardOverview: React.FC<DashboardOverviewProps> = ({ organizationId, userId }) => {
  const { error, success } = useToastActions();
  const { t } = useI18n();
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isUsingFallbackData, setIsUsingFallbackData] = useState(false);
  const [chartPalette, setChartPalette] = useState<string[]>(() => getChartPalette());

  // Accessibility enhancements
  const [mainContentRef] = useFocusManagement();
  const prefersReducedMotion = useReducedMotion();
  const dashboardTitleId = generateAccessibleId('dashboard-title');
  const fallbackDataAlertId = generateAccessibleId('fallback-data-alert');
  const metricsRegionId = generateAccessibleId('metrics-region');
  const chartsRegionId = generateAccessibleId('charts-region');
  const agenticTools = useMemo(
    () => [
      {
        id: 'run_saswave_mutuals',
        label: 'Run Saswave Mutuals',
        description: 'Use the Apify Saswave scraper to discover primary mutual connections.',
        audience: 'User/Admin',
        confirmation: 'standard',
        command: '/run_saswave_mutuals prospect:<id>',
      },
      {
        id: 'run_phantombuster_enrichment',
        label: 'PhantomBuster Enrichment',
        description: 'Secondary enrichment that requires an approval ID and never replaces Saswave.',
        audience: 'User/Admin',
        confirmation: 'detailed',
        command: '/run_phantombuster_enrichment approval:<id>',
      },
      {
        id: 'request_introduction_approval',
        label: 'Request Introduction Approval',
        description: 'Route intro drafts through the approval ladder before sending via SendGrid.',
        audience: 'User/Admin',
        confirmation: 'standard',
        command: '/request_introduction_approval prospect:<id>',
      },
      {
        id: 'dry_run_corporate_connect',
        label: 'Dry-Run Corporate Connect',
        description: 'Preview scope, cookies, and projected throughput before running the org-wide job.',
        audience: 'Admin only',
        confirmation: 'detailed',
        command: '/dry_run_corporate_connect scope=all',
      },
    ],
    []
  );

  const organizationKey = useMemo(() => stringifyId(organizationId), [organizationId]);
  const userKey = useMemo(() => stringifyId(userId), [userId]);

  const loadAnalytics = useCallback(
    async (showRefreshing = false) => {
      if (!organizationKey) {
        setAnalytics(null);
        setIsUsingFallbackData(true);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (showRefreshing) setRefreshing(true);
      else setLoading(true);

      try {
        const response = await apiService.getAnalyticsOverview(organizationKey);
        if (response.data) {
          setAnalytics(response.data);
          setIsUsingFallbackData(false);
        } else {
          setAnalytics(null);
          setIsUsingFallbackData(true);
        }
      } catch (err) {
        console.error('Failed to load analytics:', err);
        setAnalytics(null);
        setIsUsingFallbackData(true);
        error(t('dashboard.errors.loadAnalytics'), t('dashboard.errors.loadDashboardHint'));
        announceToScreenReader(t('dashboard.errors.loadAnalytics'), 'assertive');
      } finally {
        setLoading(false);
        setRefreshing(false);
        if (showRefreshing) {
          announceToScreenReader(t('dashboard.refreshComplete'), 'polite');
        }
      }
    },
    [organizationKey, error, t]
  );

  useEffect(() => {
    // Ensure we pick up the active theme palette after hydration
    setChartPalette(getChartPalette());
  }, []);

  const prospectActivityData = useMemo(() => {
    const hasRealData = analytics?.prospects?.activity_trend;
    if (!hasRealData && !isUsingFallbackData) {
      setIsUsingFallbackData(true);
    } else if (hasRealData && isUsingFallbackData) {
      setIsUsingFallbackData(false);
    }
    return hasRealData ?? [];
  }, [analytics?.prospects?.activity_trend, isUsingFallbackData]);

  const workflowDistribution = useMemo(() => {
    const hasRealData = analytics?.workflows?.distribution;
    const distribution = hasRealData ?? [];
    return distribution.map((item, index) => ({
      ...item,
      color: chartPalette[index % chartPalette.length],
    }));
  }, [analytics?.workflows?.distribution, chartPalette]);

  const responseRateData = useMemo(() => {
    const hasRealData = analytics?.prospects?.response_trend;
    return hasRealData ?? [];
  }, [analytics?.prospects?.response_trend]);

  const outreachColor = chartPalette[0] ?? '#FFD400';
  const responseColor = chartPalette[1] ?? '#111111';
  const successColor = chartPalette[2] ?? '#FFE766';

  const handleCopyToolCommand = useCallback(
    async (command: string) => {
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard) {
          throw new Error('Clipboard unavailable');
        }
        await navigator.clipboard.writeText(command);
        success(`Copied ${command} to clipboard`);
      } catch (err) {
        console.error('Failed to copy command', err);
        error('Unable to copy command', 'Copy the command manually instead.');
      }
    },
    [success, error]
  );

  const handleAnalyticsUpdate = useCallback((payload: unknown) => {
    if (typeof payload !== 'object' || payload === null) {
      return;
    }
    const update = payload as Partial<AnalyticsOverview>;
    setAnalytics((prev) => {
      if (prev) {
        return { ...prev, ...update };
      }
      if (update && Object.keys(update).length > 0) {
        return update as AnalyticsOverview;
      }
      return prev;
    });
  }, []);

  const setupWebSocketListeners = useCallback(() => {
    webSocketService.on('analytics_update', handleAnalyticsUpdate);
  }, [handleAnalyticsUpdate]);

  useEffect(() => {
    if (!organizationKey || !userKey) {
      setLoading(false);
      setAnalytics(null);
      setIsUsingFallbackData(true);
      return;
    }

    loadAnalytics();
    setupWebSocketListeners();

    return () => {
      webSocketService.off('analytics_update', handleAnalyticsUpdate);
    };
  }, [organizationKey, userKey, loadAnalytics, setupWebSocketListeners, handleAnalyticsUpdate]);

  const handleRefresh = () => {
    loadAnalytics(true);
    announceToScreenReader(t('dashboard.refreshing'), 'polite');
  };

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatPercentage = (num: number): string => {
    return `${(num * 100).toFixed(1)}%`;
  };

  if (loading) {
    return <DashboardSkeleton />;
  }

  return (
    <main
      ref={mainContentRef}
      className="space-y-6"
      role="main"
      aria-labelledby={dashboardTitleId}
      aria-live="polite"
      aria-busy={loading || refreshing}
    >
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
          <h1
            id={dashboardTitleId}
            className="text-2xl font-bold text-foreground"
          >
            {t('dashboard.header')}
          </h1>
          <p className="text-muted-foreground" role="doc-subtitle">
            {t('dashboard.subheader')}
          </p>
        </div>
        <button
          {...AccessibilityPatterns.button(
            refreshing ? t('dashboard.refreshing') : t('dashboard.refresh'),
            handleRefresh,
            { disabled: refreshing }
          )}
          aria-describedby={isUsingFallbackData ? fallbackDataAlertId : undefined}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw
            className={cn(
              'w-4 h-4',
              refreshing && !prefersReducedMotion && 'animate-spin'
            )}
            aria-hidden="true"
          />
          {refreshing ? t('dashboard.refreshing') : t('dashboard.refresh')}
        </button>
      </header>

      {/* Demo Data Banner */}
      {isUsingFallbackData && (
        <div
          id={fallbackDataAlertId}
          role="alert"
          aria-live="polite"
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle
              className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0"
              aria-label="Warning"
            />
            <div>
              <h2 className="text-sm font-medium text-amber-800 dark:text-amber-200">
                Data Unavailable
              </h2>
              <p className="text-sm text-amber-700 dark:text-amber-300">
                Unable to load live analytics data. Charts and metrics will appear once data becomes available.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Agentic Tool Catalog */}
      <section aria-labelledby="agentic-tools-heading" className="space-y-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h2 id="agentic-tools-heading" className="text-lg font-semibold text-foreground">
              {t('dashboard.sections.agenticTools', 'Agentic tool catalog')}
            </h2>
            <p className="text-sm text-muted-foreground">
              {t(
                'dashboard.sections.agenticToolsDescription',
                'Trigger Link’s automation stack directly from chat or copy a command below to run from the agent console.',
              )}
            </p>
          </div>
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            {t('dashboard.sections.guardrails', 'Saswave primary · Phantom optional · SendGrid only')}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {agenticTools.map((tool) => (
            <GlassCard key={tool.id} className="p-4 flex flex-col justify-between border border-border/30 bg-background/40">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">{tool.label}</p>
                <p className="text-xs text-muted-foreground">{tool.description}</p>
                <p className="text-[11px] text-muted-foreground/80">
                  {tool.audience} · {tool.confirmation} confirmation
                </p>
              </div>
              <button
                type="button"
                className="mt-3 inline-flex items-center gap-1 rounded-lg border border-border/40 bg-background/60 px-2 py-1 text-xs font-medium text-foreground hover:bg-muted/40 transition-colors"
                onClick={() => handleCopyToolCommand(tool.command)}
                aria-label={`Copy ${tool.command}`}
              >
                <Copy className="w-3 h-3" aria-hidden="true" />
                <span>{tool.command}</span>
              </button>
            </GlassCard>
          ))}
        </div>
      </section>

      {/* Key Metrics Grid */}
      <section
        aria-labelledby="metrics-heading"
        id={metricsRegionId}
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6"
      >
        <h2 id="metrics-heading" className="sr-only">{t('dashboard.sections.keyMetrics')}</h2>
        {/* Total Prospects */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.totalProspects')}</h3>
              <p
                className="text-3xl font-bold text-foreground"
                aria-label={`${formatNumber(analytics?.prospects?.total ?? 0)} total prospects`}
              >
                {formatNumber(analytics?.prospects?.total ?? 0)}
              </p>
              <div className="flex items-center gap-1 mt-2 text-green-500">
                <ArrowUpRight className="w-4 h-4" aria-label="Trending up" />
                <span className="text-sm font-medium" aria-label="12.5 percent increase">+12.5%</span>
                <span className="text-xs text-muted-foreground">{t('dashboard.deltas.vsLastMonth')}</span>
              </div>
            </div>
            <div className="p-3 bg-primary/20 rounded-full" aria-hidden="true">
              <Users className="w-6 h-6 text-primary" />
            </div>
          </div>
        </GlassCard>

        {/* Active Workflows */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.activeWorkflows')}</h3>
              <p
                className="text-3xl font-bold text-foreground"
                aria-label={`${analytics?.workflows?.total ?? 0} active workflows`}
              >
                {analytics?.workflows?.total ?? 0}
              </p>
              <div className="flex items-center gap-1 mt-2 text-green-500">
                <ArrowUpRight className="w-4 h-4" aria-label="Trending up" />
                <span className="text-sm font-medium" aria-label="3 new workflows">+3</span>
                <span className="text-xs text-muted-foreground">{t('dashboard.deltas.thisWeek')}</span>
              </div>
            </div>
            <div className="p-3 bg-secondary/20 rounded-full" aria-hidden="true">
              <Bot className="w-6 h-6 text-secondary" />
            </div>
          </div>
        </GlassCard>

        {/* Response Rate */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.quotaUsage')}</h3>
              <p
                className="text-3xl font-bold text-foreground"
                aria-label={`${formatPercentage(analytics?.quotas?.utilization ?? 0)} quota utilization`}
              >
                {formatPercentage(analytics?.quotas?.utilization ?? 0)}
              </p>
              <div className="flex items-center gap-1 mt-2 text-green-500">
                <ArrowUpRight className="w-4 h-4" aria-label="Trending up" />
                <span className="text-sm font-medium" aria-label="2.3 percent improvement">+2.3%</span>
                <span className="text-xs text-muted-foreground">{t('dashboard.deltas.improvement')}</span>
              </div>
            </div>
            <div className="p-3 bg-green-500/15 rounded-full" aria-hidden="true">
              <TrendingUp className="w-6 h-6 text-green-500" />
            </div>
          </div>
        </GlassCard>

        {/* Emails Sent */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.emailsThisWeek')}</h3>
              <p
                className="text-3xl font-bold text-foreground"
                aria-label={`${formatNumber(analytics?.quotas?.emails_sent_this_week ?? 0)} emails sent this week`}
              >
                {formatNumber(analytics?.quotas?.emails_sent_this_week ?? 0)}
              </p>
              <div className="flex items-center gap-1 mt-2 text-green-500">
                <ArrowUpRight className="w-4 h-4" aria-label="Trending up" />
                <span className="text-sm font-medium" aria-label="18.7 percent increase">+18.7%</span>
                <span className="text-xs text-muted-foreground">{t('dashboard.deltas.thisMonth')}</span>
              </div>
            </div>
            <div className="p-3 bg-accent/20 rounded-full" aria-hidden="true">
              <Mail className="w-6 h-6 text-accent" />
            </div>
          </div>
        </GlassCard>
      </section>

      {/* Charts Section */}
      <section
        aria-labelledby="charts-heading"
        id={chartsRegionId}
        className="grid grid-cols-1 lg:grid-cols-2 gap-6"
      >
        <h2 id="charts-heading" className="sr-only">{t('dashboard.sections.charts')}</h2>
        {/* Prospect Activity Chart */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-foreground">{t('dashboard.charts.prospectActivity')}</h3>
              <p className="text-sm text-muted-foreground">{t('dashboard.charts.prospectActivitySubtitle')}</p>
            </div>
            <BarChart3 className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
          </div>
          <div
            className="h-80"
            role="img"
            aria-label={`Prospect activity chart showing outreach and responses data over the past week. ${isUsingFallbackData ? 'Currently no live data is available.' : ''}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={prospectActivityData}
                aria-label="Prospect activity trend chart"
              >
                <defs>
                  <linearGradient id="colorContacts" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={outreachColor} stopOpacity={0.32} />
                    <stop offset="95%" stopColor={outreachColor} stopOpacity={0.06} />
                  </linearGradient>
                  <linearGradient id="colorResponses" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={responseColor} stopOpacity={0.32} />
                    <stop offset="95%" stopColor={responseColor} stopOpacity={0.06} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.1)" />
                <XAxis
                  dataKey="name"
                  stroke="rgba(148, 163, 184, 0.8)"
                  fontSize={12}
                  aria-label="Days of the week"
                />
                <YAxis
                  stroke="rgba(148, 163, 184, 0.8)"
                  fontSize={12}
                  aria-label="Number of contacts"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '8px',
                    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)',
                  }}
                  cursor={{ fill: 'rgba(255, 255, 255, 0.1)' }}
                />
                <Legend />
                <Area
                  type="monotone"
                  dataKey="contacts"
                  stroke={outreachColor}
                  fillOpacity={1}
                  fill="url(#colorContacts)"
                  strokeWidth={2}
                  name={t('dashboard.charts.outreach')}
                  aria-label="Outreach contacts"
                />
                <Area
                  type="monotone"
                  dataKey="responses"
                  stroke={responseColor}
                  fillOpacity={1}
                  fill="url(#colorResponses)"
                  strokeWidth={2}
                  name={t('dashboard.charts.responses')}
                  aria-label="Prospect responses"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* AI Workflow Distribution */}
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-foreground">{t('dashboard.charts.aiWorkflowDistribution')}</h3>
              <p className="text-sm text-muted-foreground">{t('dashboard.charts.aiWorkflowDistributionSubtitle')}</p>
            </div>
            <PieChart className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
          </div>
          <div
            className="h-80"
            role="img"
            aria-label={`AI workflow distribution pie chart showing ${workflowDistribution.map(item => `${item.name}: ${item.value}%`).join(', ')}. ${isUsingFallbackData ? 'Currently no live data is available.' : ''}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <RechartsPieChart>
                <Pie
                  data={workflowDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={120}
                  paddingAngle={5}
                  dataKey="value"
                  aria-label="Workflow distribution percentages"
                >
                  {workflowDistribution.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.color}
                      aria-label={`${entry.name}: ${entry.value}%`}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '8px',
                    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)',
                  }}
                />
                <Legend />
              </RechartsPieChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>
      </section>

      {/* Response Rate Trend */}
      <section aria-labelledby="response-rate-heading">
        <GlassCard className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 id="response-rate-heading" className="text-lg font-semibold text-foreground">{t('dashboard.charts.responseRate')}</h2>
              <p className="text-sm text-muted-foreground">{t('dashboard.charts.responseRateSubtitle')}</p>
            </div>
            <TrendingUp className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
          </div>
          <div
            className="h-80"
            role="img"
            aria-label={`Response rate trend chart showing monthly progression from ${responseRateData[0]?.month} to ${responseRateData[responseRateData.length - 1]?.month}. Current rate: ${responseRateData[responseRateData.length - 1]?.rate}%. ${isUsingFallbackData ? 'Currently no live data is available.' : ''}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={responseRateData}>
                <defs>
                  <linearGradient id="colorRate" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={successColor} stopOpacity={0.32} />
                    <stop offset="95%" stopColor={successColor} stopOpacity={0.06} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.1)" />
                <XAxis
                  dataKey="month"
                  stroke="rgba(148, 163, 184, 0.8)"
                  fontSize={12}
                  aria-label="Months"
                />
                <YAxis
                  stroke="rgba(148, 163, 184, 0.8)"
                  fontSize={12}
                  aria-label="Response rate percentage"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '8px',
                    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)',
                  }}
                  cursor={{ stroke: successColor, strokeWidth: 1, strokeDasharray: '3 3' }}
                />
                <Area
                  type="monotone"
                  dataKey="rate"
                  stroke={successColor}
                  fillOpacity={1}
                  fill="url(#colorRate)"
                  strokeWidth={3}
                  dot={{ fill: successColor, strokeWidth: 2, r: 4 }}
                  activeDot={{ r: 6, stroke: successColor, strokeWidth: 2, fill: 'white' }}
                  aria-label="Response rate trend line"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>
      </section>

      {/* Link Chat and Status Section */}
      <section aria-labelledby="status-section-heading" className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <h2 id="status-section-heading" className="sr-only">{t('dashboard.sections.statusOverview')}</h2>

        {/* Link Chat Assistant */}
        <div className="lg:col-span-1">
          <LinkChat
            organizationId={organizationId}
            userId={userId}
            className="h-96"
          />
        </div>

        {/* Status Cards */}
        <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-6" role="region" aria-label="System status cards">
        {/* Pending Approvals */}
        <GlassCard className="p-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-yellow-500/10 rounded-full" aria-hidden="true">
              <Clock className="w-6 h-6 text-yellow-500" />
            </div>
            <div className="flex-1">
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.approvalsPending')}</h3>
              <p
                className="text-2xl font-bold text-foreground"
                aria-label={`${analytics?.workflows?.pending_approval ?? 0} workflows pending approval`}
              >
                {analytics?.workflows?.pending_approval ?? 0}
              </p>
              <p className="text-xs text-yellow-600">{t('dashboard.deltas.workflowsPending')}</p>
            </div>
          </div>
        </GlassCard>

        {/* Completed Tasks */}
        <GlassCard className="p-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-green-500/10 rounded-full" aria-hidden="true">
              <CheckCircle className="w-6 h-6 text-green-500" />
            </div>
            <div className="flex-1">
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.completedThisWeek')}</h3>
              <p
                className="text-2xl font-bold text-foreground"
                aria-label={`${analytics?.workflows?.completed_this_week ?? 0} workflows completed this week`}
              >
                {analytics?.workflows?.completed_this_week ?? 0}
              </p>
              <p className="text-xs text-green-600">{t('dashboard.deltas.completedWorkflows')}</p>
            </div>
          </div>
        </GlassCard>

        {/* System Health */}
        <GlassCard className="p-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-primary/10 rounded-full" aria-hidden="true">
              <Activity className="w-6 h-6 text-primary" />
            </div>
            <div className="flex-1">
              <h3 className="text-sm text-muted-foreground font-medium">{t('dashboard.cards.systemHealth')}</h3>
              <p
                className="text-2xl font-bold text-green-500"
                aria-label="System health: 98.5 percent operational"
              >
                98.5%
              </p>
              <p className="text-xs text-green-600">{t('dashboard.deltas.systemsOperational')}</p>
            </div>
          </div>
        </GlassCard>
        </div>
      </section>
    </main>
  );
};

export default DashboardOverview;
