/** DPI al rasterizar la firma para insertar en el PDF (caja ~58×42 mm en A4). */
export const SIGNATURE_EXPORT_DPI = 220

export const A4_PAGE_PT = { w: 595, h: 842 }

export function placementTargetPixels(placement, pageSize = A4_PAGE_PT) {
  const pw = Math.max(0.01, Number(placement?.w) || 0.2)
  const ph = Math.max(0.01, Number(placement?.h) || 0.1)
  const scale = SIGNATURE_EXPORT_DPI / 72
  return {
    targetW: Math.max(64, Math.ceil(pw * pageSize.w * scale)),
    targetH: Math.max(48, Math.ceil(ph * pageSize.h * scale)),
  }
}

/**
 * Escala el PNG de firma hasta la resolución objetivo del placement (sin reducir si ya es mayor).
 * @returns {Promise<string>} dataURL PNG
 */
export function upscaleSignatureForPlacement({ dataURL, aspect, placement }) {
  if (!dataURL) return Promise.resolve('')

  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const srcW = img.naturalWidth || 1
      const srcH = img.naturalHeight || 1
      const ar = aspect > 0 ? aspect : srcW / Math.max(srcH, 1)

      const { targetW, targetH } = placementTargetPixels(placement)
      let outW = targetW
      let outH = Math.round(targetW / ar)
      if (outH > targetH) {
        outH = targetH
        outW = Math.max(1, Math.round(outH * ar))
      }

      if (outW <= srcW && outH <= srcH) {
        resolve(dataURL)
        return
      }

      const canvas = document.createElement('canvas')
      canvas.width = outW
      canvas.height = outH
      const ctx = canvas.getContext('2d')
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(img, 0, 0, outW, outH)
      resolve(canvas.toDataURL('image/png'))
    }
    img.onerror = () => resolve(dataURL)
    img.src = dataURL
  })
}
