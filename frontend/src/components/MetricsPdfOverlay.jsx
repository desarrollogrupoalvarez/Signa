import { Download, X } from 'lucide-react'
import { downloadSignedFile } from '../api/client'
import { displaySignedNombre } from '../utils/displayDocName.js'
import PdfViewer from './PdfViewer.jsx'

export default function MetricsPdfOverlay({
  selectedDoc,
  onClose,
  selectedPage,
  onPagesLoaded,
}) {
  if (!selectedDoc || selectedDoc.tipo !== 'firmado') return null

  const nombre = selectedDoc.nombre || ''

  return (
    <div
      className="absolute inset-0 z-30 flex items-stretch justify-center p-3 sm:p-5 bg-black/35"
      role="dialog"
      aria-modal="true"
      aria-label="Vista previa del PDF"
    >
      <div className="relative flex flex-col w-full max-w-[920px] min-h-0 bg-app-bg border border-app-border rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center gap-2 pl-4 pr-2 py-2 border-b border-app-border bg-app-surface shrink-0">
          <span className="flex-1 min-w-0 text-[12px] font-semibold truncate text-app-text">
            {displaySignedNombre(selectedDoc)}
          </span>
          {nombre && (
            <button
              type="button"
              onClick={() => downloadSignedFile(nombre)}
              className="shrink-0 p-2 rounded-lg text-app-muted hover:text-app-text hover:bg-app-surface2 transition-colors"
              title="Descargar PDF"
            >
              <Download size={18} strokeWidth={1.75} />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 p-2 rounded-lg text-app-muted hover:text-app-text hover:bg-app-surface2 transition-colors"
            title="Cerrar vista previa"
          >
            <X size={20} strokeWidth={2} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <PdfViewer
            selectedDoc={selectedDoc}
            croppedFirma={null}
            selectedPage={selectedPage}
            onPlacementChange={() => {}}
            onPagesLoaded={onPagesLoaded}
            hideSignedToolbar
          />
        </div>
      </div>
    </div>
  )
}
