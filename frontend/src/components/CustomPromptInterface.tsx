// Custom Prompt Interface - September 2025 AI Integration
// Interactive interface for custom AI agent prompting

'use client';

import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  Send,
  Bot,
  Sparkles,
  Code,
  FileText,
  Database,
  Zap,
  Settings,
  Copy,
  Download,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Loader2,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { cn } from '../lib/utils';
import { logUserInteraction, logWorkflowStart, logWorkflowComplete } from '../services/agentLogger';

interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  prompt: string;
  variables: string[];
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

interface PromptHistory {
  id: string;
  timestamp: string;
  prompt: string;
  response: string;
  status: 'success' | 'error' | 'processing';
  duration?: number;
  model?: string;
}

interface CustomPromptInterfaceProps {
  organizationId: string | number;
}

const CustomPromptInterface: React.FC<CustomPromptInterfaceProps> = ({ organizationId }) => {
  const [prompt, setPrompt] = useState('');
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<PromptTemplate | null>(null);
  const [history, setHistory] = useState<PromptHistory[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showTemplates, setShowTemplates] = useState(true);
  const [variables, setVariables] = useState<Map<string, string>>(new Map());
  const [selectedModel, setSelectedModel] = useState('gpt-4-turbo');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2000);
  const [showSettings, setShowSettings] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const promptTemplates: PromptTemplate[] = [
    {
      id: 'prospect-analysis',
      name: 'Prospect Analysis',
      description: 'Analyze a prospect and generate insights',
      category: 'Sales',
      prompt: 'Analyze the following prospect and provide key insights:\n\nCompany: {company}\nRole: {role}\nIndustry: {industry}\n\nProvide:\n1. Key pain points they might face\n2. How our solution addresses their needs\n3. Best approach strategy\n4. Potential objections and responses',
      variables: ['company', 'role', 'industry'],
      icon: FileText
    },
    {
      id: 'email-generation',
      name: 'Email Generator',
      description: 'Generate personalized outreach emails',
      category: 'Outreach',
      prompt: 'Write a personalized warm introduction email to {recipient_name} at {company}.\n\nContext: {context}\nOur mutual connection: {mutual_connection}\n\nTone: Professional but friendly\nLength: 150-200 words\nInclude: Clear value proposition and call to action',
      variables: ['recipient_name', 'company', 'context', 'mutual_connection'],
      icon: Send
    },
    {
      id: 'data-query',
      name: 'Data Query Assistant',
      description: 'Generate SQL queries from natural language',
      category: 'Technical',
      prompt: 'Convert this request to a SQL query:\n\n"{request}"\n\nDatabase schema:\n- prospects (id, company, full_name, role, email, status)\n- connectors (id, full_name, email, ranking_score)\n- organizations (id, name, domain, industry)\n\nProvide the SQL query with explanation.',
      variables: ['request'],
      icon: Database
    },
    {
      id: 'workflow-automation',
      name: 'Workflow Designer',
      description: 'Design autonomous workflows',
      category: 'Automation',
      prompt: 'Design an autonomous workflow for: {goal}\n\nConstraints: {constraints}\nResources available: {resources}\n\nProvide:\n1. Step-by-step workflow\n2. Decision points\n3. Success metrics\n4. Error handling\n5. Human approval touchpoints',
      variables: ['goal', 'constraints', 'resources'],
      icon: Zap
    },
    {
      id: 'code-assistant',
      name: 'Code Assistant',
      description: 'Generate or review code',
      category: 'Technical',
      prompt: 'Task: {task}\n\nProgramming language: {language}\nFramework/Library: {framework}\n\nRequirements:\n{requirements}\n\nProvide clean, production-ready code with comments and error handling.',
      variables: ['task', 'language', 'framework', 'requirements'],
      icon: Code
    }
  ];

  const models = [
    { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', description: 'Most capable, best for complex tasks' },
    { id: 'gpt-4', name: 'GPT-4', description: 'High quality, slower' },
    { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: 'Fast and efficient' },
    { id: 'claude-3-opus', name: 'Claude 3 Opus', description: 'Advanced reasoning' },
    { id: 'claude-3-sonnet', name: 'Claude 3 Sonnet', description: 'Balanced performance' }
  ];

  const organizationKey = useMemo(() => {
    if (organizationId === null || organizationId === undefined) {
      return 'default';
    }
    return typeof organizationId === 'string' ? (organizationId.trim() || 'default') : organizationId.toString();
  }, [organizationId]);

  useEffect(() => {
    // Load history from localStorage
    const savedHistory = localStorage.getItem(`prompt_history_${organizationKey}`);
    if (savedHistory) {
      try {
        setHistory(JSON.parse(savedHistory));
      } catch (error) {
        console.error('Failed to load prompt history:', error);
      }
    }
  }, [organizationKey]);

  const handleTemplateSelect = (template: PromptTemplate) => {
    setSelectedTemplate(template);
    setPrompt(template.prompt);

    // Initialize variables
    const vars = new Map<string, string>(
      template.variables.map((variable) => [variable, ''])
    );
    setVariables(vars);

    // Log template selection
    logUserInteraction('template_select', 'CustomPromptInterface', {
      template_id: template.id,
      template_name: template.name
    });
  };

  const interpolateVariables = (template: string, vars: Map<string, string>) => {
    let result = template;
    vars.forEach((value, key) => {
      const placeholder = `{${key}}`;
      result = result.split(placeholder).join(value);
    });
    return result;
  };

  const handleSubmit = async () => {
    if (!prompt.trim()) return;

    const startTime = Date.now();
    const workflowId = `prompt_${Date.now()}`;
    const finalPrompt = selectedTemplate
      ? interpolateVariables(prompt, variables)
      : prompt;

    setLoading(true);
    setResponse('');

    // Log workflow start
    await logWorkflowStart('ai-prompt', workflowId, 'custom_prompt');

    const historyEntry: PromptHistory = {
      id: workflowId,
      timestamp: new Date().toISOString(),
      prompt: finalPrompt,
      response: '',
      status: 'processing',
      model: selectedModel
    };

    setHistory(prev => [historyEntry, ...prev]);

    try {
      throw new Error('Custom prompt API is not configured.');
    } catch (error) {
      console.error('Failed to process prompt:', error);
      const message = error instanceof Error ? error.message : 'Error processing prompt.';
      setResponse(message);

      setHistory(prev => prev.map(h =>
        h.id === workflowId
          ? { ...h, response: message, status: 'error' as const }
          : h
      ));

      await logWorkflowComplete('ai-prompt', workflowId, { success: false, error: String(error) }, Date.now() - startTime);
    } finally {
      setLoading(false);
    }
  };



  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    // You could add a toast notification here
  };

  const downloadResponse = () => {
    const blob = new Blob([response], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ai_response_${Date.now()}.txt`;
    a.click();
  };

  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Custom AI Prompting</h2>
          <p className="text-muted-foreground mt-1">
            Interact with AI agents using custom prompts and templates
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="px-4 py-2 bg-muted/30 text-foreground rounded-lg hover:bg-muted/50 transition-colors flex items-center gap-2"
          >
            <FileText className="w-4 h-4" />
            History ({history.length})
          </button>

          <button
            onClick={() => setShowSettings(!showSettings)}
            className="p-2 rounded-lg hover:bg-muted/20 transition-colors"
          >
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <GlassCard className="p-4">
          <div className="space-y-4">
            <h3 className="font-semibold text-foreground">Model Settings</h3>

            <div>
              <label className="block text-sm font-medium text-foreground mb-2">Model</label>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3 py-2 bg-background/50 border border-border/20 rounded-lg text-foreground"
              >
                {models.map(model => (
                  <option key={model.id} value={model.id}>
                    {model.name} - {model.description}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Temperature: {temperature}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Max Tokens: {maxTokens}
                </label>
                <input
                  type="range"
                  min="100"
                  max="4000"
                  step="100"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                  className="w-full"
                />
              </div>
            </div>
          </div>
        </GlassCard>
      )}

      {/* Templates */}
      {showTemplates && (
        <GlassCard className="p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-foreground">Prompt Templates</h3>
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className="p-1 rounded hover:bg-muted/20"
            >
              {showTemplates ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {promptTemplates.map((template) => {
              const Icon = template.icon;
              return (
                <button
                  key={template.id}
                  onClick={() => handleTemplateSelect(template)}
                  className={cn(
                    'p-4 rounded-lg border transition-all text-left',
                    selectedTemplate?.id === template.id
                      ? 'bg-primary/10 border-primary/40'
                      : 'bg-muted/20 border-border/20 hover:bg-muted/30'
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                      <Icon className="w-5 h-5 text-primary" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-medium text-foreground">{template.name}</h4>
                      <p className="text-sm text-muted-foreground mt-1">{template.description}</p>
                      <span className="inline-block px-2 py-1 bg-muted/30 rounded text-xs text-muted-foreground mt-2">
                        {template.category}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* Variable Inputs */}
      {selectedTemplate && selectedTemplate.variables.length > 0 && (
        <GlassCard className="p-4">
          <h3 className="font-semibold text-foreground mb-4">Template Variables</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {selectedTemplate.variables.map(variable => (
              <div key={variable}>
                <label className="block text-sm font-medium text-foreground mb-1 capitalize">
                  {variable.replace('_', ' ')}
                </label>
                <input
                  type="text"
                  value={variables.get(variable) ?? ''}
                  onChange={(event) =>
                    setVariables((previous) => {
                      const next = new Map(previous);
                      next.set(variable, event.target.value);
                      return next;
                    })
                  }
                  className="w-full px-3 py-2 bg-background/50 border border-border/20 rounded-lg text-foreground"
                  placeholder={`Enter ${variable.replace('_', ' ')}`}
                />
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Main Interface */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input Section */}
        <GlassCard className="p-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-foreground">Prompt</h3>
              {selectedTemplate && (
                <button
                  onClick={() => {
                    setSelectedTemplate(null);
                    setPrompt('');
                    setVariables(new Map());
                  }}
                  className="text-sm text-muted-foreground hover:text-foreground"
                >
                  Clear template
                </button>
              )}
            </div>

            <textarea
              ref={textareaRef}
              value={selectedTemplate ? interpolateVariables(prompt, variables) : prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                adjustTextareaHeight();
              }}
              onInput={adjustTextareaHeight}
              placeholder="Enter your prompt here or select a template..."
              className="w-full min-h-[200px] max-h-[400px] px-4 py-3 bg-background/50 border border-border/20 rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 resize-none"
              disabled={loading}
            />

            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                {prompt.length} characters
              </div>

              <button
                onClick={handleSubmit}
                disabled={loading || !prompt.trim()}
                className={cn(
                  'px-6 py-2 rounded-lg font-medium transition-all flex items-center gap-2',
                  loading || !prompt.trim()
                    ? 'bg-muted/30 text-muted-foreground cursor-not-allowed'
                    : 'bg-primary text-primary-foreground hover:bg-primary/90'
                )}
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate
                  </>
                )}
              </button>
            </div>
          </div>
        </GlassCard>

        {/* Response Section */}
        <GlassCard className="p-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-foreground">Response</h3>

              {response && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(response)}
                    className="p-2 rounded-lg hover:bg-muted/20 transition-colors"
                    title="Copy to clipboard"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                  <button
                    onClick={downloadResponse}
                    className="p-2 rounded-lg hover:bg-muted/20 transition-colors"
                    title="Download response"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                  <button
                    onClick={handleSubmit}
                    disabled={loading}
                    className="p-2 rounded-lg hover:bg-muted/20 transition-colors"
                    title="Regenerate"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            <div className="min-h-[200px] max-h-[400px] overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center h-[200px]">
                  <div className="text-center">
                    <Bot className="w-12 h-12 text-primary mx-auto mb-4 animate-pulse" />
                    <p className="text-muted-foreground">AI is thinking...</p>
                  </div>
                </div>
              ) : response ? (
                <pre className="whitespace-pre-wrap text-foreground font-mono text-sm">
                  {response}
                </pre>
              ) : (
                <div className="flex items-center justify-center h-[200px] text-muted-foreground">
                  <p>Response will appear here</p>
                </div>
              )}
            </div>
          </div>
        </GlassCard>
      </div>

      {/* History Panel */}
      {showHistory && history.length > 0 && (
        <GlassCard className="p-6">
          <h3 className="text-lg font-semibold text-foreground mb-4">Prompt History</h3>

          <div className="space-y-3 max-h-[400px] overflow-y-auto">
            {history.map((item) => (
              <div
                key={item.id}
                className="p-4 bg-muted/20 rounded-lg border border-border/20"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {item.status === 'success' && <CheckCircle className="w-4 h-4 text-green-500" />}
                    {item.status === 'error' && <AlertCircle className="w-4 h-4 text-red-500" />}
                    {item.status === 'processing' && <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />}
                    <span className="text-sm text-muted-foreground">
                      {new Date(item.timestamp).toLocaleString()}
                    </span>
                    {item.duration && (
                      <span className="text-xs text-muted-foreground">
                        ({(item.duration / 1000).toFixed(2)}s)
                      </span>
                    )}
                  </div>

                  <button
                    onClick={() => {
                      setPrompt(item.prompt);
                      setResponse(item.response);
                    }}
                    className="text-xs text-primary hover:text-primary/80"
                  >
                    Load
                  </button>
                </div>

                <p className="text-sm text-foreground line-clamp-2">{item.prompt}</p>
                {item.response && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{item.response}</p>
                )}
              </div>
            ))}
          </div>

          <button
            onClick={() => {
              setHistory([]);
              localStorage.removeItem(`prompt_history_${organizationKey}`);
            }}
            className="mt-4 text-sm text-red-500 hover:text-red-400"
          >
            Clear History
          </button>
        </GlassCard>
      )}
    </div>
  );
};

export default CustomPromptInterface;
