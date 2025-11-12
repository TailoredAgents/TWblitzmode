/**
 * SEO Optimization Utilities
 * Provides comprehensive SEO management, meta tags, and structured data
 */

import React, { useEffect, type ReactNode } from 'react';
import Head from 'next/head';

// SEO configuration types
export interface SEOConfig {
  title: string;
  description: string;
  keywords?: readonly string[] | string[];
  canonical?: string;
  ogTitle?: string;
  ogDescription?: string;
  ogImage?: string;
  ogType?: 'website' | 'article' | 'product' | 'profile';
  twitterCard?: 'summary' | 'summary_large_image' | 'app' | 'player';
  twitterSite?: string;
  twitterCreator?: string;
  noindex?: boolean;
  nofollow?: boolean;
  robots?: string;
  structuredData?: unknown;
  alternateLanguages?: Array<{ lang: string; url: string }>;
}

// Default SEO configuration
export const defaultSEOConfig: Partial<SEOConfig> = {
  ogType: 'website',
  twitterCard: 'summary_large_image',
  twitterSite: '@vouchlink',
  robots: 'index,follow'
};

// Application-wide SEO constants
export const SEOConstants = {
  SITE_NAME: 'Tallwave',
  SITE_URL: 'https://vouchlink.ai',
  DEFAULT_IMAGE: '/images/og-default.png',
  LOGO: '/images/logo.png',
  FAVICON: '/favicon.ico',
  APPLE_TOUCH_ICON: '/apple-touch-icon.png',
  MANIFEST: '/manifest.json',
  THEME_COLOR: '#FFD400'
} as const;

// Page-specific SEO configurations
export const PageSEOConfigs = {
  home: {
    title: 'Tallwave - Intelligent LinkedIn Automation Platform',
    description: 'Transform your LinkedIn outreach with AI-powered automation. Generate personalized messages, manage campaigns, and track performance with Tallwave.',
    keywords: ['LinkedIn automation', 'AI outreach', 'sales automation', 'lead generation', 'personalized messaging'],
    ogImage: `${SEOConstants.SITE_URL}/images/og-home.png`
  },
  dashboard: {
    title: 'Dashboard - Tallwave',
    description: 'Monitor your LinkedIn automation campaigns, track performance metrics, and manage your outreach workflow.',
    keywords: ['dashboard', 'analytics', 'campaign management', 'performance tracking'],
    noindex: true
  },
  prospects: {
    title: 'Prospects Management - Tallwave',
    description: 'Manage your prospects, track engagement, and optimize your LinkedIn outreach campaigns.',
    keywords: ['prospects', 'lead management', 'engagement tracking', 'LinkedIn leads'],
    noindex: true
  }
} as const;

type PageSEOConfigKey = keyof typeof PageSEOConfigs;
type PageSEOConfigValue = (typeof PageSEOConfigs)[PageSEOConfigKey];

const PAGE_SEO_CONFIG_MAP = new Map<PageSEOConfigKey, PageSEOConfigValue>(
  Object.entries(PageSEOConfigs) as Array<[PageSEOConfigKey, PageSEOConfigValue]>
);

// Generate meta tags component
export function generateMetaTags(config: SEOConfig): ReactNode {
  const mergedConfig = { ...defaultSEOConfig, ...config };
  const {
    title,
    description,
    keywords,
    canonical,
    ogTitle,
    ogDescription,
    ogImage,
    ogType,
    twitterCard,
    twitterSite,
    twitterCreator,
    noindex,
    nofollow,
    robots,
    structuredData,
    alternateLanguages
  } = mergedConfig;

  let robotsContent = robots;
  const shouldOverrideRobots = [noindex, nofollow].some((flag) => Boolean(flag));
  if (shouldOverrideRobots) {
    const robotsArray: string[] = [];
    robotsArray.push(noindex ? 'noindex' : 'index');
    robotsArray.push(nofollow ? 'nofollow' : 'follow');
    robotsContent = robotsArray.join(',');
  }

  const keywordsContent = Array.isArray(keywords)
    ? keywords.join(', ')
    : typeof keywords === 'string'
      ? keywords
      : undefined;

  const elements: ReactNode[] = [
    React.createElement('title', { key: 'title' }, title),
    React.createElement('meta', { key: 'description', name: 'description', content: description }),
    keywordsContent
      ? React.createElement('meta', {
        key: 'keywords',
        name: 'keywords',
        content: keywordsContent,
      })
      : null,
    React.createElement('meta', {
      key: 'robots',
      name: 'robots',
      content: robotsContent ?? 'index,follow',
    }),
    React.createElement('meta', {
      key: 'viewport',
      name: 'viewport',
      content: 'width=device-width, initial-scale=1, shrink-to-fit=no',
    }),
    React.createElement('meta', {
      key: 'og:site_name',
      property: 'og:site_name',
      content: SEOConstants.SITE_NAME,
    }),
    React.createElement('meta', {
      key: 'og:title',
      property: 'og:title',
      content: ogTitle ?? title,
    }),
    React.createElement('meta', {
      key: 'og:description',
      property: 'og:description',
      content: ogDescription ?? description,
    }),
    React.createElement('meta', {
      key: 'og:type',
      property: 'og:type',
      content: ogType,
    }),
    React.createElement('meta', {
      key: 'og:url',
      property: 'og:url',
      content: canonical ?? SEOConstants.SITE_URL,
    }),
    React.createElement('meta', {
      key: 'og:image',
      property: 'og:image',
      content: ogImage ?? SEOConstants.DEFAULT_IMAGE,
    }),
    React.createElement('meta', {
      key: 'twitter:card',
      name: 'twitter:card',
      content: twitterCard,
    }),
    twitterSite
      ? React.createElement('meta', {
        key: 'twitter:site',
        name: 'twitter:site',
        content: twitterSite,
      })
      : null,
    twitterCreator
      ? React.createElement('meta', {
        key: 'twitter:creator',
        name: 'twitter:creator',
        content: twitterCreator,
      })
      : null,
    React.createElement('meta', {
      key: 'twitter:title',
      name: 'twitter:title',
      content: ogTitle ?? title,
    }),
    React.createElement('meta', {
      key: 'twitter:description',
      name: 'twitter:description',
      content: ogDescription ?? description,
    }),
    React.createElement('meta', {
      key: 'twitter:image',
      name: 'twitter:image',
      content: ogImage ?? SEOConstants.DEFAULT_IMAGE,
    }),
    React.createElement('link', {
      key: 'icon',
      rel: 'icon',
      href: SEOConstants.FAVICON,
    }),
    React.createElement('link', {
      key: 'apple-touch-icon',
      rel: 'apple-touch-icon',
      href: SEOConstants.APPLE_TOUCH_ICON,
    }),
    React.createElement('link', {
      key: 'manifest',
      rel: 'manifest',
      href: SEOConstants.MANIFEST,
    }),
    React.createElement('meta', {
      key: 'theme-color',
      name: 'theme-color',
      content: SEOConstants.THEME_COLOR,
    }),
  ].filter(Boolean);

  if (canonical) {
    elements.push(
      React.createElement('link', {
        key: 'canonical',
        rel: 'canonical',
        href: canonical,
      })
    );
  }

  if (alternateLanguages?.length) {
    alternateLanguages.forEach(({ lang, url }) => {
      elements.push(
        React.createElement('link', {
          key: `alt-${lang}`,
          rel: 'alternate',
          hrefLang: lang,
          href: url,
        })
      );
    });
  }

  if (structuredData) {
    const structuredJson = typeof structuredData === 'string'
      ? structuredData
      : JSON.stringify(structuredData);
    elements.push(
      React.createElement('script', {
        key: 'structured-data',
        type: 'application/ld+json',
        dangerouslySetInnerHTML: {
          __html: structuredJson,
        },
      })
    );
  }

  return React.createElement(Head, null, elements);
}

// SEO utilities
export const SEOUtils = {
  generateTitle: (pageTitle: string, includeSiteName: boolean = true): string => {
    if (!includeSiteName) return pageTitle;
    return `${pageTitle} | ${SEOConstants.SITE_NAME}`;
  },

  generateCanonicalUrl: (path: string): string => {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${SEOConstants.SITE_URL}${cleanPath}`;
  },

  generateDescription: (content: string, maxLength: number = 160): string => {
    if (content.length <= maxLength) return content;
    return content.substring(0, maxLength - 3).trim() + '...';
  }
};

// Hook for managing page SEO
import { useRouter } from 'next/router';

export function usePageSEO(pageKey: PageSEOConfigKey, customConfig?: Partial<SEOConfig>) {
  const router = useRouter();
  const baseConfig = PAGE_SEO_CONFIG_MAP.get(pageKey) ?? PageSEOConfigs.home;
  const fullConfig: SEOConfig = {
    ...baseConfig,
    ...customConfig,
    canonical: SEOUtils.generateCanonicalUrl(router.asPath),
    title: SEOUtils.generateTitle(customConfig?.title ?? baseConfig.title)
  };

  useEffect(() => {
    document.title = fullConfig.title;
    const metaDescription = document.querySelector('meta[name="description"]');
    if (metaDescription) {
      metaDescription.setAttribute('content', fullConfig.description);
    }
  }, [fullConfig.title, fullConfig.description]);

  return {
    seoConfig: fullConfig,
    metaTags: generateMetaTags(fullConfig)
  };
}

// Component for handling dynamic SEO
export interface SEOProps {
  config: SEOConfig;
  children?: ReactNode;
}

export function SEO({ config, children }: SEOProps) {
  const router = useRouter();
  const fullConfig: SEOConfig = {
    ...config,
    canonical: config.canonical ?? SEOUtils.generateCanonicalUrl(router.asPath),
    title: SEOUtils.generateTitle(config.title)
  };

  return React.createElement(
    React.Fragment,
    null,
    generateMetaTags(fullConfig),
    children
  );
}
