import { ChevronLeft, LogOut, RefreshCw, Settings } from 'lucide-react'
import LogoMark from './LogoMark.jsx'
import { groupApartadosByArea } from '../utils/apartadoAreas.js'

function ListRefreshButton({ onClick, loading = false, compact = false, className = '' }) {
  return (
    <button
      type="button"
      disabled={loading}
      onClick={() => onClick?.()}
      title="Actualizar listado"
      className={[
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-accent bg-accent/10 font-bold text-accent disabled:opacity-50',
        compact ? 'px-2.5 py-1.5 text-[10px]' : 'px-2.5 py-1 text-[11px]',
        className,
      ].join(' ')}
    >
      <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
      <span>{loading ? '…' : 'Actualizar'}</span>
    </button>
  )
}

function TangoSyncControls({
  className = '',
  apartados,
  activeApartadoCodigo,
  onApartadoChange,
  syncFecha,
  onSyncFechaChange,
  onTangoSync,
  syncingTango,
  compact = false,
  showApartadoSelect = true,
}) {
  const grouped = groupApartadosByArea(apartados)
  const multiArea = grouped.length > 1

  return (
    <div className={['items-center gap-2', className].join(' ')}>
      {showApartadoSelect && (
        <select
          className="min-w-0 flex-1 rounded-lg border border-app-border bg-app-surface2 px-2 py-1.5 text-[11px] text-app-text sm:flex-none sm:max-w-[14rem]"
          value={activeApartadoCodigo || ''}
          onChange={(e) => onApartadoChange?.(e.target.value)}
        >
          {multiArea
            ? grouped.map((g) => (
                <optgroup key={g.area_id ?? g.area_codigo} label={g.area_nombre}>
                  {(g.apartados || []).map((a) => (
                    <option key={a.codigo} value={a.codigo}>
                      {a.nombre}
                    </option>
                  ))}
                </optgroup>
              ))
            : (apartados || []).map((a) => (
                <option key={a.codigo} value={a.codigo}>
                  {a.nombre}
                </option>
              ))}
        </select>
      )}
      <input
        type="date"
        className="shrink-0 rounded-lg border border-app-border bg-app-surface2 px-2 py-1.5 text-[11px] text-app-text"
        value={syncFecha || ''}
        onChange={(e) => onSyncFechaChange?.(e.target.value)}
      />
      <button
        type="button"
        disabled={syncingTango}
        onClick={() => onTangoSync?.()}
        title="Sincroniza comprobantes desde Tango y actualiza la lista de pendientes"
        className={[
          'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-accent bg-accent/10 font-bold text-accent disabled:opacity-50',
          compact ? 'px-2.5 py-1.5 text-[10px]' : 'px-2.5 py-1 text-[11px]',
        ].join(' ')}
      >
        <RefreshCw size={14} className={syncingTango ? 'animate-spin' : ''} />
        <span>{syncingTango ? '…' : 'Actualizar'}</span>
      </button>
    </div>
  )
}

export default function Header({
  connected,
  onLogout,
  onBackToList,
  titleSuffix = 'TRANSFERENCIAS',
  showAdminButton = false,
  adminActive = false,
  onAdmin,
  showTangoSync = false,
  syncFecha,
  onSyncFechaChange,
  apartados = [],
  activeApartadoCodigo,
  onApartadoChange,
  onTangoSync,
  syncingTango = false,
  showApartadoSelect = true,
  showListRefresh = false,
  onListRefresh,
  refreshingList = false,
}) {
  const connectionLabel = connected ? 'Conectado' : 'Sin conexión'

  const tangoProps = {
    apartados,
    activeApartadoCodigo,
    onApartadoChange,
    syncFecha,
    onSyncFechaChange,
    onTangoSync,
    syncingTango,
    showApartadoSelect,
  }

  return (
    <header className="col-span-full z-10 flex min-w-0 flex-col overflow-visible border-b border-app-border bg-app-surface">
      <div className="flex min-h-14 min-w-0 items-center gap-1.5 px-2 py-1.5 sm:gap-4 sm:px-5 sm:py-0">
      {onBackToList && (
        <button
          type="button"
          onClick={onBackToList}
          className="-ml-0.5 flex-shrink-0 rounded-lg border border-transparent p-1.5 text-app-text transition-colors hover:border-app-border hover:bg-app-surface2 sm:ml-0 sm:-ml-1 sm:p-2"
          title="Volver al listado"
        >
          <ChevronLeft size={22} strokeWidth={2.5} />
        </button>
      )}
      <LogoMark className="h-8 w-auto shrink-0" alt="Signa" />

      <h1 className="min-w-0 flex-1 text-left">
        <span className="sm:hidden">
          <span className="block text-[9px] font-semibold leading-none tracking-widest text-app-muted/90 uppercase">
            SIGNA
          </span>
          <span className="mt-0.5 block text-[12px] font-extrabold leading-tight tracking-wide text-accent uppercase">
            {titleSuffix}
          </span>
        </span>
        <span className="hidden min-w-0 sm:block sm:truncate sm:text-[15px] sm:font-bold sm:uppercase sm:tracking-widest sm:text-app-text">
          SIGNA - <span className="text-accent">{titleSuffix}</span>
        </span>
      </h1>

      <div className="ml-auto flex shrink-0 items-center justify-end gap-1.5 sm:gap-3">

        {showTangoSync && (
          <TangoSyncControls className="hidden sm:flex" {...tangoProps} />
        )}

        {showListRefresh && (
          <ListRefreshButton
            className="hidden sm:inline-flex"
            onClick={onListRefresh}
            loading={refreshingList}
          />
        )}

        <span
          role="status"
          title={connectionLabel}
          aria-label={connectionLabel}
          className={[
            'inline-block h-2.5 w-2.5 flex-shrink-0 rounded-full transition-colors',
            connected ? 'bg-emerald-500' : 'bg-red-500',
          ].join(' ')}
        />

        {showAdminButton && (
          <button
            type="button"
            onClick={onAdmin}
            className={[
              'inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-extrabold tracking-widest uppercase transition-colors',
              'sm:px-2.5 sm:py-1.5 sm:text-[11px]',
              adminActive
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-app-border bg-app-surface2 text-app-muted hover:border-app-muted hover:text-app-text',
            ].join(' ')}
            title="Administración"
          >
            <Settings size={14} className="shrink-0" />
            Admin
          </button>
        )}

        {onLogout && (
          <button
            onClick={onLogout}
            title="Cerrar sesión"
            className="flex shrink-0 items-center gap-0.5 rounded-lg px-1.5 py-1 text-[10px] text-app-muted transition-colors hover:bg-red-500/10 hover:text-red-400 sm:gap-1.5 sm:px-2 sm:text-[12px]"
          >
            <LogOut size={14} className="shrink-0" />
            <span>Salir</span>
          </button>
        )}
      </div>
      </div>

      {showTangoSync && (
        <TangoSyncControls
          className="flex w-full justify-center border-t border-app-border/80 px-2 py-2 sm:hidden"
          compact
          {...tangoProps}
        />
      )}

      {showListRefresh && (
        <div className="flex w-full justify-center border-t border-app-border/80 px-2 py-2 sm:hidden">
          <ListRefreshButton compact onClick={onListRefresh} loading={refreshingList} />
        </div>
      )}
    </header>
  )
}
