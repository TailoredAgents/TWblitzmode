// Conversation Summary Panel - AI-powered chat summarization and insights
// October 2025 - Intelligent conversation tracking and analysis

'use client';

import React, { useState, useRef } from 'react';
import { FileText, TrendingUp, Users, Target, Star, RefreshCw, Minimize2, ChevronDown, Brain } from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { cn } from '../lib/utils';

interface ConversationInsight {
  type: 'key_topic' | 'action_item' | 'decision' | 'question' | 'metric' | 'contact_mentioned';
  content: string;
  confidence: number;
  timestamp: string;
  context?: string;
  metadata?: Record<string, unknown>;
}

interface ConversationMetrics {
  total_messages: number;
  user_messages: number;
  agent_responses: number;
  avg_response_time_ms: number;
  conversation_duration_ms: number;
  workflow_executions: number;
  successful_actions: number;
  failed_actions: number;
  contacts_discovered: number;
  emails_generated: number;
}

interface ConversationSummary {
  session_id: string;
  summary_text: string;
  key_insights: ConversationInsight[];
  action_items: string[];
  topics_covered: string[];
  outcome_rating: number; // 1-5 scale
  metrics: ConversationMetrics;
  participants: string[];
  start_time: string;
  last_updated: string;
  tags: string[];
  sentiment_score?: number; // -1 to 1
  productivity_score?: number; // 0-100
}

interface ConversationSummaryPanelProps {
  summaries: ConversationSummary[];
  currentSessionSummary?: ConversationSummary;
  isMinimized?: boolean;
  onToggleMinimize?: () => void;
  onRefreshSummary?: (sessionId: string) => void;
  onClearHistory?: () => void;
  className?: string;
  maxHeight?: string;
}

const ConversationSummaryPanel: React.FC<ConversationSummaryPanelProps> = ({
  summaries,
  currentSessionSummary,
  isMinimized = false,
  onToggleMinimize,
  onRefreshSummary,
  onClearHistory,
  className,
  maxHeight = 'max-h-96'
}) => {
  const [expandedSummary, setExpandedSummary] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<'all' | 'current' | 'recent'>('current');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const autoScrollRef = useRef<HTMLDivElement>(null);

  const categories: Array<{ id: 'current' | 'recent' | 'all'; label: string; count: number }> = [
    { id: 'current', label: 'Current Session', count: currentSessionSummary ? 1 : 0 },
    { id: 'recent', label: 'Recent', count: summaries.filter(s =>
      new Date(s.last_updated).getTime() > Date.now() - 24 * 60 * 60 * 1000
    ).length },
    { id: 'all', label: 'All Sessions', count: summaries.length },
  ];

  const getInsightIcon = (type: ConversationInsight['type']) => {
    switch (type) {
      case 'key_topic': return <FileText className="w-3 h-3" />;
      case 'action_item': return <Target className="w-3 h-3" />;
      case 'decision': return <Star className="w-3 h-3" />;
      case 'question': return <Brain className="w-3 h-3" />;
      case 'metric': return <TrendingUp className="w-3 h-3" />;
      case 'contact_mentioned': return <Users className="w-3 h-3" />;
      default: return <FileText className="w-3 h-3" />;
    }
  };

  const getInsightColor = (type: ConversationInsight['type']) => {
    switch (type) {
      case 'key_topic': return 'text-blue-600 bg-blue-50 border-blue-200';
      case 'action_item': return 'text-red-600 bg-red-50 border-red-200';
      case 'decision': return 'text-green-600 bg-green-50 border-green-200';
      case 'question': return 'text-blue-600 bg-blue-50 border-blue-200';
      case 'metric': return 'text-orange-600 bg-orange-50 border-orange-200';
      case 'contact_mentioned': return 'text-indigo-600 bg-indigo-50 border-indigo-200';
      default: return 'text-gray-600 bg-gray-50 border-gray-200';
    }
  };

  const formatDuration = (ms: number) => {
    const minutes = Math.floor(ms / 60000);
    const hours = Math.floor(minutes / 60);
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    return `${minutes}m`;
  };

  const getProductivityRating = (score?: number) => {
    if (!score) return { label: 'N/A', color: 'text-gray-500' };
    if (score >= 80) return { label: 'Excellent', color: 'text-green-600' };
    if (score >= 60) return { label: 'Good', color: 'text-blue-600' };
    if (score >= 40) return { label: 'Fair', color: 'text-yellow-600' };
    return { label: 'Poor', color: 'text-red-600' };
  };

  const getSentimentEmoji = (score?: number) => {
    if (!score) return '😐';
    if (score > 0.5) return '😊';
    if (score > 0) return '🙂';
    if (score > -0.5) return '😐';
    return '😔';
  };

  const handleRefresh = async (sessionId: string) => {
    if (!onRefreshSummary) return;
    setIsRefreshing(true);
    try {
      await onRefreshSummary(sessionId);
    } finally {
      setIsRefreshing(false);
    }
  };

  const filteredSummaries = () => {
    const allSummaries = currentSessionSummary ? [currentSessionSummary, ...summaries] : summaries;

    switch (selectedCategory) {
      case 'current':
        return currentSessionSummary ? [currentSessionSummary] : [];
      case 'recent':
        return allSummaries.filter(s =>
          new Date(s.last_updated).getTime() > Date.now() - 24 * 60 * 60 * 1000
        );
      default:
        return allSummaries;
    }
  };

  const renderInsight = (insight: ConversationInsight) => (
    <div key={`${insight.type}-${insight.timestamp}`} className="flex items-start space-x-2 p-2 rounded border">
      <div className={cn("p-1 rounded", getInsightColor(insight.type))}>
        {getInsightIcon(insight.type)}
      </div>
      <div className="flex-1 text-sm">
        <p className="text-gray-900">{insight.content}</p>
        {insight.context && (
          <p className="text-gray-500 text-xs mt-1">{insight.context}</p>
        )}
        <div className="flex items-center space-x-2 mt-1">
          <span className="text-xs text-gray-400">
            {new Date(insight.timestamp).toLocaleTimeString()}
          </span>
          <span className={cn(
            "text-xs px-1 rounded",
            insight.confidence > 0.8 ? "bg-green-100 text-green-700" :
            insight.confidence > 0.6 ? "bg-yellow-100 text-yellow-700" :
            "bg-red-100 text-red-700"
          )}>
            {Math.round(insight.confidence * 100)}%
          </span>
        </div>
      </div>
    </div>
  );

  const renderSummary = (summary: ConversationSummary) => {
    const isExpanded = expandedSummary === summary.session_id;
    const isCurrent = summary.session_id === currentSessionSummary?.session_id;
    const productivity = getProductivityRating(summary.productivity_score);

    return (
      <div key={summary.session_id} className="space-y-3">
        <div
          className={cn(
            "p-4 rounded-xl border-2 cursor-pointer transition-all duration-200 hover:shadow-md",
            isCurrent ? "border-blue-300 bg-blue-50/60" : "border-gray-200 bg-white/60",
            isExpanded && "ring-2 ring-blue-300 shadow-lg"
          )}
          onClick={() => setExpandedSummary(isExpanded ? null : summary.session_id)}
        >
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <h4 className="font-medium text-gray-900">
                {isCurrent ? 'Current Session' : `Session ${summary.session_id.slice(-8)}`}
              </h4>
              {isCurrent && (
                <span className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded-full">Live</span>
              )}
              <span className="text-xs text-gray-500">
                {formatDuration(summary.metrics.conversation_duration_ms)}
              </span>
            </div>
            <div className="flex items-center space-x-2">
              <span className={cn("text-sm font-medium", productivity.color)}>
                {productivity.label}
              </span>
              <span className="text-lg">{getSentimentEmoji(summary.sentiment_score)}</span>
              <ChevronDown className={cn("w-4 h-4 transition-transform", isExpanded && "rotate-180")} />
            </div>
          </div>

          <p className="text-sm text-gray-700 mb-3 line-clamp-2">{summary.summary_text}</p>

          <div className="flex items-center justify-between text-xs text-gray-500">
            <div className="flex items-center space-x-4">
              <span>{summary.metrics.total_messages} messages</span>
              <span>{summary.metrics.workflow_executions} workflows</span>
              <span>{summary.metrics.contacts_discovered} contacts found</span>
            </div>
            <div className="flex items-center space-x-2">
              {summary.outcome_rating > 0 && (
                <div className="flex">
                  {[...Array(5)].map((_, i) => (
                    <Star
                      key={i}
                      className={cn(
                        "w-3 h-3",
                        i < summary.outcome_rating ? "text-yellow-500 fill-current" : "text-gray-300"
                      )}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {isExpanded && (
          <div className="space-y-4 pl-4 border-l-2 border-blue-200">
            {/* Key Insights */}
            {summary.key_insights.length > 0 && (
              <div>
                <h5 className="font-medium text-gray-900 mb-2 flex items-center space-x-2">
                  <Brain className="w-4 h-4" />
                  <span>Key Insights</span>
                </h5>
                <div className="space-y-2">
                  {summary.key_insights.slice(0, 5).map(insight => renderInsight(insight))}
                </div>
              </div>
            )}

            {/* Action Items */}
            {summary.action_items.length > 0 && (
              <div>
                <h5 className="font-medium text-gray-900 mb-2 flex items-center space-x-2">
                  <Target className="w-4 h-4" />
                  <span>Action Items</span>
                </h5>
                <ul className="space-y-1">
                  {summary.action_items.map((item, index) => (
                    <li key={index} className="text-sm text-gray-700 flex items-start space-x-2">
                      <span className="w-1.5 h-1.5 bg-blue-500 rounded-full mt-2 flex-shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Topics Covered */}
            {summary.topics_covered.length > 0 && (
              <div>
                <h5 className="font-medium text-gray-900 mb-2">Topics Covered</h5>
                <div className="flex flex-wrap gap-1">
                  {summary.topics_covered.map((topic, index) => (
                    <span key={index} className="text-xs px-2 py-1 bg-gray-100 text-gray-700 rounded-full">
                      {topic}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Detailed Metrics */}
            <div>
              <h5 className="font-medium text-gray-900 mb-2 flex items-center space-x-2">
                <TrendingUp className="w-4 h-4" />
                <span>Performance Metrics</span>
              </h5>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Response Time:</span>
                    <span className="font-medium">{Math.round(summary.metrics.avg_response_time_ms / 1000)}s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Success Rate:</span>
                    <span className="font-medium">
                      {Math.round((summary.metrics.successful_actions /
                        (summary.metrics.successful_actions + summary.metrics.failed_actions)) * 100) || 0}%
                    </span>
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Emails Generated:</span>
                    <span className="font-medium">{summary.metrics.emails_generated}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Contacts Found:</span>
                    <span className="font-medium">{summary.metrics.contacts_discovered}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Refresh button for current session */}
            {isCurrent && onRefreshSummary && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleRefresh(summary.session_id);
                }}
                disabled={isRefreshing}
                className="flex items-center space-x-2 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
              >
                <RefreshCw className={cn("w-4 h-4", isRefreshing && "animate-spin")} />
                <span>Refresh Summary</span>
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  // Minimized floating button
  if (isMinimized) {
    const hasCurrentSession = !!currentSessionSummary;
    const recentCount = summaries.filter(s =>
      new Date(s.last_updated).getTime() > Date.now() - 24 * 60 * 60 * 1000
    ).length;

    return (
      <div className="fixed bottom-36 right-4 z-40">
        <button
          onClick={onToggleMinimize}
          className="w-14 h-14 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] text-white shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center relative"
        >
          <FileText className="w-6 h-6" />
          {(hasCurrentSession || recentCount > 0) && (
            <div className="absolute -top-2 -right-2 w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center text-xs font-bold">
              {hasCurrentSession ? '!' : recentCount}
            </div>
          )}
        </button>
      </div>
    );
  }

  return (
    <GlassCard className={cn("flex flex-col", maxHeight, className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/20 bg-gradient-to-r from-slate-50/80 to-emerald-50/80 backdrop-blur-sm">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] flex items-center justify-center shadow-lg">
            <FileText className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">Conversation Summary</h3>
            <p className="text-sm text-gray-600">
              AI-powered insights and analytics
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          {onClearHistory && summaries.length > 0 && (
            <button
              onClick={onClearHistory}
              className="text-gray-400 hover:text-gray-600 text-sm"
            >
              Clear History
            </button>
          )}
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

      {/* Category Tabs */}
      <div className="flex border-b border-white/20 bg-white/20">
        {categories.map((category) => (
          <button
            key={category.id}
            onClick={() => setSelectedCategory(category.id)}
            className={cn(
              "flex-1 px-4 py-3 text-sm font-medium transition-colors",
              selectedCategory === category.id
                ? "text-blue-600 border-b-2 border-blue-600 bg-blue-50/60"
                : "text-gray-500 hover:text-gray-700 hover:bg-white/20"
            )}
          >
            {category.label}
            {category.count > 0 && (
              <span className="ml-2 px-2 py-1 text-xs bg-gray-200 text-gray-600 rounded-full">
                {category.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Summaries List */}
      <div ref={autoScrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {filteredSummaries().length === 0 ? (
          <div className="text-center py-8">
            <FileText className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500">No conversation summaries available</p>
            <p className="text-sm text-gray-400">
              {selectedCategory === 'current'
                ? "Start chatting with Link to generate insights"
                : "Summaries from your conversations will appear here"
              }
            </p>
          </div>
        ) : (
          filteredSummaries().map(summary => renderSummary(summary))
        )}
      </div>
    </GlassCard>
  );
};

export default ConversationSummaryPanel;
