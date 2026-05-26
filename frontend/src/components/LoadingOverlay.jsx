export default function LoadingOverlay({ msg }) {
  if (!msg) return null
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-slate-50/90">
      <div className="w-10 h-10 rounded-full border-[3px] border-app-border border-t-accent animate-spin" />
      <p className="text-[14px] text-app-muted">{msg}</p>
    </div>
  )
}

