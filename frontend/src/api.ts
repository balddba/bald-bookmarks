import type {
  AdminSnapshot,
  Bookmark,
  ExportFormat,
  Folder,
  FolderTreeNode,
  ImportResult,
  Job,
  JobExecutionResult,
  Tag,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // ignore parse errors
    }
    throw new Error(detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  getFolderTree: () => request<FolderTreeNode[]>('/api/folders/tree'),
  listRootFolders: () => request<Folder[]>('/api/folders'),
  listChildren: (folderId: number) =>
    request<Folder[]>(`/api/folders/${folderId}/children`),
  createFolder: (body: {
    name: string
    parent_id?: number | null
    sort_order?: number
  }) =>
    request<Folder>('/api/folders', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateFolder: (
    folderId: number,
    body: { name?: string; parent_id?: number | null; sort_order?: number },
  ) =>
    request<Folder>(`/api/folders/${folderId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteFolder: (folderId: number, recursive = false) =>
    request<void>(`/api/folders/${folderId}?recursive=${recursive}`, {
      method: 'DELETE',
    }),
  listBookmarks: (params: {
    folder_id?: number | null
    q?: string
    tag?: string
    unfiled_only?: boolean
  }) => {
    const query = new URLSearchParams()
    if (params.folder_id != null) query.set('folder_id', String(params.folder_id))
    if (params.q) query.set('q', params.q)
    if (params.tag) query.set('tag', params.tag)
    if (params.unfiled_only) query.set('unfiled_only', 'true')
    const suffix = query.toString() ? `?${query}` : ''
    return request<Bookmark[]>(`/api/bookmarks${suffix}`)
  },
  createBookmark: (body: {
    title: string
    url: string
    description?: string | null
    folder_id?: number | null
    tag_names?: string[]
  }) =>
    request<Bookmark>('/api/bookmarks', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateBookmark: (
    bookmarkId: number,
    body: {
      title?: string
      url?: string
      description?: string | null
      folder_id?: number | null
      tag_names?: string[]
    },
  ) =>
    request<Bookmark>(`/api/bookmarks/${bookmarkId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteBookmark: (bookmarkId: number) =>
    request<void>(`/api/bookmarks/${bookmarkId}`, { method: 'DELETE' }),
  refreshThumbnail: (bookmarkId: number) =>
    request<Bookmark>(`/api/bookmarks/${bookmarkId}/thumbnail/refresh`, {
      method: 'POST',
    }),
  previewUrl: (url: string) =>
    request<{ url: string; title: string | null; description: string | null }>(
      '/api/bookmarks/url-preview',
      {
        method: 'POST',
        body: JSON.stringify({ url }),
      },
    ),
  listTags: () => request<Tag[]>('/api/tags'),
  listJobs: () => request<Job[]>('/api/jobs'),
  getAdminSnapshot: () => request<AdminSnapshot>('/api/admin'),
  regenerateAllThumbnails: () =>
    request<JobExecutionResult>('/api/admin/jobs/regenerate-thumbnails', {
      method: 'POST',
    }),
  exportBookmarkUrl: (format: ExportFormat = 'json', folderId?: number | null) => {
    const query = new URLSearchParams()
    query.set('format', format)
    if (folderId != null) query.set('folder_id', String(folderId))
    return `/api/bookmarks/export?${query}`
  },
  importBookmarks: (
    content: string,
    params?: {
      target_folder_id?: number | null
      skip_existing?: boolean
      enqueue_thumbnails?: boolean
    },
  ) => {
    const query = new URLSearchParams()
    if (params?.target_folder_id != null) {
      query.set('target_folder_id', String(params.target_folder_id))
    }
    if (params?.skip_existing != null) {
      query.set('skip_existing', String(params.skip_existing))
    }
    if (params?.enqueue_thumbnails != null) {
      query.set('enqueue_thumbnails', String(params.enqueue_thumbnails))
    }
    const suffix = query.toString() ? `?${query}` : ''
    return request<ImportResult>(`/api/bookmarks/import${suffix}`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: content,
    })
  },
}
