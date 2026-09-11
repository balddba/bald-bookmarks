import * as Sentry from '@sentry/react'

Sentry.init({
  dsn: 'https://52ed6ca55e36a70e2742d3347a670736@sentry.aaronslab.net/2',
  environment: import.meta.env.MODE,
  dataCollection: {
    // To disable sending user data and HTTP bodies, uncomment the lines below. For more info visit:
    // https://docs.sentry.io/platforms/javascript/guides/react/configuration/options/#dataCollection
    // userInfo: false,
    // httpBodies: []
  },
  integrations: [
    Sentry.browserTracingIntegration({
      beforeStartSpan: (context) => ({
        ...context,
        name: context.name.replace(/\/admin\/[^/?#]+/, '/admin/:section'),
      }),
    }),
    Sentry.browserProfilingIntegration(),
  ],
  tracesSampleRate: import.meta.env.PROD ? 0.2 : 1.0,
  profileSessionSampleRate: 1.0,
  profileLifecycle: 'trace',
  tracePropagationTargets: ['localhost', /^\/api\//],
})
