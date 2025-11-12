import React from 'react';
import { Loader2, Users, Filter } from 'lucide-react';
import ProspectCard from './ProspectCard';
import GlassCard from './GlassCard';
import { CardSkeleton } from './LoadingSkeleton';
import { cn } from '../../lib/utils';
import type { ProspectWithConnectors, ConnectorWithContext, ProspectFilters } from '../../types';

interface ProspectsGridProps {
  prospects: ProspectWithConnectors[];
  loading?: boolean;
  onProspectSelect?: (prospect: ProspectWithConnectors) => void;
  onConnectorSelect?: (connector: ConnectorWithContext, prospect: ProspectWithConnectors) => void;
  filters?: ProspectFilters;
  onFiltersChange?: (filters: ProspectFilters) => void;
  className?: string;
  emptyStateTitle?: string;
  emptyStateDescription?: string;
}

const ProspectsGrid: React.FC<ProspectsGridProps> = ({
  prospects,
  loading = false,
  onProspectSelect,
  onConnectorSelect,
  filters,
  onFiltersChange,
  className,
  emptyStateTitle = 'No prospects found',
  emptyStateDescription = 'Try adjusting your filters or import new prospects to get started.',
}) => {
  const GRID_LAYOUT_CLASSES = 'grid gap-6 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 auto-rows-fr';

  const handleConnectorSelect = (connector: ConnectorWithContext, prospect: ProspectWithConnectors) => {
    onConnectorSelect?.(connector, prospect);
  };

  // Loading skeleton
  if (loading) {
    return (
      <div className={cn('space-y-6', className)}>
        {/* Loading indicator */}
        <div className="flex items-center justify-center py-8">
          <div className="flex items-center gap-3 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Loading prospects...</span>
          </div>
        </div>

        {/* Loading skeleton grid */}
        <div className={GRID_LAYOUT_CLASSES}>
          {Array.from({ length: 6 }).map((_, index) => (
            <CardSkeleton key={index} />
          ))}
        </div>
      </div>
    );
  }

  // Empty state
  if (!prospects.length) {
    return (
      <div className={cn('space-y-6', className)}>
        <GlassCard className="text-center py-16">
          <div className="max-w-md mx-auto">
            <div className="w-16 h-16 bg-muted/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <Users className="w-8 h-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-semibold text-foreground mb-2">
              {emptyStateTitle}
            </h3>
            <p className="text-muted-foreground mb-6">
              {emptyStateDescription}
            </p>
            {filters && (
              <button
                onClick={() => onFiltersChange?.({})}
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Filter className="w-4 h-4" />
                Clear Filters
              </button>
            )}
          </div>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Results summary */}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {prospects.length} prospect{prospects.length !== 1 ? 's' : ''} found
        </span>
        {filters && Object.keys(filters).length > 0 && (
          <button
            onClick={() => onFiltersChange?.({})}
            className="flex items-center gap-1 hover:text-foreground transition-colors"
          >
            <Filter className="w-3 h-3" />
            Clear filters
          </button>
        )}
      </div>

      {/* Prospects grid */}
      <div className={GRID_LAYOUT_CLASSES}>
        {prospects.map((prospect) => (
          <ProspectCard
            key={prospect.id}
            prospect={prospect}
            {...(onProspectSelect && { onProspectSelect })}
            onConnectorSelect={(connector) => handleConnectorSelect(connector, prospect)}
            className="animate-fade-in"
          />
        ))}
      </div>

      {/* Load more indicator if needed */}
      {prospects.length > 0 && prospects.length % 20 === 0 && (
        <div className="text-center py-6">
          <GlassCard variant="interactive" className="inline-block px-6 py-3">
            <span className="text-sm text-muted-foreground">
              Scroll down for more prospects
            </span>
          </GlassCard>
        </div>
      )}
    </div>
  );
};

export default ProspectsGrid;
