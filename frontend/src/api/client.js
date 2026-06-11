export const API_BASE = window.location.origin

export function getToken() {
  return localStorage.getItem('rf_token') || ''
}

export async function apiFetch(path, options = {}) {
  const token = getToken()
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  }
  const cache =
    typeof options.cache !== 'undefined' ? options.cache : 'no-store'
  const { signal, ...rest } = options
  const res = await fetch(API_BASE + path, {
    ...rest,
    headers,
    cache,
    ...(signal ? { signal } : {}),
  })

  if (!res.ok) {
    if (res.status === 401) {
      const text = await res.text().catch(() => '')
      const err = new Error('No autorizado')
      err.status = 401
      err.detail = text || '401'
      throw err
    }
    if (res.status === 403) {
      const text = await res.text().catch(() => '')
      const err = new Error('Sin permiso')
      err.status = 403
      err.detail = text.length < 240 ? text : ''
      throw err
    }
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(body.error || `HTTP ${res.status}`)
  }
  return res
}

export function getPdfUrl(docId) {
  const token = getToken()
  return `${API_BASE}/api/documentos/${docId}/pdf${token ? `?token=${encodeURIComponent(token)}` : ''}`
}

export function getSignedPdfUrl(nombre) {
  return getSignedFileUrl(nombre)
}

/** Cualquier archivo en carpetas de firmados (imagen, PDF, oficina, etc.). */
export function getSignedFileUrl(nombre) {
  const token = getToken()
  const base = `${API_BASE}/api/firmados/archivo?n=${encodeURIComponent(nombre || '')}`
  return token ? `${base}&token=${encodeURIComponent(token)}` : base
}

/** Descarga un archivo firmado por su nombre de listado (p. ej. TRA/.../archivo.pdf). */
export function downloadSignedFile(nombre) {
  const n = (nombre || '').trim()
  if (!n) return
  const url = getSignedFileUrl(n)
  const base = n.replace(/\\/g, '/').split('/').filter(Boolean).pop() || 'documento.pdf'
  const a = document.createElement('a')
  a.href = url
  a.download = base
  a.rel = 'noreferrer'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
