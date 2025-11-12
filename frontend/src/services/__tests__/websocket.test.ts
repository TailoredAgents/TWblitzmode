import webSocketService from '../websocket';

describe('WebSocketService approval channel scoping', () => {
  beforeEach(() => {
    webSocketService.clearJoinedRooms();
    webSocketService.clearPendingMessages();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    webSocketService.clearJoinedRooms();
    webSocketService.clearPendingMessages();
  });

  it('subscribes to tenant-scoped approval rooms when tenant id provided', () => {
    webSocketService.joinApprovalRoom(42);

    expect(webSocketService.getPendingMessagesSnapshot()).toContainEqual({
      type: 'subscribe',
      channel: 'approval:42',
      channels: ['approval:42'],
    });
    expect(webSocketService.getJoinedRoomsSnapshot()).toContain('approval:42');

    webSocketService.leaveApprovalRoom(42);

    const pendingMessages = webSocketService.getPendingMessagesSnapshot();
    expect(pendingMessages[pendingMessages.length - 1]).toEqual({
      type: 'unsubscribe',
      channel: 'approval:42',
      channels: ['approval:42'],
    });
    expect(webSocketService.getJoinedRoomsSnapshot()).not.toContain('approval:42');
  });

  it('uses current tenant context when none supplied explicitly', () => {
    webSocketService.setUserContext('user-1', 'tenant-abc');

    webSocketService.joinApprovalRoom();

    expect(webSocketService.getPendingMessagesSnapshot()).toContainEqual({
      type: 'subscribe',
      channel: 'approval:tenant-abc',
      channels: ['approval:tenant-abc'],
    });
  });
});
