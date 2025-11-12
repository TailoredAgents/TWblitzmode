import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
  })),
  useSearchParams: jest.fn(() => ({
    get: jest.fn(() => null),
  })),
}));

jest.mock('../../../components/ui/ToastContainer', () => ({
  useToastActions: () => ({ success: jest.fn(), error: jest.fn() }),
}));

const mockRoster = [
  { id: 1, displayName: 'Jordan Carter', firstName: 'Jordan', lastName: 'Carter', lastLoginAt: null },
];

jest.mock('../../../services/api', () => ({
  apiService: {
    getLoginRoster: jest.fn(() => Promise.resolve({ data: mockRoster })),
    login: jest.fn(() => Promise.resolve({ data: {} })),
    setUserPreference: jest.fn(() => Promise.resolve()),
  },
}));

jest.mock('../../../contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    translate: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

jest.mock('../../../lib/authToken', () => ({
  getAccessToken: jest.fn(() => null),
  setAccessToken: jest.fn(),
}));

import LoginPage from '../page';

describe('LoginPage', () => {
  it('renders unlock form first and shows roster after successful unlock', async () => {
    const user = userEvent.setup();

    render(<LoginPage />);

    expect(
      screen.getByRole('heading', {
        name: 'Sign In',
      }),
    ).toBeInTheDocument();

    const unlockInput = screen.getByTestId('unlock-password-input');
    expect(unlockInput).toBeInTheDocument();
    expect(screen.queryByText('Jordan Carter')).not.toBeInTheDocument();

    await user.type(unlockInput, 'Tallwave123');
    await user.click(screen.getByTestId('unlock-submit'));

    expect(await screen.findByText('Jordan Carter')).toBeInTheDocument();
    expect(screen.queryByText(/Company Portal/i)).not.toBeInTheDocument();
  });
});
