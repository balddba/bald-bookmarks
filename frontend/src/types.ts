export type ThumbnailStatus =
  | 'none'
  | 'pending'
  | 'processing'
  | 'ready'
  | 'failed'

export interface Tag {
  id: number
  name: string
  created_at: string
}

export interface Folder {
  id: number
  name: string
  parent_id: number | null
  sort_order: number
  created_at: string
  updated_at: string
  bookmark_count: number
}

export interface FolderTreeNode extends Folder {
  children: FolderTreeNode[]
}

export interface Bookmark {
  id: number
  title: string
  url: string
  description: string | null
  folder_id: number | null
  thumbnail_status: ThumbnailStatus
  thumbnail_path: string | null
  thumbnail_updated_at: string | null
  created_at: string
  updated_at: string
  tags: Tag[]
}

export interface Job {
  id: number
  job_type: string
  payload_json: string
  status: string
  attempts: number
  max_attempts: number
  scheduled_at: string
  started_at: string | null
  finished_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface AdminConfig {
  db_driver: string
  oracle_user: string | null
  oracle_dsn: string | null
  oracle_password_set: boolean
  job_poll_seconds: number
  job_max_attempts: number
  media_root: string
  thumbnails_dir: string
  cors_origins: string[]
  thumbnail_viewport_width: number
  thumbnail_viewport_height: number
  thumbnail_timeout_ms: number
  thumbnail_no_sandbox: boolean
}

export interface SchemaRevision {
  revision: string
  down_revision: string | null
  doc: string | null
}

export interface SchemaStatus {
  applicable: boolean
  current_revision: string | null
  head_revisions: string[]
  is_current: boolean | null
  revisions: SchemaRevision[]
  error: string | null
}

export interface DatabaseHealth {
  ok: boolean
  driver: string
  latency_ms: number | null
  message: string
}

export interface SchedulerStatus {
  running: boolean
  poll_seconds: number
  registered_job_types: string[]
}

export interface JobExecutionResult {
  job_type: string
  jobs_enqueued: number
  bookmark_count: number
}

export interface AdminSnapshot {
  app_title: string
  app_version: string
  config: AdminConfig
  alembic: SchemaStatus
  database: DatabaseHealth
  scheduler: SchedulerStatus
  queued_jobs: Job[]
  job_history: Job[]
}
