'use client';

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

type Locale = 'en' | 'es';

interface MessageDictionary {
  [key: string]: string | MessageDictionary;
}

const dictionaries: Record<Locale, MessageDictionary> = {
  en: {
    app: {
      name: 'Tallwave Introducer',
      tagline: 'Tallwave Relationship Intelligence',
    },
    nav: {
      dashboard: 'Dashboard',
      approvals: 'Approval Queue',
      prospects: 'Prospects',
      communicationHub: 'Communication Hub',
      workflows: 'AI Workflows',
      aiPrompting: 'AI Prompting',
      masterGamePlan: 'Master Game Plan',
      corporateConnect: 'Corporate Connect',
      corporateConnectDescription: 'Executive prospecting workflows',
      emails: 'Email Management',
      integrations: 'Integrations',
      settings: 'Settings',
      notifications: 'Notifications',
      theme: 'Theme',
      language: 'Language',
      logout: 'Log out',
      mobileMenuClose: 'Close navigation menu',
    },
      auth: {
        welcome: 'Welcome back',
      description: 'Sign in with your Tallwave credentials to continue.',
      organizationSlugLabel: 'Company slug',
      emailLabel: 'Work email',
      passwordLabel: 'Password',
      rememberMe: 'Remember me',
      forgotPassword: 'Forgot password?',
      signInCta: 'Sign in',
      signingIn: 'Signing in…',
      emailPlaceholder: 'you@company.com',
      passwordPlaceholder: 'Enter your password',
      registrationPrompt: 'Self-service seating enabled — no keys required',
        errors: {
          missingEmail: 'Email is required',
        missingPassword: 'Password is required',
      },
    },
    profile: {
      welcomeTitle: 'Welcome to the Tallwave Company Portal',
      complianceNote: 'Confirm compliance with Tallwave data-handling policies.',
    },
    accessibility: {
      skipToContent: 'Skip to main content',
      mainContent: 'Main content',
      skipToNavigation: 'Skip to navigation',
    },
    dashboard: {
      greetings: {
        hello: 'Hello',
      },
      header: 'Analytics Overview',
      subheader: 'Real-time insights and performance metrics',
      refresh: 'Refresh',
      refreshing: 'Refreshing…',
      refreshComplete: 'Dashboard refreshed',
      shortcutsLabel: 'Keyboard shortcuts',
      empty: {
        title: 'Organization setup required',
        description: 'We could not determine your organization context. Please contact support to complete your configuration.',
      },
      cards: {
        totalProspects: 'Total Prospects',
        activeWorkflows: 'Active Workflows',
        quotaUsage: 'Quota Usage',
        connectorsWithEmail: 'Connectors with Valid Emails',
        approvalsPending: 'Approvals Pending',
        alertsOpen: 'Open Alerts',
        emailsThisWeek: 'Emails This Week',
        completedThisWeek: 'Completed This Week',
        systemHealth: 'System Health',
      },
      deltas: {
        vsLastMonth: 'vs last month',
        thisWeek: 'this week',
        thisMonth: 'this month',
        improvement: 'improvement',
        workflowsPending: 'Workflows pending',
        completedWorkflows: 'Completed workflows',
        systemsOperational: 'All systems operational',
      },
      charts: {
        prospectActivity: 'Prospect Activity',
        prospectActivitySubtitle: 'Weekly outreach performance',
        aiWorkflowDistribution: 'AI Workflow Distribution',
        aiWorkflowDistributionSubtitle: 'Distribution of automated tasks',
        responseRate: 'Response Rate',
        responseRateSubtitle: 'Monthly progression over time',
        outreach: 'Outreach',
        responses: 'Responses',
        meetings: 'Meetings',
      },
      placeholder: {
        emailsComingSoon: 'Email campaign management coming soon...',
        integrationsComingSoon: 'API integration management coming soon...',
      },
      notifications: {
        newApproval: 'New approval request:',
        review: 'Review',
        reviewHint: 'Click to review in the approval queue',
      },
      quickActions: {
        reviewApprovals: 'Review approvals',
      },
      errors: {
        loadAnalytics: 'Failed to load dashboard analytics',
        loadDashboardData: 'Failed to load dashboard data',
        loadDashboardHint: 'Please try refreshing the page or contact support if the issue persists.',
      },
      actions: {
        viewApprovals: 'Open approval queue',
        openNavigation: 'Open navigation menu',
      },
      organizationPending: 'Organization setup pending',
    },
    settings: {
      tabs: {
        user: 'User Preferences',
        system: 'System Config',
        security: 'Security',
        api: 'API Keys',
        cookieJar: 'Cookie Jar',
      },
      errors: {
        loadSettings: 'Failed to load settings',
        saveFailed: 'Failed to save settings',
        missingOrganization: 'Organization context missing',
        missingOrganizationHint: 'Please refresh the page and try again.',
        liAtRequired: 'li_at cookie required',
        liAtRequiredHint: 'Paste the LinkedIn li_at cookie to continue.',
        cookieUploadFailed: 'Failed to upload cookies',
        cookieUploadFailedHint: 'Please verify the values and try again.',
        noCookieJar: 'No cookie jar available to revalidate',
        revalidateFailed: 'Could not revalidate cookies',
      },
      messages: {
        saveSuccess: 'Settings saved successfully',
        cookieUpdated: 'Cookie jar updated',
        cookieUpdatedHint: 'We will validate your LinkedIn session shortly.',
        validationRequested: 'Validation requested',
        validationRequestedHint: 'We are re-checking your LinkedIn session.',
      },
      user: {
        displayNameLabel: 'Display Name',
        emailLabel: 'Email Address',
        timezoneLabel: 'Timezone',
        timezone: {
          utc: 'UTC',
          eastern: 'Eastern Time',
          central: 'Central Time',
          mountain: 'Mountain Time',
          pacific: 'Pacific Time',
        },
        themeLabel: 'Theme',
        theme: {
          light: 'Light',
          dark: 'Dark',
          auto: 'Auto',
        },
        notifications: {
          title: 'Notification Preferences',
          email: 'Email notifications',
          browser: 'Browser notifications',
          workflows: 'Workflow updates',
          approvals: 'Approval queue alerts',
          system: 'System notices',
        },
      },
      system: {
        autoApprovalLabel: 'Auto-approval Threshold',
        autoApprovalConfidence: 'confidence',
        maxWorkflowsLabel: 'Max Concurrent Workflows',
        timeoutLabel: 'Workflow Timeout (minutes)',
        rateLimitLabel: 'Rate Limit (per minute)',
        optionsTitle: 'System Options',
        options: {
          debugMode: 'Debug Mode',
          auditLogging: 'Audit Logging',
        },
      },
      security: {
        sessionTimeoutLabel: 'Session Timeout (minutes)',
        maxFailedAttemptsLabel: 'Max Failed Login Attempts',
        featuresTitle: 'Security Features',
        requireTwoFactor: 'Require Two-Factor Authentication',
        enableIpWhitelist: 'Enable IP Whitelist',
        toggle: {
          require_2fa: 'Require Two-Factor Authentication',
          ip_whitelist_enabled: 'Enable IP Whitelist',
        },
      },
      api: {
        notice: {
          title: 'Security Notice',
          description: 'API keys are encrypted and stored securely. Never share your API keys or commit them to version control.',
        },
        keys: {
          openai: 'OpenAI API Key',
          apify: 'Apify API Token',
          cufinder: 'CUFinder API Key',
          sendgrid: 'SendGrid API Key',
          phantombuster: 'PhantomBuster API Key',
          linkedin: 'LinkedIn li_at Cookie',
        },
        keysPlaceholders: {
          openai: 'Enter your OpenAI API key',
          apify: 'Enter your Apify API token',
          cufinder: 'Enter your CUFinder API key',
          sendgrid: 'Enter your SendGrid API key',
          phantombuster: 'Enter your PhantomBuster API key',
          linkedin: 'Enter your LinkedIn li_at cookie',
        },
        currentValuePrefix: 'Current',
      },
      cookie: {
        title: 'LinkedIn Cookie Jar',
        description: 'Upload encrypted LinkedIn cookies to enable personalized outreach and background validation checks.',
        signedInAs: 'Signed in as',
        liAtLabel: 'li_at Cookie',
        liAtPlaceholder: 'Paste the li_at cookie value',
        liAtHelp: 'Copy this value from your browser developer tools while logged into LinkedIn. Treat it like a password.',
        jsessionIdLabel: 'JSESSIONID (optional)',
        jsessionIdPlaceholder: 'Paste JSESSIONID',
        userAgentLabel: 'User Agent (optional)',
        userAgentPlaceholder: 'Mozilla/5.0 (Macintosh; Intel Mac OS X ...)',
        buttons: {
          saving: 'Saving…',
          upload: 'Upload Cookies',
          revalidate: 'Re-validate',
        },
        currentStatus: 'Current Status',
        lastValidated: 'Last validated',
        status: {
          pending: 'Pending validation',
          valid: 'Valid',
          invalid: 'Invalid',
          expired: 'Expired',
          missing: 'Missing',
        },
        missingHint: 'No cookies uploaded yet. Upload your LinkedIn session to activate outreach features.',
      },
    },
    login: {
      messages: {
        loginSuccess: 'Login successful!',
        registrationSuccess: 'Account created!',
      },
      errors: {
        organizationRequired: 'Organization required',
        organizationHint: 'Please enter your company slug before logging in.',
        loginFailed: 'Login failed',
        tryAgain: 'Please try again.',
        invalidCredentials: 'Please check your credentials.',
        passwordMismatch: 'Passwords do not match',
        passwordMismatchHint: 'Please confirm your password.',
        registrationKeyRequired: 'Self-service — no registration key required',
        registrationKeyHint: 'Use self-service seating: Login → Tallwave123 → “+ Team member”.',
        companySlugRequired: 'Company slug required',
        companySlugHint: 'Enter your company slug before redeeming a key.',
        registrationFailed: 'Registration failed',
        registrationRetry: 'Please verify your key and try again.',
        registrationDetails: 'Please verify your details and try again.',
      },
      cookieBanner: {
        title: 'LinkedIn session required',
        detectedPrefix: 'We detected a',
        cookieJar: 'cookie jar for',
        thisOrganization: 'this organization',
        callToAction: 'Upload a fresh LinkedIn cookie to activate outreach features.',
        reviewAction: 'Go to Cookie Jar',
        dismissAction: 'Continue without updating',
      },
      form: {
        organizationPlaceholder: 'your-company',
      },
      registration: {
        title: 'Add team member',
        subtitle: 'Self-service seating: Login → Tallwave123 → “+ Team member”.',
        close: 'Close',
        firstNameLabel: 'First Name',
        lastNameLabel: 'Last Name',
        emailPlaceholder: 'you@company.com',
        creating: 'Adding team member...',
        createAction: 'Add Team Member',
      },
    },
    shared: {
      never: 'Never',
    },
  },
  es: {
    app: {
      name: 'Tallwave Introducer',
      tagline: 'Inteligencia de relaciones Tallwave',
    },
    nav: {
      dashboard: 'Panel',
      approvals: 'Cola de aprobaciones',
      prospects: 'Prospectos',
      communicationHub: 'Centro de comunicación',
      workflows: 'Flujos de IA',
      aiPrompting: 'Asistente IA',
      masterGamePlan: 'Plan maestro',
      corporateConnect: 'Conexión corporativa',
      corporateConnectDescription: 'Procesos para prospectos ejecutivos',
      emails: 'Gestión de correos',
      integrations: 'Integraciones',
      settings: 'Configuración',
      notifications: 'Notificaciones',
      theme: 'Tema',
      language: 'Idioma',
      logout: 'Cerrar sesión',
      mobileMenuClose: 'Cerrar menú de navegación',
    },
    auth: {
      welcome: 'Bienvenido de nuevo',
      description: 'Inicia sesión con tus credenciales de Tallwave para continuar.',
      organizationSlugLabel: 'Slug de la empresa',
      emailLabel: 'Correo de trabajo',
      passwordLabel: 'Contraseña',
      rememberMe: 'Recuérdame',
      forgotPassword: '¿Olvidaste tu contraseña?',
      signInCta: 'Iniciar sesión',
      signingIn: 'Iniciando sesión…',
      emailPlaceholder: 'tu@empresa.com',
      passwordPlaceholder: 'Introduce tu contraseña',
      registrationPrompt: 'Asientos de autoservicio — sin claves',
      errors: {
        missingEmail: 'El correo es obligatorio',
        missingPassword: 'La contraseña es obligatoria',
      },
    },
    profile: {
      welcomeTitle: 'Bienvenido al portal corporativo de Tallwave',
      complianceNote: 'Confirma el cumplimiento de las políticas de manejo de datos de Tallwave.',
    },
    accessibility: {
      skipToContent: 'Saltar al contenido principal',
      mainContent: 'Contenido principal',
      skipToNavigation: 'Saltar a la navegación',
    },
    dashboard: {
      greetings: {
        hello: 'Hola',
      },
      header: 'Visión analítica',
      subheader: 'Métricas de rendimiento en tiempo real',
      refresh: 'Actualizar',
      refreshing: 'Actualizando…',
      refreshComplete: 'Panel actualizado',
      shortcutsLabel: 'Atajos de teclado',
      empty: {
        title: 'Se requiere configurar la organización',
        description: 'No pudimos determinar el contexto de tu organización. Contacta al equipo de soporte para completar la configuración.',
      },
      cards: {
        totalProspects: 'Prospectos totales',
        activeWorkflows: 'Flujos activos',
        quotaUsage: 'Uso de cuota',
        connectorsWithEmail: 'Conectores con correo válido',
        approvalsPending: 'Aprobaciones pendientes',
        alertsOpen: 'Alertas abiertas',
        emailsThisWeek: 'Correos esta semana',
        completedThisWeek: 'Completados esta semana',
        systemHealth: 'Salud del sistema',
      },
      deltas: {
        vsLastMonth: 'vs mes anterior',
        thisWeek: 'esta semana',
        thisMonth: 'este mes',
        improvement: 'mejora',
        workflowsPending: 'Flujos en espera',
        completedWorkflows: 'Flujos completados',
        systemsOperational: 'Todos los sistemas operativos',
      },
      charts: {
        prospectActivity: 'Actividad de prospectos',
        prospectActivitySubtitle: 'Desempeño semanal de alcance',
        aiWorkflowDistribution: 'Distribución de flujos IA',
        aiWorkflowDistributionSubtitle: 'Distribución de tareas automatizadas',
        responseRate: 'Tasa de respuesta',
        responseRateSubtitle: 'Evolución mensual en el tiempo',
        outreach: 'Alcance',
        responses: 'Respuestas',
        meetings: 'Reuniones',
      },
      placeholder: {
        emailsComingSoon: 'Gestión de correos disponible próximamente...',
        integrationsComingSoon: 'Gestión de integraciones disponible próximamente...',
      },
      notifications: {
        newApproval: 'Nueva solicitud de aprobación:',
        review: 'Revisar',
        reviewHint: 'Haz clic para revisar en la cola de aprobaciones',
      },
      quickActions: {
        reviewApprovals: 'Revisar aprobaciones',
      },
      errors: {
        loadAnalytics: 'No se pudieron cargar las analíticas',
        loadDashboardData: 'No se pudo cargar el panel',
        loadDashboardHint: 'Intenta actualizar la página o contacta al soporte si el problema persiste.',
      },
      actions: {
        viewApprovals: 'Abrir cola de aprobaciones',
        openNavigation: 'Abrir menú de navegación',
      },
      organizationPending: 'Configuración de la organización pendiente',
    },
    settings: {
      tabs: {
        user: 'Preferencias del usuario',
        system: 'Configuración del sistema',
        security: 'Seguridad',
        api: 'Claves API',
        cookieJar: 'Cookie Jar',
      },
      errors: {
        loadSettings: 'No se pudieron cargar los ajustes',
        saveFailed: 'No se pudieron guardar los ajustes',
        missingOrganization: 'Falta el contexto de la organización',
        missingOrganizationHint: 'Actualiza la página e inténtalo de nuevo.',
        liAtRequired: 'Se requiere la cookie li_at',
        liAtRequiredHint: 'Pega la cookie li_at de LinkedIn para continuar.',
        cookieUploadFailed: 'No se pudieron cargar las cookies',
        cookieUploadFailedHint: 'Verifica los valores e inténtalo nuevamente.',
        noCookieJar: 'No hay ninguna cookie para revalidar',
        revalidateFailed: 'No se pudieron revalidar las cookies',
      },
      messages: {
        saveSuccess: 'Ajustes guardados correctamente',
        cookieUpdated: 'Cookie jar actualizado',
        cookieUpdatedHint: 'Validaremos tu sesión de LinkedIn en breve.',
        validationRequested: 'Validación solicitada',
        validationRequestedHint: 'Estamos revisando tu sesión de LinkedIn.',
      },
      user: {
        displayNameLabel: 'Nombre para mostrar',
        emailLabel: 'Correo electrónico',
        timezoneLabel: 'Zona horaria',
        timezone: {
          utc: 'UTC',
          eastern: 'Hora del Este',
          central: 'Hora Central',
          mountain: 'Hora de la Montaña',
          pacific: 'Hora del Pacífico',
        },
        themeLabel: 'Tema',
        theme: {
          light: 'Claro',
          dark: 'Oscuro',
          auto: 'Automático',
        },
        notifications: {
          title: 'Preferencias de notificaciones',
          email: 'Notificaciones por correo',
          browser: 'Notificaciones del navegador',
          workflows: 'Actualizaciones de flujos',
          approvals: 'Alertas de aprobación',
          system: 'Avisos del sistema',
        },
      },
      system: {
        autoApprovalLabel: 'Umbral de autoaprobación',
        autoApprovalConfidence: 'confianza',
        maxWorkflowsLabel: 'Flujos concurrentes máximos',
        timeoutLabel: 'Tiempo de espera (minutos)',
        rateLimitLabel: 'Límite por minuto',
        optionsTitle: 'Opciones del sistema',
        options: {
          debugMode: 'Modo depuración',
          auditLogging: 'Registro de auditoría',
        },
      },
      security: {
        sessionTimeoutLabel: 'Tiempo de sesión (minutos)',
        maxFailedAttemptsLabel: 'Intentos fallidos máximos',
        featuresTitle: 'Funciones de seguridad',
        requireTwoFactor: 'Requerir autenticación de dos factores',
        enableIpWhitelist: 'Habilitar lista blanca de IP',
        toggle: {
          require_2fa: 'Requerir autenticación de dos factores',
          ip_whitelist_enabled: 'Habilitar lista blanca de IP',
        },
      },
      api: {
        notice: {
          title: 'Aviso de seguridad',
          description: 'Las claves API se almacenan cifradas. Nunca compartas tus claves ni las publiques en el repositorio.',
        },
        keys: {
          openai: 'Clave API de OpenAI',
          apify: 'Token API de Apify',
          cufinder: 'Clave API de CUFinder',
          sendgrid: 'Clave API de SendGrid',
          phantombuster: 'Clave API de PhantomBuster',
          linkedin: 'Cookie li_at de LinkedIn',
        },
        keysPlaceholders: {
          openai: 'Introduce tu clave de OpenAI',
          apify: 'Introduce tu token de Apify',
          cufinder: 'Introduce tu clave de CUFinder',
          sendgrid: 'Introduce tu clave de SendGrid',
          phantombuster: 'Introduce tu clave de PhantomBuster',
          linkedin: 'Introduce tu cookie li_at de LinkedIn',
        },
        currentValuePrefix: 'Actual',
      },
      cookie: {
        title: 'LinkedIn Cookie Jar',
        description: 'Carga cookies cifradas de LinkedIn para habilitar verificaciones y personalización.',
        signedInAs: 'Conectado como',
        liAtLabel: 'Cookie li_at',
        liAtPlaceholder: 'Pega el valor de la cookie li_at',
        liAtHelp: 'Copia este valor desde las herramientas del navegador mientras estás en LinkedIn. Trátalo como una contraseña.',
        jsessionIdLabel: 'JSESSIONID (opcional)',
        jsessionIdPlaceholder: 'Pega el JSESSIONID',
        userAgentLabel: 'User Agent (opcional)',
        userAgentPlaceholder: 'Mozilla/5.0 (Macintosh; Intel Mac OS X ...)',
        buttons: {
          saving: 'Guardando…',
          upload: 'Cargar cookies',
          revalidate: 'Revalidar',
        },
        currentStatus: 'Estado actual',
        lastValidated: 'Última validación',
        status: {
          pending: 'Pendiente',
          valid: 'Válida',
          invalid: 'Inválida',
          expired: 'Expirada',
          missing: 'Sin datos',
        },
        missingHint: 'Aún no hay cookies cargadas. Sube tu sesión de LinkedIn para activar las funciones.',
      },
    },
    login: {
      messages: {
        loginSuccess: 'Inicio de sesión exitoso',
        registrationSuccess: 'Cuenta creada',
      },
      errors: {
        organizationRequired: 'Se requiere la organización',
        organizationHint: 'Introduce el slug de tu empresa antes de iniciar sesión.',
        loginFailed: 'Error al iniciar sesión',
        tryAgain: 'Inténtalo de nuevo.',
        invalidCredentials: 'Verifica tus credenciales.',
        passwordMismatch: 'Las contraseñas no coinciden',
        passwordMismatchHint: 'Confirma tu contraseña.',
        registrationKeyRequired: 'Autoservicio — no se requiere clave',
        registrationKeyHint: 'Usa el autoservicio: Inicia sesión → Tallwave123 → “+ Integrante”.',
        companySlugRequired: 'Se requiere el slug de la empresa',
        companySlugHint: 'Ingresa el slug de tu empresa antes de canjear la clave.',
        registrationFailed: 'No se pudo completar el registro',
        registrationRetry: 'Verifica tu clave e inténtalo nuevamente.',
        registrationDetails: 'Revisa tus datos e inténtalo de nuevo.',
      },
      cookieBanner: {
        title: 'Se requiere la sesión de LinkedIn',
        detectedPrefix: 'Detectamos un',
        cookieJar: 'cookie jar para',
        thisOrganization: 'esta organización',
        callToAction: 'Carga una cookie nueva de LinkedIn para activar las funciones.',
        reviewAction: 'Ir al Cookie Jar',
        dismissAction: 'Continuar sin actualizar',
      },
      form: {
        organizationPlaceholder: 'tu-empresa',
      },
      registration: {
        title: 'Agregar integrante',
        subtitle: 'Autoservicio: Inicia sesión → Tallwave123 → “+ Integrante”.',
        close: 'Cerrar',
        firstNameLabel: 'Nombre',
        lastNameLabel: 'Apellido',
        emailPlaceholder: 'tu@empresa.com',
        creating: 'Agregando integrante…',
        createAction: 'Agregar integrante',
      },
    },
    shared: {
      never: 'Nunca',
    },
  },
};

interface I18nContextValue {
  locale: Locale;
  availableLocales: Locale[];
  setLocale: (locale: Locale) => void;
  t: (key: string, fallback?: string) => string;
}

const LOCALE_DICTIONARY_MAP = new Map<Locale, MessageDictionary>(
  Object.entries(dictionaries) as Array<[Locale, MessageDictionary]>
);

const defaultLocale: Locale = 'en';

const I18nContext = createContext<I18nContextValue>({
  locale: defaultLocale,
  availableLocales: ['en', 'es'],
  setLocale: () => undefined,
  t: (key) => key,
});

const getMessage = (dictionary: MessageDictionary, path: string[]): string | MessageDictionary | undefined => {
  const [current, ...rest] = path;
  if (current === undefined) {
    return undefined;
  }
  const map = new Map<string, string | MessageDictionary>(
    Object.entries(dictionary)
  );
  const value = map.get(current);
  if (value === undefined) {
    return undefined;
  }
  if (typeof value === 'string' || rest.length === 0) {
    return value;
  }
  return getMessage(value as MessageDictionary, rest);
};

export const I18nProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [locale, setLocaleState] = useState<Locale>(defaultLocale);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('tallwave-locale', next);
    }
  }, []);

  React.useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem('tallwave-locale') as Locale | null;
    if (stored && LOCALE_DICTIONARY_MAP.has(stored)) {
      setLocaleState(stored);
    }
  }, []);

  const translate = useCallback(
    (key: string, fallback?: string) => {
      const dictionary = LOCALE_DICTIONARY_MAP.get(locale) ?? LOCALE_DICTIONARY_MAP.get(defaultLocale);
      if (!dictionary) {
        return fallback ?? key;
      }
      const result = getMessage(dictionary, key.split('.'));
      if (typeof result === 'string') {
        return result;
      }
      if (fallback) {
        return fallback;
      }
      return key;
    },
    [locale],
  );

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      availableLocales: Array.from(LOCALE_DICTIONARY_MAP.keys()),
      setLocale,
      t: translate,
    }),
    [locale, setLocale, translate],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = (): I18nContextValue => {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
};
