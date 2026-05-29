/** Evita sync Tango redundante (misma sesión, usuario, apartado y fecha). */
const PREFIX = 'rf_tango_sync:'
const TTL_MS = 5 * 60 * 1000

export function tangoSyncCacheKey(username, apartadoCodigo, fecha) {
  const u = (username || '').trim().toUpperCase()
  const c = (apartadoCodigo || '').trim()
  const f = (fecha || '').trim().slice(0, 10)
  return `${PREFIX}${u}:${c}:${f}`
}

export function shouldSkipTangoSync(key) {
  if (!key) return false
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return false
    const ts = Number(raw)
    if (!Number.isFinite(ts)) return false
    return Date.now() - ts < TTL_MS
  } catch {
    return false
  }
}

export function markTangoSynced(key) {
  if (!key) return
  try {
    sessionStorage.setItem(key, String(Date.now()))
  } catch {
    /* ignore */
  }
}
