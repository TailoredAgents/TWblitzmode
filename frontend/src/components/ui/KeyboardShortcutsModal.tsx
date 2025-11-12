'use client';

import React, { useState, useEffect } from 'react';
import { type LucideIcon, X, Keyboard, Search, Navigation, Palette, Zap, HelpCircle } from 'lucide-react';
import { cn } from '../../lib/utils';
import GlassCard from './GlassCard';
import type { KeyboardShortcut } from '../../hooks/useKeyboardShortcuts';

interface KeyboardShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
  shortcuts: KeyboardShortcut[];
}

const CATEGORY_ICON_MAP = new Map<string, LucideIcon>([
  ['Navigation', Navigation],
  ['Interface', Palette],
  ['Search', Search],
  ['Actions', Zap],
  ['Help', HelpCircle],
]);

const KeyboardShortcutsModal: React.FC<KeyboardShortcutsModalProps> = ({
  isOpen,
  onClose,
  shortcuts,
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  // Close modal on Escape key
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  // Group shortcuts by category
  const groupedShortcuts = shortcuts.reduce((acc, shortcut) => {
    const existing = acc.get(shortcut.category);
    if (existing) {
      existing.push(shortcut);
    } else {
      acc.set(shortcut.category, [shortcut]);
    }
    return acc;
  }, new Map<string, KeyboardShortcut[]>());

  // Filter shortcuts based on search term
  const filteredGroups = new Map<string, KeyboardShortcut[]>();
  groupedShortcuts.forEach((categoryShortcuts, category) => {
    const filtered = categoryShortcuts.filter(shortcut =>
      shortcut.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
      shortcut.key.toLowerCase().includes(searchTerm.toLowerCase())
    );
    if (filtered.length > 0) {
      filteredGroups.set(category, filtered);
    }
  });
  const filteredEntries = Array.from(filteredGroups.entries());

  const formatShortcut = (shortcut: KeyboardShortcut) => {
    const keys: string[] = [];

    if (shortcut.metaKey) keys.push('⌘');
    if (shortcut.ctrlKey) keys.push('Ctrl');
    if (shortcut.shiftKey) keys.push('⇧');
    if (shortcut.altKey) keys.push('⌥');

    keys.push(shortcut.key === ' ' ? 'Space' : shortcut.key.toUpperCase());

    return keys;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-4xl max-h-[90vh] mx-4 overflow-hidden">
        <GlassCard className="h-full flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-border/20">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Keyboard className="w-5 h-5 text-primary" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-foreground">Keyboard Shortcuts</h2>
                <p className="text-sm text-muted-foreground">
                  Boost your productivity with these keyboard shortcuts
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-muted/50 transition-colors"
              aria-label="Close keyboard shortcuts modal"
            >
              <X className="w-5 h-5 text-muted-foreground" />
            </button>
          </div>

          {/* Search */}
          <div className="p-6 border-b border-border/20">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search shortcuts..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-muted/30 border border-border/20 rounded-lg text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30 transition-colors"
              />
            </div>
          </div>

          {/* Shortcuts List */}
          <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-8">
              {filteredEntries.map(([category, categoryShortcuts]) => {
                const IconComponent = CATEGORY_ICON_MAP.get(category) ?? Keyboard;
                return (
                  <div key={category}>
                    <div className="flex items-center gap-2 mb-4">
                      <div className="p-1.5 rounded-md bg-primary/10">
                        <IconComponent className="w-4 h-4" />
                      </div>
                      <h3 className="text-base font-medium text-foreground">{category}</h3>
                      <div className="flex-1 h-px bg-border/20" />
                    </div>

                    <div className="grid gap-3">
                      {categoryShortcuts.map((shortcut, index) => (
                        <div
                          key={`${category}-${index}`}
                          className="flex items-center justify-between p-3 rounded-lg bg-muted/20 hover:bg-muted/30 transition-colors"
                        >
                          <span className="text-sm text-foreground">{shortcut.description}</span>
                          <div className="flex items-center gap-1">
                            {formatShortcut(shortcut).map((key, keyIndex) => (
                              <kbd
                                key={keyIndex}
                                className={cn(
                                  'inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 text-xs font-mono',
                                  'bg-background/80 border border-border/30 rounded shadow-sm',
                                  'text-foreground'
                                )}
                              >
                                {key}
                              </kbd>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {filteredEntries.length === 0 && searchTerm && (
              <div className="text-center py-12">
                <Search className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-medium text-foreground mb-2">No shortcuts found</h3>
                <p className="text-muted-foreground">
                  Try searching for a different term or clear your search.
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-6 border-t border-border/20">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <kbd className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 text-xs font-mono bg-background/80 border border-border/30 rounded shadow-sm">
                ?
              </kbd>
              <span>to open this help</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <kbd className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 text-xs font-mono bg-background/80 border border-border/30 rounded shadow-sm">
                Esc
              </kbd>
              <span>to close</span>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
};

export default KeyboardShortcutsModal;
