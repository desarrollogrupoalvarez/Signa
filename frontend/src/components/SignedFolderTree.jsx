import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Folder } from 'lucide-react'
import SignedListItem from './SignedListItem.jsx'
import {
  buildSignedFolderTree,
  collectExpandedIdsForSearch,
  DEFAULT_EXPANDED_ROOT_IDS,
} from '../utils/signedFolderTree.js'

export default function SignedFolderTree({
  docs = [],
  searchQuery = '',
  selectedDoc,
  onSelectSigned,
}) {
  const searchActive = Boolean((searchQuery || '').trim())
  const tree = useMemo(
    () => buildSignedFolderTree(docs, { searchActive }),
    [docs, searchActive],
  )

  const [expandedIds, setExpandedIds] = useState(() => new Set(DEFAULT_EXPANDED_ROOT_IDS))
  const prevSearchActiveRef = useRef(searchActive)

  // Solo resetear expansión al entrar/salir de búsqueda; no al refrescar la lista (polling).
  useEffect(() => {
    const wasSearch = prevSearchActiveRef.current
    if (wasSearch !== searchActive) {
      prevSearchActiveRef.current = searchActive
      if (searchActive) {
        setExpandedIds(new Set(collectExpandedIdsForSearch(tree)))
      } else {
        setExpandedIds(new Set(DEFAULT_EXPANDED_ROOT_IDS))
      }
      return
    }

    if (searchActive) {
      setExpandedIds((prev) => {
        const needed = collectExpandedIdsForSearch(tree)
        const next = new Set(prev)
        for (const id of needed) next.add(id)
        return next
      })
    }
  }, [searchActive, tree])

  const toggle = (id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const isDocActive = (doc) =>
    selectedDoc?.tipo === 'firmado' &&
    selectedDoc?.nombre === doc.nombre &&
    (selectedDoc?.origen || '') === (doc.origen || '')

  return (
    <div className="space-y-0.5">
      {tree.map((node) => (
        <TreeNode
          key={node.id}
          node={node}
          depth={0}
          expandedIds={expandedIds}
          onToggle={toggle}
          isDocActive={isDocActive}
          onSelectSigned={onSelectSigned}
        />
      ))}
    </div>
  )
}

function TreeNode({ node, depth, expandedIds, onToggle, isDocActive, onSelectSigned }) {
  if (node.type === 'file') {
    return (
      <div style={{ paddingLeft: `${depth * 12 + 4}px` }}>
        <SignedListItem
          doc={node.doc}
          active={isDocActive(node.doc)}
          onClick={() => onSelectSigned(node.doc)}
          compact
        />
      </div>
    )
  }

  const expanded = expandedIds.has(node.id)
  const hasChildren = (node.children || []).length > 0
  const indent = depth * 12

  return (
    <div>
      <button
        type="button"
        onClick={() => hasChildren && onToggle(node.id)}
        className={[
          'w-full flex items-center gap-1.5 py-1.5 pr-2 rounded-md text-left transition-colors',
          hasChildren ? 'hover:bg-app-surface2 cursor-pointer' : 'cursor-default',
          node.type === 'root' ? 'font-bold' : 'font-semibold',
        ].join(' ')}
        style={{ paddingLeft: `${indent + 4}px` }}
      >
        <span className="shrink-0 w-4 h-4 flex items-center justify-center text-app-muted">
          {hasChildren ? (
            expanded ? (
              <ChevronDown size={14} strokeWidth={2} />
            ) : (
              <ChevronRight size={14} strokeWidth={2} />
            )
          ) : null}
        </span>
        <Folder
          size={node.type === 'root' ? 15 : 14}
          strokeWidth={1.75}
          className={node.type === 'root' ? 'text-accent-dark shrink-0' : 'text-app-muted shrink-0'}
        />
        <span
          className={[
            'flex-1 min-w-0 truncate',
            node.type === 'root' ? 'text-[12px] text-app-text' : 'text-[11px] text-app-text',
          ].join(' ')}
        >
          {node.label}
        </span>
        {(node.fileCount ?? 0) > 0 && (
          <span className="shrink-0 text-[9px] font-bold px-1.5 py-px rounded-full bg-app-surface2 text-app-muted border border-app-border">
            {node.fileCount}
          </span>
        )}
      </button>
      {expanded &&
        hasChildren &&
        (node.children || []).map((child) => (
          <TreeNode
            key={child.id}
            node={child}
            depth={depth + 1}
            expandedIds={expandedIds}
            onToggle={onToggle}
            isDocActive={isDocActive}
            onSelectSigned={onSelectSigned}
          />
        ))}
    </div>
  )
}
