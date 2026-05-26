/** Lado largo máximo (px) antes de subir — reduce peso y es suficiente para PDF. */
const MAX_LONG_EDGE = 2048
/** Calidad JPEG al comprimir (0–1) */
const JPEG_QUALITY = 0.78

/**
 * Rota, achica si hace falta y devuelve JPEG comprimido.
 * Los archivos de cámara suelen ser muy pesados; esto baja el tamaño sin afectar legibilidad en el remito.
 */
export function fileToJpegForUpload(file, { rotation: degrees = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const w0 = img.naturalWidth
        const h0 = img.naturalHeight
        if (!w0 || !h0) {
          URL.revokeObjectURL(url)
          reject(new Error('Imagen inválida'))
          return
        }

        const d = ((degrees % 360) + 360) % 360
        const maxSrc = Math.max(w0, h0)
        const preScale = maxSrc > MAX_LONG_EDGE ? MAX_LONG_EDGE / maxSrc : 1
        const sw = w0 * preScale
        const sh = h0 * preScale

        const canvas = document.createElement('canvas')
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          URL.revokeObjectURL(url)
          reject(new Error('Canvas'))
          return
        }

        if (d === 0) {
          const rw = Math.max(1, Math.round(sw))
          const rh = Math.max(1, Math.round(sh))
          canvas.width = rw
          canvas.height = rh
          ctx.drawImage(img, 0, 0, w0, h0, 0, 0, rw, rh)
        } else {
          const swap = d === 90 || d === 270
          const cw = Math.max(1, Math.round(swap ? sh : sw))
          const ch = Math.max(1, Math.round(swap ? sw : sh))
          canvas.width = cw
          canvas.height = ch
          ctx.translate(cw / 2, ch / 2)
          ctx.rotate((d * Math.PI) / 180)
          ctx.drawImage(img, 0, 0, w0, h0, -sw / 2, -sh / 2, sw, sh)
        }

        canvas.toBlob(
          (blob) => {
            URL.revokeObjectURL(url)
            if (!blob) {
              reject(new Error('toBlob'))
              return
            }
            const name = (file.name || 'foto').replace(/\.[^.]+$/, '') + '.jpg'
            resolve(new File([blob], name, { type: 'image/jpeg' }))
          },
          'image/jpeg',
          JPEG_QUALITY,
        )
      } catch (e) {
        URL.revokeObjectURL(url)
        reject(e)
      }
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Carga de imagen'))
    }
    img.src = url
  })
}

/**
 * Aplica rotación (grados, horario) y devuelve un File JPEG.
 */
export function rotateImageFileToJpeg(file, degrees) {
  return fileToJpegForUpload(file, { rotation: degrees })
}
