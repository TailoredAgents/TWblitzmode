'use client';

import { useEffect, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';

export interface KeyboardShortcut {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  action: () => void;
  description: string;
  category: string;
}

interface UseKeyboardShortcutsProps {
  shortcuts: KeyboardShortcut[];
  enabled?: boolean;
}

export const useKeyboardShortcuts = ({ shortcuts, enabled = true }: UseKeyboardShortcutsProps) => {
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (!enabled) return;

    // Don't trigger shortcuts when user is typing in inputs
    const activeElement = document.activeElement as HTMLElement;
    if (
      activeElement &&
      (activeElement.tagName === 'INPUT' ||
        activeElement.tagName === 'TEXTAREA' ||
        activeElement.contentEditable === 'true')
    ) {
      return;
    }

    const matchingShortcut = shortcuts.find(shortcut => {
      return (
        shortcut.key.toLowerCase() === event.key.toLowerCase() &&
        !!shortcut.ctrlKey === event.ctrlKey &&
        !!shortcut.metaKey === event.metaKey &&
        !!shortcut.shiftKey === event.shiftKey &&
        !!shortcut.altKey === event.altKey
      );
    });

    if (matchingShortcut) {
      event.preventDefault();
      event.stopPropagation();
      matchingShortcut.action();
    }
  }, [shortcuts, enabled]);

  useEffect(() => {
    if (!enabled) return;

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown, enabled]);
};

// Global keyboard shortcuts hook for the dashboard
export const useGlobalShortcuts = (
  onViewChange: (view: string) => void,
  onShowShortcuts?: () => void
) => {
  const { theme, setTheme } = useTheme();

  const globalShortcuts: KeyboardShortcut[] = [
    // Navigation shortcuts
    {
      key: '1',
      metaKey: true,
      action: () => onViewChange('dashboard'),
      description: 'Go to Dashboard',
      category: 'Navigation',
    },
    {
      key: '2',
      metaKey: true,
      action: () => onViewChange('approvals'),
      description: 'Go to Approval Queue',
      category: 'Navigation',
    },
    {
      key: '3',
      metaKey: true,
      action: () => onViewChange('prospects'),
      description: 'Go to Prospects',
      category: 'Navigation',
    },
    {
      key: '4',
      metaKey: true,
      action: () => onViewChange('workflows'),
      description: 'Go to AI Workflows',
      category: 'Navigation',
    },
    {
      key: '5',
      metaKey: true,
      action: () => onViewChange('master-game-plan'),
      description: 'Go to Master Game Plan',
      category: 'Navigation',
    },
    {
      key: '6',
      metaKey: true,
      action: () => onViewChange('emails'),
      description: 'Go to Email Management',
      category: 'Navigation',
    },
    {
      key: '7',
      metaKey: true,
      action: () => onViewChange('integrations'),
      description: 'Go to Integrations',
      category: 'Navigation',
    },
    {
      key: '8',
      metaKey: true,
      action: () => onViewChange('settings'),
      description: 'Go to Settings',
      category: 'Navigation',
    },

    // Theme shortcuts
    {
      key: 't',
      metaKey: true,
      action: () => {
        const themes = ['light', 'dark', 'system'] as const;
        const currentIndex = themes.indexOf(theme);
        const nextIndex = (currentIndex + 1) % themes.length;
        const nextTheme = themes.at(nextIndex) ?? 'light';
        setTheme(nextTheme);
      },
      description: 'Toggle Theme',
      category: 'Interface',
    },
    {
      key: 'd',
      metaKey: true,
      shiftKey: true,
      action: () => setTheme('dark'),
      description: 'Switch to Dark Mode',
      category: 'Interface',
    },
    {
      key: 'l',
      metaKey: true,
      shiftKey: true,
      action: () => setTheme('light'),
      description: 'Switch to Light Mode',
      category: 'Interface',
    },

    // Search and filter shortcuts
    {
      key: 'f',
      metaKey: true,
      action: () => {
        const searchInput = document.querySelector('input[placeholder*="Search"]') as HTMLInputElement;
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      },
      description: 'Focus Search',
      category: 'Search',
    },
    {
      key: 'k',
      metaKey: true,
      action: () => {
        // Placeholder for upcoming command palette integration
      },
      description: 'Open Command Palette (Coming Soon)',
      category: 'Search',
    },

    // Quick actions
    {
      key: 'r',
      metaKey: true,
      action: () => {
        window.location.reload();
      },
      description: 'Refresh Page',
      category: 'Actions',
    },
    {
      key: 'Escape',
      action: () => {
        // Close any open modals or overlays
        const modals = document.querySelectorAll('[role="dialog"]');
        modals.forEach(modal => {
          const closeButton = modal.querySelector('[aria-label*="close"], [aria-label*="Close"]') as HTMLButtonElement;
          if (closeButton) {
            closeButton.click();
          }
        });
      },
      description: 'Close Modals/Overlays',
      category: 'Actions',
    },

    // Help
    {
      key: '?',
      shiftKey: true,
      action: () => {
        if (onShowShortcuts) {
          onShowShortcuts();
        }
      },
      description: 'Show Keyboard Shortcuts',
      category: 'Help',
    },
  ];

  useKeyboardShortcuts({ shortcuts: globalShortcuts });

  return globalShortcuts;
};
