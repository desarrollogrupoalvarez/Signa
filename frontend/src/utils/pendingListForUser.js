/** Normaliza usuario Tango / login para comparar sin depender de mayúsculas. */
export function normListUsername(val) {
  return (val || '').trim().toUpperCase()
}

/**
 * Firmantes solo ven pendientes con tango_usuario propio.
 * Defensa en profundidad si la API o caché devuelve datos de otro usuario.
 */
export function filterPendingForUser(documentos, user) {
  if (!user) return []
  const role = user.role
  if (role === 'superadmin' || role === 'administrador') return documentos || []
  const want = normListUsername(user.username)
  if (!want) return []
  return (documentos || []).filter((d) => normListUsername(d.tango_usuario) === want)
}
