import { useCallback, useEffect, useState } from 'react'
import { Button, Chip } from '@heroui/react'
import { api } from './api'
import type { AdminSnapshot, Job, SchemaStatus } from './types'

export const ADMIN_SECTIONS = [
  {
    id: 'configuration',
    title: 'Configuration',
    blurb: 'Runtime settings with secrets omitted',
  },
  {
    id: 'database',
    title: 'Database',
    blurb: 'Connectivity health check',
  },
  {
    id: 'schema',
    title: 'Schema',
    blurb: 'Deployed Alembic revision',
  },
  {
    id: 'jobs',
    title: 'Jobs',
    blurb: 'Scheduler, queued work, and history',
  },
] as const

export type AdminSectionId = (typeof ADMIN_SECTIONS)[number]['id']

export function parseAdminSection(pathname: string): AdminSectionId | null {
  if (!pathname.startsWith('/admin')) return null
  const rest = pathname.replace(/^\/admin\/?/, '')
  const id = rest.split('/')[0] || 'configuration'
  if (ADMIN_SECTIONS.some((section) => section.id === id)) {
    return id as AdminSectionId
  }
  return 'configuration'
}

export function adminSectionMeta(section: AdminSectionId) {
  return ADMIN_SECTIONS.find((item) => item.id === section) ?? ADMIN_SECTIONS[0]
}

function formatTs(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function formatValue(value: string | number | boolean | null | string[]): string {
  if (value == null) return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

export function AdminConsole({ section }: { section: AdminSectionId }) {
  const [snapshot, setSnapshot] = useState<AdminSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    try {
      setError(null)
      setLoading(true)
      setSnapshot(await api.getAdminSnapshot())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin console')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <div className="admin-stack">
      <div className="admin-toolbar">
        <Button size="sm" variant="secondary" onPress={() => void reload()}>
          Refresh
        </Button>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {loading && !snapshot ? (
        <p className="empty-state">Loading admin console…</p>
      ) : null}
      {snapshot ? (
        <AdminSection snapshot={snapshot} section={section} onReload={reload} />
      ) : null}
    </div>
  )
}

function AdminSection({
  snapshot,
  section,
  onReload,
}: {
  snapshot: AdminSnapshot
  section: AdminSectionId
  onReload: () => Promise<void>
}) {
  if (section === 'configuration') {
    return <ConfigurationSection snapshot={snapshot} />
  }
  if (section === 'database') {
    return <DatabaseSection snapshot={snapshot} />
  }
  if (section === 'schema') {
    return <SchemaSection snapshot={snapshot} />
  }
  return <JobsSection snapshot={snapshot} onReload={onReload} />
}

function ConfigurationSection({ snapshot }: { snapshot: AdminSnapshot }) {
  const { config } = snapshot
  return (
    <section className="panel admin-card">
      <header className="admin-card-header">
        <h2>Runtime settings</h2>
        <Chip size="sm">
          {snapshot.app_title} v{snapshot.app_version}
        </Chip>
      </header>
      <dl className="kv-list">
        <Kv label="DB driver" value={config.db_driver} />
        <Kv label="Oracle user" value={config.oracle_user} />
        <Kv label="Oracle DSN" value={config.oracle_dsn} mono />
        <Kv
          label="Oracle password"
          value={config.oracle_password_set ? 'set' : 'not set'}
        />
        <Kv label="Job poll seconds" value={config.job_poll_seconds} />
        <Kv label="Job max attempts" value={config.job_max_attempts} />
        <Kv label="Media root" value={config.media_root} mono />
        <Kv label="Thumbnails dir" value={config.thumbnails_dir} mono />
        <Kv label="CORS origins" value={config.cors_origins} />
        <Kv
          label="Thumbnail viewport"
          value={`${config.thumbnail_viewport_width}×${config.thumbnail_viewport_height}`}
        />
        <Kv label="Thumbnail timeout" value={`${config.thumbnail_timeout_ms} ms`} />
        <Kv label="Thumbnail no sandbox" value={config.thumbnail_no_sandbox} />
      </dl>
    </section>
  )
}

function DatabaseSection({ snapshot }: { snapshot: AdminSnapshot }) {
  const { database } = snapshot
  return (
    <section className="panel admin-card">
      <header className="admin-card-header">
        <h2>Connectivity</h2>
        <StatusChip ok={database.ok} label={database.ok ? 'Healthy' : 'Unhealthy'} />
      </header>
      <dl className="kv-list">
        <Kv label="Driver" value={database.driver} />
        <Kv
          label="Latency"
          value={database.latency_ms == null ? '—' : `${database.latency_ms} ms`}
        />
        <Kv label="Message" value={database.message} />
      </dl>
    </section>
  )
}

function SchemaSection({ snapshot }: { snapshot: AdminSnapshot }) {
  const { alembic } = snapshot
  return (
    <section className="panel admin-card">
      <header className="admin-card-header">
        <h2>Alembic</h2>
        <SchemaChip schema={alembic} />
      </header>
      <dl className="kv-list">
        <Kv
          label="Applies to this driver"
          value={alembic.applicable ? 'yes (Oracle)' : 'no (memory)'}
        />
        <Kv label="Deployed revision" value={alembic.current_revision} mono />
        <Kv
          label="Local heads"
          value={
            alembic.head_revisions.length ? alembic.head_revisions.join(', ') : null
          }
          mono
        />
        {alembic.error ? <Kv label="Error" value={alembic.error} /> : null}
      </dl>
      {alembic.revisions.length ? (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Revision</th>
              <th>Parent</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {alembic.revisions.map((rev) => (
              <tr
                key={rev.revision}
                className={
                  rev.revision === alembic.current_revision ? 'is-current' : undefined
                }
              >
                <td className="mono">{rev.revision}</td>
                <td className="mono">{rev.down_revision ?? '—'}</td>
                <td>{rev.doc ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}

function JobsSection({
  snapshot,
  onReload,
}: {
  snapshot: AdminSnapshot
  onReload: () => Promise<void>
}) {
  const { scheduler } = snapshot
  const [runningJob, setRunningJob] = useState<string | null>(null)
  const [jobMessage, setJobMessage] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)

  const runRegenerateThumbnails = useCallback(async () => {
    setRunningJob('regenerate-thumbnails')
    setJobMessage(null)
    setJobError(null)
    try {
      const result = await api.regenerateAllThumbnails()
      setJobMessage(
        `Queued ${result.jobs_enqueued} thumbnail job${result.jobs_enqueued === 1 ? '' : 's'} for ${result.bookmark_count} bookmark${result.bookmark_count === 1 ? '' : 's'}.`,
      )
      await onReload()
    } catch (err) {
      setJobError(
        err instanceof Error ? err.message : 'Failed to regenerate thumbnails',
      )
    } finally {
      setRunningJob(null)
    }
  }, [onReload])

  return (
    <div className="admin-stack">
      <section className="panel admin-card">
        <header className="admin-card-header">
          <h2>Run jobs</h2>
        </header>
        <div className="admin-job-actions">
          <div className="admin-job-action">
            <div className="admin-job-action-copy">
              <h3>Regenerate all thumbnails</h3>
              <p>
                Re-capture page previews for every bookmark. Each bookmark is
                reset to pending and queued for the scheduler.
              </p>
            </div>
            <Button
              size="sm"
              variant="primary"
              isDisabled={runningJob !== null}
              onPress={() => void runRegenerateThumbnails()}
            >
              {runningJob === 'regenerate-thumbnails' ? 'Running…' : 'Run'}
            </Button>
          </div>
        </div>
        {jobError ? <div className="error-banner admin-job-feedback">{jobError}</div> : null}
        {jobMessage ? (
          <p className="admin-job-feedback admin-job-success">{jobMessage}</p>
        ) : null}
      </section>
      <section className="panel admin-card">
        <header className="admin-card-header">
          <h2>Scheduler</h2>
          <StatusChip
            ok={scheduler.running}
            label={scheduler.running ? 'Running' : 'Stopped'}
          />
        </header>
        <dl className="kv-list">
          <Kv label="Poll seconds" value={scheduler.poll_seconds} />
          <Kv label="Registered jobs" value={scheduler.registered_job_types} mono />
        </dl>
      </section>
      <section className="panel admin-card">
        <header className="admin-card-header">
          <h2>Scheduled jobs</h2>
          <Chip size="sm">{snapshot.queued_jobs.length} queued</Chip>
        </header>
        <JobTable jobs={snapshot.queued_jobs} empty="No pending or running jobs." />
      </section>
      <section className="panel admin-card">
        <header className="admin-card-header">
          <h2>Job history</h2>
          <Chip size="sm">{snapshot.job_history.length} finished</Chip>
        </header>
        <JobTable jobs={snapshot.job_history} empty="No finished jobs yet." />
      </section>
    </div>
  )
}

function SchemaChip({ schema }: { schema: SchemaStatus }) {
  if (!schema.applicable) {
    return <span className="status-chip">Not applied</span>
  }
  if (schema.is_current === true) {
    return <StatusChip ok label="Current" />
  }
  if (schema.is_current === false) {
    return <StatusChip ok={false} warn label="Behind" />
  }
  return <span className="status-chip">Unknown</span>
}

function Kv({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string | number | boolean | null | string[]
  mono?: boolean
}) {
  return (
    <div className="kv-row">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{formatValue(value)}</dd>
    </div>
  )
}

function StatusChip({
  ok,
  warn = false,
  label,
}: {
  ok: boolean
  warn?: boolean
  label: string
}) {
  const tone = warn ? 'is-warn' : ok ? 'is-ok' : 'is-bad'
  return <span className={`status-chip ${tone}`}>{label}</span>
}

function JobTable({ jobs, empty }: { jobs: Job[]; empty: string }) {
  if (!jobs.length) {
    return <p className="empty-state">{empty}</p>
  }
  return (
    <table className="admin-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Type</th>
          <th>Status</th>
          <th>Attempts</th>
          <th>Scheduled</th>
          <th>Finished</th>
          <th>Error / payload</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id}>
            <td className="mono">{job.id}</td>
            <td className="mono">{job.job_type}</td>
            <td>
              <JobStatusChip status={job.status} />
            </td>
            <td>
              {job.attempts}/{job.max_attempts}
            </td>
            <td>{formatTs(job.scheduled_at)}</td>
            <td>{formatTs(job.finished_at)}</td>
            <td className="job-detail">
              {job.last_error ? (
                <span className="job-error">{job.last_error}</span>
              ) : (
                <span className="mono job-payload">{job.payload_json}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function JobStatusChip({ status }: { status: string }) {
  const tone =
    status === 'succeeded'
      ? 'is-ok'
      : status === 'failed'
        ? 'is-bad'
        : status === 'running'
          ? 'is-warn'
          : ''
  return <span className={`status-chip ${tone}`}>{status}</span>
}
