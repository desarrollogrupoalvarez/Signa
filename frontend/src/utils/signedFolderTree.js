const ROOTS = [
  { key: 'transferencias', label: 'Transferencias', modoFlujo: 'transferencia' },
  { key: 'ingresos', label: 'Ingresos', modoFlujo: 'ingreso' },
]

/** Raíz del árbol según modo_flujo u origen del apartado. */
export function getSignedRootKey(doc) {
  const modo = (doc?.modo_flujo || '').trim().toLowerCase()
  if (modo === 'ingreso') return 'ingresos'
  if (modo === 'transferencia') return 'transferencias'
  const origen = (doc?.origen || doc?.apartado_codigo || '').trim().toLowerCase()
  if (origen.includes('ingreso')) return 'ingresos'
  return 'transferencias'
}

/** Segmentos de carpeta y nombre de archivo a partir de doc.nombre. */
export function parseSignedPathSegments(nombre) {
  const norm = (nombre || '').trim().replace(/\\/g, '/')
  const parts = norm.split('/').filter(Boolean)
  if (parts.length <= 1) {
    return { folderSegments: [], filename: parts[0] || norm }
  }
  const rest = parts.slice(1)
  return {
    folderSegments: rest.slice(0, -1),
    filename: rest[rest.length - 1],
  }
}

function compareFolderLabels(a, b) {
  return a.localeCompare(b, 'es', { sensitivity: 'base' })
}

function compareFileNodes(a, b) {
  const da = a.doc?.modificado_en || ''
  const db = b.doc?.modificado_en || ''
  return db.localeCompare(da)
}

/** Lista plana: más reciente primero (ISO modificado_en). */
export function sortSignedDocsByRecent(docs) {
  return [...(docs || [])].sort(
    (a, b) => (b.modificado_en || '').localeCompare(a.modificado_en || ''),
  )
}

function countFilesInSubtree(node) {
  if (node.type === 'file') return 1
  return (node.children || []).reduce((sum, child) => sum + countFilesInSubtree(child), 0)
}

function attachFileCounts(node) {
  if (node.type === 'file') return node
  const children = (node.children || []).map(attachFileCounts)
  return { ...node, children, fileCount: countFilesInSubtree({ ...node, children }) }
}

function pruneEmptyBranches(nodes) {
  const out = []
  for (const node of nodes) {
    if (node.type === 'file') {
      out.push(node)
      continue
    }
    const children = pruneEmptyBranches(node.children || [])
    if (children.length === 0) continue
    out.push(attachFileCounts({ ...node, children }))
  }
  return out
}

function buildBranch(rootKey, label, branch) {
  const folderNodes = [...branch.children.entries()]
    .sort(([a], [b]) => compareFolderLabels(a, b))
    .map(([seg, child]) => {
      const id = `${rootKey}::${child.path.join('::')}`
      return buildFolderNode(id, seg, child, rootKey)
    })

  const fileNodes = [...branch.docs]
    .sort(compareFileNodes)
    .map((doc) => ({
      id: `${doc.origen || ''}::${doc.nombre}`,
      type: 'file',
      label: parseSignedPathSegments(doc.nombre).filename,
      doc,
    }))

  const children = [...folderNodes, ...fileNodes]
  const node = {
    id: rootKey,
    type: 'root',
    label,
    children: children.length ? children : undefined,
    fileCount: 0,
  }
  return attachFileCounts(node)
}

function buildFolderNode(id, label, branch, rootKey) {
  const folderNodes = [...branch.children.entries()]
    .sort(([a], [b]) => compareFolderLabels(a, b))
    .map(([seg, child]) => {
      const childId = `${rootKey}::${child.path.join('::')}`
      return buildFolderNode(childId, seg, child, rootKey)
    })

  const fileNodes = [...branch.docs]
    .sort(compareFileNodes)
    .map((doc) => ({
      id: `${doc.origen || ''}::${doc.nombre}`,
      type: 'file',
      label: parseSignedPathSegments(doc.nombre).filename,
      doc,
    }))

  const children = [...folderNodes, ...fileNodes]
  const node = {
    id,
    type: 'folder',
    label,
    children: children.length ? children : undefined,
    fileCount: 0,
  }
  return attachFileCounts(node)
}

function emptyBranch() {
  return { children: new Map(), docs: [], path: [] }
}

function ensureFolder(parent, segment) {
  if (!parent.children.has(segment)) {
    parent.children.set(segment, { ...emptyBranch(), path: [...parent.path, segment] })
  }
  return parent.children.get(segment)
}

/**
 * Construye el árbol Transferencias / Ingresos → subcarpetas → archivos.
 * @param {object[]} docs
 * @param {{ searchActive?: boolean }} options
 */
export function buildSignedFolderTree(docs, { searchActive = false } = {}) {
  const branches = new Map(
    ROOTS.map((r) => [r.key, { ...emptyBranch(), path: [] }]),
  )

  for (const doc of docs || []) {
    const rootKey = getSignedRootKey(doc)
    if (!branches.has(rootKey)) {
      branches.set(rootKey, { ...emptyBranch(), path: [] })
    }
    const { folderSegments } = parseSignedPathSegments(doc.nombre)
    let node = branches.get(rootKey)
    for (const seg of folderSegments) {
      node = ensureFolder(node, seg)
    }
    node.docs.push(doc)
  }

  let tree = ROOTS.map((r) => buildBranch(r.key, r.label, branches.get(r.key)))

  if (searchActive) {
    tree = pruneEmptyBranches(tree)
  }

  return tree
}

/** IDs de carpetas a expandir cuando hay búsqueda activa. */
export function collectExpandedIdsForSearch(tree) {
  const ids = []
  const walk = (nodes) => {
    for (const node of nodes || []) {
      if (node.type === 'file') continue
      ids.push(node.id)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(tree)
  return ids
}

/** Raíces expandidas por defecto (sin búsqueda). */
export const DEFAULT_EXPANDED_ROOT_IDS = ROOTS.map((r) => r.key)

/** Adapta documentos de métricas/registros al formato del árbol de digitalizados. */
export function metricsDocsToTreeDocs(docs, apartados = []) {
  const apMap = new Map((apartados || []).map((a) => [a.codigo, a]))
  return (docs || [])
    .filter((d) => (d?.nombre_firmado || '').trim())
    .map((d) => {
      const ap = apMap.get(d.apartado)
      const modo_flujo = ap?.modo_flujo || 'transferencia'
      const fecha = (d.fecha || '').trim()
      return {
        nombre: d.nombre_firmado.trim(),
        origen: d.apartado || '',
        modo_flujo,
        modificado_en: fecha ? (fecha.includes('T') ? fecha : `${fecha}T12:00:00`) : null,
        categoria: 'pdf',
      }
    })
}
