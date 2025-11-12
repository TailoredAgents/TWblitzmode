/**
 * Brand Color Consistency Tests
 *
 * Verifies that the application consistently uses the approved brand color palette:
 * - Primary: #FFD400 (Signal Yellow)
 * - Secondary: #111111 (Onyx Black)
 * - Accent: #FFE766 (Soft Yellow)
 *
 * These tests ensure color consistency across components and prevent regression
 * to the old purple color scheme.
 */

import fs from 'fs';
import path from 'path';

describe('Brand Color Consistency', () => {
  let globalsCss: string;

  beforeAll(() => {
    // Read the globals.css file
    const globalsPath = path.join(__dirname, '../../app/globals.css');
    globalsCss = fs.readFileSync(globalsPath, 'utf-8');
  });

  describe('CSS Custom Properties', () => {
    test('should define correct primary color in light mode', () => {
      expect(globalsCss).toMatch(/--primary:\s*#FFD400/);
    });

    test('should define correct secondary color in light mode', () => {
      expect(globalsCss).toMatch(/--secondary:\s*#111111/);
    });

    test('should define correct accent color in light mode', () => {
      expect(globalsCss).toMatch(/--accent:\s*#FFE766/);
    });

    test('should not contain deprecated OKLCH color values', () => {
      // Check that OKLCH values have been removed
      expect(globalsCss).not.toMatch(/oklch\(/i);
    });

    test('should not contain deprecated tailored-* color references', () => {
      // Check for any leftover tailored color references
      expect(globalsCss).not.toMatch(/--tailored-/);
    });

    test('should define dark mode primary color correctly', () => {
      expect(globalsCss).toMatch(/\.dark[\s\S]*--primary:\s*#FFD400/);
    });

    test('should define dark mode accent color correctly', () => {
      expect(globalsCss).toMatch(/\.dark[\s\S]*--accent:\s*#FFE766/);
    });
  });

  describe('Component Color Usage', () => {
    let linkChatComponent: string;
    let dashboardComponent: string;
    let landingPageComponent: string;

    beforeAll(() => {
      // Read component files
      const linkChatPath = path.join(__dirname, '../../components/LinkChat.tsx');
      const dashboardPath = path.join(__dirname, '../../components/DashboardOverview.tsx');
      const landingPath = path.join(__dirname, '../../app/page.tsx');

      linkChatComponent = fs.readFileSync(linkChatPath, 'utf-8');
      dashboardComponent = fs.readFileSync(dashboardPath, 'utf-8');
      landingPageComponent = fs.readFileSync(landingPath, 'utf-8');
    });

    test('LinkChat should not contain purple gradient references', () => {
      // Check that purple gradients have been replaced
      expect(linkChatComponent).not.toMatch(/from-.*purple|to-.*purple/);
      expect(linkChatComponent).not.toMatch(/from-indigo.*to-purple/);

      // Should contain brand colors
      expect(linkChatComponent).toMatch(/from-\[#111111\]/);
      expect(linkChatComponent).toMatch(/to-\[#FFD400\]/);
    });

    test('Dashboard should not contain tailored-* color classes', () => {
      // Check that tailored color classes have been replaced
      expect(dashboardComponent).not.toMatch(/tailored-\d+/);

      // Should use semantic color tokens
      expect(dashboardComponent).toMatch(/text-primary|bg-primary/);
      expect(dashboardComponent).toMatch(/text-secondary|bg-secondary/);
    });

    test('Landing page should use brand-compliant icon colors', () => {
      // Should not contain deprecated color classes
      expect(landingPageComponent).not.toMatch(/text-violet-400/);
      expect(landingPageComponent).not.toMatch(/text-sky-400/);

      // Should use semantic color tokens
      expect(landingPageComponent).toMatch(/text-primary/);
      expect(landingPageComponent).toMatch(/bg-secondary|border-primary|bg-\[#FFD400|border-\[#FFD400/);
    });

    test('No component should contain hardcoded purple colors', () => {
      const files = [linkChatComponent, dashboardComponent, landingPageComponent];

      files.forEach((fileContent) => {

        // Check for specific deprecated purple colors
        expect(fileContent).not.toMatch(/#7266ff/); // Old tailored purple
        expect(fileContent).not.toMatch(/purple-[0-9]+/); // Tailwind purple classes
        expect(fileContent).not.toMatch(/violet-[0-9]+/); // Tailwind violet classes
        expect(fileContent).not.toMatch(/indigo.*purple/); // Indigo to purple gradients
      });
    });
  });

  describe('Color Accessibility', () => {
    test('should maintain high contrast focus rings', () => {
      expect(globalsCss).toMatch(/--focus-ring.*rgba\(255,\s*212,\s*0/);
    });

    test('should define accessible selection colors', () => {
      expect(globalsCss).toMatch(/::selection[\s\S]*rgba\(255,\s*212,\s*0/);
    });

    test('should support high contrast mode', () => {
      expect(globalsCss).toMatch(/@media \(prefers-contrast: high\)/);
    });
  });

  describe('Chart Color Palette', () => {
    test('should define brand-compliant chart colors', () => {
      expect(globalsCss).toMatch(/--chart-1:\s*#FFD400/);
      expect(globalsCss).toMatch(/--chart-2:\s*#111111/);
      expect(globalsCss).toMatch(/--chart-3:\s*#FFE766/);
    });

    test('should not contain deprecated chart colors', () => {
      // Should not contain old purple-based chart colors
      expect(globalsCss).not.toMatch(/--chart-.*#[a-fA-F0-9]*[7-9a-fA-F][0-9a-fA-F]*ff/);
    });
  });
});

/**
 * Visual Regression Test Utilities
 *
 * These functions help detect color inconsistencies and can be extended
 * for automated visual testing with tools like Percy or Chromatic.
 */
export const brandColorValidators = {
  /**
   * Validates that a color string matches brand palette
   */
  isValidBrandColor: (color: string): boolean => {
    const brandColors = ['#FFD400', '#111111', '#FFE766', '#B38F00', '#333333'];
    return brandColors.includes(color.toUpperCase());
  },

  /**
   * Extracts color values from CSS content
   */
  extractColors: (cssContent: string): string[] => {
    const colorRegex = /#[a-fA-F0-9]{6}/g;
    return cssContent.match(colorRegex) || [];
  },

  /**
   * Checks for deprecated color patterns
   */
  hasDeprecatedColors: (content: string): boolean => {
    const deprecatedPatterns = [
      /oklch\(/i,
      /--tailored-/,
      /purple-[0-9]+/,
      /violet-[0-9]+/,
      /#[a-fA-F0-9]*[7-9a-fA-F][0-9a-fA-F]*ff/ // Purple hex patterns
    ];

    return deprecatedPatterns.some(pattern => pattern.test(content));
  }
};
