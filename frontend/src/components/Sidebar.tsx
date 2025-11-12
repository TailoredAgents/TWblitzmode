// Navigation Sidebar for the Tallwave dashboard

import React from 'react';
import { BarChart3, Clock, Users, Bot, Settings, Mail, Database, Activity, LogOut, User as UserIcon, X, MessageSquare, Terminal, Bell } from 'lucide-react';
import type { User } from '../types';
import GlassCard from './ui/GlassCard';
import ThemeToggle from './ui/ThemeToggle';
import { cn } from '../lib/utils';
import LanguageSwitcher from './ui/LanguageSwitcher';
import { useI18n } from '../contexts/I18nContext';
import { performLogout } from '../lib/logout';

interface SidebarProps {
  activeView: string;
  onViewChange: (view: string) => void;
  user?: User | null;
  pendingApprovals: number;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  featureFlags?: Record<string, boolean>;
}

const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onViewChange,
  user,
  pendingApprovals,
  sidebarOpen,
  setSidebarOpen,
  featureFlags,
}) => {
  const { t } = useI18n();

  const flags = featureFlags ?? {};
  const corporateLabel = flags.corporate_connect
    ? t('nav.corporateConnect', 'Corporate Connect')
    : t('nav.masterGamePlan');
  const corporateDescription = flags.corporate_connect
    ? t('nav.corporateConnectDescription', 'Executive prospecting workflows')
    : 'AI Prospecting';

  const navigationItems = [
    {
      id: 'dashboard',
      label: t('nav.dashboard'),
      icon: <BarChart3 className="w-5 h-5" />,
      description: 'Overview & Analytics',
    },
    {
      id: 'approvals',
      label: t('nav.approvals'),
      icon: <Clock className="w-5 h-5" />,
      description: 'Human-in-the-Loop',
      badge: pendingApprovals,
    },
    {
      id: 'prospects',
      label: t('nav.prospects'),
      icon: <Users className="w-5 h-5" />,
      description: 'Contact Pipeline',
    },
    {
      id: 'communication-hub',
      label: t('nav.communicationHub'),
      icon: <MessageSquare className="w-5 h-5" />,
      description: 'AI Agent Communication',
    },
    {
      id: 'workflows',
      label: t('nav.workflows'),
      icon: <Bot className="w-5 h-5" />,
      description: 'Automation Status',
    },
    {
      id: 'ai-prompting',
      label: t('nav.aiPrompting'),
      icon: <Terminal className="w-5 h-5" />,
      description: 'Custom AI Assistant',
    },
    {
      id: 'master-game-plan',
      label: corporateLabel,
      icon: <Activity className="w-5 h-5" />,
      description: corporateDescription,
    },
    {
      id: 'emails',
      label: t('nav.emails'),
      icon: <Mail className="w-5 h-5" />,
      description: 'Campaigns & Templates',
    },
    {
      id: 'integrations',
      label: t('nav.integrations'),
      icon: <Database className="w-5 h-5" />,
      description: 'API Connections',
    },
    {
      id: 'settings',
      label: t('nav.settings'),
      icon: <Settings className="w-5 h-5" />,
      description: 'Configuration',
    },
  ];

  const handleLogout = () => {
    void performLogout();
  };

  return (
    <>
      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <div
        id="sidebar-nav"
        className={cn(
          "h-screen bg-background/80 backdrop-blur-xl border-r border-border/20 flex flex-col transition-transform duration-300 z-50",
          "lg:w-64 lg:translate-x-0 lg:static",
          "fixed w-80 top-0 left-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        )}
        role="navigation"
        aria-label="Main navigation"
      >
      {/* Header */}
      <div className="p-6 border-b border-border/20">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 backdrop-blur-sm flex items-center justify-center">
              <Activity className="w-6 h-6 text-primary" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-foreground">{t('app.name')}</h1>
              <p className="text-xs text-muted-foreground">{t('app.tagline')}</p>
            </div>
          </div>

          {/* Mobile Close Button */}
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden p-2 rounded-lg hover:bg-muted/20 transition-colors"
            aria-label={t('nav.mobileMenuClose')}
          >
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>

        <div className="flex items-center justify-end">
          <LanguageSwitcher />
        </div>

        {user && (
          <GlassCard className="p-3">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                <UserIcon className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{user.name}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {user.organization?.name ?? 'Organization setup pending'}
                </p>
              </div>
            </div>
          </GlassCard>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2 overflow-y-auto sidebar-nav" aria-label="Dashboard navigation">
        {navigationItems.map((item) => {
          const isActive = activeView === item.id;
          return (
            <button
              type="button"
              key={item.id}
              onClick={() => onViewChange(item.id)}
              className={cn(
                'w-full text-left p-3 rounded-lg transition-all duration-200 group relative',
                'hover:bg-muted/50 hover:backdrop-blur-sm',
                isActive
                  ? 'bg-primary/10 text-primary border border-primary/20'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              aria-current={isActive ? 'page' : undefined}
              aria-label={`Navigate to ${item.label}. ${item.description}${item.badge ? `. ${item.badge} pending items` : ''}`}
              title={`${item.label} - ${item.description}`}
            >
              <div className="flex items-center gap-3">
                <div className={cn(
                  'flex-shrink-0 transition-colors duration-200',
                  isActive ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'
                )}>
                  {item.icon}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className={cn(
                      'font-medium truncate transition-colors duration-200',
                      isActive ? 'text-primary' : 'text-foreground'
                    )}>
                      {item.label}
                    </span>
                    {item.badge && item.badge > 0 && (
                      <span className="ml-2 px-1.5 py-0.5 bg-destructive text-destructive-foreground text-xs rounded-full font-medium">
                        {item.badge}
                      </span>
                    )}
                  </div>
                  <span className={cn(
                    'text-xs truncate block mt-0.5 transition-colors duration-200',
                    isActive ? 'text-primary/70' : 'text-muted-foreground'
                  )}>
                    {item.description}
                  </span>
                </div>
              </div>

              {/* Active indicator */}
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary/80 rounded-r-full" />
              )}
            </button>
          );
        })}
      </nav>

      {/* Divider */}
      <div className="mx-4 h-px bg-border/20" />

      {/* Footer Actions */}
      <div className="p-4 space-y-2">
        <button
          type="button"
          className="w-full flex items-center gap-3 p-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-lg transition-colors"
          aria-label={t('nav.notifications')}
        >
          <Bell className="w-4 h-4" />
          <span>{t('nav.notifications')}</span>
        </button>

        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground">{t('nav.theme')}</span>
          <ThemeToggle variant="glass" size="sm" />
        </div>

        <button
          type="button"
          onClick={handleLogout}
          data-testid="logout-button"
          className="w-full flex items-center gap-3 p-2 text-sm text-destructive hover:text-destructive-foreground hover:bg-destructive/10 rounded-lg transition-colors"
          aria-label={t('nav.logout')}
        >
          <LogOut className="w-4 h-4" />
          <span>{t('nav.logout')}</span>
        </button>
      </div>
      </div>
    </>
  );
};

export default Sidebar;
