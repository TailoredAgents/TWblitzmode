/**
 * Accessibility Utilities and WCAG 2.1 Compliance Framework
 * Provides comprehensive accessibility helpers, validation, and audit tools.
 */

import { useEffect, useRef, type RefObject } from 'react';

const DEFAULT_FOCUS_DELAY_MS = 100;
const SCREEN_READER_DISMISS_MS = 1000;

// WCAG 2.1 Color Contrast Ratios
export const WCAG_CONTRAST_RATIOS = {
  AA_NORMAL: 4.5,
  AA_LARGE: 3,
  AAA_NORMAL: 7,
  AAA_LARGE: 4.5,
} as const;

// Accessibility roles and properties
export interface AccessibilityProps {
  role?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
  'aria-expanded'?: boolean;
  'aria-hidden'?: boolean;
  'aria-live'?: 'off' | 'polite' | 'assertive';
  'aria-atomic'?: boolean;
  'aria-relevant'?: 'text' | 'all' | 'additions' | 'additions removals' | 'additions text' | 'removals' | 'removals additions' | 'removals text' | 'text additions' | 'text removals';
  'aria-required'?: boolean;
  'aria-modal'?: boolean;
  tabIndex?: number;
}

// Color contrast calculation
export function calculateColorContrast(foreground: string, background: string): number {
  const getLuminance = (color: string): number => {
    // Convert hex to RGB
    const hex = color.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16) / 255;
    const g = parseInt(hex.substr(2, 2), 16) / 255;
    const b = parseInt(hex.substr(4, 2), 16) / 255;

    // Calculate relative luminance
    const sRGB = [r, g, b].map(c => {
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });

    return 0.2126 * (sRGB[0] ?? 0) + 0.7152 * (sRGB[1] ?? 0) + 0.0722 * (sRGB[2] ?? 0);
  };

  const l1 = getLuminance(foreground);
  const l2 = getLuminance(background);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);

  return (lighter + 0.05) / (darker + 0.05);
}

// Check WCAG compliance
export function checkWCAGCompliance(
  foreground: string,
  background: string,
  fontSize: number = 16,
  fontWeight: number = 400
): {
  ratio: number;
  AA: boolean;
  AAA: boolean;
  level: 'AA' | 'AAA' | 'fail';
} {
  const ratio = calculateColorContrast(foreground, background);
  const isLargeText = fontSize >= 18 || (fontSize >= 14 && fontWeight >= 700);

  const aaThreshold = isLargeText ? WCAG_CONTRAST_RATIOS.AA_LARGE : WCAG_CONTRAST_RATIOS.AA_NORMAL;
  const aaaThreshold = isLargeText ? WCAG_CONTRAST_RATIOS.AAA_LARGE : WCAG_CONTRAST_RATIOS.AAA_NORMAL;

  const AA = ratio >= aaThreshold;
  const AAA = ratio >= aaaThreshold;

  return {
    ratio,
    AA,
    AAA,
    level: AAA ? 'AAA' : AA ? 'AA' : 'fail'
  };
}

// Focus management hook
export function useFocusManagement(autoFocus: boolean = false): [RefObject<HTMLElement | null>, () => void] {
  const elementRef = useRef<HTMLElement>(null);

  const focus = () => {
    if (elementRef.current) {
      elementRef.current.focus();
    }
  };

  useEffect(() => {
    if (autoFocus && elementRef.current) {
      // Delay focus to ensure proper rendering
      setTimeout(() => {
        elementRef.current?.focus();
      }, DEFAULT_FOCUS_DELAY_MS);
    }
  }, [autoFocus]);

  return [elementRef, focus];
}

// Keyboard navigation handler
export function useKeyboardNavigation(
  onEscape?: () => void,
  onEnter?: () => void,
  onArrowKeys?: (direction: 'up' | 'down' | 'left' | 'right') => void
) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      switch (event.key) {
        case 'Escape':
          if (onEscape) {
            event.preventDefault();
            onEscape();
          }
          break;
        case 'Enter':
          if (onEnter) {
            event.preventDefault();
            onEnter();
          }
          break;
        case 'ArrowUp':
          if (onArrowKeys) {
            event.preventDefault();
            onArrowKeys('up');
          }
          break;
        case 'ArrowDown':
          if (onArrowKeys) {
            event.preventDefault();
            onArrowKeys('down');
          }
          break;
        case 'ArrowLeft':
          if (onArrowKeys) {
            event.preventDefault();
            onArrowKeys('left');
          }
          break;
        case 'ArrowRight':
          if (onArrowKeys) {
            event.preventDefault();
            onArrowKeys('right');
          }
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onEscape, onEnter, onArrowKeys]);
}

// Screen reader announcements
export function announceToScreenReader(message: string, priority: 'polite' | 'assertive' = 'polite') {
  const announcement = document.createElement('div');
  announcement.setAttribute('aria-live', priority);
  announcement.setAttribute('aria-atomic', 'true');
  announcement.className = 'sr-only';
  announcement.textContent = message;

  document.body.appendChild(announcement);

  // Remove after announcement
  setTimeout(() => {
    document.body.removeChild(announcement);
  }, SCREEN_READER_DISMISS_MS);
}

// Focus trap for modals
export function useFocusTrap(isActive: boolean): RefObject<HTMLElement | null> {
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!isActive || !containerRef.current) return;

    const container = containerRef.current;
    const focusableElements = container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );

    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

    const handleTabKey = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;

      if (event.shiftKey) {
        if (document.activeElement === firstElement) {
          event.preventDefault();
          lastElement?.focus();
        }
      } else {
        if (document.activeElement === lastElement) {
          event.preventDefault();
          firstElement?.focus();
        }
      }
    };

    // Focus first element when trap becomes active
    firstElement?.focus();

    document.addEventListener('keydown', handleTabKey);
    return () => document.removeEventListener('keydown', handleTabKey);
  }, [isActive]);

  return containerRef;
}

// Reduced motion preference detection
export function useReducedMotion(): boolean {
  const prefersReducedMotion = typeof window !== 'undefined'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;

  return prefersReducedMotion;
}

// High contrast mode detection
export function useHighContrast(): boolean {
  const prefersHighContrast = typeof window !== 'undefined'
    ? window.matchMedia('(prefers-contrast: high)').matches
    : false;

  return prefersHighContrast;
}

// Generate accessible ID
export function generateAccessibleId(prefix: string = 'a11y'): string {
  return `${prefix}-${Math.random().toString(36).substr(2, 9)}`;
}

// Skip link component props
export interface SkipLinkProps {
  href: string;
  children: React.ReactNode;
  className?: string;
}

// Common accessibility patterns
export const AccessibilityPatterns = {
  // Button with proper ARIA
  button: (label: string, onClick: () => void, options?: {
    disabled?: boolean;
    expanded?: boolean;
    describedBy?: string;
  }): AccessibilityProps & { onClick: () => void } => ({
    role: 'button',
    'aria-label': label,
    ...(options?.expanded !== undefined && { 'aria-expanded': options.expanded }),
    ...(options?.describedBy && { 'aria-describedby': options.describedBy }),
    tabIndex: options?.disabled ? -1 : 0,
    onClick
  }),

  // Input with proper labeling
  input: (labelId: string, describedBy?: string): AccessibilityProps => ({
    'aria-labelledby': labelId,
    ...(describedBy && { 'aria-describedby': describedBy }),
    'aria-required': true
  }),

  // Modal with proper ARIA
  modal: (labelId: string, describedBy?: string): AccessibilityProps => ({
    role: 'dialog',
    'aria-modal': true,
    'aria-labelledby': labelId,
    ...(describedBy && { 'aria-describedby': describedBy })
  }),

  // Live region for dynamic content
  liveRegion: (level: 'polite' | 'assertive' = 'polite'): AccessibilityProps => ({
    'aria-live': level,
    'aria-atomic': true
  })
};

// Accessibility audit function
export interface AccessibilityAuditResult {
  passed: boolean;
  issues: Array<{
    type: 'error' | 'warning';
    message: string;
    element?: string;
    suggestion?: string;
  }>;
  score: number;
}

export function auditElementAccessibility(element: HTMLElement): AccessibilityAuditResult {
  const issues: AccessibilityAuditResult['issues'] = [];
  let score = 100;

  // Check for missing alt text on images
  const images = element.querySelectorAll('img');
  images.forEach((img, index) => {
    if (!img.alt && !img.getAttribute('aria-label')) {
      issues.push({
        type: 'error',
        message: `Image ${index + 1} missing alt text`,
        element: `img[src="${img.src}"]`,
        suggestion: 'Add descriptive alt text or aria-label'
      });
      score -= 10;
    }
  });

  // Check for buttons without accessible names
  const buttons = element.querySelectorAll('button');
  buttons.forEach((button, index) => {
    const hasAccessibleName = [
      button.textContent?.trim(),
      button.getAttribute('aria-label'),
      button.getAttribute('aria-labelledby'),
    ].some((value) => typeof value === 'string' && value.trim().length > 0);

    if (!hasAccessibleName) {
      issues.push({
        type: 'error',
        message: `Button ${index + 1} missing accessible name`,
        element: button.outerHTML.substring(0, 50) + '...',
        suggestion: 'Add aria-label or visible text'
      });
      score -= 15;
    }
  });

  // Check for form inputs without labels
  const inputs = element.querySelectorAll('input, textarea, select');
  inputs.forEach((input, index) => {
    const hasAttributeLabel = [
      input.getAttribute('aria-label'),
      input.getAttribute('aria-labelledby'),
    ].some((value) => typeof value === 'string' && value.trim().length > 0);
    const hasAssociatedLabel =
      Boolean(input.id) && element.querySelector(`label[for="${input.id}"]`) !== null;
    if (!hasAttributeLabel && !hasAssociatedLabel) {
      issues.push({
        type: 'error',
        message: `Form input ${index + 1} missing label`,
        element: input.outerHTML.substring(0, 50) + '...',
        suggestion: 'Add aria-label, aria-labelledby, or associated label element'
      });
      score -= 12;
    }
  });

  // Check for heading hierarchy
  const headings = Array.from(element.querySelectorAll('h1, h2, h3, h4, h5, h6'));
  if (headings.length > 1) {
    let currentLevel = 0;
    headings.forEach((heading) => {
      const level = parseInt(heading.tagName.charAt(1));
      if (currentLevel > 0 && level > currentLevel + 1) {
        issues.push({
          type: 'warning',
          message: `Heading level skipped from h${currentLevel} to h${level}`,
          element: heading.outerHTML.substring(0, 50) + '...',
          suggestion: 'Use proper heading hierarchy without skipping levels'
        });
        score -= 5;
      }
      currentLevel = level;
    });
  }

  // Check for sufficient color contrast (simplified check)
  const textElements = element.querySelectorAll('p, span, div, button, a, label');
  textElements.forEach((textEl) => {
    const computedStyle = window.getComputedStyle(textEl);
    const color = computedStyle.color;
    const backgroundColor = computedStyle.backgroundColor;

    // Only check if we have both colors (simplified)
    if (color && backgroundColor && color !== 'rgba(0, 0, 0, 0)' && backgroundColor !== 'rgba(0, 0, 0, 0)') {
      // This is a simplified check - in production, you'd want more robust color parsing
      if (color === backgroundColor) {
        issues.push({
          type: 'warning',
          message: 'Potential color contrast issue detected',
          element: textEl.outerHTML.substring(0, 50) + '...',
          suggestion: 'Verify color contrast meets WCAG AA standards'
        });
        score -= 3;
      }
    }
  });

  return {
    passed: issues.filter(i => i.type === 'error').length === 0,
    issues,
    score: Math.max(0, score)
  };
}
