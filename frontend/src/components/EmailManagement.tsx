import React, { useState, useEffect, useCallback } from 'react';
import { Mail, Send, Clock, Plus, Edit2, Trash2, CheckCircle2, AlertCircle, FileText, Users } from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { useToastActions } from './ui/ToastContainer';
import { cn } from '../lib/utils';
import { apiService } from '../services/api';
import type { EmailCampaign, EmailTemplate, EmailMetrics } from '../types';

interface EmailManagementProps {
  organizationId: number;
}

const EmailManagement: React.FC<EmailManagementProps> = ({ organizationId }) => {
  const [activeTab, setActiveTab] = useState<'campaigns' | 'templates' | 'metrics'>('campaigns');
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [metrics, setMetrics] = useState<EmailMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const { success, error } = useToastActions();

  const loadEmailData = useCallback(async () => {
    setLoading(true);
    try {
      switch (activeTab) {
        case 'campaigns':
          // Load email campaigns
          const campaignsData = await apiService.getEmailCampaigns(organizationId);
          setCampaigns(campaignsData.data ?? []);
          break;
        case 'templates':
          // Load email templates
          const templatesData = await apiService.getEmailTemplates(organizationId);
          setTemplates(templatesData.data ?? []);
          break;
        case 'metrics':
          // Load email metrics
          const metricsData = await apiService.getEmailMetrics(organizationId);
          setMetrics(metricsData.data ?? null);
          break;
      }
    } catch (_err) {
      console.error('Failed to load email data:', _err);
      error('Failed to load email data', 'Please check your connection and try again');

      // Clear any existing data on error
      setCampaigns([]);
      setTemplates([]);
      setMetrics(null);
    } finally {
      setLoading(false);
    }
  }, [activeTab, organizationId, error]);

  useEffect(() => {
    void loadEmailData();
  }, [loadEmailData]);

  const handlePauseCampaign = async (campaignId: string) => {
    try {
      await apiService.pauseEmailCampaign(campaignId);
      success('Campaign paused');
      await loadEmailData();
    } catch (_err) {
      error('Failed to pause campaign', 'Please try again');
    }
  };

  const handleDeleteTemplate = async (templateId: string) => {
    if (window.confirm('Are you sure you want to delete this template?')) {
      try {
        await apiService.deleteEmailTemplate(templateId);
        success('Template deleted');
        await loadEmailData();
      } catch (_err) {
        error('Failed to delete template', 'Please try again');
      }
    }
  };

  const getStatusColor = (status: EmailCampaign['status']) => {
    switch (status) {
      case 'active': return 'text-green-600 bg-green-100';
      case 'scheduled': return 'text-blue-600 bg-blue-100';
      case 'completed': return 'text-gray-600 bg-gray-100';
      case 'paused': return 'text-yellow-600 bg-yellow-100';
      default: return 'text-gray-500 bg-gray-100';
    }
  };

  const getCategoryIcon = (category: EmailTemplate['category']) => {
    switch (category) {
      case 'introduction': return <Users className="w-4 h-4" />;
      case 'follow-up': return <Clock className="w-4 h-4" />;
      case 'proposal': return <FileText className="w-4 h-4" />;
      case 'meeting': return <Mail className="w-4 h-4" />;
      default: return <Mail className="w-4 h-4" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Email Management</h2>
          <p className="text-muted-foreground">Manage email campaigns, templates, and automation</p>
        </div>
        <div className="flex items-center gap-2">
          {activeTab === 'campaigns' && (
            <button
              onClick={() => error('Campaign creation not available yet', 'This preview build does not include campaign authoring.')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              <Plus className="w-4 h-4" />
              New Campaign
            </button>
          )}
          {activeTab === 'templates' && (
            <button
              onClick={() => error('Template creation not available yet', 'Add templates via the backend or contact support.')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              <Plus className="w-4 h-4" />
              New Template
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <GlassCard className="p-1">
        <div className="flex space-x-1">
          <button
            onClick={() => setActiveTab('campaigns')}
            className={cn(
              'flex-1 px-4 py-2 rounded-lg transition-colors',
              activeTab === 'campaigns'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            )}
          >
            <div className="flex items-center justify-center gap-2">
              <Send className="w-4 h-4" />
              Campaigns
            </div>
          </button>
          <button
            onClick={() => setActiveTab('templates')}
            className={cn(
              'flex-1 px-4 py-2 rounded-lg transition-colors',
              activeTab === 'templates'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            )}
          >
            <div className="flex items-center justify-center gap-2">
              <FileText className="w-4 h-4" />
              Templates
            </div>
          </button>
          <button
            onClick={() => setActiveTab('metrics')}
            className={cn(
              'flex-1 px-4 py-2 rounded-lg transition-colors',
              activeTab === 'metrics'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            )}
          >
            <div className="flex items-center justify-center gap-2">
              <AlertCircle className="w-4 h-4" />
              Metrics
            </div>
          </button>
        </div>
      </GlassCard>

      {/* Content */}
      {loading ? (
        <GlassCard className="p-8">
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        </GlassCard>
      ) : (
        <>
          {/* Campaigns Tab */}
          {activeTab === 'campaigns' && (
            <div className="grid gap-4">
              {campaigns.length === 0 ? (
                <GlassCard className="p-8 text-center">
                  <Mail className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-lg font-semibold mb-2">No campaigns yet</h3>
                  <p className="text-muted-foreground mb-4">Create your first email campaign to start reaching out</p>
                  <button
                    onClick={() =>
                      error(
                        'Campaign creation not available yet',
                        'This preview build does not include campaign authoring.'
                      )
                    }
                    className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                  >
                    <Plus className="w-4 h-4" />
                    Create Campaign
                  </button>
                </GlassCard>
              ) : (
                campaigns.map(campaign => (
                  <GlassCard key={campaign.id} className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3 mb-2">
                          <h3 className="text-lg font-semibold">{campaign.name}</h3>
                          <span className={cn('px-2 py-1 rounded-full text-xs font-medium', getStatusColor(campaign.status))}>
                            {campaign.status}
                          </span>
                        </div>
                        <div className="grid grid-cols-4 gap-4 text-sm">
                          <div>
                            <p className="text-muted-foreground">Recipients</p>
                            <p className="font-medium">{campaign.recipients_count}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Sent</p>
                            <p className="font-medium">{campaign.sent_count}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Open Rate</p>
                            <p className="font-medium">{campaign.open_rate}%</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Click Rate</p>
                            <p className="font-medium">{campaign.click_rate}%</p>
                          </div>
                        </div>
                        {campaign.scheduled_at && (
                          <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                            <Clock className="w-4 h-4" />
                            Scheduled for {new Date(campaign.scheduled_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {campaign.status === 'active' && (
                          <button
                            onClick={() => handlePauseCampaign(campaign.id)}
                            className="p-2 hover:bg-muted/50 rounded-lg transition-colors"
                          >
                            <AlertCircle className="w-4 h-4" />
                          </button>
                        )}
                        <button className="p-2 hover:bg-muted/50 rounded-lg transition-colors">
                          <Edit2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </GlassCard>
                ))
              )}
            </div>
          )}

          {/* Templates Tab */}
          {activeTab === 'templates' && (
            <div className="grid gap-4">
              {templates.length === 0 ? (
                <GlassCard className="p-8 text-center">
                  <FileText className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-lg font-semibold mb-2">No templates yet</h3>
                  <p className="text-muted-foreground mb-4">Create email templates to use in your campaigns</p>
                  <button
                    onClick={() =>
                      error(
                        'Template creation not available yet',
                        'Add templates via the backend or contact support.'
                      )
                    }
                    className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                  >
                    <Plus className="w-4 h-4" />
                    Create Template
                  </button>
                </GlassCard>
              ) : (
                templates.map(template => (
                  <GlassCard key={template.id} className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3 mb-2">
                          <div className="flex items-center gap-2">
                            {getCategoryIcon(template.category)}
                            <h3 className="text-lg font-semibold">{template.name}</h3>
                          </div>
                          <span className="px-2 py-1 bg-muted/50 rounded text-xs">
                            {template.category}
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground mb-2">
                          <span className="font-medium">Subject:</span> {template.subject}
                        </p>
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {template.body}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {template.variables.map(variable => (
                            <span key={variable} className="px-2 py-1 bg-primary/10 text-primary rounded text-xs">
                              {`{{${variable}}}`}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() =>
                            error(
                              'Template editing not available yet',
                              'Please update templates via the backend until editor support ships.'
                            )
                          }
                          className="p-2 hover:bg-muted/50 rounded-lg transition-colors"
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDeleteTemplate(template.id)}
                          className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </GlassCard>
                ))
              )}
            </div>
          )}

          {/* Metrics Tab */}
          {activeTab === 'metrics' && metrics && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Total Sent</h3>
                  <Send className="w-5 h-5 text-primary" />
                </div>
                <p className="text-3xl font-bold">{metrics.total_sent.toLocaleString()}</p>
                <p className="text-sm text-muted-foreground mt-2">
                  {metrics.total_delivered.toLocaleString()} delivered
                </p>
              </GlassCard>

              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Open Rate</h3>
                  <Mail className="w-5 h-5 text-primary" />
                </div>
                <p className="text-3xl font-bold">
                  {((metrics.total_opened / metrics.total_delivered) * 100).toFixed(1)}%
                </p>
                <p className="text-sm text-muted-foreground mt-2">
                  {metrics.total_opened.toLocaleString()} opened
                </p>
              </GlassCard>

              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Click Rate</h3>
                  <CheckCircle2 className="w-5 h-5 text-primary" />
                </div>
                <p className="text-3xl font-bold">
                  {((metrics.total_clicked / metrics.total_opened) * 100).toFixed(1)}%
                </p>
                <p className="text-sm text-muted-foreground mt-2">
                  {metrics.total_clicked.toLocaleString()} clicked
                </p>
              </GlassCard>

              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Bounce Rate</h3>
                  <AlertCircle className="w-5 h-5 text-yellow-500" />
                </div>
                <p className="text-3xl font-bold">{metrics.bounce_rate}%</p>
                <p className="text-sm text-muted-foreground mt-2">
                  Quality score: {100 - metrics.bounce_rate}%
                </p>
              </GlassCard>

              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Unsubscribe Rate</h3>
                  <Users className="w-5 h-5 text-red-500" />
                </div>
                <p className="text-3xl font-bold">{metrics.unsubscribe_rate}%</p>
                <p className="text-sm text-muted-foreground mt-2">
                  Industry avg: 1.2%
                </p>
              </GlassCard>

              <GlassCard className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">Engagement Score</h3>
                  <CheckCircle2 className="w-5 h-5 text-green-500" />
                </div>
                <p className="text-3xl font-bold">
                  {(((metrics.total_opened / metrics.total_delivered) + (metrics.total_clicked / metrics.total_opened)) * 50).toFixed(0)}
                </p>
                <p className="text-sm text-muted-foreground mt-2">
                  Out of 100
                </p>
              </GlassCard>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default EmailManagement;
