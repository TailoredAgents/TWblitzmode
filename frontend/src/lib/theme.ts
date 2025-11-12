/**
 * Dark Mode Theme System
 * Provides comprehensive theme management with accessibility support
 */

import React, { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { announceToScreenReader } from './accessibility';

// Theme types
export type ThemeMode = 'light' | 'dark' | 'system';
export type ActualTheme = 'light' | 'dark';

// Theme configuration
export interface ThemeConfig {
  mode: ThemeMode;
  actualTheme: ActualTheme;
  systemPreference: ActualTheme;
  isSystemTheme: boolean;
}

// Theme context
export interface ThemeContextType {
  config: ThemeConfig;
  setTheme: (mode: ThemeMode) => void;
  toggleTheme: () => void;
  isLoading: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Theme storage key
const THEME_STORAGE_KEY = 'vouchlink-theme';

// Default theme configuration
const defaultThemeConfig: ThemeConfig = {
  mode: 'system',
  actualTheme: 'light',
  systemPreference: 'light',
  isSystemTheme: true
};

// Theme manager class
export class ThemeManager {
  private static instance: ThemeManager;
  private config: ThemeConfig = defaultThemeConfig;
  private listeners: Array<(config: ThemeConfig) => void> = [];
  private mediaQuery: MediaQueryList | null = null;

  static getInstance(): ThemeManager {
    if (!ThemeManager.instance) {
      ThemeManager.instance = new ThemeManager();
    }
    return ThemeManager.instance;
  }

  constructor() {
    if (typeof window !== 'undefined') {
      this.initialize();
    }
  }

  private initialize(): void {
    this.mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    this.mediaQuery.addEventListener('change', this.handleSystemThemeChange);
    this.loadTheme();
    this.applyTheme();
  }

  private loadTheme(): void {
    try {
      const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
      const systemPreference: ActualTheme = this.mediaQuery?.matches ? 'dark' : 'light';

      if (savedTheme && ['light', 'dark', 'system'].includes(savedTheme)) {
        const mode = savedTheme as ThemeMode;
        this.config = {
          mode,
          actualTheme: mode === 'system' ? systemPreference : (mode as ActualTheme),
          systemPreference,
          isSystemTheme: mode === 'system'
        };
      } else {
        this.config = {
          mode: 'system',
          actualTheme: systemPreference,
          systemPreference,
          isSystemTheme: true
        };
      }
    } catch (error) {
      console.warn('Failed to load theme from localStorage:', error);
      this.config = {
        ...defaultThemeConfig,
        systemPreference: this.mediaQuery?.matches ? 'dark' : 'light',
        actualTheme: this.mediaQuery?.matches ? 'dark' : 'light'
      };
    }
  }

  private saveTheme(): void {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, this.config.mode);
    } catch (error) {
      console.warn('Failed to save theme to localStorage:', error);
    }
  }

  private applyTheme(): void {
    const { actualTheme } = this.config;

    if (actualTheme === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    } else {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    }

    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
      metaThemeColor.setAttribute(
        'content',
        actualTheme === 'dark' ? '#1a1a1a' : '#ffffff'
      );
    }

    this.listeners.forEach(listener => listener(this.config));
  }

  private handleSystemThemeChange = (event: MediaQueryListEvent): void => {
    const systemPreference: ActualTheme = event.matches ? 'dark' : 'light';

    this.config = {
      ...this.config,
      systemPreference,
      actualTheme: this.config.isSystemTheme ? systemPreference : this.config.actualTheme
    };

    if (this.config.isSystemTheme) {
      this.applyTheme();
      announceToScreenReader(
        `Theme automatically changed to ${systemPreference} mode based on system preference`,
        'polite'
      );
    }
  };

  setTheme(mode: ThemeMode): void {
    const systemPreference = this.mediaQuery?.matches ? 'dark' : 'light';
    const actualTheme: ActualTheme = mode === 'system' ? systemPreference : (mode as ActualTheme);
    const isSystemTheme = mode === 'system';

    this.config = {
      mode,
      actualTheme,
      systemPreference,
      isSystemTheme
    };

    this.saveTheme();
    this.applyTheme();

    const themeDescription = isSystemTheme
      ? `system preference (currently ${actualTheme})`
      : actualTheme;
    announceToScreenReader(`Theme changed to ${themeDescription} mode`, 'polite');
  }

  toggleTheme(): void {
    const { mode } = this.config;
    let newMode: ThemeMode;

    if (mode === 'system') {
      newMode = 'light';
    } else if (mode === 'light') {
      newMode = 'dark';
    } else {
      newMode = 'system';
    }

    this.setTheme(newMode);
  }

  getConfig(): ThemeConfig {
    return { ...this.config };
  }

  subscribe(listener: (config: ThemeConfig) => void): () => void {
    this.listeners.push(listener);
    return () => {
      const index = this.listeners.indexOf(listener);
      if (index > -1) {
        this.listeners.splice(index, 1);
      }
    };
  }

  destroy(): void {
    if (this.mediaQuery) {
      this.mediaQuery.removeEventListener('change', this.handleSystemThemeChange);
    }
    this.listeners = [];
  }
}

export const themeManager = ThemeManager.getInstance();

// Theme provider component
interface ThemeProviderProps {
  children: ReactNode;
  defaultTheme?: ThemeMode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [config, setConfig] = useState<ThemeConfig>(defaultThemeConfig);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = themeManager.subscribe(setConfig);
    setConfig(themeManager.getConfig());
    setIsLoading(false);
    return unsubscribe;
  }, []);

  const contextValue: ThemeContextType = {
    config,
    setTheme: themeManager.setTheme.bind(themeManager),
    toggleTheme: themeManager.toggleTheme.bind(themeManager),
    isLoading
  };

  return React.createElement(
    ThemeContext.Provider,
    { value: contextValue },
    children
  );
}

// Theme hook
export function useTheme(): ThemeContextType {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

// Theme utilities
export const ThemeUtils = {
  isDark: (theme: ActualTheme): boolean => theme === 'dark',
  isLight: (theme: ActualTheme): boolean => theme === 'light',
  getThemedColor: (lightColor: string, darkColor: string, theme: ActualTheme): string =>
    theme === 'dark' ? darkColor : lightColor,
  getThemeClass: (theme: ActualTheme): string => theme,
  getThemeIcon: (mode: ThemeMode): string => {
    switch (mode) {
      case 'light': return 'sun';
      case 'dark': return 'moon';
      case 'system': return 'monitor';
      default: return 'monitor';
    }
  },
  getThemeDisplayName: (mode: ThemeMode): string => {
    switch (mode) {
      case 'light': return 'Light';
      case 'dark': return 'Dark';
      case 'system': return 'System';
      default: return 'System';
    }
  }
};

// Hook for theme-aware styling
export function useThemedStyles() {
  const { config } = useTheme();
  const { actualTheme } = config;

  return {
    theme: actualTheme,
    isDark: ThemeUtils.isDark(actualTheme),
    isLight: ThemeUtils.isLight(actualTheme),
    getColor: (lightColor: string, darkColor: string) =>
      ThemeUtils.getThemedColor(lightColor, darkColor, actualTheme)
  };
}
