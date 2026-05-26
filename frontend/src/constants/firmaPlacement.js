/**
 * Zona de firma en transferencias (coordenadas 0–1, origen arriba-izquierda, A4).
 * Mantener alineado con `placement_firma_transferencia_norm()` en backend/generador.py
 */
const PAGE_A4_W_MM = 210
const PAGE_A4_H_MM = 297
const DOC_MARGIN_R_MM = 10
const DOC_MARGIN_B_MM = 8
const FIRMA_TOTAL_ROW_MM = 11
const FIRMA_CAJA_ANCHO_MM = 58
const FIRMA_CAJA_ALTO_MM = 42
const FIRMA_MARGEN_SUPERIOR_MM = 6

export const FIRMA_META_KEY = 'rf_firma'

export function transferenciaFirmaZone() {
  const x = (PAGE_A4_W_MM - DOC_MARGIN_R_MM - FIRMA_CAJA_ANCHO_MM) / PAGE_A4_W_MM
  const y =
    (PAGE_A4_H_MM - DOC_MARGIN_B_MM - FIRMA_TOTAL_ROW_MM - FIRMA_CAJA_ALTO_MM - FIRMA_MARGEN_SUPERIOR_MM) /
    PAGE_A4_H_MM
  return {
    x,
    y,
    w: FIRMA_CAJA_ANCHO_MM / PAGE_A4_W_MM,
    h: FIRMA_CAJA_ALTO_MM / PAGE_A4_H_MM,
  }
}

/**
 * Lee zona desde Keywords del PDF.
 * Formato actual: rf_firma=página,x,y,w,h
 * Formato antiguo: rf_firma=x,y,w,h (página = última hoja)
 */
export function parseFirmaZoneFromKeywords(keywords, numPages = 1) {
  if (!keywords) return null
  const s = String(keywords)
  const m5 = s.match(/rf_firma=(\d+),([\d.]+),([\d.]+),([\d.]+),([\d.]+)/)
  if (m5) {
    return { page: +m5[1], x: +m5[2], y: +m5[3], w: +m5[4], h: +m5[5] }
  }
  const m4 = s.match(/rf_firma=([\d.]+),([\d.]+),([\d.]+),([\d.]+)/)
  if (m4) {
    return { page: numPages, x: +m4[1], y: +m4[2], w: +m4[3], h: +m4[4] }
  }
  return null
}

/** Rectángulo del overlay en píxeles = caja de firma de la plantilla (tamaño fijo). */
export function zoneOverlayRect(zone, pageW, pageH) {
  return {
    ox: zone.x * pageW,
    oy: zone.y * pageH,
    ow: zone.w * pageW,
    oh: zone.h * pageH,
  }
}

/** Placement normalizado 0–1 para guardar en PDF (misma caja que la plantilla). */
export function zonePlacementNormalized(zone) {
  return { x: zone.x, y: zone.y, w: zone.w, h: zone.h }
}

/** Encaja la firma dentro de la zona (modo libre / no transferencia). */
export function fitSignatureInZone(zone, pageW, pageH, aspect, pad = 8) {
  const boxW = zone.w * pageW
  const boxH = zone.h * pageH
  const boxX = zone.x * pageW
  const boxY = zone.y * pageH
  const innerW = Math.max(20, boxW - 2 * pad)
  const innerH = Math.max(16, boxH - 2 * pad)
  let sw = innerW
  let sh = sw / aspect
  if (sh > innerH) {
    sh = innerH
    sw = sh * aspect
  }
  return {
    ox: boxX + (boxW - sw) / 2,
    oy: boxY + (boxH - sh) / 2,
    ow: sw,
    oh: sh,
  }
}
