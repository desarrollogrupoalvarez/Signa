/** Convierte ruta Windows/UNC/POSIX a URL file:// (vista previa local en el visor). */
export function toFileUrl(path) {
  if (!path) return null
  const s = String(path).trim()
  if (!s) return null
  if (s.startsWith('\\\\')) {
    return `file://///${s.slice(2).replace(/\\/g, '/')}`
  }
  if (/^[A-Za-z]:[\\/]/.test(s)) {
    return `file:///${s.replace(/\\/g, '/')}`
  }
  const posix = s.replace(/\\/g, '/')
  if (posix.startsWith('/')) {
    return `file://${posix}`
  }
  return `file:///${posix}`
}
