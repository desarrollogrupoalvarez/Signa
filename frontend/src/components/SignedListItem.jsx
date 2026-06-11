import { displaySignedNombre } from '../utils/displayDocName.js'

export default function SignedListItem({ doc, active, onClick, compact = false }) {
  const date = new Date(doc.modificado_en).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
  const shortName = displaySignedNombre(doc)
  return (
    <div
      onClick={onClick}
      className={[
        'rounded-card border cursor-pointer transition-all select-none',
        compact ? 'px-2 py-2 mb-0.5' : 'px-3 py-3 mb-1',
        active
          ? 'bg-accent/10 border-accent-dark'
          : 'border-transparent hover:bg-app-surface2 hover:border-app-border',
      ].join(' ')}
    >
      <div
        className={[
          'font-semibold truncate',
          compact ? 'text-[11px]' : 'text-[12px] mb-1',
          active ? 'text-accent-dark' : 'text-app-text',
        ].join(' ')}
      >
        {shortName}
      </div>
      <div className={['text-app-muted font-mono', compact ? 'text-[9px]' : 'text-[10px]'].join(' ')}>
        {date}
      </div>
    </div>
  )
}
