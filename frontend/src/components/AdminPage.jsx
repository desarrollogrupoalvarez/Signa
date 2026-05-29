import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Save, Trash2, UserX } from 'lucide-react'
import { toast } from 'sonner'
import { apiFetch } from '../api/client'

const TANGO_FUENTE_OPTIONS = [
  { id: 'SAN_RAFAEL', label: 'SAN_RAFAEL (Agro)' },
  { id: 'CTC', label: 'CTC (Telecom)' },
]

const DEFAULT_CATEGORIAS_TRANSFERENCIA = [
  { nombre: 'Regulares', keywords: '' },
  { nombre: 'Importante', keywords: 'fibra,bateria,batería' },
]

function cloneCategorias(cats) {
  return (cats || []).map((c) => ({
    nombre: c.nombre || '',
    keywords: c.keywords || '',
  }))
}

function makeDeposito(overrides = {}) {
  return {
    carpeta: '',
    tango_fuente: 'SAN_RAFAEL',
    cod_depositos: '2',
    categorias: cloneCategorias(DEFAULT_CATEGORIAS_TRANSFERENCIA),
    ...overrides,
  }
}

const DEFAULT_DEPOSITOS = [
  makeDeposito({ carpeta: 'AGROINDUSTRIAS', tango_fuente: 'SAN_RAFAEL' }),
  makeDeposito({ carpeta: 'TELECOMUNICACIONES', tango_fuente: 'CTC' }),
]

function legacyCategoriasFromApartado(apartado) {
  const rows = apartado?.categorias_destino
  if (Array.isArray(rows) && rows.length > 0) {
    return cloneCategorias(rows)
  }
  const kw = (apartado?.keywords_importante || '').trim()
  return [
    { nombre: 'Regulares', keywords: '' },
    { nombre: 'Importante', keywords: kw || 'fibra,bateria,batería' },
  ]
}

function depositosFromApartado(apartado) {
  const fallbackCats = legacyCategoriasFromApartado(apartado)
  const rows = apartado?.depositos_config
  if (Array.isArray(rows) && rows.length > 0) {
    return rows.map((d) => ({
      carpeta: d.carpeta || '',
      tango_fuente: d.tango_fuente || 'SAN_RAFAEL',
      cod_depositos: Array.isArray(d.cod_depositos) ? d.cod_depositos.join(',') : String(d.cod_depositos || '2'),
      categorias:
        Array.isArray(d.categorias) && d.categorias.length > 0
          ? cloneCategorias(d.categorias)
          : cloneCategorias(fallbackCats),
    }))
  }
  const cod = (apartado?.cod_deposito || '2').trim() || '2'
  return DEFAULT_DEPOSITOS.map((d) => ({ ...d, cod_depositos: cod, categorias: cloneCategorias(fallbackCats) }))
}

function depositosToPayload(rows, { incluirCategorias = false } = {}) {
  return rows.map((d) => {
    const item = {
      carpeta: (d.carpeta || '').trim(),
      tango_fuente: (d.tango_fuente || '').trim(),
      cod_depositos: (d.cod_depositos || '2')
        .split(/[,;]+/)
        .map((x) => x.trim())
        .filter(Boolean),
    }
    if (incluirCategorias) {
      item.categorias = categoriasToPayload(d.categorias || [])
    }
    return item
  })
}

function categoriasToPayload(rows) {
  return rows.map((c) => {
    const nombre = (c.nombre || '').trim()
    const keywords = (c.keywords || '').trim()
    return keywords ? { nombre, keywords } : { nombre }
  })
}

/** Etiqueta visible al asignar apartados a usuarios (nombre UI, no código interno). */
function apartadoAssignLabel(a) {
  const nombre = (a?.nombre || '').trim()
  return nombre || a?.codigo || ''
}

function canManageUsers(perms = []) {
  return perms.includes('usuarios:listar') || perms.includes('usuarios:crear') || perms.includes('usuarios:editar') || perms.includes('usuarios:eliminar')
}

function canManageRoles(perms = []) {
  return perms.includes('roles:listar') || perms.includes('roles:gestionar')
}

function canManagePaths(perms = []) {
  return perms.includes('configuracion:rutas')
}

function canGestionarApartados(perms = []) {
  return perms.includes('apartados:gestionar')
}

function canCrearApartados(perms = []) {
  return canGestionarApartados(perms) || perms.includes('apartados:crear')
}

function canEditarApartados(perms = []) {
  return canGestionarApartados(perms) || perms.includes('apartados:editar')
}

export default function AdminPage({ currentUser, section = 'rutas' }) {
  const permissions = currentUser?.permissions || []
  const allowUsers = canManageUsers(permissions)
  const allowRoles = canManageRoles(permissions)
  const allowPaths = canManagePaths(permissions)
  const allowApartadosPaths = canEditarApartados(permissions) || allowPaths
  const allowApartadosCrear = canCrearApartados(permissions)
  const allowApartadosLista = allowApartadosCrear || canEditarApartados(permissions)
  const canEditApartadoAssign = permissions.includes('usuarios:editar')

  const [loading, setLoading] = useState(false)
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [perms, setPerms] = useState([])
  const [apartadosList, setApartadosList] = useState([])
  const [apartadosAdmin, setApartadosAdmin] = useState([])

  const roleOptions = useMemo(() => roles.map((r) => r.name), [roles])

  async function refreshAll() {
    setLoading(true)
    try {
      const reqs = []
      if (allowUsers) reqs.push(apiFetch('/api/users').then((r) => r.json()).then(setUsers))
      if (allowUsers && canEditApartadoAssign) {
        reqs.push(apiFetch('/api/apartados/asignables').then((r) => r.json()).then(setApartadosList))
      }
      if (allowApartadosLista || allowApartadosPaths) {
        reqs.push(apiFetch('/api/apartados').then((r) => r.json()).then(setApartadosAdmin))
      }
      if (allowRoles) {
        reqs.push(apiFetch('/api/roles').then((r) => r.json()).then(setRoles))
        reqs.push(apiFetch('/api/permissions').then((r) => r.json()).then(setPerms))
      }
      await Promise.all(reqs)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const id =
      section === 'rutas'
        ? 'admin-rutas'
        : section === 'apartados'
          ? 'admin-apartados'
          : section === 'usuarios'
            ? 'admin-usuarios'
            : section === 'roles'
              ? 'admin-roles'
              : null
    if (!id) return
    const el = document.getElementById(id)
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [section])

  return (
    <div className="flex-1 overflow-y-auto p-5 scrollbar-thin">
      <div className="w-full space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-extrabold tracking-widest uppercase text-app-text">Administración</h2>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={refreshAll}
            className="px-3 py-2 rounded-card text-[12px] font-bold text-app-text bg-app-surface2 border border-app-border hover:border-app-muted disabled:opacity-60 transition-colors"
          >
            {loading ? 'Actualizando…' : 'Actualizar'}
          </button>
        </div>

        {!allowUsers && !allowRoles && !allowPaths && !allowApartadosPaths && !allowApartadosLista && (
          <div className="bg-app-surface border border-app-border rounded-2xl p-4 text-[13px] text-app-muted">
            Tu usuario no tiene permisos para ver esta sección.
          </div>
        )}

        {allowApartadosPaths && <ApartadoPathsPanel />}

        {allowApartadosLista && (
          <ApartadosPanel
            onSaved={() => refreshAll()}
            initialRows={apartadosAdmin}
            currentUser={currentUser}
            canCreate={allowApartadosCrear}
            canDelete={canGestionarApartados(permissions)}
          />
        )}

        {allowUsers && (
          <UsersPanel
            users={users}
            roleOptions={roleOptions}
            apartadosList={apartadosList}
            canEditApartadoAssign={canEditApartadoAssign}
            onCreated={() => refreshAll()}
            onUpdated={() => refreshAll()}
            onDeactivated={() => refreshAll()}
          />
        )}

        {allowRoles && (
          <RolesPanel
            roles={roles}
            perms={perms}
            onCreated={() => refreshAll()}
            onUpdated={() => refreshAll()}
          />
        )}
      </div>
    </div>
  )
}

function ApartadoPathsPanel() {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [apartados, setApartados] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState({
    nombre: '',
    bandeja_path: '',
    destino_path: '',
    depositos: DEFAULT_DEPOSITOS.map((d) => ({
      ...d,
      categorias: cloneCategorias(d.categorias),
    })),
  })

  async function load() {
    setLoading(true)
    try {
      const r = await apiFetch('/api/apartados')
      const rows = await r.json()
      setApartados(rows || [])
      const first = rows?.[0]?.id ? String(rows[0].id) : ''
      setSelectedId((prev) => prev || first)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const selected = useMemo(
    () => apartados.find((a) => String(a.id) === String(selectedId)),
    [apartados, selectedId],
  )

  useEffect(() => {
    if (!selected) return
    setForm({
      nombre: selected.nombre || '',
      bandeja_path: selected.bandeja_path || '',
      destino_path: selected.destino_path || '',
      depositos: depositosFromApartado(selected),
    })
  }, [selected?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function onSubmit(e) {
    e.preventDefault()
    if (!selected) return
    setSaving(true)
    try {
      await apiFetch(`/api/apartados/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          nombre: (form.nombre || selected.nombre || '').trim(),
          bandeja_path: form.bandeja_path.trim(),
          destino_path: form.destino_path.trim(),
          depositos_config: depositosToPayload(form.depositos, {
            incluirCategorias: true,
          }),
        }),
      })
      toast.success('Rutas actualizadas')
      await load()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section id="admin-rutas" className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-hidden">
      <div className="px-4 py-3 border-b border-app-border">
        <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Rutas de archivos</div>
              </div>
      <form onSubmit={onSubmit} className="p-4 space-y-3">
        <Field label="Apartado">
          <select
            className={inputCls}
            value={selectedId}
            disabled={loading || apartados.length === 0}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {apartados.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nombre} ({a.codigo})
              </option>
            ))}
          </select>
        </Field>

        <Field label="Nombre visible">
          <input
            className={inputCls}
            value={form.nombre}
            onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))}
            disabled={loading || !selected}
            spellCheck={false}
          />
        </Field>

        <Field label="Depósitos (carpetas, Tango y categorías)">
          <div className="space-y-3">
            {form.depositos.map((dep, idx) => (
              <div
                key={idx}
                className="rounded-card bg-app-surface2 border border-app-border p-2 space-y-2"
              >
                <div className="flex flex-wrap sm:flex-nowrap gap-2 items-center">
                  <input
                    className={`${inputCls} flex-1 min-w-[10rem]`}
                    value={dep.carpeta}
                    onChange={(e) =>
                      setForm((f) => {
                        const depositos = [...f.depositos]
                        depositos[idx] = { ...depositos[idx], carpeta: e.target.value }
                        return { ...f, depositos }
                      })
                    }
                    disabled={loading}
                    placeholder="Carpeta (ej. AGROINDUSTRIAS)"
                    spellCheck={false}
                  />
                  <select
                    className={`${inputCls} flex-1 min-w-[9rem] sm:max-w-[12rem]`}
                    value={dep.tango_fuente}
                    onChange={(e) =>
                      setForm((f) => {
                        const depositos = [...f.depositos]
                        depositos[idx] = { ...depositos[idx], tango_fuente: e.target.value }
                        return { ...f, depositos }
                      })
                    }
                    disabled={loading}
                  >
                    {TANGO_FUENTE_OPTIONS.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <input
                    className={`${inputCls} w-full sm:w-28 flex-shrink-0`}
                    value={dep.cod_depositos}
                    onChange={(e) =>
                      setForm((f) => {
                        const depositos = [...f.depositos]
                        depositos[idx] = { ...depositos[idx], cod_depositos: e.target.value }
                        return { ...f, depositos }
                      })
                    }
                    disabled={loading}
                    placeholder="Cód. Tango"
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    disabled={loading || form.depositos.length <= 1}
                    onClick={() =>
                      setForm((f) => ({
                        ...f,
                        depositos: f.depositos.filter((_, i) => i !== idx),
                      }))
                    }
                    className="flex-shrink-0 h-9 w-9 grid place-items-center rounded-card text-red-700 bg-red-50 border border-red-200 hover:border-red-300 disabled:opacity-50 transition-colors"
                    title="Quitar depósito"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
                {form.depositos[idx].categorias && (
                  <div className="pl-1 sm:pl-2 space-y-1.5 border-l-2 border-app-border ml-1">
                    <div className="text-[10px] font-extrabold tracking-widest uppercase text-app-muted">
                      Categorías firmados — {dep.carpeta || `Depósito ${idx + 1}`}
                    </div>
                    {(dep.categorias || []).map((cat, cidx) => (
                      <div key={cidx} className="flex flex-wrap sm:flex-nowrap gap-2 items-center">
                        <input
                          className={`${inputCls} w-full sm:w-36 flex-shrink-0`}
                          value={cat.nombre}
                          onChange={(e) =>
                            setForm((f) => {
                              const depositos = [...f.depositos]
                              const categorias = [...(depositos[idx].categorias || [])]
                              categorias[cidx] = { ...categorias[cidx], nombre: e.target.value }
                              depositos[idx] = { ...depositos[idx], categorias }
                              return { ...f, depositos }
                            })
                          }
                          disabled={loading}
                          placeholder="Nombre (ej. Regulares)"
                          spellCheck={false}
                        />
                        <input
                          className={`${inputCls} flex-1 min-w-[10rem]`}
                          value={cat.keywords}
                          onChange={(e) =>
                            setForm((f) => {
                              const depositos = [...f.depositos]
                              const categorias = [...(depositos[idx].categorias || [])]
                              categorias[cidx] = { ...categorias[cidx], keywords: e.target.value }
                              depositos[idx] = { ...depositos[idx], categorias }
                              return { ...f, depositos }
                            })
                          }
                          disabled={loading}
                          placeholder="Códigos artículo COD_ARTICU (coma, opcional)"
                          spellCheck={false}
                        />
                        <button
                          type="button"
                          disabled={loading || (dep.categorias || []).length <= 1}
                          onClick={() =>
                            setForm((f) => {
                              const depositos = [...f.depositos]
                              depositos[idx] = {
                                ...depositos[idx],
                                categorias: (depositos[idx].categorias || []).filter((_, i) => i !== cidx),
                              }
                              return { ...f, depositos }
                            })
                          }
                          className="flex-shrink-0 h-9 w-9 grid place-items-center rounded-card text-red-700 bg-red-50 border border-red-200 hover:border-red-300 disabled:opacity-50 transition-colors"
                          title="Quitar categoría"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      disabled={loading}
                      onClick={() =>
                        setForm((f) => {
                          const depositos = [...f.depositos]
                          depositos[idx] = {
                            ...depositos[idx],
                            categorias: [...(depositos[idx].categorias || []), { nombre: '', keywords: '' }],
                          }
                          return { ...f, depositos }
                        })
                      }
                      className="px-2 py-1 rounded-card text-[10px] font-bold text-app-text border border-app-border hover:border-app-muted"
                    >
                      + Categoría
                    </button>
                  </div>
                )}
              </div>
            ))}
            <button
              type="button"
              disabled={loading}
              onClick={() =>
                setForm((f) => ({
                  ...f,
                  depositos: [...f.depositos, makeDeposito()],
                }))
              }
              className="px-3 py-1.5 rounded-card text-[11px] font-bold text-app-text border border-app-border hover:border-app-muted"
            >
              + Agregar depósito
            </button>
            <p className="text-[11px] text-app-muted">
              PDFs pendientes en <span className="font-semibold">{'{carpeta}/Sin Firmar/'}</span>. Cada depósito define
              sus propias categorías de destino al firmar (por código de artículo COD_ARTICU).
            </p>
          </div>
        </Field>
        <Field label="Bandeja (PDFs entrantes)">
          <input
            className={inputCls}
            value={form.bandeja_path}
            onChange={(e) => setForm((f) => ({ ...f, bandeja_path: e.target.value }))}
            disabled={loading}
            spellCheck={false}
          />
        </Field>
        <Field label="Destino (firmados)">
          <input
            className={inputCls}
            value={form.destino_path}
            onChange={(e) => setForm((f) => ({ ...f, destino_path: e.target.value }))}
            disabled={loading}
            spellCheck={false}
          />
        </Field>
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <button
            type="button"
            disabled={loading}
            onClick={() => load()}
            className="px-3 py-2 rounded-card text-[12px] font-bold text-app-text bg-app-surface2 border border-app-border hover:border-app-muted disabled:opacity-60"
          >
            Recargar
          </button>
          <button
            type="submit"
            disabled={
              saving ||
              loading ||
              !selected ||
              !(form.nombre || '').trim() ||
              !form.bandeja_path.trim() ||
              !form.destino_path.trim()
            }
            className="px-4 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50"
          >
            {saving ? 'Guardando…' : 'Guardar apartado'}
          </button>
        </div>
      </form>
    </section>
  )
}

const CODIGOS_APARTADO_RESERVADOS = ['transferencias', 'ingresos']

function ApartadosPanel({ onSaved, initialRows, currentUser, canCreate = false, canDelete = false }) {
  const isSuperadmin = currentUser?.role === 'superadmin'
  const [rows, setRows] = useState(initialRows || [])
  const [editNames, setEditNames] = useState({})
  const [editActivo, setEditActivo] = useState({})
  const [savingId, setSavingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    codigo: '',
    nombre: '',
    bandeja_path: '',
    destino_path: '',
    modo_flujo: 'transferencia',
    prefijo: '',
    cod_deposito: '2',
  })

  useEffect(() => {
    const list = initialRows || []
    setRows(list)
    const names = {}
    const activos = {}
    for (const a of list) {
      names[a.id] = a.nombre || ''
      activos[a.id] = a.activo !== false
    }
    setEditNames(names)
    setEditActivo(activos)
  }, [initialRows])

  async function saveApartadoRow(apartado) {
    const nombre = (editNames[apartado.id] ?? apartado.nombre ?? '').trim()
    if (!nombre) {
      toast.error('El nombre no puede estar vacío')
      return
    }
    setSavingId(apartado.id)
    try {
      await apiFetch(`/api/apartados/${apartado.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          nombre,
          activo: editActivo[apartado.id] !== false,
        }),
      })
      toast.success('Apartado actualizado')
      onSaved?.()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSavingId(null)
    }
  }

  async function deleteApartadoRow(apartado) {
    const reservado = CODIGOS_APARTADO_RESERVADOS.includes(apartado.codigo)
    if (reservado && !isSuperadmin) {
      toast.error('Solo superadmin puede eliminar transferencias o ingresos')
      return
    }
    const msg = reservado
      ? `¿Eliminar el apartado reservado «${apartado.codigo}»? La app dejará de usar ese flujo hasta recrearlo.`
      : `¿Eliminar el apartado «${apartado.nombre || apartado.codigo}» de la base de datos?`
    if (!window.confirm(msg)) return
    setDeletingId(apartado.id)
    try {
      await apiFetch(`/api/apartados/${apartado.id}`, { method: 'DELETE' })
      toast.success('Apartado eliminado')
      onSaved?.()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setDeletingId(null)
    }
  }

  async function createApartado(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await apiFetch('/api/apartados', {
        method: 'POST',
        body: JSON.stringify({
          codigo: form.codigo.trim(),
          nombre: form.nombre.trim() || form.codigo.trim(),
          bandeja_path: form.bandeja_path.trim(),
          destino_path: form.destino_path.trim(),
          modo_flujo: form.modo_flujo,
          prefijo: form.prefijo.trim(),
          depositos_config: depositosToPayload(DEFAULT_DEPOSITOS, {
            incluirCategorias: form.modo_flujo === 'transferencia',
          }),
        }),
      })
      toast.success('Apartado creado')
      setForm({
        codigo: '',
        nombre: '',
        bandeja_path: '',
        destino_path: '',
        modo_flujo: 'transferencia',
        prefijo: '',
        cod_deposito: '2',
      })
      onSaved?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section id="admin-apartados" className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-hidden">
      <div className="px-4 py-3 border-b border-app-border">
        <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Apartados</div>
          </div>
      <div className="p-4 space-y-4">
        {canCreate && (
        <form onSubmit={createApartado} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          <Field label="Código (slug)">
            <input className={inputCls} value={form.codigo} onChange={(e) => setForm((f) => ({ ...f, codigo: e.target.value }))} placeholder="AAA_001" spellCheck={false} />
          </Field>
          <Field label="Nombre UI">
            <input className={inputCls} value={form.nombre} onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))} placeholder="Apartado" />
          </Field>
          <Field label="Código depósito Tango">
            <input
              className={inputCls}
              value={form.cod_deposito}
              onChange={(e) => setForm((f) => ({ ...f, cod_deposito: e.target.value }))}
              placeholder="2"
              spellCheck={false}
            />
          </Field>
          <Field label="Prefijo (único, p. ej. s)">
            <input className={inputCls} value={form.prefijo} onChange={(e) => setForm((f) => ({ ...f, prefijo: e.target.value }))} maxLength={8} placeholder="AAA" />
          </Field>
          <Field label="Modo">
            <select className={inputCls} value={form.modo_flujo} onChange={(e) => setForm((f) => ({ ...f, modo_flujo: e.target.value }))}>
              <option value="transferencia">Transferencia (firma en hoja)</option>
              <option value="ingreso">Ingreso (adjuntar escaneos / completar)</option>
            </select>
          </Field>
          <Field label="Bandeja (PDFs entrantes)">
            <input className={inputCls} value={form.bandeja_path} onChange={(e) => setForm((f) => ({ ...f, bandeja_path: e.target.value }))} />
          </Field>
          <Field label="Destino (firmados)">
            <input className={inputCls} value={form.destino_path} onChange={(e) => setForm((f) => ({ ...f, destino_path: e.target.value }))} />
          </Field>
          <div className="sm:col-span-2 lg:col-span-3 flex justify-end">
            <button
              type="submit"
              disabled={saving || !form.codigo.trim() || !form.prefijo.trim() || !form.bandeja_path.trim() || !form.destino_path.trim()}
              className="px-4 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50"
            >
              {saving ? 'Guardando…' : 'Crear apartado'}
            </button>
          </div>
        </form>
        )}

        <div className={canCreate ? 'border-t border-app-border pt-4' : ''}>
          <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted mb-2">
            Apartados existentes ({rows.length})
          </div>
          {rows.length === 0 ? (
            <p className="text-[13px] text-app-muted">No hay apartados cargados.</p>
          ) : (
            <div className="space-y-2">
              {rows.map((a) => {
                const reservado = CODIGOS_APARTADO_RESERVADOS.includes(a.codigo)
                const canDeleteRow = canDelete && (!reservado || isSuperadmin)
                return (
                  <div
                    key={a.id}
                    className="flex flex-col sm:flex-row sm:items-center gap-2 p-3 rounded-card bg-app-surface2 border border-app-border"
                  >
                    <div className="min-w-0 flex-1 grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
                      <div className="sm:col-span-3 text-[12px] font-mono text-app-muted truncate" title={a.codigo}>
                        {a.codigo}
                        {reservado && (
                          <span className="ml-1 text-[10px] uppercase text-amber-600 font-bold">reservado</span>
                        )}
                      </div>
                      <input
                        className={`${inputCls} sm:col-span-4`}
                        value={editNames[a.id] ?? ''}
                        onChange={(e) =>
                          setEditNames((m) => ({ ...m, [a.id]: e.target.value }))
                        }
                        placeholder="Nombre visible"
                        spellCheck={false}
                      />
                      <span className="sm:col-span-2 text-[11px] text-app-muted capitalize">{a.modo_flujo}</span>
                      <label className="sm:col-span-2 flex items-center gap-1.5 text-[12px] text-app-text cursor-pointer">
                        <input
                          type="checkbox"
                          checked={editActivo[a.id] !== false}
                          onChange={(e) =>
                            setEditActivo((m) => ({ ...m, [a.id]: e.target.checked }))
                          }
                          className="rounded border-app-border"
                        />
                        Activo
                      </label>
                    </div>
                    <div className="flex flex-wrap gap-2 sm:flex-shrink-0">
                      <button
                        type="button"
                        disabled={savingId === a.id || deletingId === a.id}
                        onClick={() => saveApartadoRow(a)}
                        className="px-3 py-1.5 rounded-card text-[11px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50"
                      >
                        {savingId === a.id ? 'Guardando…' : 'Guardar'}
                      </button>
                      {canDeleteRow && (
                      <button
                        type="button"
                        disabled={savingId === a.id || deletingId === a.id}
                        title={deletingId === a.id ? 'Eliminando…' : 'Eliminar apartado de la base'}
                        onClick={() => deleteApartadoRow(a)}
                        className="h-9 w-9 grid place-items-center rounded-card text-red-700 bg-red-50 border border-red-200 hover:border-red-300 disabled:opacity-50 transition-colors"
                      >
                        <Trash2 size={16} />
                      </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          <p className="text-[11px] text-app-muted mt-2">
            {canCreate
              ? 'El código y las rutas detalladas se editan en «Rutas de archivos». Como superadmin podés eliminar apartados reservados.'
              : 'El código y las rutas se editan en «Rutas de archivos». Solo podés modificar apartados asignados a tu usuario.'}
          </p>
        </div>
      </div>
    </section>
  )
}

function UsersPanel({ users, roleOptions, apartadosList = [], canEditApartadoAssign, onCreated, onUpdated, onDeactivated }) {
  const [form, setForm] = useState({ username: '', password: '', role: roleOptions[0] || '' })
  const [createApartados, setCreateApartados] = useState(new Set())
  const [saving, setSaving] = useState(false)
  const [showCreatePass, setShowCreatePass] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState('')

  useEffect(() => {
    setForm((f) => ({ ...f, role: f.role || roleOptions[0] || '' }))
  }, [roleOptions])

  useEffect(() => {
    if (!selectedUserId && users?.[0]?.id) setSelectedUserId(String(users[0].id))
  }, [users, selectedUserId])

  const selectedUser = useMemo(
    () => users.find((u) => String(u.id) === String(selectedUserId)),
    [users, selectedUserId],
  )

  async function createUser(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await apiFetch('/api/users', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          ...(canEditApartadoAssign ? { apartado_ids: [...createApartados] } : {}),
        }),
      })
      toast.success('Usuario creado')
      setForm({ username: '', password: '', role: roleOptions[0] || '' })
      setCreateApartados(new Set())
      onCreated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  async function updateUser(userId, patch) {
    setSaving(true)
    try {
      await apiFetch(`/api/users/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      })
      toast.success('Usuario actualizado')
      onUpdated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  async function deactivateUser(userId) {
    if (!confirm('¿Desactivar este usuario?')) return
    setSaving(true)
    try {
      await apiFetch(`/api/users/${userId}`, { method: 'DELETE' })
      toast.success('Usuario desactivado')
      onDeactivated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  async function purgeUser(user) {
    const ok = window.prompt(`Escribí el usuario para eliminar definitivamente: ${user.username}`, '')
    if ((ok || '').trim() !== user.username) return
    setSaving(true)
    try {
      await apiFetch(`/api/users/${user.id}/purge`, { method: 'DELETE' })
      toast.success('Usuario eliminado')
      onDeactivated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section id="admin-usuarios" className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-hidden">
      <div className="px-4 py-3 border-b border-app-border flex items-center justify-between">
        <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Usuarios</div>
        <div className="text-[12px] text-app-muted font-mono">{users.length} total</div>
      </div>

      <div className="p-4 space-y-4">
        <form onSubmit={createUser} className="bg-app-surface2/40 border border-app-border rounded-2xl p-3.5 w-full">
          <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted mb-2">Crear usuario</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <Field label="Usuario">
              <input
                className={inputCls}
                value={form.username}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              />
            </Field>
            <Field label="Contraseña">
              <PasswordInput
                value={form.password}
                show={showCreatePass}
                onToggle={() => setShowCreatePass((s) => !s)}
                onChange={(v) => setForm((f) => ({ ...f, password: v }))}
              />
            </Field>
            <Field label="Rol">
              <select className={inputCls} value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                {roleOptions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </Field>
            {canEditApartadoAssign && (
              <div className="sm:col-span-2 space-y-1">
                <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted">Apartados</div>
                <div className="flex flex-wrap gap-2">
                  {(apartadosList || []).map((a) => (
                    <label
                      key={a.id}
                      className="flex items-center gap-1.5 text-[12px] text-app-text border border-app-border rounded-lg px-2 py-1 bg-app-bg"
                    >
                      <input
                        type="checkbox"
                        checked={createApartados.has(a.id)}
                        onChange={() =>
                          setCreateApartados((s) => {
                            const n = new Set(s)
                            if (n.has(a.id)) n.delete(a.id)
                            else n.add(a.id)
                            return n
                          })
                        }
                        disabled={saving}
                      />
                      <span title={a.codigo}>{apartadoAssignLabel(a)}</span>
                    </label>
                  ))}
                  {apartadosList.length === 0 && (
                    <span className="text-[12px] text-app-muted">No hay apartados disponibles.</span>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className="flex justify-end mt-3">
            <button
              type="submit"
              disabled={saving || !form.username.trim() || !form.password || !form.role}
              className="px-4 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50 transition-colors"
            >
              Crear
            </button>
          </div>
        </form>

        <div className="border border-app-border rounded-2xl overflow-hidden">
          <div className="px-3 py-2 border-b border-app-border bg-app-surface2/30 text-[11px] font-extrabold tracking-widest uppercase text-app-muted">
            Editar usuario
          </div>
          <div className="p-3 space-y-3">
            <Field label="Seleccionar usuario">
              <select
                className={inputCls}
                value={selectedUserId}
                disabled={saving || users.length === 0}
                onChange={(e) => setSelectedUserId(e.target.value)}
              >
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username} ({u.role})
                  </option>
                ))}
              </select>
            </Field>
            {selectedUser ? (
              <div className="border border-app-border rounded-xl overflow-hidden">
                <UserRow
                  user={selectedUser}
                  roleOptions={roleOptions}
                  apartadosList={apartadosList}
                  canEditApartadoAssign={canEditApartadoAssign}
                  disabled={saving}
                  onUpdate={(patch) => updateUser(selectedUser.id, patch)}
                  onDeactivate={() => deactivateUser(selectedUser.id)}
                  onPurge={() => purgeUser(selectedUser)}
                />
              </div>
            ) : (
              <div className="p-3 text-[13px] text-app-muted">Sin usuarios para editar.</div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function UserRow({ user, roleOptions, apartadosList = [], canEditApartadoAssign, disabled, onUpdate, onDeactivate, onPurge }) {
  const [role, setRole] = useState(user.role || '')
  const [password, setPassword] = useState('')
  const [showNewPass, setShowNewPass] = useState(false)
  const [apartadoIds, setApartadoIds] = useState(new Set((user.apartado_ids || []).map(Number)))

  useEffect(() => {
    setApartadoIds(new Set((user.apartado_ids || []).map(Number)))
  }, [user.id, (user.apartado_ids || []).join(',')])

  const superUser = user.role === 'superadmin'
  const dirtyAp =
    canEditApartadoAssign &&
    !superUser &&
    (user.apartado_ids || []).slice().sort().join() !==
      [...apartadoIds].sort().join()
  const dirty = role !== (user.role || '') || !!password || dirtyAp

  function toggleAp(id) {
    setApartadoIds((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  return (
    <div className="p-3">
      <div className="min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 text-[13px] font-semibold text-app-text truncate">
            {user.username}{' '}
            <span className={['text-[11px] font-mono', user.is_active ? 'text-app-muted' : 'text-red-600'].join(' ')}>
              {user.is_active ? 'activo' : 'inactivo'}
            </span>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              disabled={disabled || !dirty}
              onClick={() => {
                const patch = { role }
                if (password) patch.password = password
                if (dirtyAp && canEditApartadoAssign && !superUser) {
                  patch.apartado_ids = [...apartadoIds]
                }
                onUpdate(patch)
                setPassword('')
              }}
              className="h-9 w-9 grid place-items-center rounded-card text-app-text bg-app-surface2 border border-app-border hover:border-app-muted disabled:opacity-50 transition-colors"
              title="Guardar cambios"
            >
              <Save size={16} />
            </button>
            <button
              type="button"
              disabled={disabled || !user.is_active}
              onClick={onDeactivate}
              className="h-9 w-9 grid place-items-center rounded-card text-red-700 bg-red-50 border border-red-200 hover:border-red-300 disabled:opacity-50 transition-colors"
              title="Desactivar usuario"
            >
              <UserX size={16} />
            </button>
            <button
              type="button"
              disabled={disabled || user.username === 'superadmin'}
              onClick={onPurge}
              className="h-9 w-9 grid place-items-center rounded-card text-red-700 bg-red-50 border border-red-200 hover:border-red-300 disabled:opacity-50 transition-colors"
              title="Eliminar definitivamente"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2 items-end">
          <Field label="Usuario">
            <input className={inputCls} value={user.username || ''} disabled readOnly />
          </Field>
          <Field label="Rol">
            <select className={inputCls} value={role} disabled={disabled} onChange={(e) => setRole(e.target.value)}>
              {roleOptions.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </Field>

          <Field label="Nueva contraseña (opcional)">
            <PasswordInput
              value={password}
              show={showNewPass}
              disabled={disabled}
              placeholder="(sin cambios)"
              onToggle={() => setShowNewPass((s) => !s)}
              onChange={(v) => setPassword(v)}
            />
          </Field>

          {canEditApartadoAssign && (
            <div className="sm:col-span-2 space-y-1.5">
              <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted">Apartados</div>
              {superUser ? (
                <p className="text-[12px] text-app-muted">Superadmin: acceso a todos (sin asignación).</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {(apartadosList || []).map((a) => (
                    <label
                      key={a.id}
                      className="flex items-center gap-1.5 text-[12px] text-app-text border border-app-border rounded-lg px-2 py-1 bg-app-bg"
                    >
                      <input
                        type="checkbox"
                        checked={apartadoIds.has(a.id)}
                        onChange={() => toggleAp(a.id)}
                        disabled={disabled}
                      />
                      <span title={a.codigo}>{apartadoAssignLabel(a)}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

function RolesPanel({ roles, perms, onCreated, onUpdated }) {
  const [mode, setMode] = useState('edit')
  const [selectedRoleId, setSelectedRoleId] = useState(roles[0]?.id || '')
  const [saving, setSaving] = useState(false)

  const selectedRole = useMemo(() => roles.find((r) => String(r.id) === String(selectedRoleId)), [roles, selectedRoleId])

  useEffect(() => {
    if (!selectedRoleId && roles[0]?.id) setSelectedRoleId(roles[0].id)
  }, [roles, selectedRoleId])

  async function createRole(payload) {
    setSaving(true)
    try {
      await apiFetch('/api/roles', { method: 'POST', body: JSON.stringify(payload) })
      toast.success('Rol creado')
      onCreated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  async function updateRole(roleId, payload) {
    setSaving(true)
    try {
      await apiFetch(`/api/roles/${roleId}`, { method: 'PUT', body: JSON.stringify(payload) })
      toast.success('Rol actualizado')
      onUpdated?.()
    } catch (e2) {
      toast.error(e2.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section id="admin-roles" className="bg-app-surface border border-app-border rounded-2xl shadow-card overflow-hidden">
      <div className="px-4 py-3 border-b border-app-border flex items-center justify-between gap-3">
        <div className="text-[12px] font-extrabold tracking-widest uppercase text-app-text">Roles y permisos</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMode('edit')}
            className={pillCls(mode === 'edit')}
          >
            Editar
          </button>
          <button
            type="button"
            onClick={() => setMode('create')}
            className={pillCls(mode === 'create')}
          >
            Crear
          </button>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
        <div className="border border-app-border rounded-2xl overflow-hidden">
          <div className="px-3 py-2 border-b border-app-border bg-app-surface2/30 text-[11px] font-extrabold tracking-widest uppercase text-app-muted">
            Roles ({roles.length})
          </div>
          <div className="max-h-[360px] overflow-y-auto scrollbar-thin divide-y divide-app-border">
            {roles.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelectedRoleId(r.id)}
                className={[
                  'w-full text-left px-3 py-2.5 transition-colors',
                  String(selectedRoleId) === String(r.id) ? 'bg-accent/10' : 'hover:bg-app-surface2/60',
                ].join(' ')}
              >
                <div className="text-[13px] font-semibold text-app-text truncate">{r.name}</div>
                <div className="text-[11px] text-app-muted truncate">{r.description || '—'}</div>
              </button>
            ))}
            {roles.length === 0 && <div className="p-4 text-[13px] text-app-muted">Sin roles.</div>}
          </div>
        </div>

        {mode === 'create' ? (
          <RoleEditor
            title="Crear rol"
            perms={perms}
            saving={saving}
            initial={{ name: '', description: '', permissions: [] }}
            onSave={createRole}
          />
        ) : (
          <RoleEditor
            title="Editar rol"
            perms={perms}
            saving={saving}
            initial={{
              name: selectedRole?.name || '',
              description: selectedRole?.description || '',
              permissions: selectedRole?.permissions || [],
            }}
            onSave={(payload) => updateRole(selectedRoleId, payload)}
            disabled={!selectedRoleId}
            hideName
          />
        )}
      </div>
    </section>
  )
}

function RoleEditor({ title, initial, perms, onSave, saving, disabled, hideName }) {
  const [name, setName] = useState(initial.name || '')
  const [description, setDescription] = useState(initial.description || '')
  const [selected, setSelected] = useState(new Set(initial.permissions || []))

  useEffect(() => {
    setName(initial.name || '')
    setDescription(initial.description || '')
    setSelected(new Set(initial.permissions || []))
  }, [initial.name, initial.description, (initial.permissions || []).join('|')])

  const grouped = useMemo(() => {
    const map = new Map()
    for (const p of perms) {
      const key = p.resource || 'otros'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(p)
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0], 'es'))
  }, [perms])

  function toggle(name2) {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(name2)) next.delete(name2)
      else next.add(name2)
      return next
    })
  }

  return (
    <div className={['border border-app-border rounded-2xl p-3.5', disabled ? 'opacity-60 pointer-events-none' : ''].join(' ')}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted">{title}</div>
        <div className="text-[11px] text-app-muted font-mono">{selected.size} permisos</div>
      </div>

      {!hideName && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-2.5">
          <Field label="Nombre">
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Descripción">
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
      )}

      {hideName && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-2.5">
          <Field label="Rol">
            <div className="text-[13px] text-app-text font-mono px-3 py-2 rounded-lg border border-app-border bg-app-bg">
              {name || '—'}
            </div>
          </Field>
          <Field label="Descripción">
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
      )}

      <div className="mt-3 border border-app-border rounded-2xl overflow-hidden">
        <div className="max-h-[280px] overflow-y-auto scrollbar-thin divide-y divide-app-border">
          {grouped.map(([resource, list]) => (
            <div key={resource} className="p-3">
              <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted mb-2">{resource}</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {list.map((p) => (
                  <label key={p.name} className="flex items-start gap-2 text-[12px] text-app-text select-none">
                    <input type="checkbox" checked={selected.has(p.name)} onChange={() => toggle(p.name)} />
                    <span className="min-w-0">
                      <span className="font-mono">{p.name}</span>
                      <span className="text-app-muted"> — {p.description || '—'}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          ))}
          {perms.length === 0 && <div className="p-4 text-[13px] text-app-muted">Sin permisos cargados.</div>}
        </div>
      </div>

      <div className="flex justify-end mt-3">
        <button
          type="button"
          disabled={saving || (!hideName && !name.trim())}
          onClick={() => onSave({ ...(hideName ? {} : { name: name.trim() }), description: description.trim(), permissions: Array.from(selected) })}
          className="px-4 py-2 rounded-card text-[12px] font-bold text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50 transition-colors"
        >
          Guardar
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-extrabold tracking-widest uppercase text-app-muted">{label}</div>
      {children}
    </div>
  )
}

const inputCls =
  'w-full text-[13px] px-3 py-2 rounded-lg border border-app-border bg-app-bg text-app-text placeholder:text-app-muted focus:outline-none focus:border-accent-dark transition-colors'

function PasswordInput({ value, onChange, show, onToggle, disabled, placeholder }) {
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        className={[inputCls, 'pr-10'].join(' ')}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="new-password"
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        onClick={onToggle}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md text-app-muted hover:text-app-text hover:bg-app-surface2 transition-colors"
        title={show ? 'Ocultar' : 'Mostrar'}
        tabIndex={-1}
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  )
}

function pillCls(active) {
  return [
    'px-3 py-1.5 rounded-full border text-[11px] font-extrabold tracking-widest uppercase transition-colors',
    active ? 'bg-accent/10 border-accent-dark text-accent-dark' : 'bg-transparent border-app-border text-app-muted hover:bg-app-surface2',
  ].join(' ')
}

