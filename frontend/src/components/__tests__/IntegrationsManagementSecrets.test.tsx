import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IntegrationsManagement from '../IntegrationsManagement';
import { apiService } from '../../services/api';

const toastSuccess = jest.fn();
const toastError = jest.fn();

jest.mock('../ui/ToastContainer', () => ({
  useToastActions: () => ({
    success: toastSuccess,
    error: toastError,
  }),
}));

jest.mock('../../services/api', () => {
  const actual = jest.requireActual('../../services/api');
  return {
    __esModule: true,
    ...actual,
    apiService: {
      getTenantIntegrations: jest.fn(),
      setTenantIntegrations: jest.fn(),
      testIntegrationConnection: jest.fn(),
      getCredentialSecretValue: jest.fn(),
    },
  };
});

describe('IntegrationsManagement credential copying', () => {
  const originalClipboard = navigator.clipboard;
  let originalWriteText: Clipboard['writeText'] | undefined;
  let clipboardWriteMock: jest.Mock<Promise<void>, [string]>;

  beforeAll(() => {
    clipboardWriteMock = jest.fn().mockResolvedValue(undefined);

    if (!navigator.clipboard) {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: clipboardWriteMock,
        } as unknown as Clipboard,
      });
      originalWriteText = undefined;
    } else {
      originalWriteText = navigator.clipboard.writeText.bind(navigator.clipboard);
      Object.defineProperty(navigator.clipboard, 'writeText', {
        configurable: true,
        value: clipboardWriteMock,
      });
    }
  });

  afterEach(() => {
    jest.clearAllMocks();
    clipboardWriteMock.mockReset();
    clipboardWriteMock.mockResolvedValue(undefined);
  });

  afterAll(() => {
    if (navigator.clipboard) {
      Object.defineProperty(
        navigator.clipboard,
        'writeText',
        originalWriteText
          ? { configurable: true, value: originalWriteText }
          : { configurable: true, value: () => Promise.resolve() },
      );
    }

    if (originalClipboard === undefined) {
      delete (navigator as unknown as { clipboard?: Clipboard }).clipboard;
    } else {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: originalClipboard,
      });
    }
  });

  it('copies newly entered secrets directly from the input', async () => {
    const getIntegrationsMock = apiService.getTenantIntegrations as jest.Mock;
    const getSecretValueMock = apiService.getCredentialSecretValue as jest.Mock;

    getIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          openai_api_key: {
            configured: true,
            masked: '',
            vaultItemId: 'vault-001',
          },
        },
      },
    });

    const user = userEvent.setup();
    render(<IntegrationsManagement organizationId={101} />);

    const configureButtons = await screen.findAllByTitle('Configure');
    await user.click(configureButtons[0]);

    await screen.findByRole('heading', { name: /configure openai/i });
    const secretInput = screen.getByLabelText<HTMLInputElement>(/openai api key/i);
    secretInput.value = '';
    await user.type(secretInput, 'sk-live-entry');

    const copyButton = await screen.findByTitle('Copy to clipboard');
    await user.click(copyButton);

    expect(getSecretValueMock).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith('API key copied to clipboard');
    expect(toastError).not.toHaveBeenCalled();
  });

  it('fetches and copies stored secrets when input is empty', async () => {
    const getIntegrationsMock = apiService.getTenantIntegrations as jest.Mock;
    const getSecretValueMock = apiService.getCredentialSecretValue as jest.Mock;

    getIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          openai_api_key: {
            configured: true,
            masked: '',
            vaultItemId: 'vault-002',
          },
        },
      },
    });

    getSecretValueMock.mockResolvedValue({
      status: 200,
      data: {
        value: 'sk-secret-openai',
      },
    });

    const user = userEvent.setup();
    render(<IntegrationsManagement organizationId={202} />);

    const configureButtons = await screen.findAllByTitle('Configure');
    await user.click(configureButtons[0]);

    const copyButton = await screen.findByTitle('Copy to clipboard');
    await user.click(copyButton);

    await waitFor(() => {
      expect(getSecretValueMock).toHaveBeenCalledWith('openai_api_key', 202);
    });
    expect(toastSuccess).toHaveBeenCalledWith('API key copied to clipboard');
    expect(toastError).not.toHaveBeenCalled();
  });

  it('fetches stored secrets when the masked placeholder is still present', async () => {
    const getIntegrationsMock = apiService.getTenantIntegrations as jest.Mock;
    const getSecretValueMock = apiService.getCredentialSecretValue as jest.Mock;

    getIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          openai_api_key: {
            configured: true,
            masked: '••••••••',
            vaultItemId: 'vault-003',
          },
        },
      },
    });

    getSecretValueMock.mockResolvedValue({
      status: 200,
      data: {
        value: 'sk-secret-masked',
      },
    });

    const user = userEvent.setup();
    render(<IntegrationsManagement organizationId={303} />);

    const configureButtons = await screen.findAllByTitle('Configure');
    await user.click(configureButtons[0]);

    await screen.findByRole('heading', { name: /configure openai/i });
    const copyButton = await screen.findByTitle('Copy to clipboard');
    await user.click(copyButton);

    await waitFor(() => {
      expect(getSecretValueMock).toHaveBeenCalledWith('openai_api_key', 303);
    });
    expect(toastSuccess).toHaveBeenCalledWith('API key copied to clipboard');
    expect(toastError).not.toHaveBeenCalled();
  });

  it('masks LinkedIn secrets and renders optional webhook secrets as password inputs', async () => {
    const getIntegrationsMock = apiService.getTenantIntegrations as jest.Mock;

    getIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          linkedin_li_at: {
            configured: true,
            masked: 'li_at_cookie_value',
            vaultItemId: 'vault-li-at',
          },
          linkedin_jsessionid: {
            configured: true,
            masked: 'linkedin_jsession_cookie',
            vaultItemId: 'vault-jsession',
          },
          linkedin_cookies_json: {
            configured: true,
            masked: '{"cookie":"secret"}',
            vaultItemId: 'vault-cookie-json',
          },
          apify_api_token: {
            configured: true,
            masked: 'apify-token-value',
            vaultItemId: 'vault-apify-token',
          },
          apify_webhook_secret: {
            configured: true,
            masked: 'apify-webhook-secret',
            vaultItemId: 'vault-apify-webhook',
          },
          apify_li_cookie_secret_name: {
            configured: true,
            masked: 'li-cookie-secret',
            vaultItemId: 'vault-apify-cookie',
          },
        },
      },
    });

    const user = userEvent.setup();
    render(<IntegrationsManagement organizationId={404} />);

    await screen.findByRole('heading', { name: /linkedin/i });

    const headings = screen.getAllByRole('heading', { level: 3 });
    const configureButtons = await screen.findAllByTitle('Configure');
    const linkedinIndex = headings.findIndex((heading) => /linkedin/i.test(heading.textContent ?? ''));
    const apifyIndex = headings.findIndex((heading) => /apify/i.test(heading.textContent ?? ''));

    expect(linkedinIndex).toBeGreaterThan(-1);
    expect(apifyIndex).toBeGreaterThan(-1);

    const labelFor = (field: string) => `${field.replace('_', ' ')}:`;
    const liAtLabel = await screen.findByText((content) => {
      return content.trim().toLowerCase() === labelFor('linkedin_li_at').toLowerCase();
    });
    const liAtRow = liAtLabel.parentElement;
    expect(liAtRow).not.toBeNull();
    const liAtValue = liAtRow?.querySelector('span.font-mono');
    expect(liAtValue).not.toBeNull();
    expect(liAtValue?.textContent ?? '').toContain('...');
    expect(liAtValue?.textContent ?? '').not.toContain('li_at_cookie_value');

    const jsessionLabel = screen.getByText((content) => {
      return content.trim().toLowerCase() === labelFor('linkedin_jsessionid').toLowerCase();
    });
    const jsessionRow = jsessionLabel.parentElement;
    expect(jsessionRow).not.toBeNull();
    const jsessionValue = jsessionRow?.querySelector('span.font-mono');
    expect(jsessionValue).not.toBeNull();
    expect(jsessionValue?.textContent ?? '').toContain('...');
    expect(jsessionValue?.textContent ?? '').not.toContain('linkedin_jsession_cookie');

    const linkedinButton = configureButtons.at(linkedinIndex);
    expect(linkedinButton).toBeDefined();
    if (!linkedinButton) {
      throw new Error('LinkedIn Configure button not found');
    }
    await user.click(linkedinButton);

    await screen.findByRole('heading', { name: /configure linkedin/i });

    const liAtInput = await screen.findByLabelText<HTMLInputElement>(/linkedin li at/i);
    const jsessionInput = screen.getByLabelText<HTMLInputElement>(/linkedin jsessionid/i);
    const cookiesInput = screen.getByLabelText<HTMLInputElement>(/linkedin cookies json/i);
    expect(liAtInput).toHaveAttribute('type', 'password');
    expect(jsessionInput).toHaveAttribute('type', 'password');
    expect(cookiesInput).toHaveAttribute('type', 'password');

    const closeButton = screen.getByRole('button', { name: '✕' });
    await user.click(closeButton);

    const apifyButton = configureButtons.at(apifyIndex);
    expect(apifyButton).toBeDefined();
    if (!apifyButton) {
      throw new Error('Apify Configure button not found');
    }
    await user.click(apifyButton);

    await screen.findByRole('heading', { name: /configure apify/i });
    const webhookInput = await screen.findByLabelText<HTMLInputElement>(/apify webhook secret/i);
    expect(webhookInput).toHaveAttribute('type', 'password');
    const webhookCopyButton = webhookInput.parentElement?.querySelector('button[title="Copy to clipboard"]');
    expect(webhookCopyButton).not.toBeNull();
  });
});

describe('IntegrationsManagement secret persistence', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('does not resubmit masked placeholders when saving configuration without changes', async () => {
    const getIntegrationsMock = apiService.getTenantIntegrations as jest.Mock;
    const setIntegrationsMock = apiService.setTenantIntegrations as jest.Mock;

    const maskedValue = '••••••••';

    getIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          openai_api_key: {
            configured: true,
            masked: maskedValue,
            vaultItemId: 'vault-010',
          },
        },
      },
    });

    setIntegrationsMock.mockResolvedValue({
      status: 200,
      data: {
        secrets: {
          openai_api_key: {
            configured: true,
            masked: maskedValue,
            vaultItemId: 'vault-010',
          },
        },
      },
      message: 'Saved credentials',
    });

    const user = userEvent.setup();
    render(<IntegrationsManagement organizationId={404} />);

    const configureButtons = await screen.findAllByTitle('Configure');
    await user.click(configureButtons[0]);

    await screen.findByRole('heading', { name: /configure openai/i });
    const saveButton = await screen.findByRole('button', { name: /save configuration/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(setIntegrationsMock).toHaveBeenCalledTimes(1);
    });

    const payload = setIntegrationsMock.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.secrets).toBeUndefined();
    expect(JSON.stringify(payload)).not.toContain('•');
    expect(toastSuccess).toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });
});
