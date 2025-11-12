// Message Thread - Communication Hub Component
// September 2025 AI Integration

import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';
import type { Conversation, Message } from '../../types';

interface MessageThreadProps {
  conversation: Conversation;
  onSendMessage: (content: string, type?: 'text' | 'approval_request') => void;
}

const MessageThread: React.FC<MessageThreadProps> = ({
  conversation,
  onSendMessage
}) => {
  const [messageInput, setMessageInput] = useState('');
  const [messageType, setMessageType] = useState<'text' | 'approval_request'>('text');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollToBottom();
  }, [conversation.messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleSendMessage = () => {
    if (!messageInput.trim()) return;

    onSendMessage(messageInput.trim(), messageType);
    setMessageInput('');
    setMessageType('text');
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getMessageIcon = (message: Message) => {
    const iconClass = "w-4 h-4";

    if (message.sender_type === 'ai') {
      return <Bot className={iconClass} />;
    }

    return <User className={iconClass} />;
  };

  const getMessageStatus = (message: Message) => {
    switch (message.status) {
      case 'sent':
        return <CheckCircle className="w-3 h-3 text-green-500" />;
      case 'failed':
        return <XCircle className="w-3 h-3 text-red-500" />;
      case 'pending':
        return <Clock className="w-3 h-3 text-yellow-500" />;
      default:
        return null;
    }
  };

  const getApprovalStatus = (message: Message) => {
    const statusValue = message.metadata?.approval_status;
    if (message.message_type !== 'approval_request' || typeof statusValue !== 'string') {
      return null;
    }

    const status = statusValue as 'pending' | 'approved' | 'rejected' | string;
    const statusColors = {
      pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
      approved: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
      rejected: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
    };

    return (
      <div className={cn(
        'mt-2 px-2 py-1 rounded text-xs font-medium inline-flex items-center gap-1',
        statusColors[status as keyof typeof statusColors] || statusColors.pending
      )}>
        {status === 'pending' && <Clock className="w-3 h-3" />}
        {status === 'approved' && <CheckCircle className="w-3 h-3" />}
        {status === 'rejected' && <XCircle className="w-3 h-3" />}
        {`${status.charAt(0).toUpperCase()}${status.slice(1)}`}
      </div>
    );
  };

  return (
    <GlassCard className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-border/20 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              {conversation.title}
            </h2>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-muted-foreground">
                {conversation.participants.length} participant{conversation.participants.length !== 1 ? 's' : ''}
              </span>
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
            </div>
          </div>

          {conversation.priority === 'high' && (
            <div className="flex items-center gap-1 text-red-500">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">High Priority</span>
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {conversation.messages && conversation.messages.length > 0 ? (
          conversation.messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                'flex gap-3',
                message.sender_type === 'human' ? 'flex-row-reverse' : 'flex-row'
              )}
            >
              {/* Avatar */}
              <div className={cn(
                'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
                message.sender_type === 'ai'
                  ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-900/30 dark:text-slate-300'
              )}>
                {getMessageIcon(message)}
              </div>

              {/* Message Content */}
              <div className={cn(
                'flex flex-col max-w-xs lg:max-w-md',
                message.sender_type === 'human' ? 'items-end' : 'items-start'
              )}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-foreground">
                    {message.sender_name && message.sender_name.trim().length > 0
                      ? message.sender_name
                      : message.sender_type === 'ai'
                        ? 'AI Agent'
                        : 'You'}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatTimestamp(message.created_at)}
                  </span>
                  {getMessageStatus(message)}
                </div>

                <div className={cn(
                  'rounded-lg px-4 py-2 max-w-full',
                  message.sender_type === 'ai'
                    ? 'bg-muted/30 text-foreground'
                    : 'bg-primary text-primary-foreground',
                  message.message_type === 'approval_request' && 'border-2 border-yellow-200 dark:border-yellow-800'
                )}>
                  {message.message_type === 'approval_request' && (
                    <div className="flex items-center gap-2 mb-2 text-xs opacity-80">
                      <AlertTriangle className="w-3 h-3" />
                      Approval Request
                    </div>
                  )}

                  <p className="text-sm whitespace-pre-wrap break-words">
                    {message.content}
                  </p>

                  {getApprovalStatus(message)}
                </div>

                {/* Metadata */}
                {message.metadata && Object.keys(message.metadata).length > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {typeof message.metadata.workflow_id === 'string' && message.metadata.workflow_id && (
                      <span>Workflow: {message.metadata.workflow_id}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="text-center py-8">
            <Bot className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-foreground mb-2">Start the Conversation</h3>
            <p className="text-muted-foreground">Send your first message to begin communicating with the AI agent</p>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Message Input */}
      <div className="border-t border-border/20 p-4">
        <div className="space-y-3">
          {/* Message Type Selector */}
          <div className="flex gap-2">
            <button
              onClick={() => setMessageType('text')}
              className={cn(
                'px-3 py-1 rounded-md text-xs font-medium transition-colors',
                messageType === 'text'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'
              )}
            >
              Message
            </button>
            <button
              onClick={() => setMessageType('approval_request')}
              className={cn(
                'px-3 py-1 rounded-md text-xs font-medium transition-colors',
                messageType === 'approval_request'
                  ? 'bg-yellow-500 text-white'
                  : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'
              )}
            >
              Approval Request
            </button>
          </div>

          {/* Input Area */}
          <div className="flex gap-3">
            <textarea
              ref={inputRef}
              value={messageInput}
              onChange={(e) => setMessageInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={
                messageType === 'approval_request'
                  ? 'Describe what needs approval...'
                  : 'Type your message...'
              }
              className="flex-1 resize-none rounded-lg border border-border/20 bg-background/80 backdrop-blur-sm px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors"
              rows={2}
            />
            <button
              onClick={handleSendMessage}
              disabled={!messageInput.trim()}
              className={cn(
                'px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2',
                messageInput.trim()
                  ? messageType === 'approval_request'
                    ? 'bg-yellow-500 hover:bg-yellow-600 text-white'
                    : 'bg-primary hover:bg-primary/90 text-primary-foreground'
                  : 'bg-muted/30 text-muted-foreground cursor-not-allowed'
              )}
            >
              <Send className="w-4 h-4" />
              Send
            </button>
          </div>

          {messageType === 'approval_request' && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">
              This message will require approval before being processed by the AI agent.
            </p>
          )}
        </div>
      </div>
    </GlassCard>
  );
};

export default MessageThread;
