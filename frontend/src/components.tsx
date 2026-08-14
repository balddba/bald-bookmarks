import { Button, Chip, Input, Skeleton } from '@heroui/react'
import type { Bookmark, Folder, FolderTreeNode } from './types'

interface FolderTreeProps {
  nodes: FolderTreeNode[]
  expanded: Set<number>
  selectedFolderId: number | null
  onToggle: (folderId: number) => void
  onSelect: (folderId: number | null) => void
  onDelete: (folder: Folder) => void
}

export function FolderTree({
  nodes,
  expanded,
  selectedFolderId,
  onToggle,
  onSelect,
  onDelete,
}: FolderTreeProps) {
  if (nodes.length === 0) {
    return <p className="empty-state">No folders yet.</p>
  }
  return (
    <ul className="folder-tree">
      {nodes.map((node) => (
        <TreeNode
          key={node.id}
          node={node}
          depth={0}
          expanded={expanded}
          selectedFolderId={selectedFolderId}
          onToggle={onToggle}
          onSelect={onSelect}
          onDelete={onDelete}
        />
      ))}
    </ul>
  )
}

function TreeNode({
  node,
  depth,
  expanded,
  selectedFolderId,
  onToggle,
  onSelect,
  onDelete,
}: {
  node: FolderTreeNode
  depth: number
  expanded: Set<number>
  selectedFolderId: number | null
  onToggle: (folderId: number) => void
  onSelect: (folderId: number | null) => void
  onDelete: (folder: Folder) => void
}) {
  const isExpanded = expanded.has(node.id)
  const hasChildren = node.children.length > 0
  return (
    <li>
      <div className="folder-row-wrap" style={{ paddingLeft: `${depth}rem` }}>
        <button
          type="button"
          className="folder-toggle"
          aria-label={isExpanded ? 'Collapse' : 'Expand'}
          disabled={!hasChildren}
          onClick={() => onToggle(node.id)}
        >
          {hasChildren ? (isExpanded ? '▾' : '▸') : '·'}
        </button>
        <button
          type="button"
          className={`folder-row ${selectedFolderId === node.id ? 'is-selected' : ''}`}
          onClick={() => onSelect(node.id)}
        >
          <span className="folder-name">{node.name}</span>
          <span className="folder-count">{node.bookmark_count}</span>
        </button>
        <button
          type="button"
          className="folder-delete"
          aria-label={`Delete ${node.name}`}
          onClick={() => onDelete(node)}
        >
          ×
        </button>
      </div>
      {hasChildren && isExpanded ? (
        <ul>
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              selectedFolderId={selectedFolderId}
              onToggle={onToggle}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

interface BookmarkListProps {
  bookmarks: Bookmark[]
  onEdit: (bookmark: Bookmark) => void
  onDelete: (bookmarkId: number) => void
  onRefreshThumbnail: (bookmarkId: number) => void
}

export function BookmarkList({
  bookmarks,
  onEdit,
  onDelete,
  onRefreshThumbnail,
}: BookmarkListProps) {
  if (bookmarks.length === 0) {
    return <p className="empty-state">No bookmarks in this view.</p>
  }
  return (
    <div className="bookmark-grid">
      {bookmarks.map((bookmark) => (
        <article key={bookmark.id} className="bookmark-item">
          <Thumbnail bookmark={bookmark} />
          <div className="bookmark-body">
            <a href={bookmark.url} target="_blank" rel="noreferrer" className="bookmark-title">
              {bookmark.title}
            </a>
            <p className="bookmark-url">{bookmark.url}</p>
            {bookmark.description ? (
              <p className="bookmark-desc">{bookmark.description}</p>
            ) : null}
            <div className="tag-row">
              {bookmark.tags.map((tag) => (
                <Chip key={tag.id} size="sm">
                  {tag.name}
                </Chip>
              ))}
            </div>
            <div className="bookmark-actions">
              <Button size="sm" variant="secondary" onPress={() => onEdit(bookmark)}>
                Edit
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onPress={() => onRefreshThumbnail(bookmark.id)}
              >
                Refresh preview
              </Button>
              <Button size="sm" variant="danger" onPress={() => onDelete(bookmark.id)}>
                Delete
              </Button>
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}

function Thumbnail({ bookmark }: { bookmark: Bookmark }) {
  if (bookmark.thumbnail_status === 'ready' && bookmark.thumbnail_path) {
    return (
      <img
        className="thumb"
        src={`/media/${bookmark.thumbnail_path}`}
        alt=""
        loading="lazy"
      />
    )
  }
  if (
    bookmark.thumbnail_status === 'pending' ||
    bookmark.thumbnail_status === 'processing'
  ) {
    return <Skeleton className="thumb-skel" />
  }
  return <div className="thumb placeholder">{bookmark.thumbnail_status}</div>
}

interface ModalFormProps {
  title: string
  onClose: () => void
  children: React.ReactNode
}

export function ModalPanel({ title, onClose, children }: ModalFormProps) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h2>{title}</h2>
          <Button size="sm" variant="ghost" onPress={onClose}>
            Close
          </Button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function TextField({
  label,
  value,
  onChange,
  onBlur,
  placeholder,
  type = 'text',
  hint,
  busy = false,
  maxLength,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  placeholder?: string
  type?: string
  hint?: string | null
  busy?: boolean
  maxLength?: number
}) {
  return (
    <label className={`field ${busy ? 'is-busy' : ''}`}>
      <span>{label}</span>
      <div className="field-control">
        <Input
          value={value}
          type={type}
          placeholder={placeholder}
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => onBlur?.()}
        />
        {busy ? <span className="field-spinner" aria-hidden="true" /> : null}
      </div>
      {hint ? (
        <span className="field-hint" role="status" aria-live="polite">
          {hint}
        </span>
      ) : null}
    </label>
  )
}
