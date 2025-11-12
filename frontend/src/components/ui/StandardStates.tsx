// Standard UI States - Unified Loading and Error Components
// Production-ready loading and error state management

'use client';

// Re-export all loading skeleton components
export {
  Skeleton,
  CardSkeleton,
  ChartSkeleton,
  StatsCardSkeleton,
  TableRowSkeleton,
  NavSkeleton,
  TextSkeleton,
  FormSkeleton,
  DashboardSkeleton,
  ApprovalQueueSkeleton
} from './LoadingSkeleton';

// Re-export all error state components
export {
  ErrorState,
  NetworkError,
  PermissionError,
  ServerError,
  NotFoundError,
  DatabaseError,
  RateLimitError,
  ValidationError,
  SessionExpiredError,
  MaintenanceError,
  EmptyState,
  InlineError,
  SuccessState,
  OfflineState,
  LoadingError
} from './ErrorStates';

// Combined utility functions for common patterns
import React from 'react';
import { ErrorState } from './ErrorStates';
import { Skeleton } from './LoadingSkeleton';

interface StateManagerProps {
  loading: boolean;
  error?: string | null;
  empty?: boolean;
  children: React.ReactNode;
  loadingSkeleton?: React.ComponentType;
  emptyTitle?: string;
  emptyMessage?: string;
  onRetry?: () => void;
  className?: string;
}

// Unified State Manager Component
export const StateManager: React.FC<StateManagerProps> = ({
  loading,
  error,
  empty = false,
  children,
  loadingSkeleton: LoadingSkeleton = () => <Skeleton className="h-32 w-full" />,
  emptyTitle = "No data available",
  emptyMessage = "There's nothing to show right now.",
  onRetry,
  className
}) => {
  if (loading) {
    return <LoadingSkeleton />;
  }

  if (error) {
    return (
      <ErrorState
        title="Something went wrong"
        message={error}
        {...(onRetry && { onRetry })}
        {...(className && { className })}
      />
    );
  }

  if (empty) {
    return (
      <ErrorState
        title={emptyTitle}
        message={emptyMessage}
        severity="info"
        showRetry={false}
        {...(className && { className })}
      />
    );
  }

  return <>{children}</>;
};

// Hook for common state patterns
export const useStandardStates = () => {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleAsync = React.useCallback(async (
    asyncFn: () => Promise<void>,
    options?: {
      onSuccess?: () => void;
      onError?: (error: Error) => void;
      loadingDelay?: number;
    }
  ) => {
    const { onSuccess, onError, loadingDelay = 0 } = options ?? {};

    try {
      setError(null);

      if (loadingDelay > 0) {
        setTimeout(() => setLoading(true), loadingDelay);
      } else {
        setLoading(true);
      }

      await asyncFn();
      onSuccess?.();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
      setError(errorMessage);
      onError?.(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  const clearError = React.useCallback(() => setError(null), []);
  const clearAll = React.useCallback(() => {
    setLoading(false);
    setError(null);
  }, []);

  return {
    loading,
    error,
    setLoading,
    setError,
    handleAsync,
    clearError,
    clearAll
  };
};

// Common state patterns as ready-to-use components
interface LoadingWrapperProps {
  loading: boolean;
  children: React.ReactNode;
  skeleton?: React.ComponentType;
}

export const LoadingWrapper: React.FC<LoadingWrapperProps> = ({
  loading,
  children,
  skeleton: Skeleton = () => <div className="animate-pulse bg-muted/30 rounded h-8 w-full" />
}) => {
  if (loading) return <Skeleton />;
  return <>{children}</>;
};

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ComponentType<{ error: Error }>;
}

// Error Boundary Component
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  override render() {
    if (this.state.hasError) {
      const FallbackComponent = this.props.fallback;
      const fallbackMessage =
        this.state.error?.message && this.state.error.message.trim().length > 0
          ? this.state.error.message
          : 'An unexpected error occurred in the application.';

      if (FallbackComponent && this.state.error) {
        return <FallbackComponent error={this.state.error} />;
      }

      return (
        <ErrorState
          title="Application Error"
          message={fallbackMessage}
          onRetry={() => this.setState({ hasError: false })}
          retryLabel="Reload"
        />
      );
    }

    return this.props.children;
  }
}
