import { useEffect, useRef, useState } from 'react'
import SignaturePad from 'signature_pad'

/**
 * Right panel: square signature canvas + page selector + action buttons.
 *
 * Props:
 *  - selectedDoc
 *  - numPages
 *  - selectedPage
 *  - onPageChange: (n) => void
 *  - onSignatureChange: (dataURL | null) => void
 *  - onSign: () => void
 *  - canSign: boolean
 *  - onSaveWithoutSign: () => void
 *  - canSaveWithoutSign: boolean
 *  - onRefresh: () => void
 *  - padResetKey: number — al cambiar, se borra el dibujo de la firma
 */
export default function SignaturePanel({
  selectedDoc,
  numPages,
  selectedPage,
  onPageChange,
  onSignatureChange,
  onSign,
  canSign,
  onSaveWithoutSign,
  canSaveWithoutSign = false,
  onRefresh,
  padResetKey = 0,
}) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const padRef = useRef(null)
  const [hasStroke, setHasStroke] = useState(false)

  // Init SignaturePad
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const resize = () => {
      const side = Math.max(canvas.offsetWidth, canvas.offsetHeight) || 280
      const ratio = Math.max(window.devicePixelRatio || 1, 1)
      const exportScale = 2.5
      const pixelRatio = ratio * exportScale
      canvas.width = Math.round(side * pixelRatio)
      canvas.height = Math.round(side * pixelRatio)
      canvas.getContext('2d').scale(pixelRatio, pixelRatio)
      padRef.current?.clear()
    }

    const pad = new SignaturePad(canvas, {
      minWidth: 0.6,
      maxWidth: 0.9,
      penColor: '#000000',
      backgroundColor: 'rgba(0,0,0,0)',
    })

    pad.addEventListener('endStroke', () => {
      setHasStroke(true)
      onSignatureChange(pad.toDataURL('image/png'))
    })

    padRef.current = pad
    window.addEventListener('resize', resize)
    resize()

    return () => {
      window.removeEventListener('resize', resize)
      pad.off()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Vaciar el canvas cuando el padre sube `padResetKey` (cambio de remito, o tras firmar y guardar).
  useEffect(() => {
    if (padResetKey === 0) return
    if (!padRef.current) return
    padRef.current.clear()
    setHasStroke(false)
    onSignatureChange(null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [padResetKey])

  function clear() {
    padRef.current?.clear()
    setHasStroke(false)
    onSignatureChange(null)
  }

  const isPending = selectedDoc?.tipo === 'pendiente'

  return (
    <div className="bg-app-surface border-l border-app-border flex flex-col overflow-y-auto scrollbar-thin"
      style={{ width: 'min(360px, 32vw)', minWidth: '240px', flexShrink: 0 }}>

      <div className="flex flex-col gap-3 flex-1" style={{ padding: '16px 16px 20px' }}>
        {/* Signature canvas */}
        <div>
          <p className="text-[15px] font-semibold text-app-text text-center mb-2.5">Firma</p>

          <div
            ref={containerRef}
            className={[
              'relative aspect-square max-w-[280px] mx-auto rounded-card overflow-hidden touch-none',
              hasStroke
                ? 'border border-accent-dark bg-app-surface2'
                : 'border border-dashed border-app-border bg-app-surface2',
            ].join(' ')}
          >
            <canvas
              ref={canvasRef}
              className="block w-full h-full cursor-crosshair"
            />
            {!hasStroke && (
              <span className="absolute inset-0 flex items-center justify-center text-[12px] text-app-muted pointer-events-none">
                Firmá aquí
              </span>
            )}
            {hasStroke && (
              <button
                type="button"
                onClick={clear}
                className="absolute top-1.5 right-1.5 text-[10px] font-semibold px-2 py-0.5 rounded border bg-red-50 border-red-200 text-red-600 hover:bg-red-100 transition-colors"
              >
                Limpiar
              </button>
            )}
          </div>
        </div>

        {/* Page selector */}
        {isPending && numPages > 1 && (
          <div className="flex items-center gap-2">
            <label htmlFor="select-pagina" className="text-[10px] font-semibold uppercase tracking-widest text-app-muted whitespace-nowrap">
              Página del PDF
            </label>
            <select
              id="select-pagina"
              value={selectedPage}
              onChange={(e) => onPageChange(Number(e.target.value))}
              className="bg-app-surface2 border border-app-border rounded-card px-2.5 py-1.5 text-[13px] text-app-text font-[Roboto] focus:outline-none focus:border-accent-dark"
            >
              {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>Página {n}</option>
              ))}
            </select>
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col gap-2 mt-auto pt-2">
          <button
            type="button"
            disabled={!canSign}
            onClick={onSign}
            className="w-full py-2.5 rounded-card text-[13px] font-bold text-white bg-accent border-none cursor-pointer transition-all disabled:opacity-40 disabled:cursor-not-allowed enabled:hover:bg-[#14b8a6] enabled:hover:-translate-y-px enabled:hover:shadow-card"
          >
            Firmar y Guardar
          </button>
          <button
            type="button"
            disabled={!canSaveWithoutSign}
            onClick={onSaveWithoutSign}
            className="w-full py-2.5 rounded-card text-[13px] font-bold text-accent bg-transparent border border-accent cursor-pointer transition-all disabled:opacity-40 disabled:cursor-not-allowed enabled:hover:bg-accent/10"
          >
            Guardar sin firmar
          </button>
          <button
            type="button"
            onClick={onRefresh}
            className="w-full py-2.5 rounded-card text-[13px] font-bold text-app-text bg-app-surface2 border border-app-border cursor-pointer transition-colors hover:border-app-muted"
          >
            ↺ Actualizar
          </button>
        </div>
      </div>
    </div>
  )
}
