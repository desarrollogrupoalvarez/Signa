const TANGO_FUENTE_PREFIXES = ['SAN_RAFAEL', 'CTC', 'AGROINDUSTRIAS', 'TELECOMUNICACIONES']

/** Quita la extensión del nombre de archivo (p. ej. .pdf). */
export function displayFileBasename(name) {
  const s = (name || '').trim()
  if (!s) return s
  const dot = s.lastIndexOf('.')
  if (dot > 0) return s.slice(0, dot)
  return s
}

/** Último segmento de ruta/nombre, sin extensión (para listados en UI). */
export function displayNombreArchivo(nameOrPath) {
  const s = (nameOrPath || '').trim()
  if (!s) return s
  const norm = s.replace(/\\/g, '/')
  const base = norm.split('/').filter(Boolean).pop() || norm
  return displayFileBasename(base)
}

/** Nombre pendiente: sin prefijo Tango ni extensión. */
export function displayPendingNombre(doc) {
  let n = displayNombreArchivo(doc?.nombre)
  if (!n) return n

  const candidates = new Set(TANGO_FUENTE_PREFIXES)
  const fuente = (doc?.tango_fuente || '').trim()
  if (fuente) candidates.add(fuente)

  for (const prefix of candidates) {
    const re = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s_]+`, 'i')
    const stripped = n.replace(re, '').trim()
    if (stripped && stripped !== n) {
      n = stripped
      break
    }
  }
  return n
}

/** Nombre firmado/archivado en listados: ruta o nombre sin extensión. */
export function displaySignedNombre(doc) {
  return displayNombreArchivo(doc?.nombre) || ''
}
