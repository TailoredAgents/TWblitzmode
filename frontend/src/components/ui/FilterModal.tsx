'use client';

import React, { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, Filter, Calendar, Building2, MapPin, Star, Users, Target } from 'lucide-react';
import { cva, type VariantProps } from 'class-variance-authority';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';

const filterModalVariants = cva(
  'fixed inset-0 z-50 flex items-center justify-center p-4',
  {
    variants: {
      overlay: {
        default: 'bg-black/20 backdrop-blur-sm',
        strong: 'bg-black/40 backdrop-blur-md',
      },
    },
    defaultVariants: {
      overlay: 'default',
    },
  }
);

const dialogContentVariants = cva(
  'relative w-full max-w-4xl max-h-[90vh] overflow-hidden',
  {
    variants: {
      animation: {
        default: 'animate-in fade-in-0 zoom-in-95 duration-200',
        slide: 'animate-in slide-in-from-bottom-10 fade-in-0 duration-300',
      },
    },
    defaultVariants: {
      animation: 'default',
    },
  }
);

export interface FilterOptions {
  dateRange?: {
    start?: string;
    end?: string;
  };
  companies?: string[];
  locations?: string[];
  statuses?: string[];
  priorities?: string[];
  responseRateRange?: {
    min?: number;
    max?: number;
  };
  companySizeRange?: {
    min?: number;
    max?: number;
  };
  industries?: string[];
  tags?: string[];
}

interface FilterModalProps extends VariantProps<typeof filterModalVariants> {
  isOpen: boolean;
  onClose: () => void;
  onApplyFilters: (filters: FilterOptions) => void;
  initialFilters?: FilterOptions;
}

const FilterModal: React.FC<FilterModalProps> = ({
  isOpen,
  onClose,
  onApplyFilters,
  initialFilters = {},
  overlay = 'default',
}) => {
  const [filters, setFilters] = useState<FilterOptions>(initialFilters);

  const handleApply = () => {
    onApplyFilters(filters);
    onClose();
  };

  const handleReset = () => {
    setFilters({});
  };

  const updateFilter = <K extends keyof FilterOptions>(key: K, value: FilterOptions[K]) => {
    setFilters(prev => ({
      ...prev,
      [key]: value,
    }));
  };

  // Filter option placeholders populated by parent component
  const availableCompanies = initialFilters.companies ?? [];

  const availableLocations = initialFilters.locations ?? [];

  const availableStatuses = [
    'new', 'contacted', 'responded', 'qualified', 'not_interested', 'lost'
  ];

  const availablePriorities = [
    'low', 'normal', 'high', 'critical'
  ];

  const availableIndustries = initialFilters.industries ?? [];

  const availableTags = initialFilters.tags ?? [];

  return (
    <Dialog.Root open={isOpen} onOpenChange={onClose}>
      <Dialog.Portal>
        <Dialog.Overlay className={cn(filterModalVariants({ overlay }))}>
          <Dialog.Content className={cn(dialogContentVariants())}>
            <GlassCard variant="strong" className="h-full flex flex-col">
              {/* Header */}
              <div className="flex items-center justify-between p-6 border-b border-border/20">
                <div className="flex items-center gap-3">
                  <Filter className="w-6 h-6 text-primary" />
                  <div>
                    <Dialog.Title className="text-xl font-semibold text-foreground">
                      Advanced Filters
                    </Dialog.Title>
                    <Dialog.Description className="text-sm text-muted-foreground">
                      Refine your prospect search with detailed filtering options
                    </Dialog.Description>
                  </div>
                </div>
                <Dialog.Close asChild>
                  <button
                    className="p-2 rounded-lg hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Close dialog"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </Dialog.Close>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Date Range */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <Calendar className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Date Range</h3>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          From Date
                        </label>
                        <input
                          type="date"
                          value={filters.dateRange?.start ?? ''}
                          onChange={(e) => updateFilter('dateRange', {
                            ...filters.dateRange,
                            start: e.target.value
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          To Date
                        </label>
                        <input
                          type="date"
                          value={filters.dateRange?.end ?? ''}
                          onChange={(e) => updateFilter('dateRange', {
                            ...filters.dateRange,
                            end: e.target.value
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                    </div>
                  </GlassCard>

                  {/* Companies */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <Building2 className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Companies</h3>
                    </div>
                    <div className="space-y-2 max-h-32 overflow-y-auto">
                      {availableCompanies.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No company filters available.</p>
                      ) : (
                        availableCompanies.map((company) => (
                          <label key={company} className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={filters.companies?.includes(company) ?? false}
                              onChange={(e) => {
                                const companies = filters.companies ?? [];
                                if (e.target.checked) {
                                  updateFilter('companies', [...companies, company]);
                                } else {
                                  updateFilter('companies', companies.filter(c => c !== company));
                                }
                              }}
                              className="rounded border-border focus:ring-primary/20"
                            />
                            <span className="text-sm text-foreground">{company}</span>
                          </label>
                        ))
                      )}
                    </div>
                  </GlassCard>

                  {/* Locations */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <MapPin className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Locations</h3>
                    </div>
                    <div className="space-y-2 max-h-32 overflow-y-auto">
                      {availableLocations.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No location filters available.</p>
                      ) : (
                        availableLocations.map((location) => (
                          <label key={location} className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={filters.locations?.includes(location) ?? false}
                              onChange={(e) => {
                                const locations = filters.locations ?? [];
                                if (e.target.checked) {
                                  updateFilter('locations', [...locations, location]);
                                } else {
                                  updateFilter('locations', locations.filter(l => l !== location));
                                }
                              }}
                              className="rounded border-border focus:ring-primary/20"
                            />
                            <span className="text-sm text-foreground">{location}</span>
                          </label>
                        ))
                      )}
                    </div>
                  </GlassCard>

                  {/* Response Rate Range */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <Star className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Response Rate</h3>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          Minimum (%)
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={filters.responseRateRange?.min ?? ''}
                          onChange={(e) => updateFilter('responseRateRange', {
                            ...filters.responseRateRange,
                            min: Number(e.target.value)
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          Maximum (%)
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={filters.responseRateRange?.max ?? ''}
                          onChange={(e) => updateFilter('responseRateRange', {
                            ...filters.responseRateRange,
                            max: Number(e.target.value)
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                    </div>
                  </GlassCard>

                  {/* Status & Priority */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <Target className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Status & Priority</h3>
                    </div>
                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-2">
                          Status
                        </label>
                        <div className="flex flex-wrap gap-2">
                          {availableStatuses.map((status) => (
                            <button
                              key={status}
                              onClick={() => {
                                const statuses = filters.statuses ?? [];
                                if (statuses.includes(status)) {
                                  updateFilter('statuses', statuses.filter(s => s !== status));
                                } else {
                                  updateFilter('statuses', [...statuses, status]);
                                }
                              }}
                              className={cn(
                                'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                                filters.statuses?.includes(status)
                                  ? 'bg-primary text-primary-foreground'
                                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
                              )}
                            >
                              {status.replace('_', ' ')}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-2">
                          Priority
                        </label>
                        <div className="flex flex-wrap gap-2">
                          {availablePriorities.map((priority) => (
                            <button
                              key={priority}
                              onClick={() => {
                                const priorities = filters.priorities ?? [];
                                if (priorities.includes(priority)) {
                                  updateFilter('priorities', priorities.filter(p => p !== priority));
                                } else {
                                  updateFilter('priorities', [...priorities, priority]);
                                }
                              }}
                              className={cn(
                                'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                                filters.priorities?.includes(priority)
                                  ? 'bg-primary text-primary-foreground'
                                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
                              )}
                            >
                              {priority}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </GlassCard>

                  {/* Company Size Range */}
                  <GlassCard className="p-4">
                    <div className="flex items-center gap-3 mb-4">
                      <Users className="w-5 h-5 text-primary" />
                      <h3 className="font-semibold text-foreground">Company Size</h3>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          Minimum Employees
                        </label>
                        <input
                          type="number"
                          min="1"
                          value={filters.companySizeRange?.min ?? ''}
                          onChange={(e) => updateFilter('companySizeRange', {
                            ...filters.companySizeRange,
                            min: Number(e.target.value)
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-foreground mb-1">
                          Maximum Employees
                        </label>
                        <input
                          type="number"
                          min="1"
                          value={filters.companySizeRange?.max ?? ''}
                          onChange={(e) => updateFilter('companySizeRange', {
                            ...filters.companySizeRange,
                            max: Number(e.target.value)
                          })}
                          className="w-full px-3 py-2 bg-background/50 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
                        />
                      </div>
                    </div>
                  </GlassCard>

                  {/* Industries & Tags */}
                  <GlassCard className="p-4 lg:col-span-2">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {/* Industries */}
                      <div>
                        <h4 className="font-semibold text-foreground mb-3">Industries</h4>
                        <div className="flex flex-wrap gap-2">
                          {availableIndustries.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No industry filters available.</p>
                          ) : (
                            availableIndustries.map((industry) => (
                              <button
                                key={industry}
                                onClick={() => {
                                  const industries = filters.industries ?? [];
                                  if (industries.includes(industry)) {
                                    updateFilter('industries', industries.filter(i => i !== industry));
                                  } else {
                                    updateFilter('industries', [...industries, industry]);
                                  }
                                }}
                                className={cn(
                                  'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                                  filters.industries?.includes(industry)
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                                )}
                              >
                                {industry}
                              </button>
                            ))
                          )}
                        </div>
                      </div>

                      {/* Tags */}
                      <div>
                        <h4 className="font-semibold text-foreground mb-3">Tags</h4>
                        <div className="flex flex-wrap gap-2">
                          {availableTags.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No tag filters available.</p>
                          ) : (
                            availableTags.map((tag) => (
                              <button
                                key={tag}
                                onClick={() => {
                                  const tags = filters.tags ?? [];
                                  if (tags.includes(tag)) {
                                    updateFilter('tags', tags.filter(t => t !== tag));
                                  } else {
                                    updateFilter('tags', [...tags, tag]);
                                  }
                                }}
                                className={cn(
                                  'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                                  filters.tags?.includes(tag)
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                                )}
                              >
                                {tag.replace('_', ' ')}
                              </button>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  </GlassCard>
                </div>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between p-6 border-t border-border/20">
                <div className="text-xs text-muted-foreground">
                  {Object.keys(filters).length > 0 ? (
                    `${Object.keys(filters).length} filter(s) applied`
                  ) : (
                    'No filters applied'
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleReset}
                    className="px-4 py-2 text-sm bg-muted text-muted-foreground rounded-lg hover:bg-muted/80 transition-colors"
                  >
                    Reset All
                  </button>
                  <Dialog.Close asChild>
                    <button
                      className="px-4 py-2 text-sm bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/80 transition-colors"
                    >
                      Cancel
                    </button>
                  </Dialog.Close>
                  <button
                    onClick={handleApply}
                    className="px-6 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    Apply Filters
                  </button>
                </div>
              </div>
            </GlassCard>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

export default FilterModal;
