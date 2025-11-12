'use client';

import React, { createContext, useContext, useState, useCallback } from 'react';
import Toast, { type ToastProps } from './Toast';
import { cn } from '../../lib/utils';

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastProps['variant'];
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
  dismissible?: boolean;
}

interface ToastContextType {
  addToast: (options: ToastOptions) => string;
  removeToast: (id: string) => void;
  removeAllToasts: () => void;
  toasts: Array<ToastProps & { id: string }>;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

interface ToastProviderProps {
  children: React.ReactNode;
  maxToasts?: number;
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' | 'top-center' | 'bottom-center';
}

export const ToastProvider: React.FC<ToastProviderProps> = ({
  children,
  maxToasts = 5,
  position = 'top-right',
}) => {
  const [toasts, setToasts] = useState<Array<ToastProps & { id: string }>>([]);

  const generateId = () => `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

  const addToast = useCallback((options: ToastOptions) => {
    const id = generateId();
    const toast: ToastProps & { id: string } = {
      id,
      ...options,
    };

    setToasts(prevToasts => {
      const newToasts = [toast, ...prevToasts];
      // Limit the number of toasts
      return newToasts.slice(0, maxToasts);
    });

    return id;
  }, [maxToasts]);

  const removeToast = useCallback((id: string) => {
    setToasts(prevToasts => prevToasts.filter(toast => toast.id !== id));
  }, []);

  const removeAllToasts = useCallback(() => {
    setToasts([]);
  }, []);

  const getPositionClasses = () => {
    switch (position) {
      case 'top-left':
        return 'top-4 left-4';
      case 'top-center':
        return 'top-4 left-1/2 -translate-x-1/2';
      case 'top-right':
        return 'top-4 right-4';
      case 'bottom-left':
        return 'bottom-4 left-4';
      case 'bottom-center':
        return 'bottom-4 left-1/2 -translate-x-1/2';
      case 'bottom-right':
        return 'bottom-4 right-4';
      default:
        return 'top-4 right-4';
    }
  };

  return (
    <ToastContext.Provider value={{ addToast, removeToast, removeAllToasts, toasts }}>
      {children}

      {/* Toast Container */}
      <div
        className={cn(
          'fixed z-[100] flex flex-col gap-2 pointer-events-none',
          getPositionClasses()
        )}
      >
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <Toast
              {...toast}
              onDismiss={() => removeToast(toast.id)}
            />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

// Convenience hook for common toast types
export const useToastActions = () => {
  const { addToast } = useToast();

  const success = (title: string, description?: string, options?: Partial<ToastOptions>) =>
    addToast({ title, ...(description && { description }), variant: 'success', ...options });

  const error = (title: string, description?: string, options?: Partial<ToastOptions>) =>
    addToast({ title, ...(description && { description }), variant: 'error', ...options });

  const warning = (title: string, description?: string, options?: Partial<ToastOptions>) =>
    addToast({ title, ...(description && { description }), variant: 'warning', ...options });

  const info = (title: string, description?: string, options?: Partial<ToastOptions>) =>
    addToast({ title, ...(description && { description }), variant: 'info', ...options });

  return { success, error, warning, info, addToast };
};

export default ToastProvider;
