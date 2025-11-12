import React from 'react';
import { generateMetaTags, SEOConstants } from '../seo';

describe('generateMetaTags', () => {
  it('returns a Head element with expected children', () => {
    const node = generateMetaTags({
      title: 'Dashboard',
      description: 'Control the enterprise pipeline',
      canonical: `${SEOConstants.SITE_URL}/dashboard`,
      keywords: ['dashboard', 'metrics'],
    });

    expect(React.isValidElement(node)).toBe(true);
    const children = React.Children.toArray((node as React.ReactElement).props.children);

    const titleElement = children.find(
      (child) => React.isValidElement(child) && child.type === 'title'
    ) as React.ReactElement | undefined;
    expect(titleElement?.props.children).toBe('Dashboard');

    const canonicalLink = children.find(
      (child) =>
        React.isValidElement(child) && child.type === 'link' && child.props.rel === 'canonical'
    ) as React.ReactElement | undefined;
    expect(canonicalLink?.props.href).toBe(`${SEOConstants.SITE_URL}/dashboard`);
  });
});
