/**
 * Login Page Tests
 * Validates Tallwave roster-driven authentication flow.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRouter } from 'next/navigation';

import LoginPage from '../app/login/page';

jest.mock('next/navigation', () => ({
  useRouter: jest.fn(),
}));

type LoginPayload = { userId: number; password: string };

const mockRoster = [
  {
    id: 3,
    displayName: 'Jordan Carter',
    firstName: 'Jordan',
    lastName: 'Carter',
    lastLoginAt: null,
  },
];

const pushMock = jest.fn();
const successToastMock = jest.fn();
const errorToastMock = jest.fn();
const setAccessTokenMock = jest.fn();
const replaceMock = jest.fn();
const originalLocation = window.location;

const loginMock = jest.fn(async (_payload: LoginPayload) => ({
  data: {
    access_token: 'token-123',
    cookie_status: 'valid',
    accepted_terms: true,
  },
}));

jest.mock('../services/api', () => ({
  apiService: {
    getLoginRoster: jest.fn(() => Promise.resolve({ data: mockRoster })),
    login: (payload: LoginPayload) => loginMock(payload),
    setUserPreference: jest.fn(() => Promise.resolve()),
  },
}));

jest.mock('../contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (_key: string, fallback: string) => fallback,
  }),
}));

jest.mock('../components/ui/ToastContainer', () => ({
  useToastActions: () => ({
    success: successToastMock,
    error: errorToastMock,
  }),
}));

jest.mock('../lib/authToken', () => ({
  getAccessToken: jest.fn(() => null),
  setAccessToken: (token: string) => setAccessTokenMock(token),
}));

describe('LoginPage roster flow', () => {
  beforeEach(() => {
    (useRouter as jest.Mock).mockReturnValue({
      push: pushMock,
      replace: jest.fn(),
    });
    loginMock.mockClear();
    pushMock.mockReset();
    successToastMock.mockReset();
    errorToastMock.mockReset();
    setAccessTokenMock.mockReset();
    replaceMock.mockReset();

    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: {
        ...originalLocation,
        assign: jest.fn(),
        reload: jest.fn(),
        replace: replaceMock,
        href: originalLocation.href,
      } as unknown as Location,
    });
  });

  afterAll(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
  });

  it('requires unlock before showing roster', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    expect(
      await screen.findByRole('heading', {
        name: 'Sign In',
        level: 1,
      }),
    ).toBeInTheDocument();

    expect(screen.queryByPlaceholderText('Search Tallwave teammates')).not.toBeInTheDocument();

    const unlockInput = screen.getByTestId('unlock-password-input');
    await user.type(unlockInput, 'Tallwave123');
    await user.click(screen.getByTestId('unlock-submit'));

    expect(await screen.findByPlaceholderText('Search Tallwave teammates')).toBeInTheDocument();
    expect(await screen.findByText('Jordan Carter')).toBeInTheDocument();
    expect(screen.queryByText(/Company Portal/i)).not.toBeInTheDocument();
  });

  it('logs in the selected teammate and navigates to the dashboard', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    const unlockInput = screen.getByTestId('unlock-password-input');
    await user.type(unlockInput, 'Tallwave123');
    await user.click(screen.getByTestId('unlock-submit'));

    const rosterButton = await screen.findByRole('button', { name: /Jordan Carter/i });
    await user.click(rosterButton);

    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith({
        userId: 3,
        password: 'Tallwave123',
      }),
    );
    await waitFor(() => expect(setAccessTokenMock).toHaveBeenCalledWith('token-123'));
    await waitFor(() => expect(successToastMock).toHaveBeenCalled());
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/dashboard'));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('redirects to welcome screen when terms are not accepted', async () => {
    loginMock.mockResolvedValueOnce({
      data: {
        access_token: 'token-456',
        cookie_status: 'valid',
        accepted_terms: false,
      },
    });

    const user = userEvent.setup();
    render(<LoginPage />);

    const unlockInput = screen.getByTestId('unlock-password-input');
    await user.type(unlockInput, 'Tallwave123');
    await user.click(screen.getByTestId('unlock-submit'));

    const rosterButton = await screen.findByRole('button', { name: /Jordan Carter/i });
    await user.click(rosterButton);

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/profile/welcome'));
    expect(successToastMock).toHaveBeenCalled();
    expect(errorToastMock).not.toHaveBeenCalled();
    expect(setAccessTokenMock).toHaveBeenCalledWith('token-456');
    expect(pushMock).not.toHaveBeenCalled();
  });
});
