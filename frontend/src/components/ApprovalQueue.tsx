// Human-in-the-Loop Approval Queue Component
// September 2025 AI Integration with Real-time Updates

import React, { useState, useEffect, useCallback } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import GlassCard from './ui/GlassCard';
import {
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Bot,
  User as UserIcon,
  ArrowRight,
  FileText,
  Mail,
  Database,
  Settings,
  X,
  Loader2,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import type { ApprovalRequest, User } from '../types';
import { apiService } from '../services/api';
import webSocketService from '../services/websocket';
import { useToastActions } from './ui/ToastContainer';
import { ApprovalQueueSkeleton } from './ui/LoadingSkeleton';
import { cn } from '../lib/utils';

type ApprovalSocketPayload = {
  tenant_id?: number | string;
  action?: string;
  context?: Record<string, unknown>;
};

type ApprovalSocketMessage = {
  approval?: ApprovalSocketPayload;
  data?: ApprovalSocketPayload;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const extractSocketPayload = (message: unknown): ApprovalSocketPayload | null => {
  if (!isRecord(message)) {
    return null;
  }

  const envelope = message as ApprovalSocketMessage;
  const candidate = envelope.approval ?? envelope.data ?? message;
  if (!isRecord(candidate)) {
    return null;
  }

  const payload: ApprovalSocketPayload = {};
  const tenantCandidate = candidate.tenant_id;
  if (typeof tenantCandidate === 'string' || typeof tenantCandidate === 'number') {
    payload.tenant_id = tenantCandidate;
  }
  if (typeof candidate.action === 'string') {
    payload.action = candidate.action;
  }
  if (isRecord(candidate.context)) {
    payload.context = candidate.context;
  }
  return payload;
};

interface ApprovalQueueProps {
  organizationId: number | string;
  currentUser?: User | null;
}

const ApprovalQueue: React.FC<ApprovalQueueProps> = ({ organizationId, currentUser }) => {
  const { success, error } = useToastActions();
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [decisionNotes, setDecisionNotes] = useState('');
  const [filter, setFilter] = useState<string>('pending');
  const [loading, setLoading] = useState(true);

  const loadApprovals = useCallback(async () => {
    if (!organizationId) {
      setApprovals([]);
      return;
    }

    try {
      setLoading(true);
      const statusFilter = filter === 'all' ? undefined : filter;
      const response = await apiService.getApprovalRequests({
        tenantId: organizationId,
        ...(statusFilter && { status: statusFilter }),
        page: 1,
        limit: 20,
      });
      setApprovals(response.data ?? []);
    } catch (err) {
      console.error('Failed to load approvals:', err);
      error('Failed to load approval requests');
    } finally {
      setLoading(false);
    }
  }, [organizationId, filter, error]);

  const formatActionLabel = (action?: string): string => {
    if (!action) {
      return 'Approval Request';
    }

    return action
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

const resolveRequester = (context?: Record<string, unknown>): string => {
  if (!context) {
    return 'Unknown';
  }

    const candidate =
      context.requested_by ??
      context.initiated_by ??
      context.requester ??
      context.user_email ??
      context.user ??
      context.email;

  return candidate ? String(candidate) : 'Unknown';
};

const resolveDescription = (description?: string | null): string => {
  if (typeof description === 'string' && description.trim().length > 0) {
    return description;
  }
  return 'No additional description provided.';
};

  const handleNewApproval = useCallback((message: unknown) => {
    const payload = extractSocketPayload(message);
    if (!payload) {
      return;
    }

    if (payload.tenant_id && String(payload.tenant_id) !== String(organizationId)) {
      return;
    }

    if (filter === 'pending' || filter === 'all') {
      void loadApprovals();
    }

    success(`New approval request: ${formatActionLabel(payload.action)}`);
  }, [filter, loadApprovals, organizationId, success]);

  const handleApprovalUpdate = useCallback((message: unknown) => {
    const payload = extractSocketPayload(message);
    if (!payload) {
      return;
    }

    if (payload.tenant_id && String(payload.tenant_id) !== String(organizationId)) {
      return;
    }

    void loadApprovals();
  }, [loadApprovals, organizationId]);

  const setupWebSocketListeners = useCallback(() => {
    webSocketService.on('approval_request', handleNewApproval);
    webSocketService.on('approval_decision', handleApprovalUpdate);
    webSocketService.joinApprovalRoom(organizationId);
  }, [handleNewApproval, handleApprovalUpdate, organizationId]);

  useEffect(() => {
    void loadApprovals();
    setupWebSocketListeners();

    return () => {
      webSocketService.off('approval_request', handleNewApproval);
      webSocketService.off('approval_decision', handleApprovalUpdate);
      webSocketService.leaveApprovalRoom(organizationId);
    };
  }, [organizationId, filter, loadApprovals, setupWebSocketListeners, handleNewApproval, handleApprovalUpdate]);

  const handleApprovalClick = (approval: ApprovalRequest) => {
    setSelectedApproval(approval);
    setDecisionNotes('');
    setIsModalOpen(true);
  };

  const handleDecision = async (decision: 'approve' | 'reject') => {
    if (!selectedApproval) return;

    const approverId = currentUser?.id;
    if (!approverId) {
      error('Unable to determine approver');
      return;
    }

    try {
      setIsProcessing(true);
      await apiService.makeApprovalDecision(
        selectedApproval.approval_id,
        {
          decision,
          notes: decisionNotes,
        },
        approverId
      );

      success(`Request ${decision}d successfully`);
      setIsModalOpen(false);
      await loadApprovals();
    } catch (err) {
      console.error('Failed to process approval:', err);
      error(`Failed to ${decision} request`);
    } finally {
      setIsProcessing(false);
    }
  };

  const selectedPriority = selectedApproval?.priority ?? 'normal';
  const selectedDescription = resolveDescription(selectedApproval?.description);

  const getRequestTypeIcon = (action: string) => {
    const normalized = action?.toLowerCase() ?? '';

    if (normalized.includes('tool') || normalized.includes('ai')) {
      return <Bot className="w-4 h-4" />;
    }

    if (normalized.includes('email')) {
      return <Mail className="w-4 h-4" />;
    }

    if (normalized.includes('data') || normalized.includes('export')) {
      return <Database className="w-4 h-4" />;
    }

    if (normalized.includes('system') || normalized.includes('config')) {
      return <Settings className="w-4 h-4" />;
    }

    return <FileText className="w-4 h-4" />;
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'critical':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'high':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'medium':
      case 'normal':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'low':
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  const getRiskColor = (riskScore?: number) => {
    if (riskScore === undefined || riskScore === null) {
      return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }

    const normalized = riskScore > 1 ? riskScore / 100 : riskScore;

    if (normalized >= 0.8) return 'bg-red-500/20 text-red-400 border-red-500/30';
    if (normalized >= 0.5) return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
    return 'bg-green-500/20 text-green-400 border-green-500/30';
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      case 'approved':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'rejected':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'timeout':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'escalated':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
  };

  if (loading) {
    return <ApprovalQueueSkeleton />;
  }

  return (
    <div className="space-y-4">
      {/* Filter Tabs */}
      <div className="flex flex-wrap gap-2">
        {['pending', 'approved', 'rejected', 'all'].map((filterOption) => (
          <button
            key={filterOption}
            onClick={() => setFilter(filterOption)}
            className={cn(
              'px-3 sm:px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 flex-shrink-0',
              filter === filterOption
                ? 'bg-primary text-primary-foreground shadow-lg'
                : 'bg-muted/30 text-muted-foreground hover:bg-muted/50 border border-border/20'
            )}
          >
            {filterOption.charAt(0).toUpperCase() + filterOption.slice(1)}
          </button>
        ))}
      </div>

      {/* Approval Cards */}
      <div className="space-y-3">
        {approvals.length === 0 ? (
          <GlassCard>
            <div className="text-center py-8">
              <CheckCircle className="w-12 h-12 mx-auto text-green-400 mb-4" />
              <p className="text-lg font-medium text-foreground">
                No {filter} approval requests
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                All caught up! 🎉
              </p>
            </div>
          </GlassCard>
        ) : (
          approvals.map((approval) => {
            const riskPercentage = (() => {
              if (approval.risk_score === undefined || approval.risk_score === null) {
                return undefined;
              }
              const normalized = approval.risk_score > 1 ? approval.risk_score : approval.risk_score * 100;
              return Math.round(normalized);
            })();

            return (
            <GlassCard
              key={approval.approval_id}
              onClick={() => handleApprovalClick(approval)}
              className="cursor-pointer hover:bg-muted/20 transition-all duration-200"
            >
              <div className="p-4">
                <div className="flex justify-between items-start w-full mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-muted/30 flex items-center justify-center">
                      {getRequestTypeIcon(approval.action)}
                    </div>
                    <div>
                      <h3 className="font-semibold text-foreground">
                        {formatActionLabel(approval.action)}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {resolveDescription(approval.description)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={cn('px-2 py-1 rounded-full text-xs border', getPriorityColor(approval.priority))}>
                      {approval.priority}
                    </span>
                    <span className={cn('px-2 py-1 rounded-full text-xs border', getStatusColor(approval.status))}>
                      {approval.status}
                    </span>
                  </div>
                </div>
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDistanceToNow(new Date(approval.requested_at), {
                        addSuffix: true,
                      })}
                    </span>
                    {riskPercentage !== undefined && (
                      <span className="flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        <span className={cn('px-2 py-1 rounded-full text-xs border', getRiskColor(approval.risk_score))}>
                          Risk: {riskPercentage}%
                        </span>
                      </span>
                    )}
                    <span className="flex items-center gap-1">
                      <UserIcon className="w-3 h-3" />
                      Requester: {resolveRequester(approval.context)}
                    </span>
                  </div>
                  <ArrowRight className="w-4 h-4 text-muted-foreground hidden sm:block" />
                </div>
              </div>
            </GlassCard>
            );
          })
        )}
      </div>

      {/* Approval Decision Modal */}
      <Dialog.Root open={isModalOpen} onOpenChange={setIsModalOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50" />
          <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl max-h-[90vh] overflow-y-auto z-50">
            <GlassCard className="m-4">
              <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    {selectedApproval && getRequestTypeIcon(selectedApproval.action)}
                    <span className="font-semibold text-lg">{formatActionLabel(selectedApproval?.action)}</span>
                  </div>
                  <Dialog.Close asChild>
                    <button className="p-2 rounded-lg hover:bg-muted/20 transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  </Dialog.Close>
                </div>

                <div className="flex items-center gap-2 mb-6">
                  <span className={cn('px-2 py-1 rounded-full text-xs border', getPriorityColor(selectedPriority))}>
                    {selectedApproval?.priority ?? 'normal'}
                  </span>
                  {selectedApproval?.risk_score !== undefined && selectedApproval?.risk_score !== null && (
                    <span className={cn('px-2 py-1 rounded-full text-xs border', getRiskColor(selectedApproval.risk_score))}>
                      {(() => {
                        const normalized = selectedApproval.risk_score > 1
                          ? selectedApproval.risk_score
                          : selectedApproval.risk_score * 100;
                        return `Risk: ${Math.round(normalized)}%`;
                      })()}
                    </span>
                  )}
                </div>

                <div className="space-y-6">
                  <div>
                    <h4 className="font-medium mb-2">Description</h4>
                    <p className="text-muted-foreground">{selectedDescription}</p>
                  </div>

                  <hr className="border-border/20" />

                  <div>
                    <h4 className="font-medium mb-2">Request Details</h4>
                    <div className="bg-muted/20 p-4 rounded-lg">
                      <pre className="text-sm whitespace-pre-wrap overflow-auto">
                        {JSON.stringify(selectedApproval?.context ?? {}, null, 2)}
                      </pre>
                    </div>
                  </div>

                  <hr className="border-border/20" />

                  <div>
                    <h4 className="font-medium mb-2">Timeline</h4>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span>Requested:</span>
                        <span>
                          {selectedApproval &&
                            formatDistanceToNow(new Date(selectedApproval.requested_at), {
                              addSuffix: true,
                            })}
                        </span>
                      </div>
                      {selectedApproval?.timeout_at && (
                        <div className="flex justify-between">
                          <span>Expires:</span>
                          <span className="text-orange-400">
                            {formatDistanceToNow(new Date(selectedApproval.timeout_at), {
                              addSuffix: true,
                            })}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {selectedApproval?.status === 'pending' && (
                    <>
                      <hr className="border-border/20" />
                      <div>
                        <h4 className="font-medium mb-2">Decision Notes (Optional)</h4>
                        <textarea
                          placeholder="Add notes about your decision..."
                          value={decisionNotes}
                          onChange={(e) => setDecisionNotes(e.target.value)}
                          rows={4}
                          className="w-full p-3 bg-muted/30 border border-border/20 rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30 transition-colors resize-none"
                        />
                      </div>
                    </>
                  )}
                </div>

                <div className="flex justify-end gap-3 mt-6">
                  <Dialog.Close asChild>
                    <button className="px-4 py-2 rounded-lg border border-border/20 text-muted-foreground hover:bg-muted/20 transition-colors">
                      Close
                    </button>
                  </Dialog.Close>
                  {selectedApproval?.status === 'pending' && (
                    <>
                      <button
                        onClick={() => handleDecision('reject')}
                        disabled={isProcessing}
                        className="px-4 py-2 rounded-lg bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-colors disabled:opacity-50 flex items-center gap-2"
                      >
                        {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
                        Reject
                      </button>
                      <button
                        onClick={() => handleDecision('approve')}
                        disabled={isProcessing}
                        className="px-4 py-2 rounded-lg bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30 transition-colors disabled:opacity-50 flex items-center gap-2"
                      >
                        {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                        Approve
                      </button>
                    </>
                  )}
                </div>
              </div>
            </GlassCard>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
};

export default ApprovalQueue;
