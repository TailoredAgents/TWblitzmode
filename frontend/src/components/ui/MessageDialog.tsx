import React, { useState } from 'react';
import Image from 'next/image';
import * as Dialog from '@radix-ui/react-dialog';
import { X, Send, User, Building2, Star, MessageSquare } from 'lucide-react';
import { cva, type VariantProps } from 'class-variance-authority';
import GlassCard from './GlassCard';
import ConnectorBadge from './ConnectorBadge';
import { cn } from '../../lib/utils';
import type { ConnectorWithContext, ProspectWithConnectors } from '../../types';

const messageDialogVariants = cva(
  'fixed inset-0 z-50 flex items-center justify-center p-4',
  {
    variants: {
      overlay: {
        default: 'bg-black/20 backdrop-blur-sm',
        strong: 'bg-black/40 backdrop-blur-md',
      },
    },
    defaultVariants: {
      overlay: 'default',
    },
  }
);

const dialogContentVariants = cva(
  'relative w-full max-w-2xl max-h-[90vh] overflow-hidden',
  {
    variants: {
      animation: {
        default: 'animate-in fade-in-0 zoom-in-95 duration-200',
        slide: 'animate-in slide-in-from-bottom-10 fade-in-0 duration-300',
      },
    },
    defaultVariants: {
      animation: 'default',
    },
  }
);

interface MessageDialogProps extends VariantProps<typeof messageDialogVariants> {
  isOpen: boolean;
  onClose: () => void;
  connector?: ConnectorWithContext | null;
  prospect?: ProspectWithConnectors;
  onSendMessage?: (
    message: string,
    connector: ConnectorWithContext,
    prospect: ProspectWithConnectors,
    subject?: string
  ) => void;
}

const MessageDialog: React.FC<MessageDialogProps> = ({
  isOpen,
  onClose,
  connector,
  prospect,
  onSendMessage,
  overlay = 'default',
}) => {
  const [message, setMessage] = useState('');
  const [subject, setSubject] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!message.trim() || !connector || !prospect) return;

    setLoading(true);
    try {
      await onSendMessage?.(message, connector, prospect, subject);
      setMessage('');
      setSubject('');
      onClose();
    } catch (error) {
      console.error('Failed to send message:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateSuggestedSubject = React.useCallback(() => {
    if (connector && prospect) {
      return `Introduction to ${prospect.full_name} at ${prospect.company}`;
    }
    return '';
  }, [connector, prospect]);

  React.useEffect(() => {
    if (isOpen && connector && prospect && !subject) {
      setSubject(generateSuggestedSubject());
    }
  }, [connector, generateSuggestedSubject, isOpen, prospect, subject]);

  if (!connector || !prospect) return null;

  return (
    <Dialog.Root open={isOpen} onOpenChange={onClose}>
      <Dialog.Portal>
        <Dialog.Overlay className={cn(messageDialogVariants({ overlay }))}>
          <Dialog.Content className={cn(dialogContentVariants())}>
            <GlassCard variant="strong" className="h-full flex flex-col">
              {/* Header */}
              <div className="flex items-center justify-between p-6 border-b border-border/20">
                <div className="flex items-center gap-4">
                  <MessageSquare className="w-6 h-6 text-primary" />
                  <div>
                    <Dialog.Title className="text-lg font-semibold text-foreground">
                      Request Introduction
                    </Dialog.Title>
                    <Dialog.Description className="text-sm text-muted-foreground">
                      Send a message through {connector.full_name}
                    </Dialog.Description>
                  </div>
                </div>
                <Dialog.Close asChild>
                  <button
                    className="p-2 rounded-lg hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Close dialog"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </Dialog.Close>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {/* Connection Info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Connector Card */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-3">
                      <ConnectorBadge
                        connector={connector}
                        rank={1}
                        size="lg"
                        showRank={false}
                      />
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-foreground truncate">
                          {connector.full_name}
                        </h3>
                        {connector.company && (
                          <p className="text-sm text-muted-foreground truncate">
                            {connector.company}
                          </p>
                        )}
                      </div>
                    </div>
                    {connector.mutual_context && (
                      <p className="text-xs text-muted-foreground">
                        {connector.mutual_context}
                      </p>
                    )}
                    {connector.ranking_score && (
                      <div className="flex items-center gap-1 mt-2">
                        <Star className="w-3 h-3 text-yellow-500 fill-current" />
                        <span className="text-xs text-foreground">
                          {Math.round(connector.ranking_score * 100)}% match
                        </span>
                      </div>
                    )}
                  </GlassCard>

                  {/* Prospect Card */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-3">
                      {prospect.profile_picture_url ? (
                        <Image
                          src={prospect.profile_picture_url}
                          alt={prospect.full_name ?? 'Prospect avatar'}
                          width={48}
                          height={48}
                          className="w-12 h-12 rounded-full object-cover"
                          unoptimized
                        />
                      ) : (
                        <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                          <User className="w-6 h-6 text-primary" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-foreground truncate">
                          {prospect.full_name}
                        </h3>
                        {prospect.role && (
                          <p className="text-sm text-muted-foreground truncate">
                            {prospect.role}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Building2 className="w-4 h-4" />
                      <span className="truncate">{prospect.company}</span>
                    </div>
                  </GlassCard>
                </div>

                {/* Message Form */}
                <div className="space-y-4">
                  {/* Subject Line */}
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-2">
                      Subject Line
                    </label>
                    <input
                      type="text"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      placeholder="Enter subject line..."
                      className="w-full px-4 py-3 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                    />
                  </div>

                  {/* Message Body */}
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-2">
                      Message
                    </label>
                    <textarea
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder={`Hi ${connector.full_name},\n\nI hope this message finds you well. I wanted to reach out regarding ${prospect.full_name} at ${prospect.company}...\n\nBest regards`}
                      rows={8}
                      className="w-full px-4 py-3 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors resize-none"
                    />
                    <div className="flex justify-between items-center mt-2">
                      <span className="text-xs text-muted-foreground">
                        {message.length}/1000 characters
                      </span>
                      <button
                        onClick={() => setMessage(`Hi ${connector.full_name},

I hope this message finds you well. I wanted to reach out regarding ${prospect.full_name} at ${prospect.company}.

Given your connection with them, I was wondering if you might be able to facilitate an introduction. I believe there could be some great synergy between our organizations.

Would you be open to making this introduction?

Best regards`)}
                        className="text-xs text-primary hover:text-primary/80 transition-colors"
                      >
                        Use template
                      </button>
                    </div>
                  </div>
                </div>

                {/* Preview */}
                {message && (
                  <GlassCard className="p-4 bg-muted/20">
                    <h4 className="text-sm font-medium text-foreground mb-2">Preview</h4>
                    <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                      <strong>Subject:</strong> {subject || generateSuggestedSubject()}
                      <br /><br />
                      {message}
                    </div>
                  </GlassCard>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between p-6 border-t border-border/20">
                <div className="text-xs text-muted-foreground">
                  This message will be sent through {connector.full_name}
                </div>
                <div className="flex items-center gap-3">
                  <Dialog.Close asChild>
                    <button
                      className="px-4 py-2 text-sm bg-muted text-muted-foreground rounded-lg hover:bg-muted/80 transition-colors"
                      disabled={loading}
                    >
                      Cancel
                    </button>
                  </Dialog.Close>
                  <button
                    onClick={handleSend}
                    disabled={!message.trim() || loading}
                    className="inline-flex items-center gap-2 px-6 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {loading ? (
                      <>
                        <div className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
                        Sending...
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4" />
                        Send Message
                      </>
                    )}
                  </button>
                </div>
              </div>
            </GlassCard>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

export default MessageDialog;
