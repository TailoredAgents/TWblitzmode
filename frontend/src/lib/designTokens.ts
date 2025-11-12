/**
 * Helpers for reading design tokens that are declared as CSS variables.
 * These allow runtime code (charts, canvases) to stay in sync with the design system
 * while still rendering sensible defaults during SSR.
 */

const DEFAULT_TOKENS = {
  '--primary': '#FFD400',
  '--primary-foreground': '#111111',
  '--muted-foreground': '#5C5C5C',
  '--chart-1': '#FFD400',
  '--chart-2': '#111111',
  '--chart-3': '#FFE766',
  '--chart-4': '#B38F00',
  '--chart-5': '#333333',
} as const;

const DEFAULT_TOKEN_MAP = new Map<DesignTokenKey, string>(
  Object.entries(DEFAULT_TOKENS) as Array<[DesignTokenKey, string]>
);

export type DesignTokenKey = keyof typeof DEFAULT_TOKENS;

export const CHART_TOKENS: DesignTokenKey[] = [
  '--chart-1',
  '--chart-2',
  '--chart-3',
  '--chart-4',
  '--chart-5',
];

const readCssVariable = (token: DesignTokenKey): string | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  const computed = getComputedStyle(document.documentElement).getPropertyValue(token);
  if (computed && computed.trim().length > 0) {
    return computed.trim();
  }

  return null;
};

export const getDesignTokenValue = (token: DesignTokenKey, fallback?: string): string => {
  const value = readCssVariable(token);
  if (value) {
    return value;
  }
  if (fallback) {
    return fallback;
  }
  return DEFAULT_TOKEN_MAP.get(token) ?? DEFAULT_TOKENS['--primary'];
};

export const getChartPalette = (): string[] => {
  return CHART_TOKENS.map((token) => getDesignTokenValue(token));
};
