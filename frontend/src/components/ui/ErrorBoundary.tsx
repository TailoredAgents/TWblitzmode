'use client';

import React, { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import GlassCard from './GlassCard';

interface Props {
  children: React.ReactNode;
  fallbackComponent?: React.ComponentType<{ error: Error; retry: () => void }>;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  context?: string;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorId: string;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, errorId: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorId: Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
    };
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error for debugging and monitoring
    console.error('[ErrorBoundary] Component error caught:', {
      error: error.message,
      stack: error.stack,
      errorInfo,
      context: this.props.context,
      errorId: this.state.errorId,
      timestamp: new Date().toISOString()
    });

    // Call optional error handler
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // In production, you might want to send this to an error reporting service
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
      // Report to monitoring service (Sentry, LogRocket, etc.)
      console.warn('[ErrorBoundary] Production error reported:', {
        message: error.message,
        context: this.props.context,
        errorId: this.state.errorId
      });
    }
  }

  retry = () => {
    this.setState({ hasError: false, errorId: '' });
  };

  override render() {
    if (this.state.hasError) {
      // Render custom fallback component if provided
      if (this.props.fallbackComponent) {
        const FallbackComponent = this.props.fallbackComponent;
        const fallbackError = this.state.error ?? new Error('Unknown error');
        return <FallbackComponent error={fallbackError} retry={this.retry} />;
      }

      // Default error UI
      return (
        <div className="min-h-screen bg-background flex items-center justify-center p-4">
          <GlassCard className="max-w-md w-full p-6 text-center">
            <div className="flex justify-center mb-4">
              <AlertTriangle className="w-12 h-12 text-amber-500" />
            </div>
            <h2 className="text-lg font-semibold text-foreground mb-2">
              Oops! Something went wrong
            </h2>
            <p className="text-muted-foreground mb-4 text-sm">
              {this.props.context
                ? `An error occurred in the ${this.props.context}. Please try again or contact support if the problem persists.`
                : 'An unexpected error occurred. Please try again or contact support if the problem persists.'
              }
            </p>
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-3 mb-4 text-left">
                <p className="text-xs font-mono text-destructive">
                  {this.state.error.message}
                </p>
              </div>
            )}
            <div className="space-y-2">
              <button
                onClick={this.retry}
                className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Try Again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="w-full px-4 py-2 border border-border rounded-lg text-muted-foreground hover:bg-muted/50 transition-colors text-sm"
              >
                Reload Page
              </button>
            </div>
            <p className="text-xs text-muted-foreground mt-4">
              Error ID: {this.state.errorId}
            </p>
          </GlassCard>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
