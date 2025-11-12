'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { CheckCircle, XCircle, AlertCircle, Info, X } from 'lucide-react';
import { cn } from '../../lib/utils';

const toastVariants = cva(
  'relative flex items-start gap-3 p-4 rounded-xl backdrop-blur-xl border shadow-apple-lg transition-all duration-300 ease-out max-w-md',
  {
    variants: {
      variant: {
        success: 'bg-green-50/90 border-green-200/50 text-green-900',
        error: 'bg-red-50/90 border-red-200/50 text-red-900',
        warning: 'bg-yellow-50/90 border-yellow-200/50 text-yellow-900',
        info: 'bg-blue-50/90 border-blue-200/50 text-blue-900',
        default: 'bg-white/90 border-gray-200/50 text-gray-900',
      },
      animation: {
        enter: 'animate-slide-in-from-right-full',
        exit: 'animate-slide-out-to-right-full',
      },
    },
    defaultVariants: {
      variant: 'default',
      animation: 'enter',
    },
  }
);

const iconVariants = cva('flex-shrink-0 w-5 h-5', {
  variants: {
    variant: {
      success: 'text-green-600',
      error: 'text-red-600',
      warning: 'text-yellow-600',
      info: 'text-blue-600',
      default: 'text-gray-600',
    },
  },
  defaultVariants: {
    variant: 'default',
  },
});

export interface ToastProps extends VariantProps<typeof toastVariants> {
  id: string;
  title: string;
  description?: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
  onDismiss?: () => void;
  dismissible?: boolean;
}

const Toast: React.FC<ToastProps> = ({
  id,
  title,
  description,
  variant = 'default',
  duration = 5000,
  action,
  onDismiss,
  dismissible = true,
}) => {
  const [isVisible, setIsVisible] = useState(true);
  const [animationState, setAnimationState] = useState<'enter' | 'exit'>('enter');

  const handleDismiss = useCallback(() => {
    setAnimationState('exit');
    setTimeout(() => {
      setIsVisible(false);
      onDismiss?.();
    }, 200);
  }, [onDismiss]);

  useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(() => {
        handleDismiss();
      }, duration);

      return () => clearTimeout(timer);
    }
    return undefined;
  }, [duration, handleDismiss]);

  const getIcon = () => {
    switch (variant) {
      case 'success':
        return <CheckCircle className={cn(iconVariants({ variant }))} />;
      case 'error':
        return <XCircle className={cn(iconVariants({ variant }))} />;
      case 'warning':
        return <AlertCircle className={cn(iconVariants({ variant }))} />;
      case 'info':
        return <Info className={cn(iconVariants({ variant }))} />;
      default:
        return <Info className={cn(iconVariants({ variant }))} />;
    }
  };

  if (!isVisible) return null;

  return (
    <div
      className={cn(toastVariants({ variant, animation: animationState }))}
      role="alert"
      aria-live="polite"
      data-toast-id={id}
    >
      {getIcon()}

      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm leading-tight">{title}</div>
        {description && (
          <div className="mt-1 text-sm opacity-90 leading-relaxed">{description}</div>
        )}

        {action && (
          <button
            onClick={action.onClick}
            className="mt-2 text-sm font-medium underline hover:no-underline transition-all"
          >
            {action.label}
          </button>
        )}
      </div>

      {dismissible && (
        <button
          onClick={handleDismiss}
          className="flex-shrink-0 p-1 rounded-lg hover:bg-black/5 transition-colors"
          aria-label="Dismiss notification"
        >
          <X className="w-4 h-4 opacity-60" />
        </button>
      )}

      {/* Progress bar for timed toasts */}
      {duration > 0 && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/10 rounded-b-xl overflow-hidden">
          <div
            className="h-full bg-current opacity-30 transition-all ease-linear"
            style={{
              animation: `toast-shrink ${duration}ms linear forwards`,
            }}
          />
        </div>
      )}

      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes toast-shrink {
              from { width: 100%; }
              to { width: 0%; }
            }
          `
        }}
      />
    </div>
  );
};

export default Toast;
