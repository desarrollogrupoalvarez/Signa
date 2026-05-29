import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { apiFetch } from './api/client'
import Header from './components/Header'
import AdminPage from './components/AdminPage'
import LoginPage from './components/LoginPage'
import NoPermissionScreen from './components/NoPermissionScreen'
import PdfViewer from './components/PdfViewer'
import Sidebar from './components/Sidebar'
import SignaturePanel from './components/SignaturePanel'
import IngresoAttachments from './components/IngresoAttachments'
import MetricsPage from './components/MetricsPage'
import { useCroppedSignature } from './hooks/useCroppedSignature'
import { useIsMobile } from './hooks/useIsMobile'
import { useDebounce } from './hooks/useDebounce'
import { displayPendingNombre } from './utils/displayDocName.js'
import { filterPendingForUser, normListUsername } from './utils/pendingListForUser.js'
import { markTangoSynced, shouldSkipTangoSync, tangoSyncCacheKey } from './utils/tangoSyncCache.js'
import { upscaleSignatureForPlacement } from './utils/signatureExport.js'

const POLL_INTERVAL = 8000
const SIGNED_POLL_INTERVAL = 15000
const _PERM_REQUIRED = 'Permiso requerido:'

function signedRowKey(d) {
  return `${d?.origen || ''}::${d?.nombre || ''}`
}

function mergeSignedWithOptimistic(serverDocs, prevDocs) {
  const keys = new Set((serverDocs || []).map(signedRowKey))
  const extra = (prevDocs || []).filter((d) => !keys.has(signedRowKey(d)))
  return [...extra, ...(serverDocs || [])]
}

function optimisticSignedFromArchivo(archivoFirmado, apartadoCodigo) {
  const nombre = (archivoFirmado || '').trim()
  if (!nombre) return null
  const ext = nombre.includes('.') ? nombre.slice(nombre.lastIndexOf('.')) : '.pdf'
  const origen = (apartadoCodigo || '').trim() || 'transferencias'
  return {
    nombre,
    origen,
    modificado_en: new Date().toISOString(),
    categoria: 'pdf',
    extension: ext.toLowerCase(),
  }
}

function pickDefaultTab(perms = [], { mobileIngresosOnly = false, apartados = [] } = {}) {
  const aps = apartados || []
  const ing = aps.filter((x) => x.modo_flujo === 'ingreso')
  const tra = aps.filter((x) => x.modo_flujo === 'transferencia')
  if (mobileIngresosOnly && perms.includes('documentos:listar') && ing.length) return 'pendientes'
  if (perms.includes('documentos:listar')) return 'pendientes'
  if (perms.includes('firmados:listar')) return 'firmados'
  if (perms.includes('metricas:ver')) return 'metricas'
  if (
    perms.includes('apartados:gestionar') ||
    perms.includes('apartados:editar') ||
    perms.includes('apartados:crear') ||
    perms.includes('configuracion:rutas') ||
    perms.some((p) => p.startsWith('usuarios:') || p.startsWith('roles:'))
  ) {
    return 'admin'
  }
  return 'firmados'
}

function todayBuenosAires() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Argentina/Buenos_Aires',
  }).format(new Date())
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('rf_token'))
  const [activeTab, setActiveTab] = useState('pendientes')
  const [documents, setDocuments] = useState([])
  /** Incrementa en cada login/logout; invalida listas y respuestas HTTP tardías. */
  const [listSession, setListSession] = useState(0)
  const [documentsListSession, setDocumentsListSession] = useState(-1)
  const [signedDocs, setSignedDocs] = useState([])
  const [signedListSession, setSignedListSession] = useState(-1)
  const [signedQInput, setSignedQInput] = useState('')
  const [pendingQInput, setPendingQInput] = useState('')
  const [signedOrigen, setSignedOrigen] = useState('todos')
  const signedQDeb = useDebounce(signedQInput, 400, listSession)
  const pendingQDeb = useDebounce(pendingQInput, 400, listSession)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [connected, setConnected] = useState(false)
  const [currentUser, setCurrentUser] = useState(null)
  const [adminSection, setAdminSection] = useState('rutas')
  const [metricsDocs, setMetricsDocs] = useState([])
  const [activeApartadoCodigo, setActiveApartadoCodigo] = useState('')
  const [syncFecha, setSyncFecha] = useState(() => todayBuenosAires())
  const [syncingTango, setSyncingTango] = useState(false)
  const [refreshingSigned, setRefreshingSigned] = useState(false)
  const [refreshingMetrics, setRefreshingMetrics] = useState(false)

  const [noPermission, setNoPermission] = useState(false)
  const [noPermissionDetail, setNoPermissionDetail] = useState('')
  const [listBootLoading, setListBootLoading] = useState(false)

  const [rawSignature, setRawSignature] = useState(null)
  const [placement, setPlacement] = useState(null)
  const [numPages, setNumPages] = useState(0)
  const [selectedPage, setSelectedPage] = useState(1)
  const [signaturePadReset, setSignaturePadReset] = useState(0)

  const croppedFirma = useCroppedSignature(rawSignature)
  const pollRef = useRef(null)
  const signedPollRef = useRef(null)
  const metricsPageRef = useRef(null)
  /** Incrementar al cambiar de usuario para ignorar respuestas HTTP tardías del usuario anterior. */
  const documentsFetchIdRef = useRef(0)
  const signedFetchIdRef = useRef(0)
  const documentsAbortRef = useRef(null)
  const signedAbortRef = useRef(null)
  const currentUserRef = useRef(null)
  const fetchDocumentsRef = useRef(() => {})
  const fetchSignedRef = useRef(() => {})
  const listSessionRef = useRef(0)
  const shouldBootstrapRef = useRef(false)
  const listBootLoadingRef = useRef(false)
  const activeTabRef = useRef(activeTab)
  const skipNextPollFetchRef = useRef(false)
  const signedPrefetchDoneRef = useRef(false)
  const isMobile = useIsMobile()

  useEffect(() => {
    currentUserRef.current = currentUser
  }, [currentUser])

  useEffect(() => {
    activeTabRef.current = activeTab
  }, [activeTab])

  function invalidatePendingFetches() {
    documentsFetchIdRef.current += 1
    signedFetchIdRef.current += 1
    documentsAbortRef.current?.abort()
    documentsAbortRef.current = null
    signedAbortRef.current?.abort()
    signedAbortRef.current = null
  }

  function bumpListSession() {
    listSessionRef.current += 1
    const next = listSessionRef.current
    setListSession(next)
    setDocuments([])
    setDocumentsListSession(-1)
    setSignedDocs([])
    setSignedListSession(-1)
    signedPrefetchDoneRef.current = false
  }

  /** Limpia todo estado de UI vinculado al usuario anterior (logout o antes de login nuevo). */
  function resetSessionState() {
    invalidatePendingFetches()
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (signedPollRef.current) {
      clearInterval(signedPollRef.current)
      signedPollRef.current = null
    }
    bumpListSession()
    setSelectedDoc(null)
    setSignedQInput('')
    setPendingQInput('')
    setSignedOrigen('todos')
    setMetricsDocs([])
    setActiveApartadoCodigo('')
    setSyncFecha(todayBuenosAires())
    setAdminSection('rutas')
    setNoPermission(false)
    setNoPermissionDetail('')
    setConnected(false)
    setSyncingTango(false)
    setRefreshingSigned(false)
    setRefreshingMetrics(false)
    setListBootLoading(false)
    listBootLoadingRef.current = false
    skipNextPollFetchRef.current = false
    signedPrefetchDoneRef.current = false
    resetSignature()
  }

  const permissions = currentUser?.permissions || []
  const apartados = currentUser?.apartados || []
  const canPendientes = permissions.includes('documentos:listar')
  const canFirmados = permissions.includes('firmados:listar')
  const canMetricas = permissions.includes('metricas:ver')
  const canApartadosGestion = permissions.includes('apartados:gestionar')
  const canApartadosCrear =
    canApartadosGestion || permissions.includes('apartados:crear')
  const canApartadosEditar =
    canApartadosGestion || permissions.includes('apartados:editar')
  const showAdmin =
    canApartadosCrear ||
    canApartadosEditar ||
    permissions.some((p) => p === 'configuracion:rutas' || p.startsWith('usuarios:') || p.startsWith('roles:'))

  const transferenciaAps = useMemo(() => apartados.filter((a) => a.modo_flujo === 'transferencia'), [apartados])
  const ingresoAps = useMemo(() => apartados.filter((a) => a.modo_flujo === 'ingreso'), [apartados])

  const onlyMobileIngresos = isMobile && canPendientes && ingresoAps.length > 0

  /** Selector Tango en PC: solo transferencias (ingresos se gestionan en móvil). */
  const apartadosTangoSync = onlyMobileIngresos ? ingresoAps : transferenciaAps

  useEffect(() => {
    if (!apartados.length) return
    setActiveApartadoCodigo((prev) => {
      if (onlyMobileIngresos && ingresoAps.length) {
        if (prev && ingresoAps.some((x) => x.codigo === prev)) return prev
        return ingresoAps[0]?.codigo || ''
      }
      if (transferenciaAps.length) {
        if (prev && transferenciaAps.some((x) => x.codigo === prev)) return prev
        return transferenciaAps[0]?.codigo || ''
      }
      if (prev && apartados.some((x) => x.codigo === prev)) return prev
      return apartados[0]?.codigo || ''
    })
  }, [apartados, onlyMobileIngresos, ingresoAps, transferenciaAps])
  // Durante el bootstrap (antes de /api/auth/me), evitar caer a "firmados" por permisos vacÃ­os.
  const defaultTab = currentUser
    ? pickDefaultTab(permissions, { mobileIngresosOnly: onlyMobileIngresos, apartados })
    : 'pendientes'

  const documentsForUser =
    documentsListSession === listSession ? documents : []

  const mobileIngresoDocs = useMemo(
    () => documentsForUser.filter((d) => d.modo_flujo === 'ingreso'),
    [documentsForUser],
  )

  const documentsForActiveDesktop = useMemo(() => {
    const base = onlyMobileIngresos ? [] : documentsForUser
    if (!activeApartadoCodigo) return base
    return base.filter((d) => d.apartado_codigo === activeApartadoCodigo)
  }, [documentsForUser, onlyMobileIngresos, activeApartadoCodigo])

  const signedDocsForUser = signedListSession === listSession ? signedDocs : []

  // â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function handleLogin(data) {
    localStorage.setItem('rf_token', data.token)
    resetSessionState()
    setToken(data.token)
    setCurrentUser(data.user || null)
    currentUserRef.current = data.user || null
    const mobile = typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches
    setActiveTab(pickDefaultTab(data.user?.permissions || [], { mobileIngresosOnly: mobile, apartados: data.user?.apartados || [] }))
    shouldBootstrapRef.current = true
  }

  function handleLogout() {
    localStorage.removeItem('rf_token')
    resetSessionState()
    setToken(null)
    setCurrentUser(null)
    currentUserRef.current = null
    setActiveTab('pendientes')
  }

  const handlePermissionError = useCallback(
    (detail = '') => {
      if (detail?.includes('401') || detail?.toLowerCase().includes('token')) {
        handleLogout()
        return
      }
      if (String(detail || '').includes(_PERM_REQUIRED)) {
        toast.error(detail)
        setActiveTab((prev) => {
          const next = defaultTab
          return prev === next ? prev : next
        })
        return
      }
      setNoPermission(true)
      setNoPermissionDetail(detail)
      setConnected(false)
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    },
    [defaultTab],
  ) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchDocuments = useCallback(async (opts = {}) => {
    const { silent = false } = opts
    const user = currentUserRef.current
    const sessionUser = normListUsername(user?.username)
    if (!sessionUser) return
    const listGen = listSessionRef.current
    const fetchId = documentsFetchIdRef.current
    documentsAbortRef.current?.abort()
    const ac = new AbortController()
    documentsAbortRef.current = ac
    try {
      const sp = new URLSearchParams()
      if (syncFecha) sp.set('fecha', syncFecha)
      const pq = (pendingQDeb || '').trim()
      if (pq) sp.set('q', pq)
      sp.set('_', String(Date.now()))
      const qs = sp.toString()
      const path = '/api/documentos' + (qs ? `?${qs}` : '')
      const res = await apiFetch(path, { signal: ac.signal })
      const { documentos } = await res.json()
      if (fetchId !== documentsFetchIdRef.current) return
      if (listGen !== listSessionRef.current) return
      if (sessionUser !== normListUsername(currentUserRef.current?.username)) return
      const filtered = filterPendingForUser(documentos, user)
      setDocuments(filtered)
      setDocumentsListSession(listGen)
      setConnected(true)
    } catch (e) {
      if (e?.name === 'AbortError') return
      if (fetchId !== documentsFetchIdRef.current) return
      if (listGen !== listSessionRef.current) return
      if (sessionUser !== normListUsername(currentUserRef.current?.username)) return
      if (e.status === 401 || e.status === 403) handlePermissionError(e.detail)
      else setConnected(false)
    } finally {
      if (documentsAbortRef.current === ac) documentsAbortRef.current = null
    }
  }, [handlePermissionError, syncFecha, pendingQDeb])

  fetchDocumentsRef.current = fetchDocuments

  const resolveApartadoCodigoForSync = useCallback(() => {
    if (onlyMobileIngresos) return ingresoAps[0]?.codigo || ''
    return (
      transferenciaAps.find((a) => a.codigo === activeApartadoCodigo)?.codigo ||
      transferenciaAps[0]?.codigo ||
      ''
    )
  }, [onlyMobileIngresos, ingresoAps, transferenciaAps, activeApartadoCodigo])

  const showTangoSyncToasts = useCallback((data) => {
    const nGen = (data.generados || []).length
    const nReg = (data.registrados || []).length
    const omitB = (data.omitidos_en_bandeja || []).length
    const omitF = (data.omitidos_ya_firmados || []).length
    const omitNR = (data.omitidos_sin_registro || []).length
    const filas = data.filas_tango ?? 0
    const comps = data.comprobantes_detectados ?? 0
    const errs = data.errores || []
    const porFuente = data.generados_por_fuente || {}
    const fuenteTxt = Object.entries(porFuente)
      .map(([k, arr]) => `${k}: ${(arr || []).length}`)
      .join(', ')
    if (errs.length) toast.error(errs.join('; '))
    else if (nGen) {
      const extra = fuenteTxt ? ` (${fuenteTxt})` : ''
      const regTxt = nReg ? `, ${nReg} en lista` : ''
      const skipTxt = omitNR ? `, ${omitNR} no registrados` : ''
      toast.success(
        `Tango: ${nGen} PDF(s) nuevos${regTxt}${skipTxt} (${comps} comprobante(s) en Tango, ${filas} línea(s))${extra}`,
      )
    } else if (comps > 0) {
      const extra = fuenteTxt ? ` — ${fuenteTxt}` : ''
      const regTxt = nReg ? `, ${nReg} en lista` : ''
      const skipTxt = omitNR ? `, ${omitNR} no registrados` : ''
      toast.success(
        `Sin PDFs nuevos: ${comps} comprobante(s) en Tango (${omitB} ya en bandeja${regTxt}, ${omitF} ya firmados${skipTxt})${extra}`,
      )
    } else {
      const filasPf = data.filas_tango_por_fuente || {}
      const det = Object.entries(filasPf)
        .map(([k, v]) => `${k}: ${v} filas`)
        .join(', ')
      const extra = det ? ` (${det})` : ''
      toast.success(
        `Tango: 0 comprobantes para esa fecha (usuarios: ${(data.usuarios_consultados || []).join(', ') || '—'})${extra}`,
      )
    }
  }, [])

  const syncTangoAndRefresh = useCallback(
    async ({ showToasts = true, force = false } = {}) => {
      const codigo = resolveApartadoCodigoForSync()
      if (!codigo) {
        if (showToasts) toast.error('Seleccioná un apartado')
        await fetchDocuments({ silent: true })
        return { skipped: true }
      }
      const user = normListUsername(currentUserRef.current?.username)
      const cacheKey = tangoSyncCacheKey(user, codigo, syncFecha)
      if (!force && shouldSkipTangoSync(cacheKey)) {
        await fetchDocuments({ silent: true })
        if (showToasts) {
          toast.message('Lista actualizada (Tango ya sincronizado hace poco)')
        }
        return { skipped: true, cached: true }
      }
      try {
        const res = await apiFetch(`/api/apartados/${encodeURIComponent(codigo)}/sincronizar-tango`, {
          method: 'POST',
          body: JSON.stringify({ fecha: syncFecha }),
        })
        const data = await res.json()
        markTangoSynced(cacheKey)
        if (showToasts) showTangoSyncToasts(data)
      } catch (e) {
        if (e.status === 401 || e.status === 403) {
          handlePermissionError(e.detail)
          throw e
        }
        if (showToasts) toast.error(e.message || 'Error al sincronizar con Tango')
      }
      await fetchDocuments({ silent: true })
      return { skipped: false }
    },
    [resolveApartadoCodigoForSync, syncFecha, fetchDocuments, showTangoSyncToasts, handlePermissionError],
  )

  const syncTango = useCallback(async () => {
    setSyncingTango(true)
    try {
      await syncTangoAndRefresh({ showToasts: true, force: true })
    } finally {
      setSyncingTango(false)
    }
  }, [syncTangoAndRefresh])

  const fetchSigned = useCallback(async (opts = {}) => {
    const { silent = false, fresh = false, mergeOptimistic = false } = opts
    const sessionUser = normListUsername(currentUserRef.current?.username)
    if (!sessionUser) return
    const listGen = listSessionRef.current
    const fetchId = signedFetchIdRef.current
    signedAbortRef.current?.abort()
    const ac = new AbortController()
    signedAbortRef.current = ac
    if (!silent) setRefreshingSigned(true)
    try {
      const sp = new URLSearchParams()
      const q = (signedQDeb || '').trim()
      if (q) sp.set('q', q)
      if (signedOrigen && signedOrigen !== 'todos') sp.set('origen', signedOrigen)
      if (fresh) sp.set('fresh', '1')
      sp.set('_', String(Date.now()))
      const qs = sp.toString()
      const path = '/api/firmados' + (qs ? `?${qs}` : '')
      const res = await apiFetch(path, { signal: ac.signal })
      const { documentos } = await res.json()
      if (fetchId !== signedFetchIdRef.current) return
      if (listGen !== listSessionRef.current) return
      if (sessionUser !== normListUsername(currentUserRef.current?.username)) return
      setSignedDocs((prev) =>
        mergeOptimistic ? mergeSignedWithOptimistic(documentos, prev) : documentos,
      )
      setSignedListSession(listGen)
      setConnected(true)
    } catch (e) {
      if (e?.name === 'AbortError') return
      if (fetchId !== signedFetchIdRef.current) return
      if (listGen !== listSessionRef.current) return
      if (sessionUser !== normListUsername(currentUserRef.current?.username)) return
      if (e.status === 401 || e.status === 403) handlePermissionError(e.detail)
      else {
        setConnected(false)
        if (!silent) toast.error('No se pudo cargar firmados: ' + e.message)
      }
    } finally {
      if (signedAbortRef.current === ac) signedAbortRef.current = null
      if (!silent && fetchId === signedFetchIdRef.current) setRefreshingSigned(false)
    }
  }, [handlePermissionError, signedQDeb, signedOrigen])

  const bootstrapSessionAfterAuth = useCallback(async () => {
    const user = currentUserRef.current
    if (!user) return
    const bootGen = listSessionRef.current
    listBootLoadingRef.current = true
    setListBootLoading(true)
    try {
      const perms = user.permissions || []
      const canListPending = perms.includes('documentos:listar')
      const canListSigned = perms.includes('firmados:listar')
      const bootTab = activeTabRef.current

      if (!canListPending && !canListSigned) return

      if (canListPending) {
        await fetchDocuments({ silent: true })
      } else if (canListSigned && bootTab === 'firmados') {
        await fetchSigned({ silent: true, mergeOptimistic: false })
      }
    } catch (e) {
      if (e?.status === 401 || e?.status === 403) return
      if (bootGen === listSessionRef.current) {
        const perms = user.permissions || []
        if (perms.includes('documentos:listar')) {
          try {
            await fetchDocuments({ silent: true })
          } catch {
            /* ignore */
          }
        }
      }
    } finally {
      if (bootGen === listSessionRef.current) {
        skipNextPollFetchRef.current = true
        listBootLoadingRef.current = false
        setListBootLoading(false)
      }
    }
  }, [fetchDocuments, fetchSigned])

  fetchSignedRef.current = fetchSigned

  const applyOptimisticSigned = useCallback((archivoFirmado, apartadoCodigo) => {
    const row = optimisticSignedFromArchivo(archivoFirmado, apartadoCodigo)
    if (!row) return
    const listGen = listSessionRef.current
    const rowKey = signedRowKey(row)
    setSignedDocs((prev) => {
      const rest = prev.filter((d) => signedRowKey(d) !== rowKey)
      return [row, ...rest]
    })
    setSignedListSession(listGen)
  }, [])

  /** Refresca pendientes y digitalizados sin bloquear la UI (p. ej. tras firmar). */
  const refreshListsAfterPendingChange = useCallback(() => {
    const perms = currentUserRef.current?.permissions || []
    const tasks = [fetchDocuments({ silent: true })]
    if (perms.includes('firmados:listar')) {
      tasks.push(fetchSigned({ silent: true, fresh: true, mergeOptimistic: true }))
    }
    void Promise.all(tasks).catch(() => {})
  }, [fetchDocuments, fetchSigned])

  const listRefreshLoading =
    activeTab === 'firmados'
      ? refreshingSigned
      : activeTab === 'metricas'
        ? refreshingMetrics
        : false

  const canRevealLocation =
    currentUser?.role === 'superadmin' || currentUser?.role === 'administrador'

  function handleListRefresh() {
    if (activeTab === 'firmados') {
      fetchSigned({ silent: false, fresh: true, mergeOptimistic: false })
    } else if (activeTab === 'metricas') metricsPageRef.current?.refresh()
  }

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      const meFetchId = documentsFetchIdRef.current
      try {
        const res = await apiFetch('/api/auth/me')
        const me = await res.json()
        if (cancelled || meFetchId !== documentsFetchIdRef.current) return
        const wasBootstrap = !currentUserRef.current
        setCurrentUser(me)
        currentUserRef.current = me
        const mobile = typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches
        const perms = me?.permissions || []
        const aps = me?.apartados || []
        const ingresoCount = aps.filter((a) => a?.modo_flujo === 'ingreso').length
        const mobileIngresosOnly = mobile && perms.includes('documentos:listar') && ingresoCount > 0
        setActiveTab(pickDefaultTab(perms, { mobileIngresosOnly, apartados: aps }))
        if (wasBootstrap) {
          shouldBootstrapRef.current = true
        }
      } catch (e) {
        if (e.status === 401) handleLogout()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!token || !currentUser) return
    if (!shouldBootstrapRef.current) return
    shouldBootstrapRef.current = false
    void bootstrapSessionAfterAuth()
  }, [token, currentUser?.id, listSession, bootstrapSessionAfterAuth])

  useEffect(() => {
    if (!token || !currentUser || listBootLoading || !canFirmados) return
    if (activeTab !== 'firmados') {
      if (signedPollRef.current) {
        clearInterval(signedPollRef.current)
        signedPollRef.current = null
      }
      return
    }
    fetchSigned({ silent: true })
    if (signedPollRef.current) clearInterval(signedPollRef.current)
    signedPollRef.current = setInterval(
      () => fetchSigned({ silent: true }),
      SIGNED_POLL_INTERVAL,
    )
    return () => {
      if (signedPollRef.current) {
        clearInterval(signedPollRef.current)
        signedPollRef.current = null
      }
    }
  }, [activeTab, fetchSigned, token, currentUser, listBootLoading, canFirmados])

  useEffect(() => {
    if (!token || !currentUser || listBootLoading || !canFirmados) return
    if (activeTab !== 'pendientes') return
    if (signedPrefetchDoneRef.current) return
    signedPrefetchDoneRef.current = true
    fetchSigned({ silent: true })
  }, [activeTab, token, currentUser, listBootLoading, canFirmados, fetchSigned])

  useEffect(() => {
    if (!token || !currentUser || listBootLoading) return
    if (activeTab === 'admin') {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      return
    }
    if (skipNextPollFetchRef.current) {
      skipNextPollFetchRef.current = false
    } else {
      fetchDocuments({ silent: true })
    }
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => fetchDocuments({ silent: true }), POLL_INTERVAL)
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [fetchDocuments, activeTab, token, currentUser, listBootLoading])

  useEffect(() => {
    if (selectedDoc?.tipo === 'pendiente') {
      const still = documentsForUser.find((d) => d.id === selectedDoc.id)
      if (!still) {
        setSelectedDoc(null)
        resetSignature()
      }
    }
  }, [documents]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!token) return
    // Asegurar que el tab activo sea vÃ¡lido
    if (activeTab === 'admin' && !showAdmin) setActiveTab(defaultTab)
    if (activeTab === 'firmados' && !canFirmados) setActiveTab(defaultTab)
    if (activeTab === 'metricas' && !canMetricas) setActiveTab(defaultTab)
    if (activeTab === 'pendientes' && !canPendientes) setActiveTab(defaultTab)
  }, [onlyMobileIngresos, ingresoAps, apartados, transferenciaAps, activeTab, showAdmin, canFirmados, canMetricas, canPendientes, defaultTab])

  useEffect(() => {
    if (!onlyMobileIngresos) return
    if (selectedDoc?.tipo === 'firmado' || (selectedDoc?.modo_flujo && selectedDoc.modo_flujo !== 'ingreso')) {
      setSelectedDoc(null)
      resetSignature()
    }
  }, [onlyMobileIngresos, selectedDoc?.tipo, selectedDoc?.modo_flujo]) // eslint-disable-line react-hooks/exhaustive-deps

  // No forzar deselecciÃ³n por apartado (Pendientes muestra todos)

  function onTabChange(tab) {
    if (tab === 'admin') {
      if (!showAdmin) return
      setActiveTab('admin')
      if (selectedDoc) setSelectedDoc(null)
      resetSignature()
      return
    }
    if (tab === 'metricas') {
      if (!canMetricas) return
      if (selectedDoc) setSelectedDoc(null)
      resetSignature()
      setActiveTab('metricas')
      return
    }
    if (tab === 'firmados') {
      if (!canFirmados) return
      if (selectedDoc?.tipo === 'pendiente') { setSelectedDoc(null); resetSignature() }
      setActiveTab('firmados')
      if (signedListSession !== listSession) fetchSigned({ silent: true })
      return
    }
    if (tab === 'pendientes') {
      if (!canPendientes) return
      if (selectedDoc?.tipo === 'firmado') setSelectedDoc(null)
      setActiveTab('pendientes')
      if (documentsListSession !== listSession) fetchDocuments({ silent: true })
    }
  }

  function handleSelectDoc(doc) {
    setSelectedDoc({ ...doc, tipo: 'pendiente' })
    resetSignature()
  }

  function handleSelectSigned(doc) {
    setSelectedDoc({ ...doc, tipo: 'firmado' })
  }

  async function handleSign() {
    if (!selectedDoc || !croppedFirma || !placement) return
    const doc = selectedDoc
    const docId = doc.id
    const signedApartado = doc.apartado_codigo
    const nombreToast = displayPendingNombre(doc)
    try {
      const dispositivo = `${navigator.userAgent.slice(0, 80)} | ${new Date().toISOString()}`
      const firmaPayload = await upscaleSignatureForPlacement({
        dataURL: croppedFirma.dataURL,
        aspect: croppedFirma.aspect,
        placement: {
          x: placement.x,
          y: placement.y,
          w: placement.w,
          h: placement.h,
        },
      })
      const res = await apiFetch(`/api/documentos/${docId}/firmar`, {
        method: 'POST',
        body: JSON.stringify({
          firma: firmaPayload,
          dispositivo,
          page: placement.page,
          placement: { x: placement.x, y: placement.y, w: placement.w, h: placement.h },
        }),
      })
      const data = await res.json()
      if (currentUserRef.current?.permissions?.includes('firmados:listar')) {
        applyOptimisticSigned(data.archivo_firmado, signedApartado)
      }
      const listGen = listSessionRef.current
      setDocuments((prev) => prev.filter((d) => d.id !== docId))
      setDocumentsListSession(listGen)
      toast.success(`"${nombreToast}" guardado correctamente`)
      setSelectedDoc(null)
      resetSignature()
      refreshListsAfterPendingChange()
    } catch (e) {
      if (e.status === 401 || e.status === 403) handlePermissionError(e.detail)
      else toast.error('Error al guardar: ' + e.message)
    }
  }

  async function handleSaveWithoutSign() {
    if (!selectedDoc || selectedDoc.tipo !== 'pendiente') return
    if (
      !window.confirm(
        '¿Archivar sin firma? El PDF se moverá al destino y dejará de estar pendiente.',
      )
    ) {
      return
    }
    const doc = selectedDoc
    const docId = doc.id
    const signedApartado = doc.apartado_codigo
    const nombreToast = displayPendingNombre(doc)
    try {
      const dispositivo = `${navigator.userAgent.slice(0, 80)} | ${new Date().toISOString()}`
      const res = await apiFetch(`/api/documentos/${docId}/archivar_sin_firma`, {
        method: 'POST',
        body: JSON.stringify({ dispositivo }),
      })
      const data = await res.json()
      if (currentUserRef.current?.permissions?.includes('firmados:listar')) {
        applyOptimisticSigned(data.archivo_firmado, signedApartado)
      }
      const listGen = listSessionRef.current
      setDocuments((prev) => prev.filter((d) => d.id !== docId))
      setDocumentsListSession(listGen)
      toast.success(`"${nombreToast}" archivado correctamente`)
      setSelectedDoc(null)
      resetSignature()
      refreshListsAfterPendingChange()
    } catch (e) {
      if (e.status === 401 || e.status === 403) handlePermissionError(e.detail)
      else toast.error('Error al archivar: ' + e.message)
    }
  }

  async function handleRetry() {
    setNoPermission(false)
    try {
      await apiFetch('/api/health')
      setConnected(true)
      if (activeTab === 'firmados') await fetchSigned()
      else await fetchDocuments()
      if (!pollRef.current) {
        pollRef.current = setInterval(() => fetchDocuments({ silent: true }), POLL_INTERVAL)
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) handlePermissionError(e.detail)
      else setConnected(false)
    }
  }

  function resetSignature() {
    setRawSignature(null)
    setPlacement(null)
    setNumPages(0)
    setSelectedPage(1)
    setSignaturePadReset((n) => n + 1)
  }

  const canSign = !!(selectedDoc?.tipo === 'pendiente' && croppedFirma && placement)
  const canSaveWithoutSign = !!(
    selectedDoc?.tipo === 'pendiente' && selectedDoc?.modo_flujo === 'transferencia'
  )
  const canRenderIngresoPanel = isMobile && selectedDoc?.modo_flujo === 'ingreso'
  const canRenderSignPanel = !isMobile && canPendientes && activeTab === 'pendientes' && selectedDoc?.modo_flujo === 'transferencia'
  const hideMobileIngresoSidebar = onlyMobileIngresos && !!selectedDoc
  const mobileIngresoListFull = onlyMobileIngresos && !selectedDoc

  function handleBackToIngresoList() {
    setSelectedDoc(null)
    resetSignature()
  }

  const headerSuffix =
    activeTab === 'firmados'
      ? 'DIGITALIZADOS'
      : activeTab === 'metricas'
        ? 'REGISTROS'
        : activeTab === 'admin'
          ? 'ADMIN'
          : 'PENDIENTES'

  function handlePagesLoaded(n) {
    setNumPages(n)
    setSelectedPage(n)
  }

  useEffect(() => {
    if (!currentUser) return
    if (activeTab === 'admin' && !showAdmin) {
      setActiveTab(defaultTab)
      return
    }
    if (activeTab === 'firmados' && !canFirmados) {
      setActiveTab(defaultTab)
    }
  }, [activeTab, canFirmados, showAdmin, currentUser, defaultTab])
  if (!token) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <>
      <NoPermissionScreen visible={noPermission} detail={noPermissionDetail} onRetry={handleRetry} />

      <div
        key={`${currentUser?.id ?? 'u'}-${listSession}`}
        className={[
          'h-[100dvh] min-h-0 grid overflow-hidden',
          'grid-rows-[minmax(3.5rem,auto)_minmax(0,1fr)]',
          hideMobileIngresoSidebar || mobileIngresoListFull ? 'grid-cols-1' : 'grid-cols-[320px_1fr]',
          noPermission ? 'blur-sm pointer-events-none' : '',
        ].join(' ')}
        style={{ '--tw-blur': noPermission ? 'blur(2px)' : undefined }}
      >
        <Header
          connected={connected}
          onLogout={handleLogout}
          onBackToList={hideMobileIngresoSidebar ? handleBackToIngresoList : undefined}
          titleSuffix={headerSuffix}
          showAdminButton={!isMobile && showAdmin}
          adminActive={activeTab === 'admin'}
          onAdmin={() => onTabChange('admin')}
          showTangoSync={canPendientes && activeTab === 'pendientes'}
          showListRefresh={
            (canFirmados && activeTab === 'firmados') || (canMetricas && activeTab === 'metricas')
          }
          onListRefresh={handleListRefresh}
          refreshingList={listRefreshLoading}
          syncFecha={syncFecha}
          onSyncFechaChange={setSyncFecha}
          apartados={apartadosTangoSync}
          activeApartadoCodigo={activeApartadoCodigo}
          onApartadoChange={setActiveApartadoCodigo}
          onTangoSync={syncTango}
          syncingTango={syncingTango}
          showApartadoSelect={!onlyMobileIngresos && transferenciaAps.length > 0}
        />

        {!hideMobileIngresoSidebar && (
          <Sidebar
            activeTab={activeTab}
            apartadoTabsOrigins={apartados}
            showFirmados={!isMobile && canFirmados}
            showMetricas={!isMobile && canMetricas}
            metricsDocs={metricsDocs}
            onlyIngresosLayout={!!onlyMobileIngresos}
            listFullWidth={!!mobileIngresoListFull}
            documentsForTab={documentsForActiveDesktop}
            documentsIngresoMobile={mobileIngresoDocs}
            signedDocs={signedDocsForUser}
            signedQ={signedQInput}
            onSignedQChange={setSignedQInput}
            pendingQ={pendingQInput}
            onPendingQChange={setPendingQInput}
            signedOrigen={signedOrigen}
            onSignedOrigenChange={setSignedOrigen}
            canRevealLocation={canRevealLocation}
            selectedDoc={selectedDoc}
            onTabChange={onTabChange}
            onSelectDoc={handleSelectDoc}
            onSelectSigned={handleSelectSigned}
            listLoading={listBootLoading || (syncingTango && activeTab === 'pendientes')}
            adminMenu={{
              visible: activeTab === 'admin',
              active: adminSection,
              sections: [
                ...((showAdmin && (canApartadosEditar || permissions.includes('configuracion:rutas')))
                  ? [{ id: 'rutas', label: 'Rutas' }]
                  : []),
                ...(canApartadosCrear ? [{ id: 'apartados', label: 'Apartados' }] : []),
                ...(permissions.some((p) => p.startsWith('usuarios:')) ? [{ id: 'usuarios', label: 'Usuarios' }] : []),
                ...(permissions.some((p) => p.startsWith('roles:')) ? [{ id: 'roles', label: 'Roles' }] : []),
              ],
              onChange: (id) => setAdminSection(id),
            }}
          />
        )}

        {(!onlyMobileIngresos || selectedDoc) && (
          <main
            className={[
              'h-full min-h-0 overflow-hidden bg-app-bg min-w-0',
              hideMobileIngresoSidebar ? 'col-span-full' : '',
              canRenderIngresoPanel ? 'flex min-h-0 flex-1 flex-col' : 'flex flex-1',
            ].join(' ')}
          >
            {activeTab === 'admin' ? (
              <AdminPage currentUser={currentUser} section={adminSection} />
            ) : activeTab === 'metricas' ? (
              <MetricsPage
                ref={metricsPageRef}
                apartados={apartados}
                onDocsChange={setMetricsDocs}
                onLoadingChange={setRefreshingMetrics}
              />
            ) : canRenderIngresoPanel ? (
              <IngresoAttachments
                docId={selectedDoc.id}
                onFinalizado={() => {
                  setSelectedDoc(null)
                  resetSignature()
                  fetchDocuments()
                }}
              />
            ) : (
              <>
                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                  <PdfViewer
                    selectedDoc={selectedDoc}
                    croppedFirma={croppedFirma}
                    selectedPage={selectedPage}
                    onPlacementChange={setPlacement}
                    onPagesLoaded={handlePagesLoaded}
                    canRevealLocation={canRevealLocation}
                  />
                </div>

                {canRenderSignPanel && (
                  <SignaturePanel
                    selectedDoc={selectedDoc}
                    numPages={numPages}
                    selectedPage={selectedPage}
                    onPageChange={setSelectedPage}
                    onSignatureChange={setRawSignature}
                    onSign={handleSign}
                    canSign={canSign}
                    onSaveWithoutSign={handleSaveWithoutSign}
                    canSaveWithoutSign={canSaveWithoutSign}
                    onRefresh={fetchDocuments}
                    padResetKey={signaturePadReset}
                  />
                )}
              </>
            )}
          </main>
        )}
      </div>
    </>
  )
}
