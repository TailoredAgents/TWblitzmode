import React from 'react';
import Image from 'next/image';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn, getInitials, generateGradient, formatScore } from '../../lib/utils';
import type { ConnectorWithContext } from '../../types';

const connectorBadgeVariants = cva(
  'relative inline-flex items-center justify-center rounded-full cursor-pointer transition-all duration-200 ease-apple font-medium',
  {
    variants: {
      size: {
        sm: 'w-8 h-8 text-xs',
        md: 'w-10 h-10 text-sm',
        lg: 'w-12 h-12 text-base',
      },
      variant: {
        default: 'bg-primary text-primary-foreground hover:scale-110 shadow-apple-sm hover:shadow-apple-md',
        gradient: 'text-white hover:scale-110 shadow-apple-sm hover:shadow-apple-md',
        glass: 'glass-card text-foreground hover:scale-105',
      },
    },
    defaultVariants: {
      size: 'md',
      variant: 'gradient',
    },
  }
);

const rankBadgeVariants = cva(
  'absolute flex items-center justify-center rounded-full bg-yellow-400 text-black text-xs font-bold border-2 border-white',
  {
    variants: {
      size: {
        sm: 'w-3 h-3 -top-0.5 -right-0.5 text-[8px]',
        md: 'w-4 h-4 -top-1 -right-1 text-[10px]',
        lg: 'w-5 h-5 -top-1 -right-1 text-xs',
      },
    },
    defaultVariants: {
      size: 'md',
    },
  }
);

interface ConnectorBadgeVariantProps extends VariantProps<typeof connectorBadgeVariants> {
  connector: ConnectorWithContext;
  rank: number;
  onClick?: () => void;
  showRank?: boolean;
  showTooltip?: boolean;
  className?: string;
}

const ConnectorBadge: React.FC<ConnectorBadgeVariantProps> = ({
  connector,
  rank,
  onClick,
  size = 'md',
  variant = 'gradient',
  showRank = true,
  showTooltip = false,
  className,
}) => {
  const initials = getInitials(connector.full_name);
  const gradientClass = variant === 'gradient' ? generateGradient(rank) : '';
  const score = connector.ranking_score ? formatScore(connector.ranking_score) : null;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onClick?.();
  };

  return (
    <div className="relative inline-block">
      <div
        className={cn(
          connectorBadgeVariants({ size, variant }),
          gradientClass,
          className
        )}
        onClick={handleClick}
        title={showTooltip ? `${connector.full_name} (Score: ${score}%)` : undefined}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onClick?.();
          }
        }}
      >
        {connector.profile_picture_url ? (
          <Image
            src={connector.profile_picture_url}
            alt={connector.full_name ?? 'Connector avatar'}
            fill
            className="rounded-full object-cover"
            sizes="48px"
            unoptimized
          />
        ) : (
          <span className="font-semibold">{initials}</span>
        )}
      </div>

      {showRank && rank <= 5 && (
        <div className={cn(rankBadgeVariants({ size }))}>
          {rank}
        </div>
      )}

      {/* Tooltip for additional info */}
      {showTooltip && (
        <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap z-50">
          <div className="font-semibold">{connector.full_name}</div>
          {connector.company && (
            <div className="text-gray-300">{connector.company}</div>
          )}
          {score && (
            <div className="text-green-400">Match: {score}%</div>
          )}
          {connector.connection_degree && (
            <div className="text-blue-400">
              {connector.connection_degree === 1 ? '1st' :
               connector.connection_degree === 2 ? '2nd' :
               `${connector.connection_degree}th`} connection
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ConnectorBadge;
