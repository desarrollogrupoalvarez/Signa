import { useMemo } from 'react'
import { FileText, FolderTree, LayoutList } from 'lucide-react'
import { displayPendingNombre } from '../utils/displayDocName.js'
import { metricsDocsToTreeDocs } from '../utils/signedFolderTree.js'
import SignedFlatList from './SignedFlatList.jsx'
import SignedFolderTree from './SignedFolderTree.jsx'
import { groupApartadosByArea } from '../utils/apartadoAreas.js'

export default function Sidebar({
  activeTab,
  apartadoTabsOrigins = [],
  showPendientes = true,
  showFirmados = true,
  showMetricas = false,
  metricsDocs = [],
  metricsSearchQ = '',
  /** Pendientes (ya filtrados) para la pestaña activa, o móvil ingresos */
  documentsForTab = [],
  /** Móvil: documentos con modo ingreso (una columna) */
  documentsIngresoMobile = [],
  signedDocs = [],
  signedQ = '',
  onSignedQChange = () => {},
  pendingQ = '',
  onPendingQChange = () => {},
  signedOrigen = 'todos',
  onSignedOrigenChange = () => {},
  signedViewMode = 'tree',
  onSignedViewModeChange = () => {},
  onlyIngresosLayout = false,
  listFullWidth = false,
  selectedDoc,
  onTabChange,
  onSelectDoc,
  onSelectSigned,
  adminMenu,
  listLoading = false,
}) {
  const metricsTreeDocs = useMemo(
    () => metricsDocsToTreeDocs(metricsDocs, apartadoTabsOrigins),
    [metricsDocs, apartadoTabsOrigins],
  )

  const origenGrouped = useMemo(
    () => groupApartadosByArea(apartadoTabsOrigins),
    [apartadoTabsOrigins],
  )
  const multiAreaOrigen = origenGrouped.length > 1

  const list = onlyIngresosLayout
    ? documentsIngresoMobile
    : activeTab === 'firmados'
        ? signedDocs
        : documentsForTab

  return (
    <aside
      className={[
        'box-border flex h-full min-h-0 w-full min-w-0 max-w-full flex-col overflow-hidden bg-app-surface',
        listFullWidth
          ? 'border-b border-app-border'
          : 'border-r border-app-border',
      ].join(' ')}
    >
      {onlyIngresosLayout ? (
        <div className="px-3 py-3 border-b border-app-border border-teal-800/20 bg-teal-900/5 flex-shrink-0 text-center">
          <p className="text-[10px] font-extrabold tracking-[0.2em] text-teal-800">INGRESOS</p>
          <p className="text-[11px] text-app-muted mt-0.5">
            <span className="inline-block min-w-[1.5rem] bg-teal-700 text-white text-[10px] font-bold px-1.5 py-px rounded-full">
              {documentsIngresoMobile.length}
            </span>
            <span className="ml-1.5">pendiente(s)</span>
          </p>
        </div>
      ) : (showPendientes || showFirmados || showMetricas) ? (
        <div className="flex gap-1 px-2 py-3 border-b border-app-border flex-shrink-0 flex-wrap">
          {showPendientes && (
            <TabButton active={activeTab === 'pendientes'} onClick={() => onTabChange('pendientes')}>
              Pendientes{' '}
              <span className="ml-1.5 bg-accent text-white text-[10px] font-bold px-1.5 py-px rounded-full">
                {documentsForTab.length}
              </span>
            </TabButton>
          )}
          {showFirmados && (
            <TabButton active={activeTab === 'firmados'} onClick={() => onTabChange('firmados')}>
              Digitalizados
            </TabButton>
          )}
          {showMetricas && (
            <TabButton active={activeTab === 'metricas'} onClick={() => onTabChange('metricas')}>
              Registros
            </TabButton>
          )}
        </div>
      ) : null}

      {activeTab === 'pendientes' && !onlyIngresosLayout && (
        <div className="px-3 py-2 border-b border-app-border flex-shrink-0">
          <input
            type="search"
            placeholder="Buscar en pendientes"
            value={pendingQ}
            onChange={(e) => onPendingQChange(e.target.value)}
            className="w-full text-[13px] px-3 py-2 rounded-lg border border-app-border bg-app-bg text-app-text placeholder:text-app-muted focus:outline-none focus:border-accent-dark transition-colors"
          />
        </div>
      )}

      {/* Filtros firmados */}
      {activeTab === 'firmados' && showFirmados && (
        <div className="px-3 py-2 border-b border-app-border flex-shrink-0 space-y-2">
          <input
            type="search"
            placeholder="Buscar en digitalizados"
            value={signedQ}
            onChange={(e) => onSignedQChange(e.target.value)}
            className="w-full text-[13px] px-3 py-2 rounded-lg border border-app-border bg-app-bg text-app-text placeholder:text-app-muted focus:outline-none focus:border-accent-dark transition-colors"
          />
          <div className="grid grid-cols-1 gap-1.5">
            <div>
              <span className="text-[9px] font-bold uppercase tracking-wider text-app-muted">Origen</span>
              <select
                value={signedOrigen}
                onChange={(e) => onSignedOrigenChange(e.target.value)}
                className="mt-0.5 w-full text-[12px] px-2 py-1.5 rounded-lg border border-app-border bg-app-bg text-app-text focus:outline-none focus:border-accent-dark"
              >
                <option value="todos">Todos</option>
                {multiAreaOrigen
                  ? origenGrouped.map((g) => (
                      <optgroup key={g.area_id ?? g.area_codigo} label={g.area_nombre}>
                        {(g.apartados || []).map((a) => (
                          <option key={a.codigo} value={a.codigo}>
                            {a.nombre}
                          </option>
                        ))}
                      </optgroup>
                    ))
                  : apartadoTabsOrigins.map((a) => (
                      <option key={a.codigo} value={a.codigo}>
                        {a.nombre}
                      </option>
                    ))}
              </select>
            </div>
          </div>
          <div className="flex items-center gap-1.5 pt-0.5">
            <span className="text-[9px] font-bold uppercase tracking-wider text-app-muted shrink-0">
              Vista
            </span>
            <div className="flex flex-1 rounded-lg border border-app-border p-0.5 bg-app-bg">
              <ViewModeButton
                active={signedViewMode === 'tree'}
                onClick={() => onSignedViewModeChange('tree')}
                title="Carpetas"
              >
                <FolderTree size={14} strokeWidth={2} />
              </ViewModeButton>
              <ViewModeButton
                active={signedViewMode === 'flat'}
                onClick={() => onSignedViewModeChange('flat')}
                title="Lista reciente"
              >
                <LayoutList size={14} strokeWidth={2} />
              </ViewModeButton>
            </div>
          </div>
        </div>
      )}

      {/* List */}
      <div className="w-full min-h-0 flex-1 overflow-y-auto p-2 scrollbar-thin">
        {listLoading && activeTab !== 'admin' && activeTab !== 'metricas' ? (
          <ListLoadingSkeleton tab={activeTab} />
        ) : activeTab === 'admin' ? (
          <div className="py-3">
            <div className="px-2 pb-2">
              <div className="text-[10px] font-extrabold tracking-widest uppercase text-app-muted">Administración</div>
              <div className="text-[12px] text-app-muted mt-1">Ir a sección</div>
            </div>
            <div className="space-y-1 px-1">
              {(adminMenu?.sections || []).map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => adminMenu?.onChange?.(s.id)}
                  className={[
                    'w-full text-left px-3 py-2 rounded-card border transition-colors text-[12px] font-bold',
                    adminMenu?.active === s.id
                      ? 'bg-accent/10 border-accent-dark text-accent-dark'
                      : 'bg-transparent border-transparent text-app-muted hover:bg-app-surface2 hover:border-app-border hover:text-app-text',
                  ].join(' ')}
                >
                  {s.label}
                </button>
              ))}
              {(adminMenu?.sections || []).length === 0 && (
                <div className="px-3 py-3 text-[12px] text-app-muted">Sin secciones disponibles.</div>
              )}
            </div>
          </div>
        ) : activeTab === 'firmados' ? (
          list.length === 0 ? (
            <EmptyState tab="firmados" onlyIngresos={false} />
          ) : (
            signedViewMode === 'flat' ? (
              <SignedFlatList
                docs={signedDocs}
                selectedDoc={selectedDoc}
                onSelectSigned={onSelectSigned}
              />
            ) : (
              <SignedFolderTree
                docs={signedDocs}
                searchQuery={signedQ}
                selectedDoc={selectedDoc}
                onSelectSigned={onSelectSigned}
              />
            )
          )
        ) : activeTab === 'metricas' ? (
          metricsTreeDocs.length === 0 ? (
            <div className="py-10 text-center text-app-muted text-[13px]">
              <FileText size={40} strokeWidth={1.5} className="mx-auto mb-3 opacity-30" />
              <p>Registros</p>
              <p className="text-[12px] mt-1">Sin PDFs generados para mostrar aquí.</p>
            </div>
          ) : (
            <div>
              <div className="px-2 pb-2">
                <div className="text-[10px] font-extrabold tracking-widest uppercase text-app-muted">Archivos leídos</div>
                <div className="text-[12px] text-app-muted mt-1">{metricsTreeDocs.length} archivo(s)</div>
              </div>
              <SignedFolderTree
                docs={metricsTreeDocs}
                searchQuery={metricsSearchQ}
                selectedDoc={selectedDoc}
                onSelectSigned={onSelectSigned}
              />
            </div>
          )
        ) : list.length === 0 ? (
          <EmptyState tab={activeTab} onlyIngresos={onlyIngresosLayout} />
        ) : (
          (onlyIngresosLayout ? documentsIngresoMobile : documentsForTab).map((doc) => (
            <PendingItem
              key={doc.id}
              doc={doc}
              active={selectedDoc?.tipo === 'pendiente' && selectedDoc?.id === doc.id}
              onClick={() => onSelectDoc(doc)}
            />
          ))
        )}
      </div>
    </aside>
  )
}

function ViewModeButton({ active, onClick, title, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={[
        'flex-1 flex items-center justify-center py-1.5 rounded-md transition-colors',
        active
          ? 'bg-accent/15 text-accent-dark'
          : 'text-app-muted hover:text-app-text hover:bg-app-surface2',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'flex-1 min-w-[5.5rem] text-[10px] font-semibold tracking-widest uppercase px-1.5 py-2 rounded-lg border transition-all',
        active
          ? 'bg-accent/10 border-accent-dark text-accent-dark'
          : 'bg-transparent border-transparent text-app-muted hover:bg-app-surface2 hover:text-app-text',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

function PendingItem({ doc, active, onClick }) {
  const date = new Date(doc.recibido_en).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
  return (
    <div
      onClick={onClick}
      className={[
        'px-3 py-3 rounded-card border cursor-pointer transition-all mb-1 select-none',
        active
          ? 'bg-accent/10 border-accent-dark'
          : 'border-transparent hover:bg-app-surface2 hover:border-app-border',
      ].join(' ')}
    >
      <div className={['text-[12px] font-semibold mb-1 truncate', active ? 'text-accent-dark' : 'text-app-text'].join(' ')}>
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent mr-1.5 mb-px animate-pulse-dot" />
        {displayPendingNombre(doc)}
      </div>
      <div className="text-[10px] text-app-muted font-mono">{date}</div>
    </div>
  )
}

function ListLoadingSkeleton({ tab }) {
  const label = tab === 'firmados' ? 'Cargando digitalizados…' : 'Cargando pendientes…'
  return (
    <div className="py-2">
      <p className="px-2 pb-3 text-[12px] text-app-muted">{label}</p>
      <div className="space-y-2 animate-pulse">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="px-3 py-3 rounded-card border border-app-border/40 bg-app-surface2">
            <div className="h-3 bg-app-border rounded w-[78%] mb-2" />
            <div className="h-2 bg-app-border/60 rounded w-[38%]" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyState({ tab, onlyIngresos }) {
  const msg =
    onlyIngresos
      ? 'Sin remitos pendientes'
      : tab === 'firmados'
        ? 'Sin remitos firmados'
        : 'Sin remitos pendientes en este apartado'
  return (
    <div className="py-10 text-center text-app-muted text-[13px]">
      <FileText size={40} strokeWidth={1.5} className="mx-auto mb-3 opacity-30" />
      <p>{msg}</p>
    </div>
  )
}
