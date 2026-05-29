import { useEffect, useMemo, useRef, useState } from 'react'
import { Copy, Download, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { API_BASE, apiFetch, getSignedFileUrl, getToken } from '../api/client'
import { copySignedFilePath, toFileUrl } from '../utils/clientPath.js'
import {
  parseFirmaZoneFromKeywords,
  transferenciaFirmaZone,
  zoneOverlayRect,
} from '../constants/firmaPlacement'

const WORKER_SRC = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs'

const VIDEO_EXT = new Set(['.mp4', '.webm', '.ogv', '.mov', '.mkv', '.m4v'])
const AUDIO_EXT = new Set(['.mp3', '.ogg', '.oga', '.wav', '.m4a', '.aac', '.flac', '.opus'])

function fileExtFromPath(nombre) {
  if (!nombre) return ''
  const base = (nombre.split(/[/\\]/).pop() || '').toLowerCase()
  const m = base.match(/(\.[a-z0-9]+)$/)
  return m ? m[1] : ''
}

/** Alineado con el backend (listado de firmados) para documentos viejos sin `categoria`. */
function inferCategoriaFirmado(nombre) {
  const e = fileExtFromPath(nombre)
  if (e === '.pdf') return 'pdf'
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.svg'].includes(e)) return 'imagen'
  if (['.heic', '.heif'].includes(e)) return 'otro'
  if (
    ['.txt', '.csv', '.log', '.md', '.json', '.xml', '.html', '.htm', '.yml', '.yaml', '.ini', '.conf', '.rc'].includes(e)
  ) {
    return 'texto'
  }
  if (['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.rtf'].includes(e)) {
    return 'oficina'
  }
  if (VIDEO_EXT.has(e) || AUDIO_EXT.has(e)) return 'media'
  return 'otro'
}

function mediaIsVideo(nombre) {
  return VIDEO_EXT.has(fileExtFromPath(nombre))
}

/**
 * Renders PDF pages imperatively using pdfjs-dist.
 * Firmados: también imagen, texto, audio/vídeo u oficina/otros según categoría.
 */
export default function PdfViewer({
  selectedDoc,
  croppedFirma,
  selectedPage,
  onPlacementChange,
  onPagesLoaded,
  canRevealLocation = false,
}) {
  const visorRef = useRef(null)
  const contentRef = useRef(null)
  const pagesRef = useRef([]) // [{ pageNum, wrapEl }]
  const savedPosRef = useRef(null)
  const firmaZoneRef = useRef(null)
  const [signedPath, setSignedPath] = useState(null)
  const [signedText, setSignedText] = useState('')
  const [textLoading, setTextLoading] = useState(false)

  const isSigned = selectedDoc?.tipo === 'firmado'
  const signedName = selectedDoc?.nombre || ''

  const firmadoCategoria = useMemo(() => {
    if (selectedDoc?.tipo !== 'firmado') return null
    return selectedDoc.categoria || inferCategoriaFirmado(selectedDoc.nombre)
  }, [selectedDoc?.tipo, selectedDoc?.categoria, selectedDoc?.nombre])

  const signedFileUrl = useMemo(
    () => (signedName ? getSignedFileUrl(signedName) : ''),
    [signedName],
  )

  const isPdfVista =
    !!selectedDoc && (selectedDoc.tipo === 'pendiente' || (isSigned && firmadoCategoria === 'pdf'))
  const isTextoPlano = isSigned && firmadoCategoria === 'texto' && !['.html', '.htm'].includes(fileExtFromPath(signedName))

  const fileUrl = useMemo(() => {
    const p = signedPath?.unc_file || signedPath?.client_file
    return toFileUrl(p)
  }, [signedPath?.unc_file, signedPath?.client_file])

  async function loadSignedPath(nombre) {
    if (!nombre) return
    try {
      const res = await apiFetch(`/api/firmados/path?n=${encodeURIComponent(nombre)}`)
      const data = await res.json()
      setSignedPath(data)
    } catch {
      setSignedPath(null)
    }
  }

  // ── Load PDF (pendiente o firmado PDF) ─────────────────────────────────────
  useEffect(() => {
    if (!selectedDoc) {
      clearPages()
      removeOverlay()
      onPagesLoaded(0)
      setSignedPath(null)
      setSignedText('')
      return
    }

    if (selectedDoc.tipo === 'firmado' && firmadoCategoria && firmadoCategoria !== 'pdf') {
      clearPages()
      removeOverlay()
      onPagesLoaded(0)
      return
    }

    let cancelled = false

    async function load() {
      removeOverlay()
      clearPages()
      onPagesLoaded(0)
      setSignedPath(null)

      try {
        const { getDocument, GlobalWorkerOptions } = await import('pdfjs-dist')
        GlobalWorkerOptions.workerSrc = WORKER_SRC

        if (selectedDoc.tipo === 'firmado') {
          await loadSignedPath(selectedDoc.nombre)
        }

        const token = getToken()
        const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}
        const pdfUrl =
          selectedDoc.tipo === 'firmado'
            ? `${API_BASE}/api/firmados/archivo?n=${encodeURIComponent(selectedDoc.nombre)}`
            : `${API_BASE}/api/documentos/${selectedDoc.id}/pdf`

        const res = await fetch(pdfUrl, { headers: authHeaders })
        if (!res.ok) throw new Error(`PDF ${res.status}`)
        const buf = await res.arrayBuffer()
        const pdfDoc = await getDocument({ data: buf }).promise

        firmaZoneRef.current = null
        if (selectedDoc.tipo === 'pendiente' && selectedDoc.modo_flujo === 'transferencia') {
          try {
            const meta = await pdfDoc.getMetadata()
            const kw = meta?.info?.Keywords ?? meta?.info?.keywords ?? ''
            firmaZoneRef.current =
              parseFirmaZoneFromKeywords(kw, pdfDoc.numPages) || transferenciaFirmaZone()
            if (firmaZoneRef.current && !firmaZoneRef.current.page) {
              firmaZoneRef.current.page = pdfDoc.numPages
            }
          } catch {
            firmaZoneRef.current = { ...transferenciaFirmaZone(), page: pdfDoc.numPages }
          }
        }

        if (cancelled) return

        await new Promise(requestAnimationFrame)
        const content = contentRef.current
        if (!content) {
          console.warn('[PdfViewer] contentRef vacío')
          return
        }

        for (let i = 1; i <= pdfDoc.numPages; i++) {
          if (cancelled) break
          const page = await pdfDoc.getPage(i)
          const vp = page.getViewport({ scale: 1.5 })

          const canvas = document.createElement('canvas')
          canvas.width = vp.width
          canvas.height = vp.height
          canvas.style.cssText =
            'display:block;border-radius:8px;box-shadow:0 4px 24px rgba(15,23,42,.08);border:1px solid #c9d4e5;max-width:100%;'

          await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise

          const wrap = document.createElement('div')
          wrap.style.cssText =
            'position:relative;width:fit-content;max-width:100%;margin:0 auto 12px;display:block;'
          wrap.dataset.pageNum = String(i)
          wrap.appendChild(canvas)
          content.appendChild(wrap)
          pagesRef.current.push({ pageNum: i, wrapEl: wrap })
        }

        const visor = visorRef.current
        if (visor) visor.scrollTop = 0
        if (!cancelled) onPagesLoaded(pdfDoc.numPages)
      } catch (e) {
        if (!cancelled) console.error('[PdfViewer] load error', e)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDoc?.id, selectedDoc?.tipo, selectedDoc?.nombre, selectedDoc?.categoria, firmadoCategoria])

  // Cargar metadata para firmados no PDF (ruta, botones)
  useEffect(() => {
    if (!isSigned || !signedName) {
      return
    }
    if (firmadoCategoria && firmadoCategoria !== 'pdf') {
      loadSignedPath(signedName)
    }
  }, [isSigned, signedName, firmadoCategoria])

  // Texto plano: fetch para mostrar en <pre>
  useEffect(() => {
    if (!isTextoPlano || !signedName) {
      setSignedText('')
      return
    }
    let cancel = false
    setTextLoading(true)
    ;(async () => {
      try {
        const res = await apiFetch(`/api/firmados/archivo?n=${encodeURIComponent(signedName)}`)
        const t = await res.text()
        if (!cancel) setSignedText(t.slice(0, 500_000))
      } catch {
        if (!cancel) setSignedText('No se pudo leer el archivo.')
      } finally {
        if (!cancel) setTextLoading(false)
      }
    })()
    return () => {
      cancel = true
    }
  }, [isTextoPlano, signedName])

  // ── Update overlay (solo pendiente con firma) ────────────────────────────────
  useEffect(() => {
    removeOverlay()
    onPlacementChange(null)

    if (!croppedFirma || !pagesRef.current.length || selectedDoc?.tipo === 'firmado') return

    const last = pagesRef.current[pagesRef.current.length - 1]
    const zonaPage =
      selectedDoc?.modo_flujo === 'transferencia'
        ? firmaZoneRef.current?.page ?? last?.pageNum
        : selectedPage
    const pr =
      pagesRef.current.find((p) => p.pageNum === zonaPage) ?? last
    if (!pr) return

    buildOverlay(pr.wrapEl, pr.pageNum, croppedFirma)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [croppedFirma, selectedPage, selectedDoc?.tipo, selectedDoc?.modo_flujo])

  function buildOverlay(wrapEl, pageNum, { dataURL, aspect }) {
    const W = wrapEl.clientWidth
    const H = wrapEl.clientHeight
    if (W < 1 || H < 1) return

    const isTransferencia = selectedDoc?.modo_flujo === 'transferencia'
    const zone = isTransferencia ? firmaZoneRef.current || transferenciaFirmaZone() : null
    const keepPos = savedPosRef.current?.pageNum === pageNum
    let ox, oy, ow, oh

    if (keepPos) {
      const p = savedPosRef.current
      ox = p.nx * W
      oy = p.ny * H
      ow = p.nw * W
      oh = p.nh * H
    } else if (isTransferencia && zone) {
      const rect = zoneOverlayRect(zone, W, H)
      ox = rect.ox
      oy = rect.oy
      ow = rect.ow
      oh = rect.oh
    } else {
      ow = Math.min(W * 0.2, 160)
      oh = ow / aspect
      if (oh > H * 0.42) {
        oh = H * 0.42
        ow = oh * aspect
      }
      ox = W - ow - 14
      oy = (H - oh) / 2
      ow = Math.max(36, ow)
      oh = ow / aspect
    }

    ox = Math.max(0, Math.min(ox, W - ow))
    oy = Math.max(0, Math.min(oy, H - oh))

    const overlay = document.createElement('div')
    overlay.className = 'rf-sig-overlay'
    overlay.style.cssText += `left:${ox}px;top:${oy}px;width:${ow}px;height:${oh}px;`

    const img = document.createElement('img')
    img.alt = ''
    img.src = dataURL
    img.style.cssText =
      'display:block;width:100%;height:100%;object-fit:contain;object-position:center;pointer-events:none;padding:6px;box-sizing:border-box;'
    overlay.appendChild(img)

    function savePos() {
      const W2 = wrapEl.clientWidth
      const H2 = wrapEl.clientHeight
      savedPosRef.current = {
        pageNum,
        nx: overlay.offsetLeft / W2,
        ny: overlay.offsetTop / H2,
        nw: overlay.offsetWidth / W2,
        nh: overlay.offsetHeight / H2,
      }
      onPlacementChange({
        page: pageNum,
        x: savedPosRef.current.nx,
        y: savedPosRef.current.ny,
        w: savedPosRef.current.nw,
        h: savedPosRef.current.nh,
      })
    }

    overlay.addEventListener('pointerdown', (e) => {
      if (e.button != null && e.button !== 0) return
      e.preventDefault()
      overlay.style.cursor = 'grabbing'
      const sx = e.clientX
      const sy = e.clientY
      const sl = overlay.offsetLeft
      const st = overlay.offsetTop

      const move = (e2) => {
        const W2 = wrapEl.clientWidth
        const H2 = wrapEl.clientHeight
        overlay.style.left = `${Math.max(0, Math.min(sl + e2.clientX - sx, W2 - overlay.offsetWidth))}px`
        overlay.style.top = `${Math.max(0, Math.min(st + e2.clientY - sy, H2 - overlay.offsetHeight))}px`
      }
      const up = () => {
        overlay.style.cursor = 'grab'
        document.removeEventListener('pointermove', move)
        document.removeEventListener('pointerup', up)
        savePos()
      }
      document.addEventListener('pointermove', move)
      document.addEventListener('pointerup', up)
    })

    wrapEl.appendChild(overlay)
    savePos()
  }

  function removeOverlay() {
    const root = contentRef.current
    if (!root) return
    root.querySelectorAll('.rf-sig-overlay').forEach((el) => el.remove())
  }

  function clearPages() {
    const root = contentRef.current
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    pagesRef.current = []
    savedPosRef.current = null
    firmaZoneRef.current = null
  }

  // ── Vista previa firmado no PDF ───────────────────────────────────────────
  const firmadoOtroPanel = (titulo, detalle) => (
    <div className="w-full max-w-[720px] rounded-card border border-app-border bg-app-surface2/40 p-6 text-center space-y-3">
      <p className="text-[15px] font-semibold text-app-text">{titulo}</p>
      <p className="text-[13px] text-app-muted leading-relaxed">{detalle}</p>
      {signedFileUrl && (
        <a
          href={signedFileUrl}
          target="_blank"
          rel="noreferrer"
          download
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-card text-[13px] font-bold text-white bg-teal-600 hover:bg-teal-500"
        >
          <Download size={16} />
          Descargar
        </a>
      )}
    </div>
  )

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      ref={visorRef}
      className="flex-1 min-w-0 overflow-y-auto p-5 flex flex-col items-center scrollbar-thin"
    >
      {isSigned && signedName && canRevealLocation && (
        <div className="w-fit max-w-full mx-auto mb-2 flex items-center justify-end gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => copySignedFilePath(signedName, { apiFetch, toast })}
            className="px-3 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50 transition-colors inline-flex items-center gap-2"
            title="Copiar ruta de archivo"
          >
            <Copy size={14} />
            Copiar ruta de archivo
          </button>
        </div>
      )}

      {isSigned && firmadoCategoria && firmadoCategoria !== 'pdf' && (
        <div className="w-full max-w-[980px] flex flex-col items-center gap-4 mb-4">
          {firmadoCategoria === 'imagen' && signedFileUrl && (
            <img
              src={signedFileUrl}
              alt=""
              className="max-w-full h-auto max-h-[75vh] rounded-lg border border-app-border shadow-md object-contain bg-white"
            />
          )}

          {firmadoCategoria === 'texto' && ['.html', '.htm'].includes(fileExtFromPath(signedName)) && signedFileUrl && (
            <iframe
              title="Vista HTML"
              src={signedFileUrl}
              sandbox=""
              className="w-full min-h-[50vh] rounded-lg border border-app-border bg-white"
            />
          )}

          {firmadoCategoria === 'texto' && isTextoPlano && (
            <div className="w-full max-w-[980px] rounded-lg border border-app-border bg-app-surface2/30 p-3 overflow-hidden">
              {textLoading && <p className="text-sm text-app-muted p-2">Cargando texto…</p>}
              {!textLoading && (
                <pre className="text-[12px] font-mono text-app-text whitespace-pre-wrap break-words max-h-[70vh] overflow-auto p-2">
                  {signedText}
                </pre>
              )}
            </div>
          )}

          {firmadoCategoria === 'media' && signedFileUrl && mediaIsVideo(signedName) && (
            <video src={signedFileUrl} controls className="w-full max-w-[900px] max-h-[75vh] rounded-lg bg-black" />
          )}
          {firmadoCategoria === 'media' && signedFileUrl && !mediaIsVideo(signedName) && (
            <audio src={signedFileUrl} controls className="w-full max-w-[560px]" />
          )}

          {firmadoCategoria === 'oficina' &&
            firmadoOtroPanel(
              'Vista previa no disponible',
              'Abrí el archivo con Word, Excel o el programa correspondiente, o descargalo desde el botón de abajo.',
            )}

          {firmadoCategoria === 'otro' &&
            firmadoOtroPanel(
              'Vista previa no disponible para este tipo',
              'HEIC, comprimidos u otros: usá "Descargar" o "Copiar ruta de archivo" y abrilo desde el Explorador.',
            )}
        </div>
      )}

      {isPdfVista && (
        <div
          key={isSigned ? signedName : (selectedDoc?.id ?? 'pendiente')}
          ref={contentRef}
          className="w-full"
        />
      )}

      {!selectedDoc && (
        <div className="flex-1 flex flex-col items-center justify-center text-app-muted gap-4">
          <FileText size={80} strokeWidth={0.75} className="opacity-30" />
          <p className="text-sm">Seleccioná un remito o archivo archivado para visualizarlo</p>
        </div>
      )}
    </div>
  )
}
