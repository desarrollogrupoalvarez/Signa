/** Normaliza usuario Tango / login para comparar sin depender de mayúsculas. */
export function normListUsername(val) {
  return (val || '').trim().toUpperCase()
}

/**
 * Usuarios con pendientes:ver_todos ven todos los documentos.
 * Defensa en profundidad si la API o caché devuelve datos de otro usuario.
 */
export function filterPendingForUser(documentos, user) {
  if (!user) return []
  const perms = user.permissions || []
  if (perms.includes('pendientes:ver_todos')) return documentos || []
  const want = normListUsername(user.username)
  if (!want) return []
  return (documentos || []).filter((d) => normListUsername(d.tango_usuario) === want)
}
