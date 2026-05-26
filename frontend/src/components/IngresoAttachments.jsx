import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ImagePlus, RotateCcw, RotateCw, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { API_BASE, apiFetch, getToken } from '../api/client'
import { fileToJpegForUpload } from '../utils/imageRotate'

const WORKER_SRC = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs'

/** Misma franja que la barra de girar/cuas en slides de imagen, para alinear previsualizaciones */
const SLIDE_CHROME_H = 56

/**
 * Móvil IN: carrusel horizontal (scroll-snap) = páginas del PDF + fotos a anexar, con rotar/quitar en cada foto.
 * Pie: solo Agregar imagen y Anexar.
 */
function makeItem(file) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    file,
    rotation: 0,
    previewUrl: URL.createObjectURL(file),
  }
}

/**
 * Ajusta escala a la caja: al rotar 90°/270° el cuerpo AABB pasa a ancho×alto = natH×natW,
 * así se usa el mismo “min(caja/necesario)” que para 0° y el tamaño visual coincide.
 */
function fitScaleForBox(rotDeg, natW, natH, boxW, boxH) {
  if (!boxW || !boxH || !natW || !natH) return 0
  const r = ((rotDeg % 360) + 360) % 360
  const needsW = r === 90 || r === 270 ? natH : natW
  const needsH = r === 90 || r === 270 ? natW : natH
  return Math.min(boxW / needsW, boxH / needsH, 1)
}

function IngresoFittedImage({ src, rotation }) {
  const boxRef = useRef(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const [nat, setNat] = useState({ w: 0, h: 0 })

  useLayoutEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setBox({ w: el.clientWidth, h: el.clientHeight })
    })
    ro.observe(el)
    setBox({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const r = ((rotation % 360) + 360) % 360
  const s = fitScaleForBox(rotation, nat.w, nat.h, box.w, box.h)
  const canFit = s > 0 && nat.w > 0 && nat.h > 0

  return (
    <div
      ref={boxRef}
      className="relative box-border flex h-full w-full min-h-0 min-w-0 items-center justify-center p-1"
    >
      <img
        src={src}
        alt=""
        onLoad={(e) => {
          const t = e.currentTarget
          setNat({ w: t.naturalWidth, h: t.naturalHeight })
        }}
        className="block rounded-lg shadow-sm"
        style={
          canFit
            ? {
                width: Math.max(1, Math.round(nat.w * s)),
                height: Math.max(1, Math.round(nat.h * s)),
                objectFit: 'contain',
                transform: `rotate(${r}deg)`,
              }
            : {
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
                transform: `rotate(${r}deg)`,
              }
        }
      />
    </div>
  )
}

function IngresoPdfPageSlide({ pdf, pageNum, maxW, maxH }) {
  const canvasRef = useRef(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!pdf || maxW < 40 || maxH < 40) return
    let cancel = false
    setFailed(false)
    ;(async () => {
      try {
        const page = await pdf.getPage(pageNum)
        const base = page.getViewport({ scale: 1 })
        const scale = Math.min(maxW / base.width, maxH / base.height)
        const vp = page.getViewport({ scale: Math.max(0.1, scale) })
        const canvas = canvasRef.current
        if (!canvas || cancel) return
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
        canvas.width = Math.floor(vp.width * dpr)
        canvas.height = Math.floor(vp.height * dpr)
        canvas.style.width = `${vp.width}px`
        canvas.style.height = `${vp.height}px`
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        await page.render({ canvasContext: ctx, viewport: vp }).promise
      } catch (e) {
        console.error(e)
        if (!cancel) setFailed(true)
      }
    })()
    return () => {
      cancel = true
    }
  }, [pdf, pageNum, maxW, maxH])

  return (
    <div
      className="flex h-full w-full min-h-0 min-w-0 max-w-full flex-[0_0_100%] shrink-0 flex-col box-border snap-start snap-always bg-slate-200/30"
      style={{ width: '100%' }}
      role="group"
      aria-label={`Página ${pageNum} del remito`}
    >
      <div className="box-border flex min-h-0 flex-1 items-center justify-center overflow-hidden p-2">
        {failed ? (
          <p className="text-sm text-red-600 px-4 text-center">No se pudo mostrar esta página</p>
        ) : (
          <canvas
            ref={canvasRef}
            className="max-h-full max-w-full rounded-lg border border-slate-300/80 bg-white object-contain shadow-md"
          />
        )}
      </div>
      <div className="shrink-0" style={{ height: SLIDE_CHROME_H }} aria-hidden />
    </div>
  )
}

export default function IngresoAttachments({ docId, onFinalizado }) {
  const [sending, setSending] = useState(false)
  const [items, setItems] = useState([])
  const [pdf, setPdf] = useState(null)
  const [pageCount, setPageCount] = useState(0)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState(null)
  const [slideWidth, setSlideWidth] = useState(320)
  const [railH, setRailH] = useState(400)

  const fileRef = useRef(null)
  const itemsRef = useRef(items)
  const railRef = useRef(null)
  itemsRef.current = items

  function revokeItem(it) {
    if (it?.previewUrl) URL.revokeObjectURL(it.previewUrl)
  }

  useEffect(() => {
    return () => {
      itemsRef.current.forEach(revokeItem)
    }
  }, [])

  useEffect(() => {
    setItems((cur) => {
      cur.forEach(revokeItem)
      return []
    })
  }, [docId])

  useEffect(() => {
    if (!railRef.current) return
    const el = railRef.current
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect
      if (!r) return
      if (r.width > 0) setSlideWidth(r.width)
      if (r.height > 0) setRailH(r.height)
    })
    ro.observe(el)
    setSlideWidth(el.clientWidth || 320)
    setRailH(el.clientHeight || 400)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!docId) {
      setPdf(null)
      setPageCount(0)
      setPdfError(null)
      return
    }
    let cancelled = false
    setPdfLoading(true)
    setPdfError(null)
    setPdf(null)
    setPageCount(0)

    ;(async () => {
      try {
        const { getDocument, GlobalWorkerOptions } = await import('pdfjs-dist')
        GlobalWorkerOptions.workerSrc = WORKER_SRC
        const token = getToken()
        const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}
        const res = await fetch(`${API_BASE}/api/documentos/${docId}/pdf`, { headers: authHeaders })
        if (!res.ok) throw new Error(`PDF ${res.status}`)
        const buf = await res.arrayBuffer()
        if (cancelled) return
        const doc = await getDocument({ data: buf }).promise
        if (cancelled) return
        setPdf(doc)
        setPageCount(doc.numPages)
      } catch (e) {
        console.error(e)
        if (!cancelled) setPdfError(e.message || 'Error al cargar el PDF')
      } finally {
        if (!cancelled) setPdfLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [docId])

  function addFiles(e) {
    const f = e.target?.files
    if (f?.length) {
      const add = Array.from(f).map((file) => makeItem(file))
      setItems((s) => {
        const next = [...s, ...add]
        if (next.length > 20) {
          next.slice(20).forEach(revokeItem)
          toast.message('Máximo 20 imágenes; se aceptan las primeras 20')
          return next.slice(0, 20)
        }
        return next
      })
    }
    if (e.target) e.target.value = ''
  }

  function removeItem(id) {
    setItems((s) => {
      const it = s.find((x) => x.id === id)
      if (it) revokeItem(it)
      return s.filter((x) => x.id !== id)
    })
  }

  function rotateItem(id, delta) {
    setItems((s) =>
      s.map((x) => {
        if (x.id !== id) return x
        return { ...x, rotation: (x.rotation + delta + 360) % 360 }
      }),
    )
  }

  async function anexarYArchivar() {
    if (!docId) return
    if (items.length === 0) {
      toast.error('Agregá al menos una imagen')
      return
    }
    const dispositivo = `${navigator.userAgent.slice(0, 80)} | ${new Date().toISOString()}`
    const fd = new FormData()

    for (const it of items.slice(0, 20)) {
      try {
        const out = await fileToJpegForUpload(it.file, { rotation: it.rotation })
        fd.append('imagenes', out, out.name)
      } catch (err) {
        console.error(err)
        toast.error('No se pudo procesar una imagen. Probá otra o menos pesada.')
        return
      }
    }
    fd.append('dispositivo', dispositivo)

    setSending(true)
    try {
      const r = await apiFetch(`/api/documentos/${docId}/adjuntar_escaneos`, { method: 'POST', body: fd })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.error || r.statusText)
      }
      const d = await r.json()
      const n = d.paginas_anadidas ?? 0
      toast.success(
        `Añadidas ${n} página(s) al remito. Archivado en destino. Podés verlo en Digitalizados (escritorio).`,
      )
      setItems((cur) => {
        cur.forEach(revokeItem)
        return []
      })
      onFinalizado?.()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSending(false)
    }
  }

  const safeBottom = { paddingBottom: 'max(10px, env(safe-area-inset-bottom, 0px))' }

  const pad = 20
  const pdfMaxW = Math.max(40, slideWidth - pad)
  /** Mismo alto útil que la zona de la foto (rail menos franja de botones) */
  const pdfMaxH = Math.max(40, railH - pad - SLIDE_CHROME_H)

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden bg-app-surface2/20">
      <div className="relative flex min-h-0 w-full min-w-0 flex-1 flex-col">
        <div
          ref={railRef}
          className="ingreso-snap flex min-h-0 w-full min-w-0 flex-1 flex-row flex-nowrap touch-pan-x snap-x snap-mandatory overflow-y-hidden overflow-x-scroll overscroll-x-contain [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
        >
        {pdfLoading && (
          <div
            className="box-border flex h-full min-h-0 w-full min-w-0 max-w-full flex-[0_0_100%] shrink-0 flex-col items-center justify-center p-4 snap-start snap-always"
            style={{ width: '100%' }}
          >
            <p className="text-sm text-app-muted">Cargando remito…</p>
          </div>
        )}

        {pdfError && !pdfLoading && (
          <div
            className="box-border flex h-full min-h-0 w-full min-w-0 max-w-full flex-[0_0_100%] shrink-0 flex-col items-center justify-center p-4 snap-start snap-always"
            style={{ width: '100%' }}
          >
            <p className="text-sm text-center text-red-600">{pdfError}</p>
          </div>
        )}

        {!pdfLoading &&
          !pdfError &&
          pdf &&
          pageCount > 0 &&
          Array.from({ length: pageCount }, (_, j) => (
            <IngresoPdfPageSlide
              key={`doc-page-${j + 1}`}
              pdf={pdf}
              pageNum={j + 1}
              maxW={pdfMaxW}
              maxH={pdfMaxH}
            />
          ))}

        {items.map((it, idx) => (
          <div
            key={it.id}
            className="box-border flex h-full w-full min-h-0 min-w-0 max-w-full flex-[0_0_100%] shrink-0 snap-start snap-always flex-col bg-app-bg"
            style={{ width: '100%' }}
            role="group"
            aria-label={`Foto a anexar ${idx + 1}`}
          >
            <div className="min-h-0 min-w-0 flex-1 box-border flex items-stretch justify-stretch overflow-hidden p-1">
              <IngresoFittedImage src={it.previewUrl} rotation={it.rotation} />
            </div>
            <div
              className="box-border flex shrink-0 items-center justify-center gap-1.5 border-t border-app-border/50 bg-app-surface/95 px-2 py-1.5"
              style={{ minHeight: SLIDE_CHROME_H }}
            >
              <button
                type="button"
                onClick={() => rotateItem(it.id, -90)}
                className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-app-border bg-app-surface2 py-2.5 text-[11px] font-bold text-app-text"
                title="Girar 90° antihorario"
              >
                <RotateCcw size={15} />
                90°
              </button>
              <button
                type="button"
                onClick={() => rotateItem(it.id, 90)}
                className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-app-border bg-app-surface2 py-2.5 text-[11px] font-bold text-app-text"
                title="Girar 90° horario"
              >
                <RotateCw size={15} />
                90°
              </button>
              <button
                type="button"
                onClick={() => removeItem(it.id)}
                className="inline-flex items-center justify-center gap-1 rounded-lg border border-red-200 bg-red-500/10 px-3 py-2.5 text-[11px] font-bold text-red-600"
              >
                <Trash2 size={15} />
                Quitar
              </button>
            </div>
          </div>
        ))}
        </div>
      </div>

      <div
        className="relative z-10 flex flex-shrink-0 flex-col gap-1.5 border-t-2 border-teal-800/20 bg-app-surface px-3 pt-2 shadow-[0_-4px_20px_rgba(0,0,0,0.12)]"
        style={safeBottom}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/webp"
          multiple
          capture="environment"
          className="sr-only"
          onChange={addFiles}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-teal-600/50 bg-teal-200/30 py-2.5 text-[13px] font-bold text-teal-900 active:scale-[0.99]"
        >
          <ImagePlus size={18} />
          Agregar imagen
        </button>

        <button
          type="button"
          disabled={sending || items.length === 0}
          onClick={anexarYArchivar}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 py-3 text-[13px] font-bold text-white shadow-md hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Upload size={18} />
          {sending ? 'Procesando…' : 'Anexar al PDF y archivar'}
        </button>
      </div>
    </div>
  )
}
