import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FlatCompat } from '@eslint/eslintrc';
import securityPlugin from 'eslint-plugin-security';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const ignores = [
  'node_modules/',
  '.next/',
  'out/',
  'dist/',
  'build/',
  'public/',
  '.storybook/',
  'cypress/',
  'database/',
  'tests/',
  'src/__tests__/**',
  'scripts/',
  'playwright/',
  'performance/',
  'security/',
  'middleware.ts',
  'jest.setup.js',
  'lighthouserc.js',
  '**/*.config.*',
  'jest.config.js',
  'eslint.config.mjs',
];

const RULE_LIMITS = {
  COMPLEXITY: 120,
  MAX_DEPTH: 8,
  MAX_LINES: 2000,
  MAX_LINES_PER_FUNCTION: 2000,
  MAX_NESTED_CALLBACKS: 6,
  MAX_PARAMS: 8,
};

const sharedRules = {
  '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', ignoreRestSiblings: true }],
  'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
  'no-debugger': 'error',
  'react/no-unescaped-entities': 'off',
  'react-hooks/exhaustive-deps': 'warn',
  'security/detect-object-injection': 'error',
  'security/detect-non-literal-regexp': 'warn',
  'security/detect-unsafe-regex': 'error',
  'security/detect-buffer-noassert': 'error',
  'security/detect-child-process': 'warn',
  'security/detect-disable-mustache-escape': 'error',
  'security/detect-eval-with-expression': 'error',
  'security/detect-no-csrf-before-method-override': 'error',
  'security/detect-non-literal-fs-filename': 'warn',
  'security/detect-non-literal-require': 'warn',
  'security/detect-possible-timing-attacks': 'warn',
  'security/detect-pseudoRandomBytes': 'error',
  complexity: ['warn', RULE_LIMITS.COMPLEXITY],
  'max-depth': ['warn', RULE_LIMITS.MAX_DEPTH],
  'max-lines': ['warn', RULE_LIMITS.MAX_LINES],
  'max-lines-per-function': ['warn', RULE_LIMITS.MAX_LINES_PER_FUNCTION],
  'max-nested-callbacks': ['warn', RULE_LIMITS.MAX_NESTED_CALLBACKS],
  'max-params': ['warn', RULE_LIMITS.MAX_PARAMS],
  'no-magic-numbers': 'off',
  'no-duplicate-imports': 'error',
  'no-useless-return': 'error',
  'no-var': 'error',
  'prefer-const': 'error',
  'prefer-arrow-callback': 'error',
  'prefer-template': 'off',
  'prefer-destructuring': 'off',
  'react/jsx-key': 'error',
  'react/jsx-no-duplicate-props': 'error',
  'react/jsx-no-undef': 'error',
  'react/no-direct-mutation-state': 'error',
  'react/no-unknown-property': 'error',
  'react/prop-types': 'off',
  'react/react-in-jsx-scope': 'off',
  '@typescript-eslint/no-explicit-any': 'warn',
  '@typescript-eslint/no-var-requires': 'warn',
  '@typescript-eslint/no-require-imports': 'warn',
  '@typescript-eslint/triple-slash-reference': 'warn',
  '@typescript-eslint/prefer-nullish-coalescing': 'warn',
  '@typescript-eslint/prefer-optional-chain': 'warn',
  '@typescript-eslint/no-non-null-assertion': 'warn',
  '@typescript-eslint/consistent-type-imports': 'warn',
  'import/no-anonymous-default-export': 'off',
};

export default [
  {
    ignores,
  },
  ...compat.extends('next/core-web-vitals', 'plugin:@typescript-eslint/recommended'),
  {
    files: ['src/**/*.{ts,tsx,js,jsx,mjs}'],
    plugins: {
      security: securityPlugin,
      '@typescript-eslint': tsPlugin,
    },
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        project: [
          path.join(__dirname, 'tsconfig.json'),
          path.join(__dirname, 'tsconfig.typecheck.json'),
        ],
        tsconfigRootDir: __dirname,
        sourceType: 'module',
      },
    },
    rules: sharedRules,
  },
];
