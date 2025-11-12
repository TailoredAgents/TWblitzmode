// Approval Center - Communication Hub Component
// September 2025 AI Integration

import React, { useState } from 'react';
import { CheckCircle, XCircle, Clock, AlertTriangle, Eye, MessageSquare } from 'lucide-react';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';
import type { ApprovalRequest } from '../../types';

interface ApprovalCenterProps {
  approvals: ApprovalRequest[];
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', feedback?: string) => void;
}

const ApprovalCenter: React.FC<ApprovalCenterProps> = ({
  approvals,
  onApprovalDecision
}) => {
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);
  const [feedbackInput, setFeedbackInput] = useState('');
  const [processingId, setProcessingId] = useState<string | null>(null);

  const handleDecision = async (approval: ApprovalRequest, decision: 'approved' | 'rejected') => {
    setProcessingId(approval.approval_id);
    try {
      await onApprovalDecision(approval.approval_id, decision, feedbackInput.trim() || undefined);
      setFeedbackInput('');
      setSelectedApproval(null);
    } finally {
      setProcessingId(null);
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const getPriorityColor = (priority: 'low' | 'medium' | 'high' | 'critical') => {
    switch (priority) {
      case 'high':
      case 'critical':
        return 'text-red-600 dark:text-red-400';
      case 'medium':
        return 'text-yellow-600 dark:text-yellow-400';
      case 'low':
      default:
        return 'text-green-600 dark:text-green-400';
    }
  };

  const getPriorityIcon = (priority: 'low' | 'medium' | 'high' | 'critical') => {
    const iconClass = "w-4 h-4";

    switch (priority) {
      case 'high':
      case 'critical':
        return <AlertTriangle className={cn(iconClass, "text-red-500")} />;
      case 'medium':
        return <Clock className={cn(iconClass, "text-yellow-500")} />;
      case 'low':
      default:
        return <CheckCircle className={cn(iconClass, "text-green-500")} />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Approval Center</h2>
          <p className="text-sm text-muted-foreground">
            {approvals.length} approval{approvals.length !== 1 ? 's' : ''} pending review
          </p>
        </div>

        {/* Priority Summary */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-red-500"></div>
            <span className="text-xs text-muted-foreground">
              {approvals.filter(a => a.priority === 'high').length} High
            </span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-yellow-500"></div>
            <span className="text-xs text-muted-foreground">
              {approvals.filter(a => a.priority === 'medium').length} Medium
            </span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-green-500"></div>
            <span className="text-xs text-muted-foreground">
              {approvals.filter(a => a.priority === 'low').length} Low
            </span>
          </div>
        </div>
      </div>

      {/* Approvals List */}
      {approvals.length === 0 ? (
        <GlassCard className="text-center py-12">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-foreground mb-2">All Caught Up!</h3>
          <p className="text-muted-foreground">No approvals pending at the moment</p>
        </GlassCard>
      ) : (
        <div className="space-y-4">
          {approvals
            .sort((a, b) => {
              // Sort by priority (critical -> high -> medium -> low) then by created date
              const priorityOrder = { critical: 4, high: 3, medium: 2, low: 1 };
              const priorityDiff = priorityOrder[b.priority] - priorityOrder[a.priority];
              if (priorityDiff !== 0) return priorityDiff;
              return new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime();
            })
            .map((approval) => (
              <GlassCard
                key={approval.approval_id}
                variant="interactive"
                className={cn(
                  'p-6 transition-all duration-200',
                  selectedApproval?.approval_id === approval.approval_id
                    ? 'ring-2 ring-primary/40 bg-primary/5'
                    : 'hover:bg-muted/10',
                  approval.priority === 'high' && 'border-l-4 border-red-500'
                )}
              >
                <div className="space-y-4">
                  {/* Header */}
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        {getPriorityIcon(approval.priority)}
                        <h3 className="font-semibold text-foreground">{approval.action}</h3>
                        <span className={cn(
                          'px-2 py-1 rounded text-xs font-medium capitalize',
                          getPriorityColor(approval.priority),
                          'bg-opacity-10'
                        )}>
                          {approval.priority} Priority
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground mb-3">
                        {approval.description}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setSelectedApproval(
                          selectedApproval?.approval_id === approval.approval_id ? null : approval
                        )}
                        className="p-2 rounded-lg hover:bg-muted/20 transition-colors"
                        title="View Details"
                      >
                        <Eye className="w-4 h-4 text-muted-foreground" />
                      </button>
                    </div>
                  </div>

                  {/* Metadata */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Requested by</span>
                      <p className="font-medium text-foreground">
                        {(() => {
                          const requester = approval.context?.requester;
                          return typeof requester === 'string' && requester.trim().length > 0
                            ? requester
                            : 'System';
                        })()}
                      </p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Type</span>
                      <p className="font-medium text-foreground capitalize">
                        {approval.action.replace('_', ' ')}
                      </p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Created</span>
                      <p className="font-medium text-foreground">
                        {formatTimestamp(approval.requested_at)}
                      </p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Status</span>
                      <div className="flex items-center gap-1">
                        <Clock className="w-3 h-3 text-yellow-500" />
                        <span className="font-medium text-foreground">Pending</span>
                      </div>
                    </div>
                  </div>

                  {/* Quick Actions */}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => handleDecision(approval, 'approved')}
                      disabled={processingId === approval.approval_id}
                      className={cn(
                        'px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2',
                        'bg-green-600 hover:bg-green-700 text-white',
                        processingId === approval.approval_id && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      <CheckCircle className="w-4 h-4" />
                      {processingId === approval.approval_id ? 'Processing...' : 'Approve'}
                    </button>

                    <button
                      onClick={() => handleDecision(approval, 'rejected')}
                      disabled={processingId === approval.approval_id}
                      className={cn(
                        'px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2',
                        'bg-red-600 hover:bg-red-700 text-white',
                        processingId === approval.approval_id && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      <XCircle className="w-4 h-4" />
                      {processingId === approval.approval_id ? 'Processing...' : 'Reject'}
                    </button>

                    <button
                      onClick={() => setSelectedApproval(approval)}
                      className="px-4 py-2 rounded-lg font-medium bg-muted/30 text-muted-foreground hover:bg-muted/50 transition-colors flex items-center gap-2"
                    >
                      <MessageSquare className="w-4 h-4" />
                      Add Feedback
                    </button>
                  </div>

                  {/* Extended Details */}
                  {selectedApproval?.approval_id === approval.approval_id && (
                    <div className="border-t border-border/20 pt-4 space-y-4">
                      {/* Full Content */}
                      {approval.description && (
                        <div>
                          <h4 className="font-medium text-foreground mb-2">Request Details</h4>
                          <div className="bg-muted/20 rounded-lg p-4">
                            <pre className="text-sm text-foreground whitespace-pre-wrap">
                              {approval.description}
                            </pre>
                          </div>
                        </div>
                      )}

                      {/* Metadata */}
                      {approval.context && Object.keys(approval.context).length > 0 && (
                        <div>
                          <h4 className="font-medium text-foreground mb-2">Additional Information</h4>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {Object.entries(approval.context).map(([key, value]) => (
                              <div key={key} className="bg-muted/20 rounded p-3">
                                <span className="text-sm font-medium text-foreground capitalize">
                                  {key.replace('_', ' ')}
                                </span>
                                <p className="text-sm text-muted-foreground mt-1">
                                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Feedback Input */}
                      <div>
                        <h4 className="font-medium text-foreground mb-2">Feedback (Optional)</h4>
                        <textarea
                          value={feedbackInput}
                          onChange={(e) => setFeedbackInput(e.target.value)}
                          placeholder="Add any feedback or comments for this decision..."
                          className="w-full h-24 px-3 py-2 bg-background/80 backdrop-blur-sm border border-border/20 rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors resize-none"
                        />
                      </div>

                      {/* Action Buttons with Feedback */}
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => handleDecision(approval, 'approved')}
                          disabled={processingId === approval.approval_id}
                          className={cn(
                            'px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2',
                            'bg-green-600 hover:bg-green-700 text-white',
                            processingId === approval.approval_id && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          <CheckCircle className="w-4 h-4" />
                          Approve with Feedback
                        </button>

                        <button
                          onClick={() => handleDecision(approval, 'rejected')}
                          disabled={processingId === approval.approval_id}
                          className={cn(
                            'px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2',
                            'bg-red-600 hover:bg-red-700 text-white',
                            processingId === approval.approval_id && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          <XCircle className="w-4 h-4" />
                          Reject with Feedback
                        </button>

                        <button
                          onClick={() => {
                            setSelectedApproval(null);
                            setFeedbackInput('');
                          }}
                          className="px-4 py-2 rounded-lg font-medium bg-muted/30 text-muted-foreground hover:bg-muted/50 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </GlassCard>
            ))}
        </div>
      )}
    </div>
  );
};

export default ApprovalCenter;
