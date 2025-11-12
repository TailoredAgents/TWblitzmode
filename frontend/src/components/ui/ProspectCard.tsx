import React, { useState } from 'react';
import Image from 'next/image';
import { Building2, MapPin, ExternalLink, User, Mail, Star } from 'lucide-react';
import GlassCard from './GlassCard';
import ConnectorBadge from './ConnectorBadge';
import MessageDialog from './MessageDialog';
import { cn, getStatusColor, getPriorityColor, formatRelativeTime, truncateText } from '../../lib/utils';
import type { ProspectWithConnectors, ConnectorWithContext } from '../../types';
import { useToastActions } from './ToastContainer';
import { apiService } from '../../services/api';

interface ProspectCardProps {
  prospect: ProspectWithConnectors;
  onConnectorSelect?: (connector: ConnectorWithContext) => void;
  onProspectSelect?: (prospect: ProspectWithConnectors) => void;
  className?: string;
}

const ProspectCard: React.FC<ProspectCardProps> = ({
  prospect,
  onConnectorSelect,
  onProspectSelect,
  className,
}) => {
  const [messageDialogOpen, setMessageDialogOpen] = useState(false);
  const [selectedConnector, setSelectedConnector] = useState<ConnectorWithContext | null>(null);
  const { success, error } = useToastActions();

  const handleCardClick = () => {
    onProspectSelect?.(prospect);
  };

  const handleConnectorClick = (connector: ConnectorWithContext) => {
    setSelectedConnector(connector);
    setMessageDialogOpen(true);
    onConnectorSelect?.(connector);
  };

  const handleSendMessage = async (
    message: string,
    connector: ConnectorWithContext,
    prospect: ProspectWithConnectors,
    subject?: string
  ) => {
    try {
      const resolvedTeamMemberId =
        typeof connector.team_member_id === 'number' && Number.isFinite(connector.team_member_id)
          ? connector.team_member_id
          : connector.id;

      if (!Number.isFinite(resolvedTeamMemberId)) {
        throw new Error('Unable to determine connector team member identifier.');
      }

      const preparedMessage =
        subject && subject.trim().length > 0 ? `Subject: ${subject.trim()}\n\n${message}` : message;

      await apiService.createIntroduction({
        prospectId: prospect.id,
        teamMemberId: resolvedTeamMemberId,
        message: preparedMessage,
      });

      success('Introduction recorded', 'We saved your introduction request and will handle delivery.');
    } catch (err) {
      console.error('Failed to send introduction message:', err);
      error('Failed to send introduction message', 'Please try again or contact support if the issue persists.');
      throw err;
    }
  };

  const statusBadge = (
    <span className={cn(
      'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium',
      getStatusColor(prospect.status)
    )}>
      {prospect.status.replace('_', ' ')}
    </span>
  );

  const priorityIndicator = getPriorityColor(prospect.priority);

  return (
    <GlassCard
      variant="interactive"
      className={cn(
        'group h-full transition-all duration-300 hover:shadow-apple-lg border-l-4',
        priorityIndicator,
        className
      )}
      onClick={handleCardClick}
    >
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              {prospect.profile_picture_url ? (
                <Image
                  src={prospect.profile_picture_url}
                  alt={prospect.full_name ?? 'Prospect avatar'}
                  width={32}
                  height={32}
                  className="w-8 h-8 rounded-full object-cover"
                  unoptimized
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <User className="w-4 h-4 text-primary" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                  {prospect.full_name}
                </h3>
                {prospect.role && (
                  <p className="text-sm text-muted-foreground truncate">
                    {prospect.role}
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            {statusBadge}
            {prospect.response_rate && (
              <div className="flex items-center gap-1 text-xs text-green-600">
                <Star className="w-3 h-3 fill-current" />
                {Math.round(prospect.response_rate * 100)}%
              </div>
            )}
          </div>
        </div>

        {/* Company and Location */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2 text-sm text-foreground">
            <Building2 className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            <span className="font-medium truncate">{prospect.company}</span>
            {prospect.company_size && (
              <span className="text-muted-foreground">({prospect.company_size})</span>
            )}
          </div>

          {prospect.location && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <MapPin className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">{prospect.location}</span>
            </div>
          )}

          {prospect.industry && (
            <div className="text-xs text-muted-foreground">
              {prospect.industry}
            </div>
          )}
        </div>

        {/* Headline/About */}
        {prospect.headline && (
          <div className="mb-4">
            <p className="text-sm text-muted-foreground line-clamp-2">
              {truncateText(prospect.headline, 120)}
            </p>
          </div>
        )}

        {/* Tags */}
        {prospect.tags && prospect.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-4">
            {prospect.tags.slice(0, 3).map((tag, index) => (
              <span
                key={index}
                className="inline-flex items-center px-2 py-1 rounded-md text-xs bg-secondary/50 text-secondary-foreground"
              >
                {tag}
              </span>
            ))}
            {prospect.tags.length > 3 && (
              <span className="text-xs text-muted-foreground">
                +{prospect.tags.length - 3} more
              </span>
            )}
          </div>
        )}

        {/* Connectors Section */}
        <div className="mt-auto">
          {prospect.top_connectors && prospect.top_connectors.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">
                  Mutual Connections
                </span>
                <span className="text-xs text-muted-foreground">
                  {(prospect.connectors_count ?? prospect.top_connectors.length)} total
                </span>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex -space-x-1">
                  {prospect.top_connectors.slice(0, 5).map((connector, index) => (
                    <ConnectorBadge
                      key={connector.id}
                      connector={connector}
                      rank={index + 1}
                      size="sm"
                      onClick={() => handleConnectorClick(connector)}
                      showTooltip={true}
                      className="border-2 border-white hover:z-10"
                    />
                  ))}

                  {prospect.top_connectors.length > 5 && (
                    <div className="w-8 h-8 bg-muted border-2 border-white rounded-full flex items-center justify-center text-xs font-medium text-muted-foreground">
                      +{prospect.top_connectors.length - 5}
                    </div>
                  )}
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-1">
                  {prospect.email && (
                    <button
                      className="p-1.5 rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(`mailto:${prospect.email}`, '_blank');
                      }}
                      title="Send email"
                    >
                      <Mail className="w-3 h-3" />
                    </button>
                  )}

                  {prospect.linkedin_url && (
                    <button
                      className="p-1.5 rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(prospect.linkedin_url, '_blank');
                      }}
                      title="View LinkedIn"
                    >
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>

              {/* Best connector preview */}
              {prospect.top_connectors[0] && (
                <div className="p-2 rounded-lg bg-muted/30 border border-muted">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Best match:</span>
                    <span className="font-medium text-foreground">
                      {prospect.top_connectors[0].full_name}
                    </span>
                  </div>
                  {prospect.top_connectors[0].mutual_context && (
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-1">
                      {prospect.top_connectors[0].mutual_context}
                    </p>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-4 text-muted-foreground">
              <User className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No mutual connections found</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between mt-4 pt-3 border-t border-border/50 text-xs text-muted-foreground">
          <span>Updated {formatRelativeTime(prospect.updated_at)}</span>
          <span className="capitalize">{prospect.priority} priority</span>
        </div>
      </div>

      {/* Message Dialog */}
      <MessageDialog
        isOpen={messageDialogOpen}
        onClose={() => {
          setMessageDialogOpen(false);
          setSelectedConnector(null);
        }}
        connector={selectedConnector}
        prospect={prospect}
        onSendMessage={handleSendMessage}
      />
    </GlassCard>
  );
};

export default ProspectCard;
