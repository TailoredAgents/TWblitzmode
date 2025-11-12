'use client';

import { useEffect, useRef, useCallback } from 'react';

// Focus management hook for modals and overlays
export const useFocusTrap = (isOpen: boolean, restoreFocus = true) => {
  const containerRef = useRef<HTMLElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    // Store the currently focused element
    previousFocusRef.current = document.activeElement as HTMLElement;

    const container = containerRef.current;
    if (!container) return;

    // Get all focusable elements
    const getFocusableElements = () => {
      return container.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable]'
      );
    };

    const focusableElements = getFocusableElements();
    const firstFocusable = focusableElements[0];

    // Focus the first element
    if (firstFocusable) {
      firstFocusable.focus();
    }

    const handleTabKey = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;

      const currentFocusableElements = getFocusableElements();
      const currentFirstFocusable = currentFocusableElements[0];
      const currentLastFocusable = currentFocusableElements[currentFocusableElements.length - 1];

      if (event.shiftKey) {
        // Shift + Tab
        if (document.activeElement === currentFirstFocusable) {
          event.preventDefault();
          currentLastFocusable?.focus();
        }
      } else {
        // Tab
        if (document.activeElement === currentLastFocusable) {
          event.preventDefault();
          currentFirstFocusable?.focus();
        }
      }
    };

    container.addEventListener('keydown', handleTabKey);

    return () => {
      container.removeEventListener('keydown', handleTabKey);

      // Restore focus when component unmounts
      if (restoreFocus && previousFocusRef.current) {
        previousFocusRef.current.focus();
      }
    };
  }, [isOpen, restoreFocus]);

  return containerRef;
};

// Screen reader announcements
export const useScreenReader = () => {
  const announce = useCallback((message: string, priority: 'polite' | 'assertive' = 'polite') => {
    const announcement = document.createElement('div');
    announcement.setAttribute('aria-live', priority);
    announcement.setAttribute('aria-atomic', 'true');
    announcement.className = 'sr-only';
    announcement.textContent = message;

    document.body.appendChild(announcement);

    // Remove after announcement
    setTimeout(() => {
      document.body.removeChild(announcement);
    }, 1000);
  }, []);

  return { announce };
};

// Reduced motion detection
export const useReducedMotion = () => {
  const prefersReducedMotion = typeof window !== 'undefined'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;

  return prefersReducedMotion;
};

// High contrast mode detection
export const useHighContrast = () => {
  const prefersHighContrast = typeof window !== 'undefined'
    ? window.matchMedia('(prefers-contrast: high)').matches
    : false;

  return prefersHighContrast;
};

// Keyboard navigation helpers
export const useKeyboardNavigation = () => {
  const handleArrowNavigation = useCallback((
    event: React.KeyboardEvent,
    items: HTMLElement[],
    currentIndex: number,
    onIndexChange: (index: number) => void
  ) => {
    let newIndex = currentIndex;

    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowRight':
        event.preventDefault();
        newIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
        break;
      case 'ArrowUp':
      case 'ArrowLeft':
        event.preventDefault();
        newIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
        break;
      case 'Home':
        event.preventDefault();
        newIndex = 0;
        break;
      case 'End':
        event.preventDefault();
        newIndex = items.length - 1;
        break;
      default:
        return;
    }

    onIndexChange(newIndex);
    items.at(newIndex)?.focus();
  }, []);

  return { handleArrowNavigation };
};

// ARIA live region manager
export const useAriaLive = () => {
  const liveRegionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let existingRegion = document.getElementById('aria-live-region') as HTMLDivElement | null;
    let createdRegion = false;

    if (!existingRegion) {
      existingRegion = document.createElement('div');
      existingRegion.id = 'aria-live-region';
      existingRegion.setAttribute('aria-live', 'polite');
      existingRegion.setAttribute('aria-atomic', 'true');
      existingRegion.className = 'sr-only';
      document.body.appendChild(existingRegion);
      createdRegion = true;
    }

    liveRegionRef.current = existingRegion;

    return () => {
      if (createdRegion && existingRegion?.parentNode) {
        existingRegion.parentNode.removeChild(existingRegion);
      }
    };
  }, []);

  const announce = useCallback((message: string) => {
    if (liveRegionRef.current) {
      liveRegionRef.current.textContent = message;

      // Clear the message after announcement
      setTimeout(() => {
        if (liveRegionRef.current) {
          liveRegionRef.current.textContent = '';
        }
      }, 1000);
    }
  }, []);

  return { announce };
};

// Focus visible management
export const useFocusVisible = () => {
  useEffect(() => {
    // Add focus-visible polyfill behavior
    const handleMouseDown = () => {
      document.body.classList.add('using-mouse');
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Tab') {
        document.body.classList.remove('using-mouse');
      }
    };

    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);
};
