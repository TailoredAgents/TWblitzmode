'use client';

import React from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';
import { useTheme } from '../../contexts/ThemeContext';

const themeToggleVariants = cva(
  'relative inline-flex items-center justify-center rounded-lg transition-all duration-200 hover:scale-105 active:scale-95',
  {
    variants: {
      variant: {
        default: 'p-2 bg-background/80 hover:bg-muted/50 border border-border/20',
        glass: 'p-2 bg-white/10 hover:bg-white/20 backdrop-blur-sm border border-white/20',
        minimal: 'p-2 hover:bg-muted/30',
      },
      size: {
        sm: 'w-8 h-8',
        md: 'w-10 h-10',
        lg: 'w-12 h-12',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
);

const iconVariants = cva('transition-all duration-200', {
  variants: {
    size: {
      sm: 'w-4 h-4',
      md: 'w-5 h-5',
      lg: 'w-6 h-6',
    },
  },
  defaultVariants: {
    size: 'md',
  },
});

interface ThemeToggleProps extends VariantProps<typeof themeToggleVariants> {
  showLabel?: boolean;
  className?: string;
}

const ThemeToggle: React.FC<ThemeToggleProps> = ({
  variant = 'default',
  size = 'md',
  showLabel = false,
  className,
}) => {
  const { theme, setTheme } = useTheme();

  const getThemeIcon = () => {
    switch (theme) {
      case 'light':
        return <Sun className={cn(iconVariants({ size }), 'text-yellow-600')} />;
      case 'dark':
        return <Moon className={cn(iconVariants({ size }), 'text-blue-400')} />;
      case 'system':
        return <Monitor className={cn(iconVariants({ size }), 'text-primary')} />;
      default:
        return <Monitor className={cn(iconVariants({ size }))} />;
    }
  };

  const getThemeLabel = () => {
    switch (theme) {
      case 'light':
        return 'Light';
      case 'dark':
        return 'Dark';
      case 'system':
        return 'System';
      default:
        return 'Auto';
    }
  };

  const cycleTheme = () => {
    const themes = ['light', 'dark', 'system'] as const;
    const currentIndex = themes.indexOf(theme);
    const nextIndex = (currentIndex + 1) % themes.length;
    const nextTheme = themes.at(nextIndex) ?? 'light';
    setTheme(nextTheme);
  };

  return (
    <button
      onClick={cycleTheme}
      className={cn(themeToggleVariants({ variant, size }), className)}
      title={`Switch to ${theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light'} mode`}
      aria-label={`Current theme: ${getThemeLabel()}. Click to cycle themes.`}
    >
      <div className="flex items-center gap-2">
        {getThemeIcon()}
        {showLabel && (
          <span className="text-sm font-medium text-foreground">
            {getThemeLabel()}
          </span>
        )}
      </div>

      {/* Subtle animation indicator */}
      <div className="absolute inset-0 rounded-lg bg-gradient-to-r from-transparent via-white/5 to-transparent opacity-0 hover:opacity-100 transition-opacity duration-300 pointer-events-none" />
    </button>
  );
};

export default ThemeToggle;
