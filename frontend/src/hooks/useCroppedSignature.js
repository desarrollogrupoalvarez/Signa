import { useState, useEffect } from 'react'

/**
 * Crops a signature dataURL to its bounding box and returns { dataURL, aspect }.
 * Returns null when no input.
 */
export function useCroppedSignature(rawDataURL) {
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (!rawDataURL) {
      setResult(null)
      return
    }

    const img = new Image()

    img.onload = () => {
      const cw = img.naturalWidth
      const ch = img.naturalHeight
      const c = document.createElement('canvas')
      c.width = cw
      c.height = ch
      const ctx = c.getContext('2d')
      ctx.drawImage(img, 0, 0)
      const { data } = ctx.getImageData(0, 0, cw, ch)
      const ALPHA_THRESHOLD = 20

      let minX = cw, minY = ch, maxX = -1, maxY = -1
      for (let y = 0; y < ch; y++) {
        for (let x = 0; x < cw; x++) {
          if (data[(y * cw + x) * 4 + 3] > ALPHA_THRESHOLD) {
            if (x < minX) minX = x
            if (y < minY) minY = y
            if (x > maxX) maxX = x
            if (y > maxY) maxY = y
          }
        }
      }

      if (maxX < minX) {
        setResult({ dataURL: rawDataURL, aspect: cw / Math.max(ch, 1) })
        return
      }

      const pad = 6
      const x0 = Math.max(0, minX - pad)
      const y0 = Math.max(0, minY - pad)
      const x1 = Math.min(cw - 1, maxX + pad)
      const y1 = Math.min(ch - 1, maxY + pad)
      const w = x1 - x0 + 1
      const h = y1 - y0 + 1

      const out = document.createElement('canvas')
      out.width = w
      out.height = h
      out.getContext('2d').drawImage(c, x0, y0, w, h, 0, 0, w, h)
      setResult({ dataURL: out.toDataURL('image/png'), aspect: w / Math.max(h, 1) })
    }

    img.onerror = () => setResult({ dataURL: rawDataURL, aspect: 1 })
    img.src = rawDataURL
  }, [rawDataURL])

  return result
}
