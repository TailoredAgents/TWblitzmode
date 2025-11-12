import React from 'react';
import ApprovalCenter from '../ui/ApprovalCenter';
import type { ApprovalsSectionProps } from './types';

const ApprovalsSection: React.FC<ApprovalsSectionProps> = ({ approvals, onDecision }) => {
  return (
    <section className="space-y-4">
      <ApprovalCenter approvals={approvals} onApprovalDecision={onDecision} />
    </section>
  );
};

export default ApprovalsSection;
