import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from './api'
import {
  BookmarkList,
  FolderTree,
  ModalPanel,
  TextField,
} from './components'
import {
  ADMIN_SECTIONS,
  AdminConsole,
  adminSectionMeta,
  parseAdminSection,
} from './AdminConsole'
import type {
  Bookmark,
  ExportFormat,
  Folder,
  FolderTreeNode,
  ImportResult,
} from './types'
import './App.css'

const DESCRIPTION_MAX_LENGTH = 256

function findPath(
  nodes: FolderTreeNode[],
  targetId: number,
  trail: FolderTreeNode[] = [],
): FolderTreeNode[] | null {
  for (const node of nodes) {
    const next = [...trail, node]
    if (node.id === targetId) return next
    const nested = findPath(node.children, targetId, next)
    if (nested) return nested
  }
  return null
}

function findNode(
  nodes: FolderTreeNode[],
  targetId: number,
): FolderTreeNode | null {
  const path = findPath(nodes, targetId)
  return path?.[path.length - 1] ?? null
}

function subtreeContains(node: FolderTreeNode, folderId: number): boolean {
  if (node.id === folderId) return true
  return node.children.some((child) => subtreeContains(child, folderId))
}

function countNestedFolders(node: FolderTreeNode): number {
  return node.children.reduce(
    (sum, child) => sum + 1 + countNestedFolders(child),
    0,
  )
}

function deleteFolderMessage(folder: Folder, tree: FolderTreeNode[]): string {
  const node = findNode(tree, folder.id)
  const nested = node ? countNestedFolders(node) : 0
  if (nested > 0) {
    return `Delete “${folder.name}” and ${nested} nested folder${nested === 1 ? '' : 's'}, including all bookmarks inside them? This cannot be undone.`
  }
  return `Delete “${folder.name}” and all bookmarks in it? This cannot be undone.`
}

function collectExpandedDefaults(nodes: FolderTreeNode[]): Set<number> {
  const ids = new Set<number>()
  const walk = (items: FolderTreeNode[]) => {
    for (const item of items) {
      if (item.children.length) {
        ids.add(item.id)
        walk(item.children)
      }
    }
  }
  walk(nodes)
  return ids
}

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const adminSection = parseAdminSection(location.pathname)
  const isAdmin = adminSection != null
  const adminMeta = adminSection ? adminSectionMeta(adminSection) : null
  const [tree, setTree] = useState<FolderTreeNode[]>([])
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null)
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [folderModalOpen, setFolderModalOpen] = useState(false)
  const [bookmarkModalOpen, setBookmarkModalOpen] = useState(false)
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [exportFormat, setExportFormat] = useState<ExportFormat>('json')
  const [exportScope, setExportScope] = useState<'all' | 'folder'>('all')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importTargetScope, setImportTargetScope] = useState<'root' | 'current'>(
    'root',
  )
  const [importSkipExisting, setImportSkipExisting] = useState(true)
  const [importEnqueueThumbnails, setImportEnqueueThumbnails] = useState(true)
  const [importLoading, setImportLoading] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [folderPendingDelete, setFolderPendingDelete] = useState<Folder | null>(
    null,
  )
  const [editingBookmark, setEditingBookmark] = useState<Bookmark | null>(null)
  const [folderName, setFolderName] = useState('')
  const [bookmarkForm, setBookmarkForm] = useState({
    title: '',
    url: '',
    description: '',
    tag_names: '',
  })
  const [urlPreviewStatus, setUrlPreviewStatus] = useState<
    'idle' | 'loading' | 'done' | 'error'
  >('idle')
  const [urlPreviewMessage, setUrlPreviewMessage] = useState<string | null>(null)
  const autofilledTitleRef = useRef<string | null>(null)
  const autofilledDescriptionRef = useRef<string | null>(null)
  const lastPreviewedUrlRef = useRef<string | null>(null)
  const urlPreviewRequestRef = useRef(0)

  const crumbs = useMemo(() => {
    if (selectedFolderId == null) return [] as Folder[]
    const path = findPath(tree, selectedFolderId) ?? []
    return path.map(({ children: _children, ...folder }) => folder)
  }, [tree, selectedFolderId])

  const currentTitle = useMemo(() => {
    if (selectedFolderId == null) return 'All bookmarks'
    return crumbs[crumbs.length - 1]?.name ?? 'Folder'
  }, [selectedFolderId, crumbs])

  const refreshTree = useCallback(async () => {
    const next = await api.getFolderTree()
    setTree(next)
    setExpanded((prev) => (prev.size ? prev : collectExpandedDefaults(next)))
  }, [])

  const refreshBookmarks = useCallback(async () => {
    const next = await api.listBookmarks({
      folder_id: selectedFolderId ?? undefined,
      q: search || undefined,
      unfiled_only: false,
    })
    setBookmarks(next)
  }, [selectedFolderId, search])

  const reload = useCallback(async () => {
    try {
      setError(null)
      await refreshTree()
      await refreshBookmarks()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    }
  }, [refreshTree, refreshBookmarks])

  useEffect(() => {
    void reload()
  }, [reload])

  const selectFolder = (folderId: number | null) => {
    setSelectedFolderId(folderId)
    if (location.pathname !== '/') navigate('/')
  }

  const toggleExpanded = (folderId: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(folderId)) next.delete(folderId)
      else next.add(folderId)
      return next
    })
  }

  const resetUrlPreviewState = () => {
    urlPreviewRequestRef.current += 1
    setUrlPreviewStatus('idle')
    setUrlPreviewMessage(null)
    autofilledTitleRef.current = null
    autofilledDescriptionRef.current = null
    lastPreviewedUrlRef.current = null
  }

  const openCreateBookmark = () => {
    setEditingBookmark(null)
    setBookmarkForm({ title: '', url: '', description: '', tag_names: '' })
    resetUrlPreviewState()
    setBookmarkModalOpen(true)
  }

  const openEditBookmark = (bookmark: Bookmark) => {
    setEditingBookmark(bookmark)
    setBookmarkForm({
      title: bookmark.title,
      url: bookmark.url,
      description: bookmark.description ?? '',
      tag_names: bookmark.tags.map((tag) => tag.name).join(', '),
    })
    resetUrlPreviewState()
    setBookmarkModalOpen(true)
  }

  const handleUrlBlur = async () => {
    const rawUrl = bookmarkForm.url.trim()
    if (!rawUrl || !isValidHttpUrl(rawUrl)) {
      setUrlPreviewStatus('idle')
      setUrlPreviewMessage(null)
      return
    }
    if (lastPreviewedUrlRef.current === rawUrl) {
      return
    }

    const requestId = urlPreviewRequestRef.current + 1
    urlPreviewRequestRef.current = requestId
    setUrlPreviewStatus('loading')
    setUrlPreviewMessage('Looking up page title…')
    try {
      const preview = await api.previewUrl(rawUrl)
      if (urlPreviewRequestRef.current !== requestId) {
        return
      }
      lastPreviewedUrlRef.current = rawUrl

      let appliedTitle: string | null = null
      let appliedDescription = false
      setBookmarkForm((prev) => {
        const next = { ...prev }
        const canReplaceTitle =
          !prev.title.trim() || prev.title === autofilledTitleRef.current
        if (preview.title && canReplaceTitle) {
          next.title = preview.title
          autofilledTitleRef.current = preview.title
          appliedTitle = preview.title
        }
        const canReplaceDescription =
          !prev.description.trim() ||
          prev.description === autofilledDescriptionRef.current
        if (preview.description && canReplaceDescription) {
          next.description = preview.description.slice(0, DESCRIPTION_MAX_LENGTH)
          autofilledDescriptionRef.current = next.description
          appliedDescription = true
        }
        return next
      })

      setUrlPreviewStatus('done')
      if (appliedTitle) {
        setUrlPreviewMessage(`Filled from page: ${appliedTitle}`)
      } else if (appliedDescription) {
        setUrlPreviewMessage('Description filled from page')
      } else if (preview.title || preview.description) {
        setUrlPreviewMessage('Page metadata found (fields left unchanged)')
      } else {
        setUrlPreviewMessage('No title found on that page')
      }
    } catch (err) {
      if (urlPreviewRequestRef.current !== requestId) {
        return
      }
      setUrlPreviewStatus('error')
      setUrlPreviewMessage(
        err instanceof Error ? err.message : 'Could not look up that URL',
      )
    }
  }

  const submitFolder = async () => {
    try {
      await api.createFolder({
        name: folderName.trim(),
        parent_id: selectedFolderId,
      })
      setFolderName('')
      setFolderModalOpen(false)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create folder')
    }
  }

  const confirmDeleteFolder = async () => {
    if (!folderPendingDelete) return
    const deleted = folderPendingDelete
    const node = findNode(tree, deleted.id)
    const selectedInSubtree =
      node != null &&
      selectedFolderId != null &&
      subtreeContains(node, selectedFolderId)
    try {
      await api.deleteFolder(deleted.id, true)
      setFolderPendingDelete(null)
      if (selectedInSubtree) {
        setSelectedFolderId(deleted.parent_id)
      }
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete folder')
    }
  }

  const submitBookmark = async () => {
    const tag_names = bookmarkForm.tag_names
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
    try {
      if (editingBookmark) {
        await api.updateBookmark(editingBookmark.id, {
          title: bookmarkForm.title,
          url: bookmarkForm.url,
          description: bookmarkForm.description || null,
          folder_id: selectedFolderId,
          tag_names,
        })
      } else {
        await api.createBookmark({
          title: bookmarkForm.title,
          url: bookmarkForm.url,
          description: bookmarkForm.description || null,
          folder_id: selectedFolderId,
          tag_names,
        })
      }
      setBookmarkModalOpen(false)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save bookmark')
    }
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand">
          <img src="/logo.png" alt="Bald Bookmarks Logo" className="brand-logo" />
          <div className="brand-text">
            <p className="brand-name">Bald Bookmarks</p>
            <p className="brand-sub">Personal library</p>
          </div>
        </div>

        <div className="sidebar-section">
          <p className="sidebar-label">Browse</p>
        </div>
        <nav className="sidebar-nav" aria-label="Primary">
          <button
            type="button"
            className={`nav-item ${!isAdmin && selectedFolderId === null ? 'is-active' : ''}`}
            onClick={() => selectFolder(null)}
          >
            <NavIcon />
            All bookmarks
          </button>
          <button
            type="button"
            className={`nav-item ${isAdmin ? 'is-active' : ''}`}
            onClick={() => navigate('/admin/configuration')}
          >
            <AdminIcon />
            Admin console
          </button>
        </nav>

        {isAdmin ? (
          <>
            <div className="sidebar-section">
              <p className="sidebar-label">Admin</p>
            </div>
            <div className="sidebar-folders">
              <nav className="sidebar-nav" aria-label="Admin sections">
                {ADMIN_SECTIONS.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={`nav-item ${adminSection === section.id ? 'is-active' : ''}`}
                    onClick={() => navigate(`/admin/${section.id}`)}
                  >
                    {section.title}
                  </button>
                ))}
              </nav>
            </div>
          </>
        ) : (
          <>
            <div className="sidebar-section">
              <p className="sidebar-label">Folders</p>
            </div>
            <div className="sidebar-folders">
              <FolderTree
                nodes={tree}
                expanded={expanded}
                selectedFolderId={selectedFolderId}
                onToggle={toggleExpanded}
                onSelect={selectFolder}
                onDelete={setFolderPendingDelete}
              />
            </div>
          </>
        )}

        <div className="sidebar-footer">local · dark · v0.1</div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-meta">
            <span className="meta-pill">
              <span className="meta-dot" aria-hidden="true" />
              Live
            </span>
            <span className="meta-pill">{bookmarks.length} bookmarks</span>
            <span className="meta-pill">{tree.length} root folders</span>
          </div>
          {!isAdmin ? (
            <div className="topbar-actions">
              <InputSearch value={search} onChange={setSearch} />
              <Button variant="secondary" onPress={() => setFolderModalOpen(true)}>
                New folder
              </Button>
              <Button onPress={openCreateBookmark}>New bookmark</Button>
            </div>
          ) : (
            <div className="topbar-actions">
              <span className="meta-pill">Admin console</span>
            </div>
          )}
        </header>

        <div className="page-header">
          <div className="page-heading">
            <h1>{isAdmin && adminMeta ? adminMeta.title : currentTitle}</h1>
            <p>
              {isAdmin && adminMeta
                ? `Admin console · ${adminMeta.blurb}`
                : search
                  ? `Filtered by “${search}”`
                  : selectedFolderId == null
                    ? 'Everything across your library'
                    : 'Bookmarks in this folder'}
            </p>
          </div>
          {!isAdmin ? (
            <div className="page-tools">
              <Button size="sm" variant="secondary" onPress={() => void reload()}>
                Refresh
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onPress={() => {
                  setExportScope(selectedFolderId != null ? 'folder' : 'all')
                  setExportModalOpen(true)
                }}
              >
                Export
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onPress={() => {
                  setImportFile(null)
                  setImportResult(null)
                  setImportError(null)
                  setImportTargetScope(
                    selectedFolderId != null ? 'current' : 'root',
                  )
                  setImportModalOpen(true)
                }}
              >
                Import
              </Button>
              {selectedFolderId != null ? (
                <Button
                  size="sm"
                  variant="danger"
                  onPress={() => {
                    const current = crumbs[crumbs.length - 1]
                    if (current) setFolderPendingDelete(current)
                  }}
                >
                  Delete folder
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <main className="content-pane">
          {isAdmin && adminSection ? (
            <AdminConsole section={adminSection} />
          ) : (
            <>
              {error ? <div className="error-banner">{error}</div> : null}

              <div className="panel">
                <BookmarkList
                  bookmarks={bookmarks}
                  onEdit={openEditBookmark}
                  onDelete={async (bookmarkId) => {
                    await api.deleteBookmark(bookmarkId)
                    await reload()
                  }}
                  onRefreshThumbnail={async (bookmarkId) => {
                    await api.refreshThumbnail(bookmarkId)
                    await reload()
                  }}
                />
              </div>
            </>
          )}
        </main>
      </div>

      {folderPendingDelete ? (
        <ModalPanel
          title="Delete folder"
          onClose={() => setFolderPendingDelete(null)}
        >
          <p className="modal-copy">
            {deleteFolderMessage(folderPendingDelete, tree)}
          </p>
          <div className="modal-actions">
            <Button
              variant="secondary"
              onPress={() => setFolderPendingDelete(null)}
            >
              Cancel
            </Button>
            <Button variant="danger" onPress={() => void confirmDeleteFolder()}>
              Delete folder
            </Button>
          </div>
        </ModalPanel>
      ) : null}

      {folderModalOpen ? (
        <ModalPanel title="Create folder" onClose={() => setFolderModalOpen(false)}>
          <TextField label="Name" value={folderName} onChange={setFolderName} />
          <div className="modal-actions">
            <Button variant="secondary" onPress={() => setFolderModalOpen(false)}>
              Cancel
            </Button>
            <Button onPress={() => void submitFolder()}>Create</Button>
          </div>
        </ModalPanel>
      ) : null}

      {bookmarkModalOpen ? (
        <ModalPanel
          title={editingBookmark ? 'Edit bookmark' : 'Create bookmark'}
          onClose={() => setBookmarkModalOpen(false)}
        >
          <TextField
            label="URL"
            value={bookmarkForm.url}
            type="url"
            placeholder="https://example.com"
            onChange={(url) => {
              setBookmarkForm((prev) => ({ ...prev, url }))
              urlPreviewRequestRef.current += 1
              lastPreviewedUrlRef.current = null
              if (urlPreviewStatus !== 'idle') {
                setUrlPreviewStatus('idle')
                setUrlPreviewMessage(null)
              }
            }}
            onBlur={() => void handleUrlBlur()}
            busy={urlPreviewStatus === 'loading'}
            hint={urlPreviewMessage}
          />
          <TextField
            label="Title"
            value={bookmarkForm.title}
            placeholder={
              urlPreviewStatus === 'loading' ? 'Fetching title…' : undefined
            }
            onChange={(title) => setBookmarkForm((prev) => ({ ...prev, title }))}
            busy={urlPreviewStatus === 'loading' && !bookmarkForm.title}
          />
          <TextField
            label="Description"
            value={bookmarkForm.description}
            maxLength={DESCRIPTION_MAX_LENGTH}
            onChange={(description) =>
              setBookmarkForm((prev) => ({ ...prev, description }))
            }
          />
          <TextField
            label="Tags (comma separated)"
            value={bookmarkForm.tag_names}
            onChange={(tag_names) =>
              setBookmarkForm((prev) => ({ ...prev, tag_names }))
            }
          />
          <div className="modal-actions">
            <Button variant="secondary" onPress={() => setBookmarkModalOpen(false)}>
              Cancel
            </Button>
            <Button onPress={() => void submitBookmark()}>Save</Button>
          </div>
        </ModalPanel>
      ) : null}

      {exportModalOpen ? (
        <ModalPanel
          title="Export bookmarks"
          onClose={() => setExportModalOpen(false)}
        >
          <div style={{ padding: '0.9rem', display: 'grid', gap: '0.85rem' }}>
            <div className="field">
              <span>Format</span>
              <div
                style={{
                  display: 'grid',
                  gap: '0.45rem',
                  marginTop: '0.2rem',
                }}
              >
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    fontSize: '0.8125rem',
                    color: 'var(--bb-ink)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="export-format"
                    checked={exportFormat === 'json'}
                    onChange={() => setExportFormat('json')}
                  />
                  JSON backup (full library fidelity, folders, tags)
                </label>
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    fontSize: '0.8125rem',
                    color: 'var(--bb-ink)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="export-format"
                    checked={exportFormat === 'html'}
                    onChange={() => setExportFormat('html')}
                  />
                  HTML file (Netscape Bookmark format for browsers)
                </label>
              </div>
            </div>

            {selectedFolderId != null ? (
              <div className="field">
                <span>Scope</span>
                <div
                  style={{
                    display: 'grid',
                    gap: '0.45rem',
                    marginTop: '0.2rem',
                  }}
                >
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      fontSize: '0.8125rem',
                      color: 'var(--bb-ink)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="export-scope"
                      checked={exportScope === 'folder'}
                      onChange={() => setExportScope('folder')}
                    />
                    Current folder: “{currentTitle}” (and subfolders)
                  </label>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      fontSize: '0.8125rem',
                      color: 'var(--bb-ink)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="export-scope"
                      checked={exportScope === 'all'}
                      onChange={() => setExportScope('all')}
                    />
                    Entire library
                  </label>
                </div>
              </div>
            ) : null}
          </div>

          <div className="modal-actions">
            <Button
              variant="secondary"
              onPress={() => setExportModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onPress={() => {
                const targetFolder =
                  exportScope === 'folder' ? selectedFolderId : null
                window.location.href = api.exportBookmarkUrl(
                  exportFormat,
                  targetFolder,
                )
                setExportModalOpen(false)
              }}
            >
              Download export
            </Button>
          </div>
        </ModalPanel>
      ) : null}

      {importModalOpen ? (
        <ModalPanel
          title="Import / restore bookmarks"
          onClose={() => setImportModalOpen(false)}
        >
          <div style={{ padding: '0.9rem', display: 'grid', gap: '0.85rem' }}>
            <div className="field">
              <span>Choose file (.json, .html, .htm)</span>
              <input
                type="file"
                accept=".json,.html,.htm"
                onChange={(e) => {
                  setImportFile(e.target.files?.[0] ?? null)
                  setImportResult(null)
                  setImportError(null)
                }}
                style={{
                  color: 'var(--bb-ink)',
                  fontSize: '0.8125rem',
                  padding: '0.4rem 0',
                }}
              />
            </div>

            {selectedFolderId != null ? (
              <div className="field">
                <span>Destination</span>
                <div
                  style={{
                    display: 'grid',
                    gap: '0.45rem',
                    marginTop: '0.2rem',
                  }}
                >
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      fontSize: '0.8125rem',
                      color: 'var(--bb-ink)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="import-target"
                      checked={importTargetScope === 'root'}
                      onChange={() => setImportTargetScope('root')}
                    />
                    Root level (preserve original hierarchy)
                  </label>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      fontSize: '0.8125rem',
                      color: 'var(--bb-ink)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="import-target"
                      checked={importTargetScope === 'current'}
                      onChange={() => setImportTargetScope('current')}
                    />
                    Inside folder “{currentTitle}”
                  </label>
                </div>
              </div>
            ) : null}

            <div style={{ display: 'grid', gap: '0.45rem' }}>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontSize: '0.8125rem',
                  color: 'var(--bb-ink)',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={importSkipExisting}
                  onChange={(e) => setImportSkipExisting(e.target.checked)}
                />
                Skip existing bookmark URLs (prevent duplicates)
              </label>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontSize: '0.8125rem',
                  color: 'var(--bb-ink)',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={importEnqueueThumbnails}
                  onChange={(e) => setImportEnqueueThumbnails(e.target.checked)}
                />
                Queue thumbnail preview generation for imported bookmarks
              </label>
            </div>

            {importError ? (
              <div className="error-banner">{importError}</div>
            ) : null}

            {importResult ? (
              <div
                style={{
                  padding: '0.75rem',
                  background: 'var(--bb-elevated)',
                  borderRadius: '0.375rem',
                  fontSize: '0.8125rem',
                }}
              >
                <p
                  style={{
                    margin: '0 0 0.35rem',
                    fontWeight: 600,
                    color: '#86efac',
                  }}
                >
                  Import complete
                </p>
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: '1.2rem',
                    color: 'var(--bb-ink)',
                  }}
                >
                  <li>Bookmarks imported: {importResult.bookmarks_created}</li>
                  <li>Folders created: {importResult.folders_created}</li>
                  <li>
                    Bookmarks skipped (duplicates):{' '}
                    {importResult.bookmarks_skipped}
                  </li>
                  <li>Tags created: {importResult.tags_created}</li>
                </ul>
                {importResult.errors.length > 0 ? (
                  <div
                    style={{ marginTop: '0.5rem', color: 'var(--bb-faint)' }}
                  >
                    <p style={{ margin: '0.25rem 0' }}>Warnings:</p>
                    <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
                      {importResult.errors.map((msg, i) => (
                        <li key={i}>{msg}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="modal-actions">
            <Button
              variant="secondary"
              onPress={() => setImportModalOpen(false)}
            >
              {importResult ? 'Close' : 'Cancel'}
            </Button>
            {!importResult ? (
              <Button
                isDisabled={!importFile || importLoading}
                onPress={async () => {
                  if (!importFile) return
                  try {
                    setImportLoading(true)
                    setImportError(null)
                    setImportResult(null)
                    const text = await importFile.text()
                    const targetId =
                      importTargetScope === 'current' ? selectedFolderId : null
                    const res = await api.importBookmarks(text, {
                      target_folder_id: targetId,
                      skip_existing: importSkipExisting,
                      enqueue_thumbnails: importEnqueueThumbnails,
                    })
                    setImportResult(res)
                    await reload()
                  } catch (err) {
                    setImportError(
                      err instanceof Error ? err.message : 'Import failed',
                    )
                  } finally {
                    setImportLoading(false)
                  }
                }}
              >
                {importLoading ? 'Importing…' : 'Import'}
              </Button>
            ) : null}
          </div>
        </ModalPanel>
      ) : null}
    </div>
  )
}

function InputSearch({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="search-field">
      <span className="sr-only">Search</span>
      <input
        value={value}
        placeholder="Search bookmarks"
        onChange={(event) => onChange(event.target.value)}
      />
      <kbd className="search-kbd">⌘K</kbd>
    </label>
  )
}

function NavIcon() {
  return (
    <svg className="nav-item-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2.5 3.5h11v9h-11zM5 3.5v9M11 3.5v9"
        stroke="currentColor"
        strokeWidth="1.25"
      />
    </svg>
  )
}

function AdminIcon() {
  return (
    <svg className="nav-item-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M6.2 2.75h3.6l.35 1.35 1.25.7 1.3-.55 1.8 3.1-1.05 1.05v1.2l1.05 1.05-1.8 3.1-1.3-.55-1.25.7-.35 1.35H6.2l-.35-1.35-1.25-.7-1.3.55-1.8-3.1 1.05-1.05v-1.2L1.5 7.35l1.8-3.1 1.3.55 1.25-.7z"
        stroke="currentColor"
        strokeWidth="1.15"
        strokeLinejoin="round"
      />
      <circle cx="8" cy="8" r="1.65" stroke="currentColor" strokeWidth="1.15" />
    </svg>
  )
}

function isValidHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value.includes('://') ? value : `https://${value}`)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}
