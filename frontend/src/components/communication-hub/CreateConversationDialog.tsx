import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import GlassCard from '../ui/GlassCard';
import type {
  ConversationChannel,
  ConversationPriority,
  CreateConversationParticipant,
  CreateConversationPayload,
} from './types';

interface CreateConversationDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateConversationPayload) => Promise<void> | void;
  isSubmitting: boolean;
}

const DEFAULT_PRIORITY: ConversationPriority = 'medium';
const DEFAULT_CHANNEL: ConversationChannel = 'email';

const parseParticipantsInput = (raw: string): CreateConversationParticipant[] => {
  const entries = raw
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);

  return entries.map((value, index) => ({
    id: `${value}-${index}`,
    name: value,
    type: 'human' as const,
  }));
};

export const CreateConversationDialog: React.FC<CreateConversationDialogProps> = ({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting,
}) => {
  const [subject, setSubject] = useState('');
  const [channel, setChannel] = useState<ConversationChannel>(DEFAULT_CHANNEL);
  const [priority, setPriority] = useState<ConversationPriority>(DEFAULT_PRIORITY);
  const [participantsInput, setParticipantsInput] = useState('');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    if (!isOpen) {
      setSubject('');
      setChannel(DEFAULT_CHANNEL);
      setPriority(DEFAULT_PRIORITY);
      setParticipantsInput('');
      setNotes('');
    }
  }, [isOpen]);

  const participants = useMemo(() => parseParticipantsInput(participantsInput), [participantsInput]);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!subject.trim() || participants.length === 0 || isSubmitting) {
      return;
    }

    const payload: CreateConversationPayload = {
      title: subject.trim(),
      participants,
      status: 'active',
      priority,
      metadata: {
        channel,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      },
    };

    await onSubmit(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
      <div className="relative w-full max-w-lg">
        <GlassCard className="space-y-4 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-foreground">Start a new conversation</h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full border border-border/40 p-1 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
              <span className="sr-only">Close</span>
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="flex flex-col gap-2 text-sm">
              <span className="font-medium text-foreground">Subject</span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                placeholder="Prospect follow-up with Alex"
                className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
                required
              />
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-2 text-sm">
                <span className="font-medium text-foreground">Channel</span>
                <select
                  value={channel}
                  onChange={(event) => setChannel(event.target.value as ConversationChannel)}
                  className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
                >
                  <option value="email">Email</option>
                  <option value="phone">Phone</option>
                  <option value="meeting">Meeting</option>
                  <option value="linkedin">LinkedIn</option>
                </select>
              </label>

              <label className="flex flex-col gap-2 text-sm">
                <span className="font-medium text-foreground">Priority</span>
                <select
                  value={priority}
                  onChange={(event) => setPriority(event.target.value as ConversationPriority)}
                  className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </label>
            </div>

            <label className="flex flex-col gap-2 text-sm">
              <span className="font-medium text-foreground">Participants</span>
              <textarea
                value={participantsInput}
                onChange={(event) => setParticipantsInput(event.target.value)}
                placeholder="jordan@example.com, alex@example.com"
                className="min-h-[80px] rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
                required
              />
              <span className="text-xs text-muted-foreground">
                Separate multiple emails or names with commas or line breaks.
              </span>
            </label>

            <label className="flex flex-col gap-2 text-sm">
              <span className="font-medium text-foreground">Notes (optional)</span>
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Context, goals, or required approvals before outreach."
                className="min-h-[90px] rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
              />
            </label>

            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-border/30 px-4 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || !subject.trim() || participants.length === 0}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                Create conversation
              </button>
            </div>
          </form>
        </GlassCard>
      </div>
    </div>
  );
};
