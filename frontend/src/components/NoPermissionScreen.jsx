import { TriangleAlert } from 'lucide-react'

export default function NoPermissionScreen({ visible, detail, onRetry }) {
  if (!visible) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-5"
      style={{
        background:
          'radial-gradient(1200px 500px at 20% 0%, rgba(13,148,136,0.12), transparent 60%), radial-gradient(900px 600px at 100% 30%, rgba(220,38,38,0.10), transparent 55%), rgba(238,241,247,0.88)',
        backdropFilter: 'blur(6px)',
      }}
    >
      <div className="w-[min(520px,92vw)] bg-app-surface border border-app-border rounded-2xl shadow-card p-[18px] grid grid-cols-[44px_1fr] gap-3.5">
        {/* Icon */}
        <div className="w-11 h-11 rounded-xl grid place-items-center text-red-600 bg-red-50 border border-red-200">
          <TriangleAlert size={22} strokeWidth={2.2} />
        </div>

        {/* Title */}
        <p className="font-extrabold text-[16px] text-app-text mt-0.5">Sin permiso</p>

        {/* Body */}
        <div className="col-start-2 text-[13.5px] text-app-muted leading-snug -mt-1.5">
          Esta PC o dispositivo no está autorizado para usar el sistema desde esta red.
          {detail && (
            <div className="mt-2 px-3 py-2.5 rounded-xl border border-dashed border-app-border bg-app-surface2/60 text-app-text font-mono text-[12.5px] break-words">
              {detail}
            </div>
          )}
        </div>

        {/* Action */}
        <div className="col-start-2 flex justify-end mt-2.5">
          <button
            type="button"
            onClick={onRetry}
            className="px-4 py-2 rounded-card text-[13px] font-bold text-app-text bg-app-surface2 border border-app-border hover:border-app-muted transition-colors"
          >
            Reintentar
          </button>
        </div>
      </div>
    </div>
  )
}
