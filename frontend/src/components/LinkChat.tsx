/* eslint-disable max-lines */
// Link Chat - Real-Time AI Assistant Interface
// October 2025 WebSocket Integration

'use client';

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Bot, User, Zap, AlertCircle, CheckCircle, Loader2, ArrowUp, X, Minimize2, Check, BookOpen, Info } from 'lucide-react';
import { apiService } from '../services/api';
import GlassCard from './ui/GlassCard';
import { cn } from '../lib/utils';
import { useToastActions } from './ui/ToastContainer';
import type { CookieVaultSummary, CookieVaultUserSummary } from '../types';
import { getAccessToken } from '../lib/authToken';
import { normalizeWebSocketBaseUrl } from '../lib/websocketUrl';

interface ChatMessage {
  id: string;
  type: 'user' | 'system' | 'response' | 'error' | 'typing' | 'workflow_progress' | 'custom_notification';
  message: string;
  timestamp: string;
  session_id?: string;
  metadata?: Record<string, unknown>;

  // Progress-specific fields
  workflow_type?: string;
  workflow_id?: string;
  progress_percentage?: number | string;
  current_step?: number | string;
  total_steps?: number | string;
  status?: string;
  results?: Record<string, unknown>;
  error_details?: Record<string, unknown>;
}

interface SafeTopicGuidance {
  safePractices: string[];
  cautionTopics: string[];
  prohibitedTopics: string[];
}

interface TierLimitSummary {
  monthlyContacts: string | number;
  exports: string | number;
  integrations: string | number;
  dataRetention: string;
}

export const resolveLinkChatWebSocketBase = (apiBaseUrl: string): string => {
  const explicit = process.env.NEXT_PUBLIC_WS_URL ?? process.env.NEXT_PUBLIC_WEBSOCKET_URL;
  if (explicit) {
    const preferSecure =
      explicit.startsWith('https://') ||
      (typeof window !== 'undefined' && window.location?.protocol === 'https:') ||
      (typeof window === 'undefined' && process.env.NODE_ENV === 'production');
    return normalizeWebSocketBaseUrl(explicit, { preferSecure }).toString().replace(/\/$/, '');
  }

  const preferSecure =
    (typeof window !== 'undefined' && window.location?.protocol === 'https:') ||
    (typeof window === 'undefined' && process.env.NODE_ENV === 'production');

  let fallbackHost: string | undefined;
  if (typeof window !== 'undefined') {
    const locationHost = window.location?.host;
    if (locationHost) {
      const scheme = preferSecure ? 'https' : 'http';
      fallbackHost = `${scheme}://${locationHost}`;
    }
  }

  return normalizeWebSocketBaseUrl(apiBaseUrl, {
    preferSecure,
    ...(fallbackHost && { fallbackHost }),
  }).toString().replace(/\/$/, '');
};

export const planLinkChatReconnect = (
  attempts: number,
  maxAttempts: number,
  baseDelay: number,
): { shouldRetry: boolean; nextAttempt: number; delay: number } => {
  if (attempts >= maxAttempts) {
    return { shouldRetry: false, nextAttempt: attempts, delay: 0 };
  }

  const delay = baseDelay * Math.pow(2, attempts);
  const nextAttempt = attempts + 1;
  return { shouldRetry: true, nextAttempt, delay };
};

interface LinkChatProps {
  organizationId: number | string;
  userId: number | string;
  userToken?: string;
  className?: string;
  isMinimized?: boolean;
  onToggleMinimize?: () => void;
  height?: 'compact' | 'standard' | 'expanded';
  userTier?: 'tier1' | 'tier2' | 'tier3';
  organizationTier?: 'tier1' | 'tier2' | 'tier3';
}

const LINKCHAT_DISCLOSURES: string[] = [
  'Conversations are retained for 30 days to support compliance reviews and audit trails.',
  'Bulk exports and integrations pause automatically when monthly contact or export limits are reached.',
  'Requests containing sensitive personal data are redacted and may require admin approval before execution.',
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((entry) => String(entry)) : [];

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  isRecord(value) ? value : undefined;

const toOptionalString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

const toOptionalBoolean = (value: unknown): boolean | undefined =>
  typeof value === 'boolean' ? value : undefined;

const normalizeSessionId = (value: unknown): string | null => {
  const stringCandidate = toOptionalString(value);
  if (stringCandidate && stringCandidate.trim().length > 0) {
    return stringCandidate;
  }
  if (typeof value === 'number') {
    return String(value);
  }
  return null;
};

type AgentTransport = 'ws' | 'http';

const mapCookieVaultSummary = (payload: unknown): CookieVaultSummary | null => {
  if (!isRecord(payload)) {
    return null;
  }

  const rawUserSummaries = Array.isArray(payload.user_summaries) ? payload.user_summaries : [];
  const userSummaries = rawUserSummaries.reduce<CookieVaultUserSummary[]>((acc, entry) => {
    if (!isRecord(entry)) {
      return acc;
    }

    const summary: CookieVaultUserSummary = {
      userId: String(entry.user_id ?? ''),
      active: Number(entry.active ?? 0),
      expired: Number(entry.expired ?? 0),
      expiringSoon: Number(entry.expiring_soon ?? 0),
      stale: Number(entry.stale ?? 0),
      rotationRecommended: Boolean(entry.rotation_recommended),
      vaultItemIds: toStringArray(entry.vault_item_ids),
    };

    if (typeof entry.latest_label === 'string') {
      summary.latestLabel = entry.latest_label;
    }
    if (typeof entry.latest_created_at === 'string') {
      summary.latestCreatedAt = entry.latest_created_at;
    }
    if (typeof entry.latest_expires_at === 'string') {
      summary.latestExpiresAt = entry.latest_expires_at;
    }
    if (typeof entry.rotation_due_at === 'string') {
      summary.rotationDueAt = entry.rotation_due_at;
    }

    acc.push(summary);
    return acc;
  }, []);

  const status =
    payload.status === 'healthy' || payload.status === 'warning' || payload.status === 'missing'
      ? payload.status
      : 'missing';

  return {
    tenantId: String(payload.tenant_id ?? ''),
    totalItems: Number(payload.total_items ?? 0),
    activeItems: Number(payload.active_items ?? 0),
    expiredItems: Number(payload.expired_items ?? 0),
    expiringSoon: Number(payload.expiring_soon ?? 0),
    staleItems: Number(payload.stale_items ?? 0),
    rotationRecommended: Boolean(payload.rotation_recommended),
    status,
    message:
      typeof payload.message === 'string'
        ? payload.message
        : 'Cookie management status unavailable',
    lastRotationAt:
      typeof payload.last_rotation_at === 'string' ? payload.last_rotation_at : null,
    missingVaultEntries: Number(payload.missing_vault_entries ?? 0),
    missingVaultUsers: toStringArray(payload.missing_vault_users),
    userSummaries,
    generatedAt:
      typeof payload.generated_at === 'string' ? payload.generated_at : new Date().toISOString(),
  };
};

const LinkChat: React.FC<LinkChatProps> = ({
  organizationId,
  userId,
  userToken,
  className,
  isMinimized = false,
  onToggleMinimize,
  height = 'standard',
  userTier: propUserTier,
  organizationTier: propOrganizationTier
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [, setReconnectAttempts] = useState(0);
  const [isTyping, setIsTyping] = useState(false);
  const [textareaHeight, setTextareaHeight] = useState('auto');
  const [placeholderText, setPlaceholderText] = useState('');
  const [connectionToken, setConnectionToken] = useState<string | null>(null);
  const [supportsHttpFallback, setSupportsHttpFallback] = useState<boolean>(true);
  const [httpFallbackEndpoint, setHttpFallbackEndpoint] = useState<string | null>(null);
  const [inputValidationErrors, setInputValidationErrors] = useState<string[]>([]);
  const [safetyWarnings, setSafetyWarnings] = useState<string[]>([]);
  const [showGuidance, setShowGuidance] = useState(false);
  const [promptSuggestions, setPromptSuggestions] = useState<string[]>([]);
  const [showDataDisclosure, setShowDataDisclosure] = useState(false);
  const [userTier, setUserTier] = useState<'tier1' | 'tier2' | 'tier3'>(propUserTier ?? 'tier1');
  const [effectiveOrganizationTier, setEffectiveOrganizationTier] = useState<'tier1' | 'tier2' | 'tier3'>(propOrganizationTier ?? 'tier1');
  const [automationEnabled, setAutomationEnabled] = useState<boolean>(false);
  const [cookieVaultAccess, setCookieVaultAccess] = useState<boolean>(false);
  const [cookieVaultSummary, setCookieVaultSummary] = useState<CookieVaultSummary | null>(null);
  const [tierLimits, setTierLimits] = useState<Record<string, unknown> | null>(null);
  const [tierSafeTopicGuidance, setTierSafeTopicGuidance] = useState<string[]>([]);
  const [hasAcknowledgedGuidance, setHasAcknowledgedGuidance] = useState(false);
  const [acknowledgingGuidance, setAcknowledgingGuidance] = useState(false);
  const [showFallbackBanner, setShowFallbackBanner] = useState(false);

const wsRef = useRef<WebSocket | null>(null);
const messagesEndRef = useRef<HTMLDivElement>(null);
const inputRef = useRef<HTMLTextAreaElement>(null);
const reconnectTimeoutRef = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);
const reconnectAttemptsRef = useRef(0);
const messageIdCounterRef = useRef(0);
const placeholderTimeoutRef = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);
  const { success, error: showError } = useToastActions();

  const resolveAuthToken = useCallback((): string => {
    if (userToken) {
      return userToken;
    }
    const token = getAccessToken();
    return token ?? '';
  }, [userToken]);

  // Fetch tier metadata if not provided as props
  useEffect(() => {
    const fetchTierMetadata = async () => {
      if (propUserTier && propOrganizationTier) return; // Already have tier data

      try {
        const authToken = resolveAuthToken();
        if (!authToken) return;

        // Fetch user and organization tier information from API
        const response = await fetch('/api/user/tier-info', {
          headers: {
            'Authorization': `Bearer ${authToken}`,
            'Content-Type': 'application/json',
          },
        });

        if (response.ok) {
          const tierData = await response.json();

          if (tierData.userTier && !propUserTier) {
            setUserTier(tierData.userTier);
          }

          if (tierData.organizationTier && !propOrganizationTier) {
            setEffectiveOrganizationTier(tierData.organizationTier);
          }

          if (Array.isArray(tierData.safeTopicGuidance)) {
            setTierSafeTopicGuidance(tierData.safeTopicGuidance);
          }

          if (typeof tierData.httpFallbackEnabled === 'boolean') {
            setSupportsHttpFallback(tierData.httpFallbackEnabled);
          }

          if (typeof tierData.automationEnabled === 'boolean') {
            setAutomationEnabled(tierData.automationEnabled);
          }

          if (typeof tierData.cookieVaultAccess === 'boolean') {
            setCookieVaultAccess(tierData.cookieVaultAccess);
          }

          if (tierData.cookieVaultSummary) {
            setCookieVaultSummary(mapCookieVaultSummary(tierData.cookieVaultSummary));
          } else {
            setCookieVaultSummary(null);
          }

          if (isRecord(tierData.limits)) {
            setTierLimits(tierData.limits);
          } else {
            setTierLimits(null);
          }

        } else {
          console.warn('[LinkChat] Failed to fetch tier metadata, using defaults');
          setCookieVaultSummary(null);
        }
      } catch (err) {
        console.error('[LinkChat] Error fetching tier metadata:', err);
        // Continue with default tier1 values
        setCookieVaultSummary(null);
      }
    };

    fetchTierMetadata();
  }, [propOrganizationTier, propUserTier, resolveAuthToken]);

  useEffect(() => {
    const loadGuidancePreference = async () => {
      try {
        const token = resolveAuthToken();
        if (!token) {
          if (typeof window !== 'undefined') {
            const localAck = window.localStorage.getItem('link_chat_guidance_ack');
            if (localAck) {
              setHasAcknowledgedGuidance(true);
            }
          }
          return;
        }

        const response = await apiService.getUserPreferences();
        const ackValue = response.data?.link_chat_guidance_ack;
        if (ackValue) {
          setHasAcknowledgedGuidance(true);
        } else if (typeof window !== 'undefined') {
          const localAck = window.localStorage.getItem('link_chat_guidance_ack');
          if (localAck) {
            setHasAcknowledgedGuidance(true);
          }
        }
      } catch (err) {
        if (typeof window !== 'undefined') {
          const localAck = window.localStorage.getItem('link_chat_guidance_ack');
          if (localAck) {
            setHasAcknowledgedGuidance(true);
          }
        }
      }
    };

    loadGuidancePreference();
  }, [resolveAuthToken]);

  useEffect(() => {
    if (supportsHttpFallback && connectionError) {
      setShowFallbackBanner(true);
    }
    if (!connectionError) {
      setShowFallbackBanner(false);
    }
  }, [supportsHttpFallback, connectionError]);

  // Update userTier when props change
  useEffect(() => {
    if (propUserTier) {
      setUserTier(propUserTier);
    }
  }, [propUserTier]);

  useEffect(() => {
    if (propOrganizationTier) {
      setEffectiveOrganizationTier(propOrganizationTier);
    }
  }, [propOrganizationTier]);

  // Dynamic placeholder text options
  const placeholderOptions = useMemo(
    () => [
      'Ask Link about prospects...',
      'Find LinkedIn connections...',
      'Search for company executives...',
      'Generate personalized emails...',
      'Research industry contacts...',
      'Analyze prospect relationships...',
      'What can I help you with today?',
      'Looking for specific contacts?'
    ],
    []
  );

  const cookieVaultHealth = useMemo(() => {
    if (!cookieVaultSummary) {
      return null;
    }

    const severity = cookieVaultSummary.status;
    const showWarning =
      cookieVaultSummary.rotationRecommended ||
      cookieVaultSummary.missingVaultEntries > 0 ||
      cookieVaultSummary.expiringSoon > 0;

    const colors = (() => {
      switch (severity) {
        case 'healthy':
          return {
            container: 'border-emerald-200 bg-emerald-50/80 text-emerald-800',
            icon: 'text-emerald-600',
            title: 'Cookie vault is healthy',
          } as const;
        case 'missing':
          return {
            container: 'border-rose-200 bg-rose-50/80 text-rose-800',
            icon: 'text-rose-600',
            title: 'Cookie vault missing',
          } as const;
        case 'warning':
        default:
          return {
            container: 'border-amber-200 bg-amber-50/80 text-amber-800',
            icon: 'text-amber-600',
            title: 'Cookie vault action needed',
          } as const;
      }
    })();

    return {
      severity,
      showWarning,
      colors,
      title: colors.title,
      message: cookieVaultSummary.message,
    };
  }, [cookieVaultSummary]);

  useEffect(() => {
    if (cookieVaultHealth?.showWarning && !showDataDisclosure) {
      setShowDataDisclosure(true);
    }
  }, [cookieVaultHealth, showDataDisclosure]);

  // Prompt suggestions for safe usage
  const promptSuggestionsData = useMemo(() => {
    const baseSuggestions = [
      "Find 5 marketing directors at SaaS companies in San Francisco",
      "Research connections at Acme Corp for warm introductions",
      "Generate personalized email for John Smith at TechCorp",
      "Find mutual connections with Sarah Johnson on LinkedIn",
      "Research company background for upcoming meeting",
      "Identify decision makers in the enterprise software space"
    ];

    const tier3AutomationSuggestions = [
      "Set up automated weekly prospecting for fintech startups",
      "Create automated follow-up sequence for cold outreach",
      "Build dynamic contact lists based on company growth metrics",
      "Configure real-time alerts for competitor hiring activity",
      "Automate multi-channel outreach campaigns with A/B testing",
      "Set up automated lead scoring and priority ranking"
    ];

    return automationEnabled ? [...baseSuggestions, ...tier3AutomationSuggestions] : baseSuggestions;
  }, [automationEnabled]);

  // Safety guardrails and validation patterns
  const safetyPatterns = useMemo(
    () => ({
      unsafePatterns: [
        /\b(hack|exploit|breach|penetrate)\b/i,
        /\b(scrape|crawl|extract)\s+(all|massive|bulk)\b/i,
        /\b(spam|blast|mass email)\b/i,
        /\b(personal|private|confidential)\s+(data|info)\b/i
      ],
      piiPatterns: [
        /\b(ssn|social security|phone number|address|salary)\b/i,
        /\b(credit card|payment|banking|financial)\b/i,
        /\b(password|login|credentials)\b/i
      ],
      bulkPatterns: [
        /\b(all|every|bulk|mass|thousands|hundreds)\s+(contacts|emails|prospects)\b/i,
        /\b(download|export|extract)\s+(all|everything)\b/i
      ]
    }),
    []
  );

  // Safe topic guidance system
  const defaultSafeTopicGuidance = useMemo<SafeTopicGuidance>(() => ({
    // Recommended safe topics
    safePractices: [
      "Finding specific professional contacts by role or company",
      "Research company background and recent news",
      "Generate personalized outreach messages",
      "Identify mutual connections for warm introductions",
      "Research industry trends and insights",
      "Find contact information for business development"
    ],
    // Topics to approach carefully
    cautionTopics: [
      "Large-scale data operations (consider tier limits)",
      "Integration with external systems (review security)",
      "Bulk email campaigns (ensure compliance)",
      "Cross-border data transfers (check regulations)"
    ],
    // Prohibited activities
    prohibitedTopics: [
      "Accessing private personal information",
      "Bypassing security measures or authentication",
      "Sending unsolicited bulk communications",
      "Storing or sharing sensitive financial data"
    ]
  }), []);

  const combinedSafeTopicGuidance = useMemo<SafeTopicGuidance>(() => {
    if (tierSafeTopicGuidance.length === 0) {
      return defaultSafeTopicGuidance;
    }

    return {
      safePractices: tierSafeTopicGuidance.slice(0, 5),
      cautionTopics: defaultSafeTopicGuidance.cautionTopics,
      prohibitedTopics: defaultSafeTopicGuidance.prohibitedTopics,
    };
  }, [tierSafeTopicGuidance, defaultSafeTopicGuidance]);

  // Height configurations for different modes
  const heightConfig = useMemo(() => {
    switch (height) {
      case 'compact': return 'h-80';
      case 'expanded': return 'h-[600px]';
      default: return 'h-96';
    }
  }, [height]);

  // WebSocket connection constants
  const MAX_RECONNECT_ATTEMPTS = 5;
  const BASE_RETRY_DELAY = 1000; // 1 second base delay
  const PLACEHOLDER_ROTATION_INTERVAL = 3000; // 3 seconds

  // Dynamic WebSocket URL builders
  const getApiBaseUrl = useCallback((): string => {
    if (process.env.NEXT_PUBLIC_API_URL) {
      return process.env.NEXT_PUBLIC_API_URL;
    }
    if (typeof window !== 'undefined') {
      const origin = window.location?.origin;
      if (origin) {
        try {
          const url = new URL(origin);
          url.port = '8888';
          return url.toString();
        } catch {
          return origin;
        }
      }
    }
    return 'http://localhost:8888';
  }, []);

  const getWebSocketBaseUrl = useCallback((): string => {
    const apiBase = getApiBaseUrl();
    return resolveLinkChatWebSocketBase(apiBase);
  }, [getApiBaseUrl]);

  const buildWebSocketUrl = useCallback((): string => {
    const baseUrl = getWebSocketBaseUrl();
    const token = resolveAuthToken();

    const params = new URLSearchParams({
      token,
      user_id: userId.toString(),
      organization_id: organizationId.toString()
    });

    return `${baseUrl}/ws/agent_chat?${params.toString()}`;
  }, [getWebSocketBaseUrl, resolveAuthToken, userId, organizationId]);

  // Get tier-specific data limits
  const getDataLimits = useCallback((): TierLimitSummary => {
    const parseLimitValue = (value: unknown, fallback: number): string | number => {
      if (value === undefined || value === null) {
        return fallback;
      }
      if (typeof value === 'number' && Number.isFinite(value)) {
        return value;
      }
      if (typeof value === 'string') {
        const normalized = value.trim();
        if (normalized.length === 0) {
          return fallback;
        }
        if (normalized.toLowerCase() === 'unlimited') {
          return 'Unlimited';
        }
        const parsed = Number(normalized);
        if (!Number.isNaN(parsed)) {
          return parsed;
        }
      }
      return fallback;
    };

    const parseRetention = (value: unknown, fallback: string): string => {
      return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
    };

    if (tierLimits) {
      return {
        monthlyContacts: parseLimitValue((tierLimits as Record<string, unknown>)['monthly_contacts'], 100),
        exports: parseLimitValue((tierLimits as Record<string, unknown>)['exports'], 5),
        integrations: parseLimitValue((tierLimits as Record<string, unknown>)['integrations'], 1),
        dataRetention: parseRetention((tierLimits as Record<string, unknown>)['data_retention'], '30 days'),
      };
    }

    switch (userTier) {
      case 'tier2':
        return {
          monthlyContacts: 500,
          exports: 25,
          integrations: 3,
          dataRetention: '90 days',
        };
      case 'tier3':
        return {
          monthlyContacts: 'Unlimited',
          exports: 'Unlimited',
          integrations: 'Unlimited',
          dataRetention: '1 year',
        };
      default:
        return {
          monthlyContacts: 100,
          exports: 5,
          integrations: 1,
          dataRetention: '30 days',
        };
    }
  }, [tierLimits, userTier]);

  const tierLimitSummary = useMemo<TierLimitSummary>(() => getDataLimits(), [getDataLimits]);

  // Check if user input triggers data sharing disclosure
  const checkForDataSharingDisclosure = useCallback((text: string) => {
    const dataSharingTriggers = [
      /\b(export|download|extract|share)\b.*\b(data|contacts|information)\b/i,
      /\b(send|email|forward)\b.*\b(to|outside|external)\b/i,
      /\b(integration|api|webhook|third.?party)\b/i,
      /\b(crm|salesforce|hubspot|pipedrive)\b/i
    ];

    const triggersDataSharing = dataSharingTriggers.some(pattern => pattern.test(text));
    if (triggersDataSharing && !showDataDisclosure) {
      setShowDataDisclosure(true);
    }
  }, [showDataDisclosure]);

  // Input validation and safety checks
  const validateInput = useCallback((text: string) => {
    const errors: string[] = [];
    const warnings: string[] = [];

    // Check for unsafe patterns
    safetyPatterns.unsafePatterns.forEach(pattern => {
      if (pattern.test(text)) {
        errors.push('This request appears to involve unauthorized access or unsafe activities.');
      }
    });

    // Check for PII requests
    safetyPatterns.piiPatterns.forEach(pattern => {
      if (pattern.test(text)) {
        warnings.push('Avoid requesting personal or sensitive information.');
      }
    });

    // Check for bulk operations
    safetyPatterns.bulkPatterns.forEach(pattern => {
      if (pattern.test(text)) {
        warnings.push('Large-scale data operations require special approval.');
      }
    });

    // Check message length
    if (text.length > 500) {
      warnings.push('Consider breaking down complex requests into smaller parts.');
    }

    setInputValidationErrors(errors);
    setSafetyWarnings(warnings);
  }, [safetyPatterns]);

  // Generate prompt suggestions
  const generatePromptSuggestions = useCallback(() => {
    const shuffled = [...promptSuggestionsData].sort(() => 0.5 - Math.random());
    setPromptSuggestions(shuffled.slice(0, 3));
  }, [promptSuggestionsData]);

  // Auto-resize textarea
  const handleTextareaResize = useCallback(() => {
    if (inputRef.current) {
      const textarea = inputRef.current;
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 120); // Max height: 120px (about 4-5 lines)
      textarea.style.height = `${newHeight}px`;
      setTextareaHeight(`${newHeight}px`);
    }
  }, []);

  // Apply prompt suggestion
  const applyPromptSuggestion = useCallback((suggestion: string) => {
    setInputMessage(suggestion);
    setInputValidationErrors([]);
    setSafetyWarnings([]);
    if (inputRef.current) {
      inputRef.current.focus();
    }
    handleTextareaResize();
  }, [handleTextareaResize]);

  // Generate unique message ID
  const generateMessageId = () => {
    messageIdCounterRef.current += 1;
    return `msg_${Date.now()}_${messageIdCounterRef.current}`;
  };

  // Cycle through placeholder text
  const cyclePlaceholder = useCallback(() => {
    if (!isConnected) return;

    const randomIndex = Math.floor(Math.random() * placeholderOptions.length);
    const nextPlaceholder = placeholderOptions.at(randomIndex) ?? 'Ask me anything...';
    setPlaceholderText(nextPlaceholder);

    placeholderTimeoutRef.current = globalThis.setTimeout(
      cyclePlaceholder,
      PLACEHOLDER_ROTATION_INTERVAL,
    );
  }, [isConnected, placeholderOptions]);

  const handleAgentResponsePayload = useCallback(
    (agentResponse: unknown, transport: AgentTransport) => {
      if (!isRecord(agentResponse)) {
        setIsSending(false);
        setIsTyping(false);
        return;
      }

      const status = toOptionalString(agentResponse.status) ?? 'success';
      const replyText =
        toOptionalString(agentResponse.reply) ??
        toOptionalString(agentResponse.error) ??
        toOptionalString(agentResponse.message) ??
        '';

      const nextSessionCandidate = agentResponse.session_id ?? sessionId;
      const nextSessionId = normalizeSessionId(nextSessionCandidate) ?? sessionId ?? null;

      const connectionToken = toOptionalString(agentResponse.connection_token);
      if (connectionToken) {
        setConnectionToken(connectionToken);
      }

      const supportsHttp = toOptionalBoolean(agentResponse.supports_http);
      if (supportsHttp !== undefined) {
        setSupportsHttpFallback(supportsHttp);
      }

      const httpEndpoint = toOptionalString(agentResponse.http_endpoint);
      if (httpEndpoint) {
        setHttpFallbackEndpoint(httpEndpoint);
      }

      if (nextSessionId && nextSessionId !== sessionId) {
        setSessionId(nextSessionId);
      }

      setIsSending(false);
      setIsTyping(false);

      const metadata: Record<string, unknown> = {
        transport,
        citations: Array.isArray(agentResponse.citations) ? agentResponse.citations : [],
      };

      if (agentResponse.code !== undefined) {
        metadata.code = agentResponse.code;
      }

      const hint = toOptionalString(agentResponse.hint);
      if (hint) {
        metadata.hint = hint;
      }

      const messageId = generateMessageId();
      const newMessage: ChatMessage = {
        id: messageId,
        type: status === 'error' ? 'error' : 'response',
        message: replyText,
        timestamp: new Date().toISOString(),
        metadata,
        ...(nextSessionId ? { session_id: nextSessionId } : {}),
      };

      setMessages((prev) => {
        const filtered = prev.filter((msg) => msg.type !== 'typing');
        return [...filtered, newMessage];
      });

      if (status === 'error') {
        const errorTitle =
          replyText.trim().length > 0 ? replyText : 'Link encountered an error.';
        showError(errorTitle, hint);
      } else if (hint) {
        success(hint);
      }
    },
    [sessionId, success, showError]
  );

  // Simulate typing effect for responses
  // Scroll to bottom of messages
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  // Handle incoming WebSocket messages
  const handleWebSocketMessage = useCallback(
    (rawMessage: unknown) => {
      if (!isRecord(rawMessage)) {
        console.warn('[LinkChat] Ignoring malformed WebSocket payload:', rawMessage);
        return;
      }

      const timestamp = toOptionalString(rawMessage.timestamp) ?? new Date().toISOString();
      const messageType = toOptionalString(rawMessage.type) ?? 'system';

      const connectionToken = toOptionalString(rawMessage.connection_token);
      if (connectionToken) {
        setConnectionToken(connectionToken);
      }

      const supports = asRecord(rawMessage.supports);
      if (supports) {
        const httpFallback = toOptionalBoolean(supports.http_fallback);
        if (httpFallback !== undefined) {
          setSupportsHttpFallback(httpFallback);
        }
        const httpEndpoint = toOptionalString(supports.http_endpoint);
        if (httpEndpoint) {
          setHttpFallbackEndpoint(httpEndpoint);
        }
      }

      const updateSession = (candidate: unknown): string | null => {
        const normalized = normalizeSessionId(candidate);
        if (normalized && normalized !== sessionId) {
          setSessionId(normalized);
        }
        return normalized;
      };

      switch (messageType) {
        case 'system': {
          setIsTyping(false);
          setIsSending(false);
          setConnectionError(null);
          const sessionRef = updateSession(rawMessage.session_id);
          const message = toOptionalString(rawMessage.message);
          if (!message) {
            return;
          }
          setMessages((prev) => {
            const systemMessage: ChatMessage = {
              id: generateMessageId(),
              type: 'system',
              message,
              timestamp,
              ...(sessionRef ? { session_id: sessionRef } : {}),
            };
            return [...prev, systemMessage];
          });
          return;
        }
        case 'session_established': {
          const sessionRef = updateSession(rawMessage.session_id);
          const message = toOptionalString(rawMessage.message);
          if (message) {
            setMessages((prev) => {
              const systemMessage: ChatMessage = {
                id: generateMessageId(),
                type: 'system',
                message,
                timestamp,
                ...(sessionRef ? { session_id: sessionRef } : {}),
              };
              return [...prev, systemMessage];
            });
          }
          return;
        }
        case 'session_transferred': {
          setConnectionError('This chat session was opened in another window. This tab is now inactive.');
          setIsConnected(false);
          setIsSending(false);
          showError('Session transferred to another window. This tab will stop receiving updates.');
          const sessionRef = updateSession(rawMessage.session_id);
          const message =
            toOptionalString(rawMessage.message) ?? 'Session transferred to another client.';
          const systemMessage: ChatMessage = {
            id: generateMessageId(),
            type: 'system',
            message,
            timestamp,
            ...(sessionRef ? { session_id: sessionRef } : {}),
          };
          setMessages((prev) => [...prev, systemMessage]);
          return;
        }
        case 'response': {
          const payloadRecord = asRecord(rawMessage.payload) ?? {};
          const responsePayload: Record<string, unknown> = { ...payloadRecord };
          const reply =
            toOptionalString(payloadRecord['reply']) ?? toOptionalString(rawMessage.message);
          if (reply) {
            responsePayload.reply = reply;
          }
          const status =
            toOptionalString(payloadRecord['status']) ??
            toOptionalString(rawMessage.status) ??
            'success';
          responsePayload.status = status;
          const hint =
            toOptionalString(payloadRecord['hint']) ?? toOptionalString(rawMessage.hint);
          if (hint) {
            responsePayload.hint = hint;
          }
          const code = payloadRecord['code'] ?? rawMessage.code;
          if (code !== undefined) {
            responsePayload.code = code;
          }
          const sessionRef =
            normalizeSessionId(payloadRecord['session_id']) ??
            normalizeSessionId(rawMessage.session_id);
          if (sessionRef) {
            responsePayload.session_id = sessionRef;
          }
          handleAgentResponsePayload(responsePayload, 'ws');
          return;
        }
        case 'error': {
          const payloadRecord = asRecord(rawMessage.payload) ?? {};
          const errorPayload: Record<string, unknown> = { ...payloadRecord, status: 'error' };
          const reply =
            toOptionalString(payloadRecord['reply']) ?? toOptionalString(rawMessage.message);
          if (reply) {
            errorPayload.reply = reply;
          }
          const hint =
            toOptionalString(payloadRecord['hint']) ?? toOptionalString(rawMessage.hint);
          if (hint) {
            errorPayload.hint = hint;
          }
          const code = payloadRecord['code'] ?? rawMessage.code;
          if (code !== undefined) {
            errorPayload.code = code;
          }
          const sessionRef =
            normalizeSessionId(payloadRecord['session_id']) ??
            normalizeSessionId(rawMessage.session_id);
          if (sessionRef) {
            errorPayload.session_id = sessionRef;
          }
          handleAgentResponsePayload(errorPayload, 'ws');
          return;
        }
        case 'typing': {
          setIsTyping(true);
          const sessionRef = updateSession(rawMessage.session_id);
          const message = toOptionalString(rawMessage.message) ?? 'Link is thinking...';
          setMessages((prev) => {
            const filtered = prev.filter((msg) => msg.type !== 'typing');
            const typingMessage: ChatMessage = {
              id: generateMessageId(),
              type: 'typing',
              message,
              timestamp,
              ...(sessionRef ? { session_id: sessionRef } : {}),
            };
            return [...filtered, typingMessage];
          });
          return;
        }
        case 'workflow_progress': {
          const message = toOptionalString(rawMessage.message) ?? 'Workflow update received.';
          const results = asRecord(rawMessage.results);
          const errorDetails = asRecord(rawMessage.error_details);
          const metadata = asRecord(rawMessage.metadata);
          setMessages((prev) => {
            const workflowMessage: ChatMessage = {
              id: generateMessageId(),
              type: 'workflow_progress',
              message,
              timestamp,
            };

            const workflowType = toOptionalString(rawMessage.workflow_type);
            if (workflowType) {
              workflowMessage.workflow_type = workflowType;
            }

            const workflowId = toOptionalString(rawMessage.workflow_id);
            if (workflowId) {
              workflowMessage.workflow_id = workflowId;
            }

            const progressPercentage = rawMessage.progress_percentage;
            if (typeof progressPercentage === 'number' || typeof progressPercentage === 'string') {
              workflowMessage.progress_percentage = progressPercentage;
            }

            const currentStep = rawMessage.current_step;
            if (typeof currentStep === 'number' || typeof currentStep === 'string') {
              workflowMessage.current_step = currentStep;
            }

            const totalSteps = rawMessage.total_steps;
            if (typeof totalSteps === 'number' || typeof totalSteps === 'string') {
              workflowMessage.total_steps = totalSteps;
            }

            const status = toOptionalString(rawMessage.status);
            if (status) {
              workflowMessage.status = status;
            }

            if (results) {
              workflowMessage.results = results;
            }
            if (errorDetails) {
              workflowMessage.error_details = errorDetails;
            }
            if (metadata) {
              workflowMessage.metadata = metadata;
            }

            return [...prev, workflowMessage];
          });
          return;
        }
        case 'custom_notification': {
          const message =
            toOptionalString(rawMessage.message) ?? 'Link shared a notification.';
          const metadata = asRecord(rawMessage.metadata);
          setMessages((prev) => {
            const notificationMessage: ChatMessage = {
              id: generateMessageId(),
              type: 'custom_notification',
              message,
              timestamp,
              ...(metadata ? { metadata } : {}),
            };
            return [...prev, notificationMessage];
          });
          return;
        }
        default: {
          const message =
            toOptionalString(rawMessage.message) ?? 'Unknown message type received.';
          setMessages((prev) => [
            ...prev,
            {
              id: generateMessageId(),
              type: 'system',
              message,
              timestamp,
            },
          ]);
        }
      }
    },
    [handleAgentResponsePayload, sessionId, showError]
  );

  // Connect to WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    if (reconnectTimeoutRef.current) {
      globalThis.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setIsConnecting(true);
    setConnectionError(null);

    // Get JWT token for authentication
    const token = resolveAuthToken();
    if (!token) {
      setConnectionError('Authentication token not found');
      setIsConnecting(false);
      return;
    }

    try {
      const wsUrl = buildWebSocketUrl();
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        setIsConnecting(false);
        setConnectionError(null);
        if (reconnectTimeoutRef.current) {
          globalThis.clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
        reconnectAttemptsRef.current = 0;
        setReconnectAttempts(0); // Reset on successful connection
        setConnectionToken(null);
        setSupportsHttpFallback(true);
        setHttpFallbackEndpoint(null);

        // Send initialization message with tier metadata
        const initMessage = {
          type: 'init',
          organizationId,
          userId,
          userTier,
          organizationTier: effectiveOrganizationTier,
          timestamp: new Date().toISOString(),
          auth_token: resolveAuthToken()
        };

        try {
          ws.send(JSON.stringify(initMessage));
        } catch (err) {
          console.error('[LinkChat] Failed to send initialization message:', err);
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        setIsConnecting(false);

        if (reconnectTimeoutRef.current) {
          globalThis.clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }

        if (event.code !== 1000) { // Not a normal closure
          const attempts = reconnectAttemptsRef.current;
          const plan = planLinkChatReconnect(attempts, MAX_RECONNECT_ATTEMPTS, BASE_RETRY_DELAY);
          if (plan.shouldRetry) {
            reconnectAttemptsRef.current = plan.nextAttempt;
            setReconnectAttempts(plan.nextAttempt);
            setConnectionError(`Connection lost. Retrying in ${plan.delay / 1000}s... (${plan.nextAttempt}/${MAX_RECONNECT_ATTEMPTS})`);

            // Auto-reconnect with exponential backoff
            reconnectTimeoutRef.current = globalThis.setTimeout(() => {
              reconnectTimeoutRef.current = null;
              connectWebSocket();
            }, plan.delay);
          } else {
            // Max attempts reached - stop trying
            setConnectionError(`Connection failed after ${MAX_RECONNECT_ATTEMPTS} attempts. Please check your internet connection and refresh the page.`);
            showError('Unable to connect to Link chat service', 'Please check your connection and try refreshing the page.');
          }
        } else {
          reconnectAttemptsRef.current = 0;
          setReconnectAttempts(0);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setConnectionError('Connection error occurred');
        setIsConnecting(false);
      };

      wsRef.current = ws;

    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      setConnectionError('Failed to establish connection');
      setIsConnecting(false);
    }
  }, [
    buildWebSocketUrl,
    resolveAuthToken,
    organizationId,
    userId,
    userTier,
    effectiveOrganizationTier,
    showError,
    handleWebSocketMessage,
  ]);

  // Send message to Link
  const sendViaHttpFallback = useCallback(
    async (messageText: string) => {
      if (!supportsHttpFallback) {
        throw new Error('HTTP fallback is not enabled');
      }

      const token = resolveAuthToken();
      const endpoint = httpFallbackEndpoint ?? '/api/agent_chat';

      const baseUrl = getApiBaseUrl().replace(/\/$/, '');
      const targetUrl = endpoint.startsWith('http')
        ? endpoint
        : `${baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
      if (!token) {
        throw new Error('Missing authentication token for HTTP fallback');
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      };

      const requestBody: Record<string, unknown> = {
        message: messageText,
        user_id: userId,
        organization_id: organizationId,
        resume_token: connectionToken,
        connection_token: connectionToken,
      };
      if (sessionId) {
        requestBody.session_id = sessionId;
      }

      const response = await fetch(targetUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({}));
        const errorRecord = asRecord(errorPayload);
        const responseRecord = asRecord(errorRecord?.response);
        const fallbackHint =
          toOptionalString(responseRecord?.hint) ??
          toOptionalString(errorRecord?.hint) ??
          'HTTP fallback failed';
        throw new Error(fallbackHint);
      }

      const payload = await response.json();
      handleAgentResponsePayload(payload?.response ?? payload, 'http');
      setConnectionError(null);
      success('Message sent via fallback channel.');
    },
    [
      supportsHttpFallback,
      resolveAuthToken,
      httpFallbackEndpoint,
      sessionId,
      connectionToken,
      handleAgentResponsePayload,
      success,
      userId,
      organizationId,
      getApiBaseUrl,
    ]
  );

  const sendMessage = useCallback(async () => {
    const trimmed = inputMessage.trim();
    if (!trimmed || isSending) {
      return;
    }

    const messageText = trimmed;
    setInputMessage('');
    setIsSending(true);

    const userMessage: ChatMessage = {
      id: generateMessageId(),
      type: 'user',
      message: messageText,
      timestamp: new Date().toISOString(),
      ...(sessionId && { session_id: sessionId })
    };
    setMessages(prev => [...prev, userMessage]);

    const payload = {
      message: messageText,
      session_id: sessionId,
      resume_token: connectionToken,
      connection_token: connectionToken,
      userTier,
      organizationTier: effectiveOrganizationTier,
      organizationId,
      userId,
      timestamp: new Date().toISOString()
    };

    const sendOverWebSocket = () => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(payload));
        return true;
      }
      return false;
    };

    try {
      if (!sendOverWebSocket()) {
        if (!supportsHttpFallback) {
          throw new Error('WebSocket unavailable and HTTP fallback disabled');
        }
        await sendViaHttpFallback(messageText);
        setIsSending(false);
      }
    } catch (error: unknown) {
      console.error('Failed to deliver message:', error);
      setIsSending(false);
      const errorMessage =
        error instanceof Error && error.message ? error.message : 'Failed to send message to Link';
      showError(errorMessage);
      setConnectionError('Message delivery failed. Please retry.');
    }
  }, [
    inputMessage,
    isSending,
    sessionId,
    connectionToken,
    supportsHttpFallback,
    sendViaHttpFallback,
    showError,
    userTier,
    effectiveOrganizationTier,
    organizationId,
    userId
  ]);

  // Handle input key press
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Handle input change with auto-resize
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInputMessage(value);
    handleTextareaResize();

    // Validate input in real-time
    if (value.trim()) {
      validateInput(value);
      checkForDataSharingDisclosure(value);
    } else {
      setInputValidationErrors([]);
      setSafetyWarnings([]);
    }
  };

  // Clear input and reset height
  const clearInput = () => {
    setInputMessage('');
    setInputValidationErrors([]);
    setSafetyWarnings([]);
    setShowDataDisclosure(false);
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      setTextareaHeight('auto');
    }
  };

  const handleAcknowledgeGuidance = useCallback(async () => {
    if (acknowledgingGuidance) {
      return;
    }

    setAcknowledgingGuidance(true);
    const timestamp = new Date().toISOString();

    try {
      await apiService.setUserPreference('link_chat_guidance_ack', timestamp);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('link_chat_guidance_ack', timestamp);
      }
      setHasAcknowledgedGuidance(true);
    } catch (err) {
      console.warn('[LinkChat] Failed to persist guidance acknowledgment', err);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('link_chat_guidance_ack', 'local');
      }
      setHasAcknowledgedGuidance(true);
    } finally {
      setAcknowledgingGuidance(false);
      setShowGuidance(false);
    }
  }, [acknowledgingGuidance]);

  // Connect on mount and start placeholder cycling
  useEffect(() => {
    connectWebSocket();
    generatePromptSuggestions();

    return () => {
      if (reconnectTimeoutRef.current) {
      globalThis.clearTimeout(reconnectTimeoutRef.current);
      }
      if (placeholderTimeoutRef.current) {
        globalThis.clearTimeout(placeholderTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
      }
    };
  }, [connectWebSocket, generatePromptSuggestions]);

  // Start placeholder cycling when connection status changes
  useEffect(() => {
    if (isConnected) {
      cyclePlaceholder();
    } else {
      if (placeholderTimeoutRef.current) {
        globalThis.clearTimeout(placeholderTimeoutRef.current);
      }
      setPlaceholderText('');
    }
  }, [isConnected, cyclePlaceholder]);

  // Initialize textarea height
  useEffect(() => {
    handleTextareaResize();
  }, [handleTextareaResize]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Render progress message
  const renderProgressMessage = (message: ChatMessage) => {
    const percentage = typeof message.progress_percentage === 'number' ? message.progress_percentage : 0;
    const isCompleted = message.status === 'completed';
    const isFailed = message.status === 'failed';

    return (
      <div className="flex space-x-3">
        <div className="flex-shrink-0">
          <div className="w-8 h-8 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] flex items-center justify-center">
            {isCompleted ? (
              <CheckCircle className="w-4 h-4 text-white" />
            ) : isFailed ? (
              <AlertCircle className="w-4 h-4 text-white" />
            ) : (
              <Zap className="w-4 h-4 text-white" />
            )}
          </div>
        </div>
        <div className="flex-1">
          <div className="bg-blue-50/80 backdrop-blur-sm p-4 rounded-lg border border-blue-200">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-blue-900">
                {message.workflow_type?.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())} Workflow
              </span>
              <span className="text-sm text-blue-600">
                {typeof message.current_step === 'number' && typeof message.total_steps === 'number'
                  ? `${message.current_step}/${message.total_steps}`
                  : message.status
                }
              </span>
            </div>
            <p className="text-blue-800 mb-3">{message.message}</p>
            {!isFailed && !isCompleted && (
              <div className="w-full bg-blue-200 rounded-full h-2">
                <div
                  className="bg-gradient-to-r from-[#111111] to-[#FFD400] h-2 rounded-full transition-all duration-500"
                  style={{ width: `${percentage}%` }}
                ></div>
              </div>
            )}
            {message.results && (
              <div className="mt-3 text-sm text-blue-700">
                <strong>Results:</strong> {JSON.stringify(message.results, null, 2)}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  // Render individual message
  const renderMessage = (message: ChatMessage) => {
    const isUser = message.type === 'user';
    const isSystem = message.type === 'system';
    const isError = message.type === 'error';
    const isTyping = message.type === 'typing';
    const isProgress = message.type === 'workflow_progress';

    if (isProgress) {
      return renderProgressMessage(message);
    }

    return (
      <div className={cn(
        "flex space-x-3",
        isUser && "flex-row-reverse space-x-reverse"
      )}>
        <div className="flex-shrink-0">
          <div className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center",
            isUser ? "bg-gradient-to-r from-[#111111] to-[#2C2C2C]" : "bg-gradient-to-r from-[#111111] to-[#FFD400]"
          )}>
            {isUser ? (
              <User className="w-4 h-4 text-white" />
            ) : (
              <Bot className="w-4 h-4 text-white" />
            )}
          </div>
        </div>
        <div className={cn(
          "flex-1 max-w-md",
          isUser && "flex justify-end"
        )}>
          <div className={cn(
            "p-3 rounded-lg",
            isUser
              ? "bg-gradient-to-r from-[#111111] to-[#2C2C2C] text-white"
              : isError
                ? "bg-red-50 border border-red-200 text-red-900"
                : isSystem
                  ? "bg-yellow-50 border border-yellow-200 text-yellow-900"
                  : "bg-gray-50 border border-gray-200 text-gray-900"
          )}>
            {isTyping ? (
              <div className="flex items-center space-x-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{message.message}</span>
              </div>
            ) : (
              <div className="whitespace-pre-wrap">{message.message}</div>
            )}
          </div>
        </div>
      </div>
    );
  };

  // Don't render if minimized
  const inputDisabled = isSending || (!isConnected && !supportsHttpFallback);
  const sendDisabled =
    isSending ||
    inputValidationErrors.length > 0 ||
    !inputMessage.trim() ||
    (!isConnected && !supportsHttpFallback);
  const canSend = !sendDisabled;
  const inputPlaceholder = isConnected
    ? (placeholderText.trim().length > 0 ? placeholderText : 'Ask Link anything...')
    : supportsHttpFallback
      ? 'Link is connecting; drafts will send once online.'
      : 'Connecting...';

  if (isMinimized) {
    return (
      <div className={cn("fixed bottom-4 right-4 z-50", className)}>
        <button
          onClick={onToggleMinimize}
          className="w-14 h-14 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] text-white shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center"
        >
          <Bot className="w-6 h-6" />
        </button>
      </div>
    );
  }

  return (
    <GlassCard className={cn("flex flex-col", heightConfig, className, "relative overflow-hidden")}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/20 bg-gradient-to-r from-slate-50/80 to-emerald-50/80 backdrop-blur-sm">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] flex items-center justify-center shadow-lg">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">Link</h3>
            <p className="text-sm text-gray-600 flex items-center space-x-2">
              <span>{isConnected ? 'Online' : isConnecting ? 'Connecting...' : 'Offline'}</span>
              {isTyping && isConnected && (
                <span className="flex items-center space-x-1 text-blue-600">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span className="text-xs">typing...</span>
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          {automationEnabled && (
            <div className="badge-glass px-2 py-1 bg-gradient-to-r from-[#111111] to-[#FFD400] text-white">
              <span className="text-xs font-semibold">Enhanced Automation</span>
            </div>
          )}
          {cookieVaultAccess && (
            <div className="badge-glass px-2 py-1 bg-white/70 text-emerald-700 border border-emerald-200">
              <span className="text-xs font-semibold">Cookie Vault Active</span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowGuidance(true)}
            className="relative p-1 rounded-full hover:bg-white/20 transition-colors duration-200"
            aria-label="Open Link guidance"
            data-testid="link-chat-guidance-button"
          >
            <BookOpen className="w-4 h-4 text-gray-600" />
            {!hasAcknowledgedGuidance && (
              <span className="absolute -top-1 -right-1 inline-flex h-2 w-2 rounded-full bg-rose-500 shadow" />
            )}
          </button>
          <div className={cn(
            "w-3 h-3 rounded-full shadow-inner",
            isConnected ? "bg-green-500 shadow-green-200" : isConnecting ? "bg-yellow-500 shadow-yellow-200" : "bg-red-500 shadow-red-200"
          )} />
          {onToggleMinimize && (
            <button
              onClick={onToggleMinimize}
              className="p-1 rounded-full hover:bg-white/20 transition-colors duration-200"
            >
              <Minimize2 className="w-4 h-4 text-gray-600" />
            </button>
          )}
        </div>
      </div>

      {cookieVaultAccess && cookieVaultHealth && (
        <div
          className={cn(
            'mx-4 mt-3 rounded-lg border px-3 py-2 text-xs shadow-sm',
            cookieVaultHealth.colors.container,
          )}
          data-testid="link-chat-cookie-vault-banner"
        >
          <div className="flex items-start gap-2">
            {cookieVaultHealth.severity === 'healthy' ? (
              <CheckCircle className={cn('mt-0.5 h-4 w-4', cookieVaultHealth.colors.icon)} />
            ) : (
              <AlertCircle className={cn('mt-0.5 h-4 w-4', cookieVaultHealth.colors.icon)} />
            )}
            <div className="flex-1 space-y-1">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold">{cookieVaultHealth.title}</p>
                <button
                  type="button"
                  onClick={() => setShowGuidance(true)}
                  className="rounded-full bg-white/30 px-2 py-0.5 text-[11px] font-medium text-foreground/80 hover:bg-white/40"
                >
                  View details
                </button>
              </div>
              <p>{cookieVaultHealth.message}</p>
              {cookieVaultSummary?.missingVaultEntries ? (
                <p className="font-medium">
                  Missing vault backups for {cookieVaultSummary.missingVaultEntries} jar(s)
                  {cookieVaultSummary.missingVaultUsers.length > 0 && (
                    <span>
                      {' '}— users: {cookieVaultSummary.missingVaultUsers.join(', ')}
                    </span>
                  )}
                </p>
              ) : null}
              {cookieVaultSummary?.expiringSoon ? (
                <p>
                  {cookieVaultSummary.expiringSoon} credential set(s) expire soon. Rotate before the next
                  automation run to avoid downtime.
                </p>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {showGuidance && (
        <div className="absolute inset-0 z-40 flex">
          <button
            type="button"
            className="flex-1 bg-slate-900/30 backdrop-blur-sm"
            aria-label="Close guidance overlay"
            onClick={() => setShowGuidance(false)}
          />
          <aside
            className="relative flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white/95 p-0 shadow-2xl dark:border-slate-800 dark:bg-slate-900/95"
            data-testid="link-chat-guidance-drawer"
          >
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
              <div>
                <h3 className="text-sm font-semibold text-foreground">Link usage guidance</h3>
                <p className="text-xs text-muted-foreground">
                  {`User tier ${userTier.replace('tier', '')} • Organization tier ${effectiveOrganizationTier.replace('tier', '')}`}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowGuidance(false)}
                className="rounded-full p-1 hover:bg-muted transition-colors"
                aria-label="Close guidance drawer"
              >
                <X className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 text-sm text-muted-foreground">
              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Recommended prompts</h4>
                <ul className="mt-2 space-y-1">
                  {combinedSafeTopicGuidance.safePractices.map((item) => (
                    <li key={`safe-${item}`} className="flex items-start gap-2">
                      <Check className="h-3.5 w-3.5 text-accent mt-0.5" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Use caution</h4>
                <ul className="mt-2 space-y-1">
                  {combinedSafeTopicGuidance.cautionTopics.map((item) => (
                    <li key={`caution-${item}`} className="flex items-start gap-2">
                      <AlertCircle className="h-3.5 w-3.5 text-amber-500 mt-0.5" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Prohibited</h4>
                <ul className="mt-2 space-y-1">
                  {combinedSafeTopicGuidance.prohibitedTopics.map((item) => (
                    <li key={`prohibited-${item}`} className="flex items-start gap-2">
                      <AlertCircle className="h-3.5 w-3.5 text-rose-500 mt-0.5" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Tier limits</h4>
                <ul className="mt-2 space-y-1">
                  <li className="flex items-center justify-between">
                    <span>Monthly contacts</span>
                    <span className="font-medium text-foreground">{tierLimitSummary.monthlyContacts}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>Data exports</span>
                    <span className="font-medium text-foreground">{tierLimitSummary.exports}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>Integrations</span>
                    <span className="font-medium text-foreground">{tierLimitSummary.integrations}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>Data retention</span>
                    <span className="font-medium text-foreground">{tierLimitSummary.dataRetention}</span>
                  </li>
                </ul>
              </section>

              {cookieVaultAccess && cookieVaultSummary && (
                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Cookie vault health</h4>
                  <div
                    className={cn(
                      'mt-2 rounded-lg border px-3 py-2 text-xs shadow-sm',
                      cookieVaultHealth?.colors.container ?? 'border-slate-200 bg-slate-50/80 text-slate-700',
                    )}
                  >
                    <p className="font-semibold text-foreground">{cookieVaultHealth?.title ?? 'Status unavailable'}</p>
                    <p>{cookieVaultHealth?.message ?? 'Unable to load cookie vault summary right now.'}</p>
                    <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground">
                      <span>
                        Active items: <strong>{cookieVaultSummary.activeItems}</strong> / {cookieVaultSummary.totalItems}
                      </span>
                      <span>
                        Expiring soon: <strong>{cookieVaultSummary.expiringSoon}</strong> • Expired:{' '}
                        <strong>{cookieVaultSummary.expiredItems}</strong>
                      </span>
                      <span>
                        Missing backups: <strong>{cookieVaultSummary.missingVaultEntries}</strong>
                      </span>
                    </div>
                  </div>
                  {cookieVaultSummary.userSummaries.length > 0 && (
                    <ul className="mt-3 space-y-2 text-xs">
                      {cookieVaultSummary.userSummaries.slice(0, 5).map((entry) => (
                        <li key={`vault-user-${entry.userId}`} className="rounded-md border border-slate-200 px-3 py-2">
                          <p className="font-medium text-foreground">User {entry.userId}</p>
                          <p className="text-muted-foreground">
                            Active {entry.active} • Expired {entry.expired}
                            {entry.rotationRecommended && ' • Rotation overdue'}
                          </p>
                          {entry.latestLabel && (
                            <p className="text-muted-foreground">
                              Latest label: <span className="font-medium">{entry.latestLabel}</span>
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}

              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">Disclosures</h4>
                <ul className="mt-2 space-y-2">
                  {LINKCHAT_DISCLOSURES.map((item) => (
                    <li key={`disclosure-${item}`} className="flex items-start gap-2">
                      <Info className="h-3.5 w-3.5 text-primary mt-0.5" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
            <div className="border-t border-slate-200 px-5 py-3 dark:border-slate-800">
              <button
                type="button"
                onClick={handleAcknowledgeGuidance}
                className="w-full rounded-lg bg-gradient-to-r from-[#111111] to-[#FFD400] px-4 py-2 text-sm font-semibold text-white shadow hover:from-[#111111] hover:to-[#FFE766] disabled:opacity-60"
                data-testid="link-chat-guidance-acknowledge"
                disabled={acknowledgingGuidance}
              >
                {acknowledgingGuidance ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving
                  </span>
                ) : (
                  'Acknowledge guidance'
                )}
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {connectionError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-4 h-4 text-red-600" />
              <div className="flex-1 text-sm text-red-900">
                <p>{connectionError}</p>
                <p className="mt-1 text-xs text-red-700">
                  We will keep retrying automatically. You can press retry to reconnect now or refresh the page if the
                  issue persists.
                </p>
              </div>
              <button
                onClick={connectWebSocket}
                className="text-sm font-medium text-red-600 hover:text-red-800"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {showFallbackBanner && supportsHttpFallback && (
          <div
            className="rounded-lg border border-blue-200 bg-gradient-to-r from-blue-50/80 to-emerald-50/80 p-3"
            data-testid="link-chat-fallback-banner"
          >
            <div className="flex items-start gap-3">
              <Info className="w-4 h-4 text-blue-600" />
              <div className="flex-1 text-xs text-blue-700">
                <p className="font-semibold text-blue-900">Resilient mode active</p>
                <p>
                  We switched to the HTTP fallback channel while the live connection stabilizes. Your prompts continue to
                  send, and responses will sync automatically when the socket reconnects.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowFallbackBanner(false)}
                className="p-1 text-blue-600 hover:text-blue-800"
                aria-label="Dismiss fallback notice"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div key={message.id}>
            {renderMessage(message)}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Prompt Suggestions */}
      {!inputMessage && isConnected && promptSuggestions.length > 0 && (
        <div className="border-t border-white/20 p-4 bg-gradient-to-r from-slate-50/80 to-emerald-50/80 backdrop-blur-sm">
          <h4 className="text-sm font-medium text-gray-700 mb-2">Try asking Link:</h4>
          <div className="flex flex-wrap gap-2">
            {promptSuggestions.map((suggestion, index) => (
              <button
                key={index}
                onClick={() => applyPromptSuggestion(suggestion)}
                className="text-xs px-3 py-1 rounded-full bg-white/80 hover:bg-white border border-gray-200 text-gray-700 hover:text-gray-900 transition-colors duration-200"
              >
                {suggestion}
              </button>
            ))}
          </div>
          <button
            onClick={generatePromptSuggestions}
            className="text-xs text-primary hover:text-primary/80 mt-2 font-medium"
          >
            Show different suggestions
          </button>
        </div>
      )}

      {/* Safety guidance */}
      <div className="border-t border-white/20 p-4 bg-gradient-to-r from-slate-100/80 to-white backdrop-blur-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-gray-800 mb-1">Stay within guardrails</h4>
            <p className="text-xs text-gray-600 mb-2">
              Link can assist with research, introductions, and compliant outreach.
              It must decline unsafe, bulk scraping, or sensitive data requests.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowGuidance(true)}
            className="inline-flex items-center gap-1 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-primary shadow-sm hover:bg-white transition-colors"
            data-testid="link-chat-guidance-inline"
          >
            <BookOpen className="w-3.5 h-3.5" />
            Full guidance
            {!hasAcknowledgedGuidance && (
              <span className="ml-1 inline-flex h-1.5 w-1.5 rounded-full bg-rose-500" />
            )}
          </button>
        </div>
        <div className="grid gap-2 text-xs text-gray-600 md:grid-cols-3">
          <div>
            <p className="font-medium text-gray-800">Recommended</p>
            <ul className="mt-1 space-y-1">
              {combinedSafeTopicGuidance.safePractices.slice(0, 3).map((item) => (
                <li key={item} className="flex items-start gap-1">
                  <Check className="mt-0.5 h-3 w-3 text-emerald-500" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-medium text-gray-800">Use caution</p>
            <ul className="mt-1 space-y-1">
              {combinedSafeTopicGuidance.cautionTopics.slice(0, 3).map((item) => (
                <li key={item} className="flex items-start gap-1">
                  <AlertCircle className="mt-0.5 h-3 w-3 text-amber-500" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-medium text-gray-800">Prohibited</p>
            <ul className="mt-1 space-y-1">
              {combinedSafeTopicGuidance.prohibitedTopics.slice(0, 3).map((item) => (
                <li key={item} className="flex items-start gap-1">
                  <AlertCircle className="mt-0.5 h-3 w-3 text-rose-500" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Data Sharing Disclosure */}
      {showDataDisclosure && (
        <div className="border-t border-white/20 p-4 bg-gradient-to-r from-blue-50/80 to-cyan-50/80 backdrop-blur-sm">
          <div className="flex items-start space-x-3">
            <AlertCircle className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-blue-900 mb-2">Data Sharing & Privacy Notice</h4>
              <p className="text-sm text-blue-800 mb-3">
                Your request involves data export or external sharing. Please review your {userTier.replace('tier', 'Tier ')} limits:
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs text-blue-700 mb-3">
                <div>Monthly contacts: <span className="font-medium">{tierLimitSummary.monthlyContacts}</span></div>
                <div>Data exports: <span className="font-medium">{tierLimitSummary.exports}</span></div>
                <div>Integrations: <span className="font-medium">{tierLimitSummary.integrations}</span></div>
                <div>Data retention: <span className="font-medium">{tierLimitSummary.dataRetention}</span></div>
              </div>
              {cookieVaultHealth?.showWarning && cookieVaultSummary && (
                <p className="text-xs text-blue-700 mb-3">
                  Cookie vault warning: {cookieVaultHealth.message}
                </p>
              )}
              <p className="text-xs text-blue-600">
                All data sharing follows GDPR and CCPA compliance standards.
                <button
                  className="underline ml-1 hover:text-blue-800"
                  onClick={() => setShowDataDisclosure(false)}
                >
                  Acknowledge & Continue
                </button>
              </p>
            </div>
            <button
              onClick={() => setShowDataDisclosure(false)}
              className="text-blue-600 hover:text-blue-800 p-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Validation Warnings */}
      {(inputValidationErrors.length > 0 || safetyWarnings.length > 0) && (
        <div className="border-t border-white/20 p-4 bg-gradient-to-r from-red-50/80 to-yellow-50/80 backdrop-blur-sm">
          {inputValidationErrors.map((error, index) => (
            <div key={`error-${index}`} className="flex items-start space-x-2 text-red-700 text-sm mb-2">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          ))}
          {safetyWarnings.map((warning, index) => (
            <div key={`warning-${index}`} className="flex items-start space-x-2 text-yellow-700 text-sm mb-2">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="border-t border-white/20 p-4 bg-gradient-to-r from-slate-50/80 to-emerald-50/80 backdrop-blur-sm">
        <div className="relative">
          <div className="flex items-end space-x-2">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={inputMessage}
                onChange={handleInputChange}
                onKeyPress={handleKeyPress}
                placeholder={inputPlaceholder}
                disabled={inputDisabled}
                className={cn(
                  "w-full resize-none rounded-xl border-2 border-gray-200 px-4 py-3 text-sm transition-all duration-200",
                  "focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:shadow-lg",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                  "placeholder:text-gray-400 placeholder:transition-all placeholder:duration-300",
                  "bg-white/90 backdrop-blur-sm shadow-sm",
                  "min-h-[44px] max-h-[120px] overflow-y-auto scrollbar-thin scrollbar-thumb-gray-300"
                )}
                style={{ height: textareaHeight }}
                rows={1}
              />
              {inputMessage && (
                <button
                  onClick={clearInput}
                  className="absolute right-12 top-1/2 transform -translate-y-1/2 p-1 rounded-full hover:bg-gray-200 transition-colors duration-200"
                >
                  <X className="w-4 h-4 text-gray-400" />
                </button>
              )}
            </div>
            <button
              onClick={sendMessage}
              disabled={sendDisabled}
              className={cn(
                "p-3 rounded-xl transition-all duration-200 shadow-lg",
                "flex items-center justify-center",
                canSend
                  ? "bg-gradient-to-r from-[#111111] to-[#FFD400] text-white hover:from-[#111111] hover:to-[#FFE766] hover:shadow-xl scale-100 hover:scale-105"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed opacity-50"
              )}
              data-testid="link-chat-send"
            >
              {isSending ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <ArrowUp className="w-5 h-5" />
              )}
            </button>
          </div>

          {/* Typing indicator */}
          {(isSending || isTyping) && (
            <div className="flex items-center space-x-2 mt-2 text-sm text-gray-500">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span>{isSending ? 'Sending...' : 'Link is thinking...'}</span>
            </div>
          )}
        </div>
      </div>
    </GlassCard>
  );
};

export default LinkChat;
