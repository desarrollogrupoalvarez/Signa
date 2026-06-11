/** Agrupa apartados del usuario por area/deposito para selectores UI. */
export function groupApartadosByArea(apartados = []) {
  const map = new Map()
  for (const a of apartados || []) {
    const key = a.area_id ?? `_sin_${a.area_codigo || 'area'}`
    if (!map.has(key)) {
      map.set(key, {
        area_id: a.area_id ?? null,
        area_codigo: a.area_codigo || null,
        area_nombre: a.area_nombre || 'Sin area',
        apartados: [],
      })
    }
    map.get(key).apartados.push(a)
  }
  return [...map.values()]
    .map((g) => ({
      ...g,
      apartados: [...g.apartados].sort((x, y) => (x.orden ?? 0) - (y.orden ?? 0) || String(x.codigo).localeCompare(String(y.codigo))),
    }))
    .sort((x, y) => String(x.area_nombre).localeCompare(String(y.area_nombre)))
}

export function hasMultipleAreas(apartados = []) {
  return groupApartadosByArea(apartados).length > 1
}

/** Estado inicial del arbol area->apartado desde user.area_ids y user.apartado_ids. */
export function initAreaApartadoSelection(user, areaTree = []) {
  const areaIds = new Set((user?.area_ids || []).map(Number))
  const apartadoIds = new Set((user?.apartado_ids || []).map(Number))
  for (const area of areaTree) {
    const childIds = (area.apartados || []).map((a) => Number(a.id))
    if (!areaIds.has(Number(area.id))) continue
    if (apartadoIds.size === 0) {
      childIds.forEach((id) => apartadoIds.add(id))
      continue
    }
    const explicit = childIds.filter((id) => apartadoIds.has(id))
    if (explicit.length === 0) {
      childIds.forEach((id) => apartadoIds.add(id))
    }
  }
  return { areaIds, apartadoIds }
}

export function buildAreaApartadoPayload(areaIds, apartadoIds) {
  return {
    area_ids: [...areaIds],
    apartado_ids: [...apartadoIds],
  }
}

export function toggleAreaSelection(area, areaIds, apartadoIds) {
  const nextAreas = new Set(areaIds)
  const nextAps = new Set(apartadoIds)
  const childIds = (area.apartados || []).map((a) => Number(a.id))
  const checked = nextAreas.has(Number(area.id))
  if (checked) {
    nextAreas.delete(Number(area.id))
    childIds.forEach((id) => nextAps.delete(id))
  } else {
    nextAreas.add(Number(area.id))
    childIds.forEach((id) => nextAps.add(id))
  }
  return { areaIds: nextAreas, apartadoIds: nextAps }
}

export function toggleApartadoSelection(ap, area, areaIds, apartadoIds) {
  const nextAreas = new Set(areaIds)
  const nextAps = new Set(apartadoIds)
  const apId = Number(ap.id)
  const areaId = Number(area.id)
  if (nextAps.has(apId)) {
    nextAps.delete(apId)
    const childIds = (area.apartados || []).map((a) => Number(a.id))
    const anyLeft = childIds.some((id) => nextAps.has(id))
    if (!anyLeft) nextAreas.delete(areaId)
  } else {
    nextAps.add(apId)
    nextAreas.add(areaId)
  }
  return { areaIds: nextAreas, apartadoIds: nextAps }
}

export function isAreaFullyChecked(area, areaIds, apartadoIds) {
  const childIds = (area.apartados || []).map((a) => Number(a.id))
  if (!childIds.length) return areaIds.has(Number(area.id))
  return childIds.every((id) => apartadoIds.has(id))
}

export function isAreaPartiallyChecked(area, areaIds, apartadoIds) {
  const childIds = (area.apartados || []).map((a) => Number(a.id))
  const n = childIds.filter((id) => apartadoIds.has(id)).length
  return n > 0 && n < childIds.length
}
