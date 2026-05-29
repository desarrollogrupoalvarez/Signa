import { useEffect, useState } from 'react'

/**
 * @template T
 * @param {T} value
 * @param {number} delay
 * @returns {T}
 */
export function useDebounce(value, delay, resetKey) {
  const [debounced, setDebounced] = useState(value)

  // Al cambiar sesión (login/logout), aplicar el valor actual sin esperar el delay.
  useEffect(() => {
    setDebounced(value)
  }, [resetKey]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])

  return debounced
}
