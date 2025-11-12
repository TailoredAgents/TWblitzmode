/**
 * Performance Optimization Utilities
 * Provides code splitting, lazy loading, and performance monitoring
 */

import React, {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  useCallback,
  type ComponentType,
  type ReactNode
} from 'react';
import { announceToScreenReader } from './accessibility';

const logPerformance = (...args: unknown[]) => {
  if (process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
};

const tablePerformance = (data: unknown) => {
  if (process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.table(data);
  }
};

// Performance metrics interface
export interface PerformanceMetrics {
  componentLoadTime: number;
  renderTime: number;
  bundleSize?: number;
  memoryUsage?: number;
  timestamp: number;
}

interface MemoryUsageDetails {
  jsHeapSizeLimit: number;
  totalJSHeapSize: number;
  usedJSHeapSize: number;
}

// Component loading options
export interface LazyLoadOptions {
  fallback?: ReactNode;
  errorBoundary?: boolean;
  preload?: boolean;
  timeout?: number;
  retryAttempts?: number;
}

// Performance monitoring
export class PerformanceMonitor {
  private static instance: PerformanceMonitor;
  private metrics: Map<string, PerformanceMetrics[]> = new Map();
  private observers: PerformanceObserver[] = [];

  static getInstance(): PerformanceMonitor {
    if (!PerformanceMonitor.instance) {
      PerformanceMonitor.instance = new PerformanceMonitor();
    }
    return PerformanceMonitor.instance;
  }

  constructor() {
    if (typeof window !== 'undefined') {
      this.initializeObservers();
    }
  }

  private initializeObservers(): void {
    // Observe paint metrics
    if ('PerformanceObserver' in window) {
      try {
        const paintObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            logPerformance(`${entry.name}: ${entry.startTime}ms`);
          }
        });
        paintObserver.observe({ entryTypes: ['paint'] });
        this.observers.push(paintObserver);

        // Observe navigation metrics
        const navigationObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            this.recordNavigationMetrics(entry as PerformanceNavigationTiming);
          }
        });
        navigationObserver.observe({ entryTypes: ['navigation'] });
        this.observers.push(navigationObserver);

        // Observe resource loading
        const resourceObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            this.recordResourceMetrics(entry as PerformanceResourceTiming);
          }
        });
        resourceObserver.observe({ entryTypes: ['resource'] });
        this.observers.push(resourceObserver);
      } catch (error) {
        console.warn('Failed to initialize performance observers:', error);
      }
    }
  }

  private recordNavigationMetrics(entry: PerformanceNavigationTiming): void {
    const metrics: PerformanceMetrics = {
      componentLoadTime: entry.loadEventEnd - entry.startTime,
      renderTime: entry.domContentLoadedEventEnd - entry.domContentLoadedEventStart,
      timestamp: Date.now()
    };

    this.recordMetrics('navigation', metrics);
  }

  private recordResourceMetrics(entry: PerformanceResourceTiming): void {
    // Only track JavaScript bundles
    if (entry.name.includes('.js') || entry.name.includes('chunk')) {
      const metrics: PerformanceMetrics = {
        componentLoadTime: entry.responseEnd - entry.requestStart,
        renderTime: 0,
        bundleSize: entry.transferSize,
        timestamp: Date.now()
      };

      this.recordMetrics(`resource:${entry.name}`, metrics);
    }
  }

  recordMetrics(componentName: string, metrics: PerformanceMetrics): void {
    const existingMetrics = this.metrics.get(componentName);
    if (!existingMetrics) {
      this.metrics.set(componentName, [metrics]);
      return;
    }

    const componentMetrics = existingMetrics;
    componentMetrics.push(metrics);

    // Keep only last 10 measurements
    if (componentMetrics.length > 10) {
      componentMetrics.shift();
    }
  }

  getMetrics(componentName: string): PerformanceMetrics[] {
    return this.metrics.get(componentName) ?? [];
  }

  getAverageLoadTime(componentName: string): number {
    const metrics = this.getMetrics(componentName);
    if (metrics.length === 0) return 0;

    const totalTime = metrics.reduce((sum, metric) => sum + metric.componentLoadTime, 0);
    return totalTime / metrics.length;
  }

  getAllMetrics(): Array<{ component: string; metrics: PerformanceMetrics[] }> {
    return Array.from(this.metrics.entries()).map(([component, metrics]) => ({
      component,
      metrics
    }));
  }

  clearMetrics(): void {
    this.metrics.clear();
  }

  destroy(): void {
    this.observers.forEach(observer => observer.disconnect());
    this.observers = [];
    this.metrics.clear();
  }
}

// Get performance monitor instance
export const performanceMonitor = PerformanceMonitor.getInstance();

// Enhanced lazy loading with performance tracking
type ComponentModule<P> = { default: ComponentType<P> };

export function createLazyComponent<P extends Record<string, unknown> = Record<string, unknown>>(
  importFn: () => Promise<ComponentModule<P>>,
  componentName: string,
  options: LazyLoadOptions = {}
): ComponentType<P> {
  const {
    fallback = null,
    timeout = 10000,
    retryAttempts = 3
  } = options;

  let loadPromise: Promise<ComponentModule<P>> | null = null;
  let retryCount = 0;

  const loadComponent = async (): Promise<ComponentModule<P>> => {
    const startTime = performance.now();

    try {
      const loadedModule = await Promise.race([
        importFn(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('Component load timeout')), timeout)
        )
      ]);

      const loadTime = performance.now() - startTime;

      // Record performance metrics
      performanceMonitor.recordMetrics(componentName, {
        componentLoadTime: loadTime,
        renderTime: 0,
        timestamp: Date.now()
      });

      // Announce successful load to screen readers if it took more than 2 seconds
      if (loadTime > 2000) {
        announceToScreenReader(`${componentName} component loaded`, 'polite');
      }

      return loadedModule;
    } catch (error) {
      console.error(`Failed to load component ${componentName}:`, error);

      if (retryCount < retryAttempts) {
        retryCount++;
        logPerformance(`Retrying component load for ${componentName} (attempt ${retryCount}/${retryAttempts})`);

        // Wait before retry with exponential backoff
        await new Promise(resolve => setTimeout(resolve, Math.pow(2, retryCount) * 1000));

        return loadComponent();
      }

      announceToScreenReader(`Failed to load ${componentName} component. Please refresh the page.`, 'assertive');
      throw error;
    }
  };

  const LazyComponent = lazy(() => {
    if (!loadPromise) {
      loadPromise = loadComponent();
    }
    return loadPromise;
  });

  type PreloadableComponent = ComponentType<P> & {
    preload: () => Promise<ComponentModule<P>>;
  };

  const LazyComponentWrapper: ComponentType<P> = (componentProps) =>
    React.createElement(LazyComponent, componentProps);

  const WrappedComponent = ((props: P) =>
    React.createElement(
      Suspense,
      { fallback },
      React.createElement(LazyComponentWrapper, props),
    )) as PreloadableComponent;

  WrappedComponent.displayName = `Lazy(${componentName})`;

  WrappedComponent.preload = () => {
    if (!loadPromise) {
      loadPromise = loadComponent();
    }
    return loadPromise;
  };

  return WrappedComponent;
}

// Code splitting utilities
export const CodeSplitting = {
  // Create route-based lazy component
  createRoute: <P extends Record<string, unknown> = Record<string, unknown>>(
    importFn: () => Promise<ComponentModule<P>>,
    routeName: string
  ) => createLazyComponent(importFn, `Route:${routeName}`, {
    fallback: React.createElement(
      'div',
      { className: 'min-h-screen flex items-center justify-center' },
      React.createElement(
        'div',
        { className: 'text-center' },
        React.createElement('div', { className: 'animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4' }),
        React.createElement('p', { className: 'text-muted-foreground' }, `Loading ${routeName}...`)
      )
    )
  }),

  // Create feature-based lazy component
  createFeature: <P extends Record<string, unknown> = Record<string, unknown>>(
    importFn: () => Promise<ComponentModule<P>>,
    featureName: string
  ) => createLazyComponent(importFn, `Feature:${featureName}`, {
    fallback: React.createElement(
      'div',
      { className: 'flex items-center justify-center p-4' },
      React.createElement(
        'div',
        { className: 'animate-pulse flex space-x-4' },
        React.createElement('div', { className: 'rounded-full bg-muted h-4 w-4' }),
        React.createElement(
          'div',
          { className: 'space-y-2' },
          React.createElement('div', { className: 'h-4 bg-muted rounded w-20' }),
          React.createElement('div', { className: 'h-4 bg-muted rounded w-16' })
        )
      )
    )
  }),

  // Create modal-based lazy component
  createModal: <P extends Record<string, unknown> = Record<string, unknown>>(
    importFn: () => Promise<ComponentModule<P>>,
    modalName: string
  ) => createLazyComponent(importFn, `Modal:${modalName}`, {
    fallback: React.createElement(
      'div',
      { className: 'fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center' },
      React.createElement(
        'div',
        { className: 'bg-card p-6 rounded-lg shadow-lg' },
        React.createElement('div', { className: 'animate-spin rounded-full h-6 w-6 border-b-2 border-primary mx-auto mb-2' }),
        React.createElement('p', { className: 'text-sm text-muted-foreground' }, 'Loading...')
      )
    )
  })
};

// Hook for measuring component render performance
export function useRenderPerformance(componentName: string) {
  const renderStart = useRef<number>(0);
  const renderCount = useRef<number>(0);

  useEffect(() => {
    renderStart.current = performance.now();
    renderCount.current++;

    return () => {
      const renderTime = performance.now() - renderStart.current;

      performanceMonitor.recordMetrics(componentName, {
        componentLoadTime: 0,
        renderTime,
        timestamp: Date.now()
      });
    };
  });

  return {
    renderCount: renderCount.current,
    getAverageRenderTime: () => performanceMonitor.getAverageLoadTime(componentName)
  };
}

// Hook for lazy loading images
export function useLazyImage(src: string, placeholder?: string) {
  const [currentSrc, setCurrentSrc] = useState(placeholder ?? '');
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    if (!src) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry && entry.isIntersecting) {
          const img = new Image();
          img.onload = () => {
            setCurrentSrc(src);
            setIsLoading(false);
          };
          img.onerror = () => {
            setHasError(true);
            setIsLoading(false);
          };
          img.src = src;
          observer.disconnect();
        }
      },
      { threshold: 0.1 }
    );

    if (imgRef.current) {
      observer.observe(imgRef.current);
    }

    return () => observer.disconnect();
  }, [src]);

  return {
    ref: imgRef,
    src: currentSrc,
    isLoading,
    hasError
  };
}

// Hook for monitoring memory usage
export function useMemoryMonitor(componentName: string) {
  const [memoryInfo, setMemoryInfo] = useState<MemoryUsageDetails | null>(null);

  useEffect(() => {
    const updateMemoryInfo = () => {
      if ('memory' in performance) {
        const performanceWithMemory = performance as Performance & { memory?: MemoryUsageDetails };
        const memory = performanceWithMemory.memory;
        if (memory) {
          setMemoryInfo(memory);

          performanceMonitor.recordMetrics(`memory:${componentName}`, {
            componentLoadTime: 0,
            renderTime: 0,
            memoryUsage: memory.usedJSHeapSize,
            timestamp: Date.now()
          });
        }
      }
    };

    updateMemoryInfo();
    const interval = setInterval(updateMemoryInfo, 5000);

    return () => clearInterval(interval);
  }, [componentName]);

  return memoryInfo;
}

// Hook for preloading components
export function useComponentPreloader() {
  const preloadedComponents = useRef<Set<string>>(new Set());

  const preload = useCallback((components: Array<{ preload: () => Promise<unknown> }>) => {
    components.forEach((component, index) => {
      const componentKey = `preload-${index}`;
      if (!preloadedComponents.current.has(componentKey)) {
        preloadedComponents.current.add(componentKey);
        component.preload().catch(error => {
          console.warn('Failed to preload component:', error);
          preloadedComponents.current.delete(componentKey);
        });
      }
    });
  }, []);

  return { preload };
}

// Bundle analyzer utility (development only)
export function analyzeBundleSize() {
  if (process.env.NODE_ENV !== 'development') {
    console.warn('Bundle analysis is only available in development mode');
    return;
  }

  const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
  const jsResources = resources.filter(resource =>
    resource.name.includes('.js') && resource.transferSize > 0
  );

  const bundleInfo = jsResources.map(resource => ({
    name: resource.name.split('/').pop(),
    size: resource.transferSize,
    loadTime: resource.responseEnd - resource.requestStart,
    cached: resource.transferSize === 0
  }));

  bundleInfo.sort((a, b) => b.size - a.size);

  tablePerformance(bundleInfo);
  logPerformance('Total JS bundle size:', bundleInfo.reduce((sum, bundle) => sum + bundle.size, 0), 'bytes');
}

// Web Vitals monitoring
export function initializeWebVitals() {
  if (typeof window === 'undefined') return;

  // Monitor Largest Contentful Paint (LCP)
  const lcpObserver = new PerformanceObserver((list) => {
    const entries = list.getEntries();
    const lastEntry = entries[entries.length - 1];
    logPerformance('LCP:', lastEntry?.startTime);
  });

  try {
    lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (error) {
    console.warn('LCP observation not supported');
  }

  // Monitor First Input Delay (FID)
  const fidObserver = new PerformanceObserver((list) => {
    const entries = list.getEntries();
    entries.forEach(entry => {
      const eventEntry = entry as PerformanceEntry & { processingStart?: number };
      if (typeof eventEntry.processingStart === 'number') {
        logPerformance('FID:', eventEntry.processingStart - eventEntry.startTime);
      }
    });
  });

  try {
    fidObserver.observe({ type: 'first-input', buffered: true });
  } catch (error) {
    console.warn('FID observation not supported');
  }
}

// Initialize web vitals monitoring
if (typeof window !== 'undefined') {
  initializeWebVitals();
}
