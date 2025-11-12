import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

const STATUS_COLOR_MAP = new Map<string, string>([
  ['pending_lookup', 'bg-gray-100 text-gray-800'],
  ['lookup_complete', 'bg-blue-100 text-blue-800'],
  ['mutuals_found', 'bg-emerald-100 text-emerald-700'],
  ['enriched', 'bg-green-100 text-green-800'],
  ['scheduled', 'bg-yellow-100 text-yellow-800'],
  ['contacted', 'bg-sky-100 text-sky-700'],
  ['low', 'bg-gray-100 text-gray-800'],
  ['medium', 'bg-blue-100 text-blue-800'],
  ['high', 'bg-orange-100 text-orange-800'],
  ['urgent', 'bg-red-100 text-red-800'],
]);

const PRIORITY_COLOR_MAP = new Map<string, string>([
  ['low', 'border-l-gray-400'],
  ['medium', 'border-l-blue-400'],
  ['high', 'border-l-orange-400'],
  ['urgent', 'border-l-red-400'],
]);

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date): string {
  const d = new Date(date);
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(d);
}

export function formatRelativeTime(date: string | Date): string {
  const d = new Date(date);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - d.getTime()) / 1000);

  if (diffInSeconds < 60) return 'just now';
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  if (diffInSeconds < 604800) return `${Math.floor(diffInSeconds / 86400)}d ago`;
  return formatDate(d);
}

export function getStatusColor(status: string): string {
  return STATUS_COLOR_MAP.get(status) ?? 'bg-gray-100 text-gray-800';
}

export function getPriorityColor(priority: string): string {
  return PRIORITY_COLOR_MAP.get(priority) ?? 'border-l-gray-400';
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength).trim() + '...';
}

export function getInitials(name: string): string {
  return name
    .split(' ')
    .map(part => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('');
}

export function generateGradient(rank: number): string {
  const gradients = [
    'bg-gradient-to-br from-[#111111] via-[#1F1F1F] to-[#FFD400]', // top performer
    'bg-gradient-to-br from-[#FFD400] to-[#111111]',               // high performer
    'bg-gradient-to-br from-[#FFE766] to-[#FFD400]',               // rising
    'bg-gradient-to-br from-[#111111] to-[#2A2A2A]',               // default
  ];

  if (rank === 1) return gradients[0] ?? gradients[3] ?? '';
  if (rank === 2) return gradients[1] ?? gradients[3] ?? '';
  if (rank === 3) return gradients[2] ?? gradients[3] ?? '';
  return gradients[3] ?? '';
}

export function formatScore(score: number): string {
  return Math.round(score * 100).toString();
}

export function debounce<TArgs extends unknown[], TResult>(
  func: (...args: TArgs) => TResult,
  wait: number
): (...args: TArgs) => void {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  return (...args: TArgs) => {
    if (timeout) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(() => func(...args), wait);
  };
}

export function throttle<TArgs extends unknown[], TResult>(
  func: (...args: TArgs) => TResult,
  limit: number
): (...args: TArgs) => void {
  let inThrottle = false;
  return (...args: TArgs) => {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

export function generateId(): string {
  return Math.random().toString(36).substring(2) + Date.now().toString(36);
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for older browsers
  const textArea = document.createElement('textarea');
  textArea.value = text;
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand('copy');
  } catch (err) {
    console.error('Unable to copy to clipboard', err);
  }
  document.body.removeChild(textArea);
  return Promise.resolve();
}

export function coerceNumericId(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function stringifyId(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toString();
  }
  return null;
}
