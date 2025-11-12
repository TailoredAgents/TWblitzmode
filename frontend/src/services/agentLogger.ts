/**
 * Agent Logger Service - Frontend Component
 * September 2025 AI Integration
 * Client-side logging service for AI agents and user interactions
 */

import { getAccessToken } from '../lib/authToken';

export enum LogLevel {
  DEBUG = 'debug',
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  CRITICAL = 'critical'
}

export enum AgentEventType {
  AGENT_START = 'agent_start',
  AGENT_STOP = 'agent_stop',
  AGENT_ERROR = 'agent_error',
  TASK_START = 'task_start',
  TASK_COMPLETE = 'task_complete',
  TASK_ERROR = 'task_error',
  API_CALL = 'api_call',
  API_RESPONSE = 'api_response',
  WORKFLOW_START = 'workflow_start',
  WORKFLOW_COMPLETE = 'workflow_complete',
  USER_INTERACTION = 'user_interaction',
  APPROVAL_REQUEST = 'approval_request',
  APPROVAL_DECISION = 'approval_decision',
  COMMUNICATION = 'communication',
  SYSTEM_EVENT = 'system_event',
  UI_EVENT = 'ui_event',
  NAVIGATION = 'navigation'
}

interface LogEvent {
  timestamp: string;
  eventId: string;
  sessionId: string;
  eventType: AgentEventType;
  agentId?: string;
  level: LogLevel;
  message: string;
  tenantId?: string;
  userId?: string;
  workflowId?: string;
  taskId?: string;
  metadata?: Record<string, unknown>;
  url?: string;
  userAgent?: string;
}

interface AgentSummary {
  agentId: string;
  startTime: Date;
  lastActivity: Date;
  eventsCount: number;
  status: string;
  currentTask?: string;
  errorCount: number;
}

class FrontendAgentLogger {
  private sessionId: string;
  private userId?: string;
  private tenantId?: string;
  private eventBuffer: LogEvent[] = [];
  private maxBufferSize = 100;
  private flushInterval = 30000; // 30 seconds
  private agentSummaries: Map<string, AgentSummary> = new Map();

  constructor() {
    this.sessionId = this.generateUUID();

    // Only set up browser-specific features on client side
    if (typeof window !== 'undefined') {
      this.setupPeriodicFlush();
      this.setupUserTracking();
      this.setupUnloadHandler();
    }
  }

  private generateUUID(): string {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
      const r = Math.random() * 16 | 0;
      const v = char === 'x' ? r : ((r & 0x3) | 0x8);
      return v.toString(16);
    });
  }

  private setupUserTracking(): void {
    // Extract user/tenant info from local storage or API
    if (typeof window !== 'undefined' && typeof localStorage !== 'undefined') {
      try {
        const storedUser = localStorage.getItem('user');
        if (storedUser) {
          const user = JSON.parse(storedUser);
          this.userId = user.id?.toString();
          this.tenantId = user.organization?.id?.toString();
        }
      } catch (error) {
        console.warn('Failed to extract user tracking info:', error);
      }
    }
  }

  private setupPeriodicFlush(): void {
    setInterval(() => {
      this.flush();
    }, this.flushInterval);
  }

  private setupUnloadHandler(): void {
    if (typeof window !== 'undefined') {
      window.addEventListener('beforeunload', () => {
        this.flush(true); // Synchronous flush on unload
      });
    }
  }

  async logEvent(
    eventType: AgentEventType,
    message: string,
    level: LogLevel = LogLevel.INFO,
    agentId?: string,
    metadata?: Record<string, unknown>,
    workflowId?: string,
    taskId?: string
  ): Promise<void> {
    const viewportMetadata = typeof window !== 'undefined'
      ? {
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
          },
          performance: performance.now(),
        }
      : {};

    const locationHref = typeof window !== 'undefined' ? window.location?.href : undefined;
    const userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : undefined;

    const event: LogEvent = {
      timestamp: new Date().toISOString(),
      eventId: this.generateUUID(),
      sessionId: this.sessionId,
      eventType,
      ...(agentId && { agentId }),
      level,
      message,
      ...(this.tenantId && { tenantId: this.tenantId }),
      ...(this.userId && { userId: this.userId }),
      ...(workflowId && { workflowId }),
      ...(taskId && { taskId }),
      metadata: {
        ...metadata,
        ...viewportMetadata,
      },
      ...(locationHref ? { url: locationHref } : {}),
      ...(userAgent ? { userAgent } : {}),
    };

    // Console logging for development
    const logMessage = `[${eventType.toUpperCase()}] ${agentId ? `Agent ${agentId}: ` : ''}${message}`;

    if (level === LogLevel.ERROR || level === LogLevel.CRITICAL) {
      console.error(logMessage, metadata);
    } else if (level === LogLevel.WARNING) {
      console.warn(logMessage, metadata);
    } else {
      console.info(logMessage, metadata);
    }

    // Add to buffer
    this.eventBuffer.push(event);

    // Update agent tracking
    if (agentId) {
      this.updateAgentTracking(agentId, eventType, event);
    }

    // Flush if buffer is full
    if (this.eventBuffer.length >= this.maxBufferSize) {
      await this.flush();
    }

    // Immediate flush for critical events
    if (level === LogLevel.CRITICAL || level === LogLevel.ERROR) {
      await this.flush();
    }
  }

  private updateAgentTracking(agentId: string, eventType: AgentEventType, event: LogEvent): void {
    let summary = this.agentSummaries.get(agentId);

    if (!summary) {
      summary = {
        agentId,
        startTime: new Date(),
        lastActivity: new Date(),
        eventsCount: 0,
        status: 'unknown',
        errorCount: 0
      };
      this.agentSummaries.set(agentId, summary);
    }

    summary.lastActivity = new Date();
    summary.eventsCount++;

    // Update status based on event type
    switch (eventType) {
      case AgentEventType.AGENT_START:
        summary.status = 'active';
        break;
      case AgentEventType.AGENT_STOP:
        summary.status = 'stopped';
        break;
      case AgentEventType.AGENT_ERROR:
      case AgentEventType.TASK_ERROR:
        summary.status = 'error';
        summary.errorCount++;
        break;
      case AgentEventType.TASK_START:
        summary.status = 'busy';
        if (event.taskId) {
          summary.currentTask = event.taskId;
        }
        break;
      case AgentEventType.TASK_COMPLETE:
        summary.status = 'idle';
        delete summary.currentTask;
        break;
    }
  }

  async flush(sync: boolean = false): Promise<void> {
    if (this.eventBuffer.length === 0) return;

    const events = [...this.eventBuffer];
    this.eventBuffer = [];

    const token = typeof window !== 'undefined' ? getAccessToken() : null;
    if (!token) {
      // Without an access token the backend will reject the request; avoid unnecessary 401 chatter.
      this.eventBuffer.unshift(...events);
      this.eventBuffer = this.eventBuffer.slice(-this.maxBufferSize);
      return;
    }

    const payload = {
      session_id: this.sessionId,
      events,
    };

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    const requestInit: RequestInit = {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      credentials: 'include',
      keepalive: sync,
    };

    try {
      if (typeof fetch !== 'undefined') {
        await fetch('/api/logs/agent-events', requestInit);
      }
    } catch (error) {
      console.error('Failed to flush agent logs:', error);
      // Re-add events to buffer on failure (with limit to avoid infinite growth)
      if (this.eventBuffer.length < this.maxBufferSize / 2) {
        this.eventBuffer.unshift(...events.slice(-this.maxBufferSize / 2));
      }
    }
  }

  // Convenience methods for common events
  async logAgentStart(agentId: string, agentType: string, config: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.AGENT_START,
      `Agent started: ${agentType}`,
      LogLevel.INFO,
      agentId,
      { agentType, config }
    );
  }

  async logAgentStop(agentId: string, reason: string = 'normal'): Promise<void> {
    await this.logEvent(
      AgentEventType.AGENT_STOP,
      `Agent stopped: ${reason}`,
      LogLevel.INFO,
      agentId,
      { reason }
    );
  }

  async logTaskStart(agentId: string, taskId: string, taskType: string, taskData: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.TASK_START,
      `Task started: ${taskType}`,
      LogLevel.INFO,
      agentId,
      { taskType, taskData },
      undefined,
      taskId
    );
  }

  async logTaskComplete(agentId: string, taskId: string, result: Record<string, unknown>, durationMs: number): Promise<void> {
    await this.logEvent(
      AgentEventType.TASK_COMPLETE,
      `Task completed in ${durationMs.toFixed(2)}ms`,
      LogLevel.INFO,
      agentId,
      { result, durationMs },
      undefined,
      taskId
    );
  }

  async logTaskError(agentId: string, taskId: string, error: string, stackTrace?: string): Promise<void> {
    await this.logEvent(
      AgentEventType.TASK_ERROR,
      `Task failed: ${error}`,
      LogLevel.ERROR,
      agentId,
      { error, stackTrace },
      undefined,
      taskId
    );
  }

  async logWorkflowStart(agentId: string, workflowId: string, workflowType: string): Promise<void> {
    await this.logEvent(
      AgentEventType.WORKFLOW_START,
      `Workflow started: ${workflowType}`,
      LogLevel.INFO,
      agentId,
      { workflowType },
      workflowId
    );
  }

  async logWorkflowComplete(agentId: string, workflowId: string, result: Record<string, unknown>, durationMs: number): Promise<void> {
    await this.logEvent(
      AgentEventType.WORKFLOW_COMPLETE,
      `Workflow completed in ${durationMs.toFixed(2)}ms`,
      LogLevel.INFO,
      agentId,
      { result, durationMs },
      workflowId
    );
  }

  async logUserInteraction(interactionType: string, element: string, data?: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.USER_INTERACTION,
      `User ${interactionType}: ${element}`,
      LogLevel.INFO,
      undefined,
      { interactionType, element, ...data }
    );
  }

  async logApprovalRequest(agentId: string, approvalId: string, requestType: string, details: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.APPROVAL_REQUEST,
      `Approval requested: ${requestType}`,
      LogLevel.INFO,
      agentId,
      { approvalId, requestType, details }
    );
  }

  async logApprovalDecision(agentId: string, approvalId: string, decision: string, feedback?: string): Promise<void> {
    await this.logEvent(
      AgentEventType.APPROVAL_DECISION,
      `Approval ${decision}: ${approvalId}`,
      LogLevel.INFO,
      agentId,
      { approvalId, decision, feedback }
    );
  }

  async logNavigation(from: string, to: string, method: string = 'click'): Promise<void> {
    await this.logEvent(
      AgentEventType.NAVIGATION,
      `Navigation: ${from} → ${to}`,
      LogLevel.DEBUG,
      undefined,
      { from, to, method }
    );
  }

  async logUIEvent(eventType: string, component: string, data?: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.UI_EVENT,
      `UI ${eventType}: ${component}`,
      LogLevel.DEBUG,
      undefined,
      { eventType, component, ...data }
    );
  }

  async logAPICall(endpoint: string, method: string, params?: Record<string, unknown>): Promise<void> {
    await this.logEvent(
      AgentEventType.API_CALL,
      `API call: ${method} ${endpoint}`,
      LogLevel.DEBUG,
      undefined,
      { endpoint, method, params }
    );
  }

  async logAPIResponse(endpoint: string, statusCode: number, responseTimeMs: number, error?: string): Promise<void> {
    const level = statusCode >= 400 ? LogLevel.ERROR : LogLevel.DEBUG;
    await this.logEvent(
      AgentEventType.API_RESPONSE,
      `API response: ${statusCode} in ${responseTimeMs.toFixed(2)}ms${error ? ` - ${error}` : ''}`,
      level,
      undefined,
      { endpoint, statusCode, responseTimeMs, error }
    );
  }

  getAgentSummary(agentId: string): AgentSummary | undefined {
    return this.agentSummaries.get(agentId);
  }

  getAllAgentsSummary(): AgentSummary[] {
    return Array.from(this.agentSummaries.values());
  }

  getSessionId(): string {
    return this.sessionId;
  }

  setUserContext(userId: string, tenantId: string): void {
    this.userId = userId;
    this.tenantId = tenantId;
  }
}

// Global agent logger instance
export const agentLogger = new FrontendAgentLogger();

// Export convenience functions
export const logAgentStart = (agentId: string, agentType: string, config: Record<string, unknown>) =>
  agentLogger.logAgentStart(agentId, agentType, config);

export const logAgentStop = (agentId: string, reason?: string) =>
  agentLogger.logAgentStop(agentId, reason);

export const logTaskStart = (agentId: string, taskId: string, taskType: string, taskData: Record<string, unknown>) =>
  agentLogger.logTaskStart(agentId, taskId, taskType, taskData);

export const logTaskComplete = (agentId: string, taskId: string, result: Record<string, unknown>, durationMs: number) =>
  agentLogger.logTaskComplete(agentId, taskId, result, durationMs);

export const logTaskError = (agentId: string, taskId: string, error: string, stackTrace?: string) =>
  agentLogger.logTaskError(agentId, taskId, error, stackTrace);

export const logWorkflowStart = (agentId: string, workflowId: string, workflowType: string) =>
  agentLogger.logWorkflowStart(agentId, workflowId, workflowType);

export const logWorkflowComplete = (agentId: string, workflowId: string, result: Record<string, unknown>, durationMs: number) =>
  agentLogger.logWorkflowComplete(agentId, workflowId, result, durationMs);

export const logUserInteraction = (interactionType: string, element: string, data?: Record<string, unknown>) =>
  agentLogger.logUserInteraction(interactionType, element, data);

export const logApprovalRequest = (agentId: string, approvalId: string, requestType: string, details: Record<string, unknown>) =>
  agentLogger.logApprovalRequest(agentId, approvalId, requestType, details);

export const logApprovalDecision = (agentId: string, approvalId: string, decision: string, feedback?: string) =>
  agentLogger.logApprovalDecision(agentId, approvalId, decision, feedback);

export const logNavigation = (from: string, to: string, method?: string) =>
  agentLogger.logNavigation(from, to, method);

export const logUIEvent = (eventType: string, component: string, data?: Record<string, unknown>) =>
  agentLogger.logUIEvent(eventType, component, data);

export const logAPICall = (endpoint: string, method: string, params?: Record<string, unknown>) =>
  agentLogger.logAPICall(endpoint, method, params);

export const logAPIResponse = (endpoint: string, statusCode: number, responseTimeMs: number, error?: string) =>
  agentLogger.logAPIResponse(endpoint, statusCode, responseTimeMs, error);

export default agentLogger;
