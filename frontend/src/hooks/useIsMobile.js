import { useEffect, useState } from 'react'

const MQ = '(max-width: 640px)'

/**
 * true en viewports estrechos (p. ej. celular). Ingresos (cámara) solo se ofrece en móvil.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MQ).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(MQ)
    const on = () => setIsMobile(mq.matches)
    mq.addEventListener('change', on)
    on()
    return () => mq.removeEventListener('change', on)
  }, [])
  return isMobile
}
