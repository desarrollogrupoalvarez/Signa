import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { toast } from 'sonner'
import { apiFetch } from '../api/client'

const DEFAULT_SORT = { key: 'fecha', dir: 'desc' }

function compareSortValues(a, b, key, dir) {
  const av = a[key]
  const bv = b[key]
  const mul = dir === 'asc' ? 1 : -1

  if (key === 'cantidad') {
    const an = typeof av === 'number' ? av : null
    const bn = typeof bv === 'number' ? bv : null
    if (an == null && bn == null) return 0
    if (an == null) return 1
    if (bn == null) return -1
    return (an - bn) * mul
  }

  return String(av ?? '').localeCompare(String(bv ?? ''), 'es', { numeric: true, sensitivity: 'base' }) * mul
}

function SortableTh({ label, colKey, sortKey, sortDir, onSort, className = '', align = 'left' }) {
  const active = sortKey === colKey
  return (
    <th className={`px-3 py-2 ${className}`}>
      <button
        type="button"
        onClick={() => onSort(colKey)}
        title={`Ordenar por ${label}`}
        className={[
          'inline-flex items-center gap-1 font-inherit transition-colors w-full',
          align === 'right' ? 'justify-end' : 'justify-start',
          active ? 'text-app-text' : 'text-app-muted hover:text-app-text',
        ].join(' ')}
      >
        <span>{label}</span>
        <span className="inline-flex flex-col -space-y-1.5 shrink-0">
          <ChevronUp
            size={11}
            strokeWidth={2.5}
            className={active && sortDir === 'asc' ? 'text-accent-dark' : 'text-app-muted/35'}
          />
          <ChevronDown
            size={11}
            strokeWidth={2.5}
            className={active && sortDir === 'desc' ? 'text-accent-dark' : 'text-app-muted/35'}
          />
        </span>
      </button>
    </th>
  )
}

/** Solo PDFs en disco (sidebar «Archivos leídos»); excluye filas solo-Tango sin archivo generado. */
function documentosConPdfGenerado(documentos) {
  const seen = new Set()
  const out = []
  for (const d of documentos || []) {
    const archivo = (d.archivo || '').trim()
    const nombreFirmado = (d.nombre_firmado || '').trim()
    if (d.origen_datos !== 'pdf' && !archivo) continue
    if (!archivo && !nombreFirmado) continue
    const key = nombreFirmado || `${d.apartado}::${archivo}::${d.ruta || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(d)
  }
  return out
}

const MetricsPage = forwardRef(function MetricsPage(
  { apartados = [], onDocsChange = () => {}, onLoadingChange, onSearchQueryChange = () => {} },
  ref,
) {
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('ingresos') // 'ingresos' | 'transferencias'
  const now = new Date()
  const [year, setYear] = useState(String(now.getFullYear()))
  const [month, setMonth] = useState(String(now.getMonth() + 1).padStart(2, '0'))
  const [stats, setStats] = useState(null)
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [apDropdownOpen, setApDropdownOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [sortKey, setSortKey] = useState(DEFAULT_SORT.key)
  const [sortDir, setSortDir] = useState(DEFAULT_SORT.dir)
  const ingresoApartados = useMemo(() => (apartados || []).filter((a) => a && a.modo_flujo === 'ingreso'), [apartados])
  const transferenciaApartados = useMemo(
    () => (apartados || []).filter((a) => a && a.modo_flujo === 'transferencia'),
    [apartados],
  )
  const apartadosForMode = mode === 'transferencias' ? transferenciaApartados : ingresoApartados
  const [selected, setSelected] = useState(() => new Set())
  const selectedCount = selected?.size || 0

  useEffect(() => {
    // Por defecto: todos los apartados del modo seleccionado
    const next = new Set()
    for (const a of apartadosForMode) next.add(a.codigo)
    setSelected(next)
  }, [apartadosForMode, mode])

  const load = useCallback(async (overrides = {}) => {
    const queryQ = overrides.q !== undefined ? overrides.q : q
    const queryYear = overrides.year !== undefined ? overrides.year : year
    const queryMonth = overrides.month !== undefined ? overrides.month : month
    if (!queryYear) {
      toast.error('Seleccioná el año para consultar registros')
      return
    }
    setLoading(true)
    try {
      const sp = new URLSearchParams()
      if (String(queryQ || '').trim()) sp.set('q', String(queryQ).trim())
      sp.set('year', queryYear)
      if (queryMonth) sp.set('month', queryMonth)
      const sel = Array.from(selected || [])
      for (const c of sel) sp.append('apartado', c)
      if (String(queryQ || '').trim()) {
        sp.set('limit', '800')
      } else {
        sp.set('limit', mode === 'transferencias' ? '2000' : '2500')
      }
      const endpoint = mode === 'transferencias' ? '/api/metricas/transferencias' : '/api/metricas/ingresos'
      const res = await apiFetch(endpoint + '?' + sp.toString())
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.error || res.statusText || 'Error al cargar registros')
      }
      setRows(data.documentos || [])
      setStats({
        filas_tango: data.filas_tango,
        comprobantes_tango: data.comprobantes_tango,
        pdfs_escaneados: data.pdfs_escaneados,
      })
      const archivosSidebar = data.archivos_generados ?? data.documentos
      onDocsChange(documentosConPdfGenerado(archivosSidebar))
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [q, year, month, selected, mode, onDocsChange])

  useImperativeHandle(ref, () => ({
    refresh: () => load(),
  }), [load])

  useEffect(() => {
    onLoadingChange?.(loading)
  }, [loading, onLoadingChange])

  useEffect(() => {
    onSearchQueryChange(q)
  }, [q, onSearchQueryChange])

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Al cambiar de tipo/selección, recargar automáticamente.
  // Esto evita quedar con la lista “vacía” si se cambió a Transferencias y nunca se volvió a pedir al backend.
  const selectedKey = useMemo(() => Array.from(selected || []).sort().join('|'), [selected])
  useEffect(() => {
    // Si todavía no hay selección pero sí hay apartados disponibles para el modo, esperar al efecto que setea defaults.
    if (!selectedKey && apartadosForMode.length > 0) return
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, selectedKey, year, month])

  useEffect(() => {
    setSortKey(DEFAULT_SORT.key)
    setSortDir(DEFAULT_SORT.dir)
    setPage(1)
  }, [mode])

  const flatItems = useMemo(() => {
    const out = []
    for (const d of rows || []) {
      for (const it of d.items || []) {
        out.push({
          fecha: d.fecha || '—',
          apartado: d.apartado || '—',
          archivo: d.archivo || '—',
          proveedor: d.proveedor || '—',
          comprobante: d.comprobante || '—',
          origen: d.origen || '—',
          destino: d.destino || '—',
          codigo: it.codigo || '—',
          descripcion: it.descripcion || '—',
          cantidad: it.cantidad ?? null,
          um: it.um || '',
        })
      }
    }
    return out
  }, [rows])

  const sortedItems = useMemo(() => {
    const arr = [...flatItems]
    arr.sort((a, b) => compareSortValues(a, b, sortKey, sortDir))
    return arr
  }, [flatItems, sortKey, sortDir])

  function handleSort(colKey) {
    setPage(1)
    if (sortKey === colKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(colKey)
      setSortDir(colKey === 'cantidad' || colKey === 'fecha' ? 'desc' : 'asc')
    }
  }

  const totals = useMemo(() => {
    let sum = 0
    const byUm = new Map()
    for (const r of flatItems) {
      const v = typeof r.cantidad === 'number' ? r.cantidad : null
      if (v == null) continue
      sum += v
      const um = (r.um || '—').trim() || '—'
      byUm.set(um, (byUm.get(um) || 0) + v)
    }
    const byUmArr = Array.from(byUm.entries()).sort((a, b) => String(a[0]).localeCompare(String(b[0])))
    return { sum: Math.round(sum * 1000) / 1000, byUm: byUmArr }
  }, [flatItems])

  const pageCount = useMemo(() => Math.max(1, Math.ceil((sortedItems.length || 0) / pageSize)), [sortedItems.length, pageSize])
  useEffect(() => {
    // Clamp si cambia el tamaño o el dataset
    setPage((p) => Math.min(Math.max(1, p), pageCount))
  }, [pageCount])

  const pagedItems = useMemo(() => {
    const start = (page - 1) * pageSize
    const end = start + pageSize
    return sortedItems.slice(start, end)
  }, [sortedItems, page, pageSize])

  function handleSearch() {
    if (Array.from(selected || []).length === 0) {
      toast.error('Seleccioná al menos un apartado')
      return
    }
    setPage(1)
    load()
  }

  function handleClearFilters() {
    const y = String(new Date().getFullYear())
    const m = String(new Date().getMonth() + 1).padStart(2, '0')
    setQ('')
    setYear(y)
    setMonth(m)
    setPage(1)
    load({ q: '', year: y, month: m })
  }

  return (
    <div className="h-full w-full min-h-0 min-w-0 overflow-y-auto p-5 scrollbar-thin">
      <div className="w-full space-y-4">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-widest uppercase text-app-text">Registros</h2>
            <p className="text-[11px] text-app-muted mt-0.5">
              Datos desde Tango
              {stats?.filas_tango != null ? (
                <span className="font-mono">
                  {' '}
                  · {stats.filas_tango} filas
                  {stats.comprobantes_tango != null ? ` · ${stats.comprobantes_tango} comprobantes` : ''}
                  {stats.pdfs_escaneados > 0 ? ` · ${stats.pdfs_escaneados} PDFs` : ''}
                </span>
              ) : null}
            </p>
        </div>

        <section className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-visible">
          <div className="px-4 py-3 border-b border-app-border">
            <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Filtros</div>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-xl border border-app-border bg-app-bg p-1">
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => setMode('ingresos')}
                  className={[
                    'px-3 py-2 rounded-lg text-[12px] font-extrabold tracking-widest uppercase transition-colors',
                    mode === 'ingresos' ? 'bg-accent/10 text-accent-dark' : 'text-app-muted hover:text-app-text',
                  ].join(' ')}
                >
                  Ingresos
                </button>
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => setMode('transferencias')}
                  className={[
                    'px-3 py-2 rounded-lg text-[12px] font-extrabold tracking-widest uppercase transition-colors',
                    mode === 'transferencias' ? 'bg-accent/10 text-accent-dark' : 'text-app-muted hover:text-app-text',
                  ].join(' ')}
                >
                  Transfer.
                </button>
              </div>

              <div className="relative">
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => setApDropdownOpen((v) => !v)}
                  className="px-3 py-2 rounded-card text-[12px] font-bold text-app-text bg-app-surface2 border border-app-border hover:border-app-muted disabled:opacity-60 transition-colors"
                >
                  Apartados {selectedCount}/{apartadosForMode.length}
                </button>
                {apDropdownOpen && (
                  <div className="absolute z-20 mt-2 w-[320px] max-w-[85vw] rounded-2xl border border-app-border bg-app-surface shadow-card overflow-hidden">
                    <div className="px-3 py-2 border-b border-app-border flex items-center justify-between">
                      <div className="text-[10px] font-extrabold tracking-widest uppercase text-app-muted">
                        Selección
                      </div>
                      <button
                        type="button"
                        className="text-[12px] font-bold text-app-muted hover:text-app-text"
                        onClick={() => setApDropdownOpen(false)}
                      >
                        Cerrar
                      </button>
                    </div>
                    <div className="max-h-[45vh] overflow-auto scrollbar-thin p-2">
                      {(apartadosForMode || []).map((a) => {
                        const checked = selected?.has(a.codigo)
                        return (
                          <label
                            key={a.codigo}
                            className="flex items-start gap-2 px-3 py-2 rounded-xl border border-transparent hover:bg-app-surface2 hover:border-app-border cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={!!checked}
                              onChange={(e) => {
                                const next = new Set(selected || [])
                                if (e.target.checked) next.add(a.codigo)
                                else next.delete(a.codigo)
                                setSelected(next)
                              }}
                              className="mt-1"
                            />
                            <span className="min-w-0">
                              <div className="text-[12px] font-bold text-app-text truncate">{a.nombre || a.codigo}</div>
                              <div className="text-[11px] text-app-muted font-mono truncate">{a.codigo}</div>
                            </span>
                          </label>
                        )
                      })}
                      {apartadosForMode.length === 0 && (
                        <div className="px-3 py-3 text-[12px] text-app-muted">
                          No hay apartados disponibles para tu usuario.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-[260px] mx-2 flex items-center gap-2">
                <input
                  className="flex-1 min-w-0 text-[13px] px-3 py-2 rounded-lg border border-app-border bg-app-bg text-app-text placeholder:text-app-muted focus:outline-none focus:border-accent-dark transition-colors"
                  placeholder="Buscar en archivos y registros Tango"
                  title="Sin texto: todos los PDFs del mes. Con texto: filtra archivos y suma coincidencias Tango"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleSearch()
                    }
                  }}
                />
                <button
                  type="button"
                  disabled={loading}
                  onClick={handleSearch}
                  className="px-4 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50"
                >
                  Buscar
                </button>
                <button
                  type="button"
                  disabled={loading || (!q && !year && !month)}
                  onClick={handleClearFilters}
                  className="px-3 py-2 rounded-card text-[12px] font-bold text-app-text bg-app-surface2 border border-app-border hover:border-app-muted disabled:opacity-50"
                  title="Borrar búsqueda, año y mes"
                >
                  Borrar
                </button>
              </div>

              <div className="flex items-center gap-2 ml-auto self-center">
                <select
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  className="text-[12px] px-2 py-2 rounded-lg border border-app-border bg-app-bg text-app-text focus:outline-none focus:border-accent-dark"
                  title="Año"
                >
                  <option value="" disabled>
                    Año
                  </option>
                    {Array.from({ length: 8 }).map((_, i) => {
                      const y = String(new Date().getFullYear() - i)
                      return (
                        <option key={y} value={y}>
                          {y}
                        </option>
                      )
                    })}
                </select>
                <select
                  value={month}
                  onChange={(e) => setMonth(e.target.value)}
                  className="text-[12px] px-2 py-2 rounded-lg border border-app-border bg-app-bg text-app-text focus:outline-none focus:border-accent-dark"
                  title="Mes"
                >
                  <option value="">Mes</option>
                    {Array.from({ length: 12 }).map((_, i) => {
                      const m = String(i + 1).padStart(2, '0')
                      return (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      )
                    })}
                </select>
              </div>
            </div>

            {/* Selector compacto reemplaza la grilla de checkboxes */}
          </div>
        </section>

        <section className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-hidden">
          <div className="px-4 py-3 border-b border-app-border flex items-center justify-between">
            <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Items</div>
            <div className="flex items-center gap-3">
              <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">
                Total: {totals.sum}
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={String(pageSize)}
                  onChange={(e) => { setPageSize(Number(e.target.value || 50)); setPage(1) }}
                  className="text-[12px] px-2 py-1.5 rounded-lg border border-app-border bg-app-bg text-app-text focus:outline-none focus:border-accent-dark"
                  title="Filas por página"
                >
                  <option value="25">25</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                  <option value="200">200</option>
                </select>
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-2 py-1.5 rounded-lg text-[12px] font-bold border border-app-border bg-app-bg text-app-text hover:border-app-muted disabled:opacity-50"
                >
                  Ant.
                </button>
                <div className="text-[12px] text-app-muted font-mono min-w-[4.5rem] text-center">
                  {page}/{pageCount}
                </div>
                <button
                  type="button"
                  disabled={page >= pageCount}
                  onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                  className="px-2 py-1.5 rounded-lg text-[12px] font-bold border border-app-border bg-app-bg text-app-text hover:border-app-muted disabled:opacity-50"
                >
                  Sig.
                </button>
              </div>
            </div>
          </div>
          <div className="max-h-[65vh] overflow-auto scrollbar-thin">
            <table className="w-full text-[12px]">
              <thead className="sticky top-0 bg-app-surface2/60 backdrop-blur border-b border-app-border">
                <tr className="text-left text-app-muted">
                  <SortableTh label="Fecha" colKey="fecha" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  {mode === 'transferencias' ? (
                    <>
                      <SortableTh label="Origen" colKey="origen" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                      <SortableTh label="Destino" colKey="destino" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    </>
                  ) : (
                    <SortableTh label="Proveedor" colKey="proveedor" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  )}
                  <SortableTh label="Artículo" colKey="codigo" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh label="Descripción" colKey="descripcion" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh
                    label="Cantidad"
                    colKey="cantidad"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={handleSort}
                    align="right"
                  />
                  <SortableTh label="U/M" colKey="um" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh label="Apartado" colKey="apartado" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                </tr>
              </thead>
              <tbody className="divide-y divide-app-border">
                {pagedItems.map((r, idx) => (
                  <tr key={idx} className="hover:bg-app-surface2/40">
                    <td className="px-3 py-2 font-mono">{r.fecha}</td>
                    {mode === 'transferencias' ? (
                      <>
                        <td className="px-3 py-2">{r.origen}</td>
                        <td className="px-3 py-2">{r.destino}</td>
                      </>
                    ) : (
                      <td className="px-3 py-2">{r.proveedor}</td>
                    )}
                    <td className="px-3 py-2 font-mono">{r.codigo}</td>
                    <td className="px-3 py-2">{r.descripcion}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.cantidad ?? '—'}</td>
                    <td className="px-3 py-2 font-mono">{r.um}</td>
                    <td className="px-3 py-2 font-mono">{r.apartado}</td>
                  </tr>
                ))}
                {pagedItems.length === 0 && (
                  <tr>
                    <td className="px-3 py-6 text-center text-app-muted" colSpan={mode === 'transferencias' ? 8 : 7}>
                      Sin resultados.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
})

export default MetricsPage

