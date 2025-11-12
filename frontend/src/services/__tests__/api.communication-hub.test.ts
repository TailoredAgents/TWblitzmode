import type { AxiosInstance } from 'axios';
import { apiService } from '../api';

const getApiClient = (): AxiosInstance => {
  const container = apiService as unknown as Record<string, unknown>;
  const client = Reflect.get(container, 'client') as AxiosInstance | undefined;
  if (!client) {
    throw new Error('Expected API client to be available for testing.');
  }
  return client;
};

describe('apiService.getCommunicationConversations', () => {
  it('serializes nested filter objects without losing structure', async () => {
    const getSpy = jest
      .spyOn(getApiClient(), 'get')
      .mockResolvedValue({ data: { data: [] } } as never);

    try {
      await apiService.getCommunicationConversations({
        organization_id: '123',
        status: 'active',
        priority: 'high',
        participant_type: 'human',
        date_range: {
          start: '2024-01-01',
          end: '2024-01-31',
        },
      });

      expect(getSpy).toHaveBeenCalledTimes(1);
      const [requestedUrl] = getSpy.mock.calls[0] ?? [];
      expect(requestedUrl).toBeDefined();
      if (!requestedUrl) {
        return;
      }
      const url = new URL(requestedUrl, 'https://example.com');

      expect(url.searchParams.get('organization_id')).toBe('123');
      expect(url.searchParams.get('status')).toBe('active');
      expect(url.searchParams.get('priority')).toBe('high');
      expect(url.searchParams.get('participant_type')).toBe('human');
      expect(url.searchParams.get('date_range[start]')).toBe('2024-01-01');
      expect(url.searchParams.get('date_range[end]')).toBe('2024-01-31');
    } finally {
      getSpy.mockRestore();
    }
  });

  it('serializes array and boolean filter values correctly', async () => {
    const getSpy = jest
      .spyOn(getApiClient(), 'get')
      .mockResolvedValue({ data: { data: [] } } as never);

    try {
      await apiService.getCommunicationConversations({
        status: 'archived',
        tags: ['urgent', 'vip'],
        include_archived: false,
      });

      const [requestedUrl] = getSpy.mock.calls[0] ?? [];
      expect(requestedUrl).toBeDefined();
      if (!requestedUrl) {
        return;
      }
      const url = new URL(requestedUrl, 'https://example.com');

      expect(url.searchParams.get('status')).toBe('archived');
      expect(url.searchParams.getAll('tags[]')).toEqual(['urgent', 'vip']);
      expect(url.searchParams.get('include_archived')).toBe('false');
    } finally {
      getSpy.mockRestore();
    }
  });
});
