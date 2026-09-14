/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SENTRY_DSN?: string
  readonly VITE_SENTRY_ENVIRONMENT?: string
  readonly VITE_SENTRY_TRACES_SAMPLE_RATE?: string
}

interface Window {
  __ENV__?: Pick<
    ImportMetaEnv,
    'VITE_SENTRY_DSN' | 'VITE_SENTRY_ENVIRONMENT' | 'VITE_SENTRY_TRACES_SAMPLE_RATE'
  >
}
