/**
 * Error Boundary Component for graceful error handling
 * Implements React error boundaries with accessibility and user experience best practices
 */

import React, { Component } from 'react';
import { AlertTriangle, RefreshCw, Home, Bug } from 'lucide-react';
import { announceToScreenReader } from '../lib/accessibility';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  showDetails?: boolean;
  className?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  isRetrying: boolean;
}

class ErrorBoundary extends Component<Props, State> {
  private retryAttempts: number = 0;
  private maxRetryAttempts: number = 3;

  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      isRetrying: false,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorInfo: null,
      isRetrying: false,
    };
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({
      error,
      errorInfo,
    });

    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // Log error to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('Error Boundary caught an error:', error, errorInfo);
    }

    // Announce error to screen readers
    announceToScreenReader(
      'An error occurred while loading this section. Please try refreshing or contact support if the problem persists.',
      'assertive'
    );

    // In production, log to error reporting service
    if (process.env.NODE_ENV === 'production') {
      this.logErrorToService(error, errorInfo);
    }
  }

  private logErrorToService = (error: Error, errorInfo: React.ErrorInfo) => {
    // Implement your error reporting service here
    // For example: Sentry, LogRocket, Datadog, etc.
    try {
      const errorData = {
        message: error.message,
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
        url: window.location.href,
      };

      // Send to error reporting service
      // Example: Sentry.captureException(error, { extra: errorData });
      console.warn('Error logged to reporting service:', errorData);
    } catch (loggingError) {
      console.error('Failed to log error to service:', loggingError);
    }
  };

  private handleRetry = async () => {
    if (this.retryAttempts >= this.maxRetryAttempts) {
      announceToScreenReader(
        'Maximum retry attempts reached. Please refresh the page or contact support.',
        'assertive'
      );
      return;
    }

    this.setState({ isRetrying: true });
    this.retryAttempts++;

    // Wait for a brief moment before retrying
    await new Promise(resolve => setTimeout(resolve, 1000));

    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      isRetrying: false,
    });

    announceToScreenReader('Retrying to load content.', 'polite');
  };

  private handleRefreshPage = () => {
    window.location.reload();
  };

  private handleGoHome = () => {
    window.location.href = '/';
  };

  override render() {
    if (this.state.hasError) {
      // If custom fallback is provided, use it
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const { error, errorInfo } = this.state;
      const canRetry = this.retryAttempts < this.maxRetryAttempts;

      return (
        <div
          className={`min-h-[400px] flex items-center justify-center p-6 ${this.props.className ?? ''}`}
          role="alert"
          aria-live="assertive"
        >
          <div className="max-w-md mx-auto text-center">
            {/* Error Icon */}
            <div className="mb-6">
              <div className="mx-auto w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-destructive" aria-hidden="true" />
              </div>
            </div>

            {/* Error Message */}
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-foreground mb-2">
                Something went wrong
              </h2>
              <p className="text-muted-foreground text-sm">
                We encountered an unexpected error while loading this section.
                {canRetry && ' You can try again or refresh the page.'}
              </p>
            </div>

            {/* Error Details (Development only) */}
            {this.props.showDetails && process.env.NODE_ENV === 'development' && error && (
              <details className="mb-6 text-left">
                <summary className="cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground">
                  <Bug className="inline w-4 h-4 mr-1" aria-hidden="true" />
                  Show Error Details
                </summary>
                <div className="mt-2 p-3 bg-muted rounded-lg text-xs font-mono text-left overflow-auto max-h-32">
                  <div className="mb-2">
                    <strong>Error:</strong> {error.message}
                  </div>
                  {errorInfo && (
                    <div>
                      <strong>Component Stack:</strong>
                      <pre className="whitespace-pre-wrap text-xs">
                        {errorInfo.componentStack}
                      </pre>
                    </div>
                  )}
                </div>
              </details>
            )}

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              {canRetry && (
                <button
                  onClick={this.handleRetry}
                  disabled={this.state.isRetrying}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  aria-label={this.state.isRetrying ? 'Retrying...' : 'Retry loading content'}
                >
                  <RefreshCw
                    className={`w-4 h-4 ${this.state.isRetrying ? 'animate-spin' : ''}`}
                    aria-hidden="true"
                  />
                  {this.state.isRetrying ? 'Retrying...' : 'Try Again'}
                </button>
              )}

              <button
                onClick={this.handleRefreshPage}
                className="inline-flex items-center gap-2 px-4 py-2 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/90 focus:outline-none focus:ring-2 focus:ring-secondary focus:ring-offset-2 transition-colors"
                aria-label="Refresh the entire page"
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
                Refresh Page
              </button>

              <button
                onClick={this.handleGoHome}
                className="inline-flex items-center gap-2 px-4 py-2 border border-border bg-background text-foreground rounded-lg hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 transition-colors"
                aria-label="Go to home page"
              >
                <Home className="w-4 h-4" aria-hidden="true" />
                Go Home
              </button>
            </div>

            {/* Retry Attempts Counter */}
            {this.retryAttempts > 0 && (
              <p className="mt-4 text-xs text-muted-foreground">
                Retry attempts: {this.retryAttempts}/{this.maxRetryAttempts}
              </p>
            )}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// Higher-order component for wrapping components with error boundary
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  errorBoundaryConfig?: {
    fallback?: React.ReactNode;
    onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
    showDetails?: boolean;
  }
) {
  const WrappedComponent = (props: P) => (
    <ErrorBoundary {...errorBoundaryConfig}>
      <Component {...props} />
    </ErrorBoundary>
  );

  const componentName =
    (typeof Component.displayName === 'string' && Component.displayName.trim().length > 0
      ? Component.displayName
      : undefined) ??
    Component.name ??
    'Component';

  WrappedComponent.displayName = `withErrorBoundary(${componentName})`;
  return WrappedComponent;
}

// Hook for programmatic error handling
export function useErrorHandler() {
  return (error: Error, errorInfo?: React.ErrorInfo) => {
    // This can be used to manually trigger error boundaries
    // or handle errors in event handlers, async operations, etc.
    console.error('Manual error handling:', error, errorInfo);

    // Announce to screen readers
    announceToScreenReader(
      'An error occurred. Please try again or contact support if the problem persists.',
      'assertive'
    );

    // In a real application, you might want to:
    // 1. Log to error reporting service
    // 2. Show a toast notification
    // 3. Redirect to an error page
    // 4. Clear problematic state
  };
}

export default ErrorBoundary;
