import React from 'react'
import * as Sentry from '@sentry/react'
import {
  createRoutesFromChildren,
  matchRoutes,
  useLocation,
  useNavigationType,
} from 'react-router'

type SentryEnvName =
  | 'VITE_SENTRY_DSN'
  | 'VITE_SENTRY_ENVIRONMENT'
  | 'VITE_SENTRY_TRACES_SAMPLE_RATE'

function readEnvValue(name: SentryEnvName): string {
  const fromRuntime = window.__ENV__?.[name]
  const fromVite = import.meta.env[name]
  if (typeof fromRuntime === 'string' && fromRuntime.trim()) {
    return fromRuntime.trim()
  }
  if (typeof fromVite === 'string' && fromVite.trim()) {
    return fromVite.trim()
  }
  return ''
}

function parseSampleRate(raw: string, fallback: number): number {
  if (!raw) {
    return fallback
  }
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
    return fallback
  }
  return parsed
}

const dsn = readEnvValue('VITE_SENTRY_DSN')

if (dsn) {
  Sentry.init({
    dsn,
    environment: readEnvValue('VITE_SENTRY_ENVIRONMENT') || import.meta.env.MODE,
    dataCollection: {
      // To disable sending user data and HTTP bodies, uncomment the lines below. For more info visit:
      // https://docs.sentry.io/platforms/javascript/guides/react/configuration/options/#dataCollection
      // userInfo: false,
      // httpBodies: []
    },
    integrations: [
      Sentry.reactRouterV7BrowserTracingIntegration({
        useEffect: React.useEffect,
        useLocation,
        useNavigationType,
        createRoutesFromChildren,
        matchRoutes,
      }),
      Sentry.browserProfilingIntegration(),
    ],
    tracesSampleRate: parseSampleRate(
      readEnvValue('VITE_SENTRY_TRACES_SAMPLE_RATE'),
      import.meta.env.PROD ? 0.2 : 1.0,
    ),
    tracePropagationTargets: ['localhost', /^\/api\//],
    profileSessionSampleRate: 1.0,
    profileLifecycle: 'trace',
  })
}
