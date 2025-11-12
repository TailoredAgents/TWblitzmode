// Error State Components - Consistent Error UI Patterns
// Standardized error states for production-ready error handling

'use client';

import React from 'react';
import {
  AlertCircle,
  WifiOff,
  Shield,
  RefreshCw,
  XCircle,
  AlertTriangle,
  FileX,
  Database,
  Server,
  EyeOff,
  Clock,
  Ban,
  Search,
  Zap
} from 'lucide-react';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';

interface BaseErrorProps {
  className?: string;
  onRetry?: () => void;
  retryLabel?: string;
  retryLoading?: boolean;
}

type ErrorIconComponent = React.ComponentType<{ className?: string }>;

interface ErrorStateProps extends BaseErrorProps {
  title?: string;
  message?: string;
  icon?: ErrorIconComponent;
  severity?: 'error' | 'warning' | 'info';
  showRetry?: boolean;
  children?: React.ReactNode;
}

type ErrorSeverity = NonNullable<ErrorStateProps['severity']>;

interface SeverityStyle {
  icon: string;
  bg: string;
  title: string;
  message: string;
  button: string;
}

const SEVERITY_STYLE_MAP = new Map<ErrorSeverity, SeverityStyle>([
  [
    'error',
    {
      icon: 'text-red-500',
      bg: 'bg-red-50 border-red-200',
      title: 'text-red-900',
      message: 'text-red-700',
      button: 'bg-red-600 hover:bg-red-700 text-white'
    }
  ],
  [
    'warning',
    {
      icon: 'text-yellow-500',
      bg: 'bg-yellow-50 border-yellow-200',
      title: 'text-yellow-900',
      message: 'text-yellow-700',
      button: 'bg-yellow-600 hover:bg-yellow-700 text-white'
    }
  ],
  [
    'info',
    {
      icon: 'text-blue-500',
      bg: 'bg-blue-50 border-blue-200',
      title: 'text-blue-900',
      message: 'text-blue-700',
      button: 'bg-blue-600 hover:bg-blue-700 text-white'
    }
  ]
]);

// Generic Error State Component
export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Something went wrong',
  message = 'An unexpected error occurred. Please try again.',
  icon: Icon = AlertCircle,
  severity = 'error',
  showRetry = true,
  onRetry,
  retryLabel = 'Try again',
  retryLoading = false,
  className,
  children
}) => {
  const styles = SEVERITY_STYLE_MAP.get(severity) ?? SEVERITY_STYLE_MAP.get('error');

  if (!styles) {
    return null;
  }

  return (
    <GlassCard className={cn("p-8 text-center", className)}>
      <div className="flex flex-col items-center space-y-4">
        <div className={cn("w-16 h-16 rounded-full border-2 flex items-center justify-center", styles.bg)}>
          <Icon className={cn("w-8 h-8", styles.icon)} />
        </div>

        <div className="space-y-2">
          <h3 className={cn("text-lg font-semibold", styles.title)}>
            {title}
          </h3>
          <p className={cn("text-sm max-w-md", styles.message)}>
            {message}
          </p>
        </div>

        {children}

        {showRetry && onRetry && (
          <button
            onClick={onRetry}
            disabled={retryLoading}
            className={cn(
              "inline-flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
              styles.button
            )}
          >
            {retryLoading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {retryLabel}
          </button>
        )}
      </div>
    </GlassCard>
  );
};

// Network Connection Error
export const NetworkError: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="Connection Problem"
    message="Unable to connect to our servers. Please check your internet connection and try again."
    icon={WifiOff}
    severity="error"
    {...props}
  />
);

// Authentication/Permission Error
export const PermissionError: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="Access Denied"
    message="You don't have permission to access this resource. Please contact your administrator."
    icon={Shield}
    severity="warning"
    showRetry={false}
    {...props}
  />
);

// Server Error (5xx)
export const ServerError: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="Server Error"
    message="Our servers are experiencing issues. Please try again in a few moments."
    icon={Server}
    severity="error"
    {...props}
  />
);

// Data Not Found Error
export const NotFoundError: React.FC<BaseErrorProps & { resource?: string }> = ({
  resource = "content",
  ...props
}) => (
  <ErrorState
    title={`${resource.charAt(0).toUpperCase() + resource.slice(1)} Not Found`}
    message={`The ${resource} you're looking for doesn't exist or has been removed.`}
    icon={FileX}
    severity="info"
    showRetry={false}
    {...props}
  />
);

// Database/API Error
export const DatabaseError: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="Data Unavailable"
    message="We're having trouble loading your data. This may be a temporary issue."
    icon={Database}
    severity="error"
    {...props}
  />
);

// Rate Limit Error
export const RateLimitError: React.FC<BaseErrorProps & { retryAfter?: number }> = ({
  retryAfter,
  ...props
}) => (
  <ErrorState
    title="Too Many Requests"
    message={`You've made too many requests. ${retryAfter ? `Please wait ${retryAfter} seconds before trying again.` : 'Please wait a moment before trying again.'}`}
    icon={Clock}
    severity="warning"
    {...props}
  />
);

// Validation Error
export const ValidationError: React.FC<BaseErrorProps & { errors?: string[] }> = ({
  errors = [],
  ...props
}) => (
  <ErrorState
    title="Invalid Input"
    message="Please correct the following errors and try again."
    icon={AlertTriangle}
    severity="warning"
    showRetry={false}
    {...props}
  >
    {errors.length > 0 && (
      <div className="text-left">
        <ul className="text-sm text-red-700 space-y-1">
          {errors.map((error, index) => (
            <li key={index} className="flex items-start gap-2">
              <XCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
              {error}
            </li>
          ))}
        </ul>
      </div>
    )}
  </ErrorState>
);

// Session Expired Error
export const SessionExpiredError: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="Session Expired"
    message="Your session has expired. Please sign in again to continue."
    icon={EyeOff}
    severity="warning"
    retryLabel="Sign In"
    {...props}
  />
);

// Maintenance Mode Error
export const MaintenanceError: React.FC<BaseErrorProps & { estimatedTime?: string }> = ({
  estimatedTime,
  ...props
}) => (
  <ErrorState
    title="Maintenance in Progress"
    message={`We're performing scheduled maintenance. ${estimatedTime ? `Expected completion: ${estimatedTime}` : 'Please check back shortly.'}`}
    icon={Ban}
    severity="info"
    retryLabel="Check Status"
    {...props}
  />
);

// Empty State with Error Context
interface EmptyStateProps extends BaseErrorProps {
  title?: string;
  message?: string;
  icon?: ErrorIconComponent;
  actionLabel?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'No data available',
  message = 'There\'s nothing to show right now.',
  icon: Icon = Search,
  actionLabel,
  onAction,
  className
}) => (
  <GlassCard className={cn("p-8 text-center", className)}>
    <div className="flex flex-col items-center space-y-4">
      <div className="w-16 h-16 rounded-full bg-gray-50 border-2 border-gray-200 flex items-center justify-center">
        <Icon className="w-8 h-8 text-gray-400" />
      </div>

      <div className="space-y-2">
        <h3 className="text-lg font-semibold text-gray-900">
          {title}
        </h3>
        <p className="text-sm text-gray-600 max-w-md">
          {message}
        </p>
      </div>

      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 font-medium transition-colors"
        >
          {actionLabel}
        </button>
      )}
    </div>
  </GlassCard>
);

// Inline Error Message (for forms/components)
interface InlineErrorProps {
  message: string;
  className?: string;
  icon?: boolean;
}

export const InlineError: React.FC<InlineErrorProps> = ({
  message,
  className,
  icon = true
}) => (
  <div className={cn("flex items-center gap-2 text-sm text-red-600", className)}>
    {icon && <AlertCircle className="w-4 h-4 flex-shrink-0" />}
    <span>{message}</span>
  </div>
);

// Success State (for consistency)
export const SuccessState: React.FC<{
  title?: string;
  message?: string;
  onContinue?: () => void;
  continueLabel?: string;
  className?: string;
}> = ({
  title = 'Success!',
  message = 'Operation completed successfully.',
  onContinue,
  continueLabel = 'Continue',
  className
}) => (
  <ErrorState
    title={title}
    message={message}
    icon={Zap}
    severity="info"
    showRetry={!!onContinue}
    {...(onContinue && { onRetry: onContinue })}
    retryLabel={continueLabel}
    {...(className && { className })}
  />
);

// Offline State
export const OfflineState: React.FC<BaseErrorProps> = (props) => (
  <ErrorState
    title="You're Offline"
    message="Please check your internet connection. Some features may be limited."
    icon={WifiOff}
    severity="warning"
    retryLabel="Retry Connection"
    {...props}
  />
);

// Loading Error (when data fails to load)
export const LoadingError: React.FC<BaseErrorProps & { resource?: string }> = ({
  resource = "data",
  ...props
}) => (
  <ErrorState
    title={`Failed to Load ${resource.charAt(0).toUpperCase() + resource.slice(1)}`}
    message={`We couldn't load the ${resource}. Please try again.`}
    icon={RefreshCw}
    severity="error"
    {...props}
  />
);
