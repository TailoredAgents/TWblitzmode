// Conversations List - Communication Hub Component
// September 2025 AI Integration

import React from 'react';
import { MessageSquare, Bot, User, Clock, Plus } from 'lucide-react';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';
import type { Conversation } from '../../types';

interface ConversationsListProps {
  conversations: Conversation[];
  selectedConversation: Conversation | null;
  onConversationSelect: (conversation: Conversation) => void;
  onNewConversation: () => void;
}

const ConversationsList: React.FC<ConversationsListProps> = ({
  conversations,
  selectedConversation,
  onConversationSelect,
  onNewConversation
}) => {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

    if (diffInHours < 1) {
      return 'Just now';
    } else if (diffInHours < 24) {
      return `${Math.floor(diffInHours)}h ago`;
    } else {
      return date.toLocaleDateString();
    }
  };

  const getLastMessage = (conversation: Conversation) => {
    if (!conversation.messages || conversation.messages.length === 0) {
      return 'No messages yet';
    }
    return conversation.messages[conversation.messages.length - 1]?.content ?? 'No content';
  };

  const getParticipantIcon = (type: 'human' | 'ai') => {
    return type === 'ai' ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />;
  };

  return (
    <div className="space-y-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Conversations</h2>
        <button
          onClick={onNewConversation}
          className="p-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          title="New Conversation"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* Conversations List */}
      <div className="space-y-2 overflow-y-auto flex-1">
        {conversations.length === 0 ? (
          <GlassCard className="text-center py-8">
            <MessageSquare className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <h3 className="font-medium text-foreground mb-1">No Conversations</h3>
            <p className="text-sm text-muted-foreground mb-4">Start a new conversation with an AI agent</p>
            <button
              onClick={onNewConversation}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
            >
              Start Conversation
            </button>
          </GlassCard>
        ) : (
          conversations.map((conversation) => (
            <GlassCard
              key={conversation.id}
              variant="interactive"
              className={cn(
                'p-4 cursor-pointer transition-all duration-200',
                selectedConversation?.id === conversation.id
                  ? 'ring-2 ring-primary/40 bg-primary/5'
                  : 'hover:bg-muted/10'
              )}
              onClick={() => onConversationSelect(conversation)}
            >
              <div className="space-y-3">
                {/* Header */}
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-foreground truncate">
                      {conversation.title}
                    </h3>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex items-center gap-1">
                        {conversation.participants.map((participant, index) => (
                          <div
                            key={index}
                            className="flex items-center gap-1 text-xs text-muted-foreground"
                            title={participant.name}
                          >
                            {getParticipantIcon(participant.type)}
                            <span className="truncate max-w-16">
                              {participant.name}
                            </span>
                            {index < conversation.participants.length - 1 && (
                              <span className="text-muted-foreground/50">,</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Clock className="w-3 h-3" />
                    {formatTime(conversation.updated_at)}
                  </div>
                </div>

                {/* Last Message Preview */}
                <div className="text-sm text-muted-foreground">
                  <p className="line-clamp-2">
                    {getLastMessage(conversation)}
                  </p>
                </div>

                {/* Status Indicators */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {/* Conversation Status */}
                    <span
                      className={cn(
                        'px-2 py-1 rounded-full text-xs font-medium',
                        conversation.status === 'active'
                          ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                          : conversation.status === 'pending_approval'
                          ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                          : 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400'
                      )}
                    >
                      {conversation.status.replace('_', ' ')}
                    </span>

                    {/* Priority Indicator */}
                    {conversation.priority === 'high' && (
                      <div className="w-2 h-2 rounded-full bg-red-500" title="High Priority" />
                    )}
                  </div>

                  {/* Unread Messages Count */}
                  {conversation.unread_count > 0 && (
                    <div className="bg-primary text-primary-foreground text-xs rounded-full w-5 h-5 flex items-center justify-center">
                      {conversation.unread_count > 9 ? '9+' : conversation.unread_count}
                    </div>
                  )}
                </div>
              </div>
            </GlassCard>
          ))
        )}
      </div>
    </div>
  );
};

export default ConversationsList;
