/** Convierte ruta Windows/UNC/POSIX a URL file:// (vista previa local en el visor). */
export function toFileUrl(path) {
  if (!path) return null
  const s = String(path).trim()
  if (!s) return null
  if (s.startsWith('\\\\')) {
    return `file://///${s.slice(2).replace(/\\/g, '/')}`
  }
  if (/^[A-Za-z]:[\\/]/.test(s)) {
    return `file:///${s.replace(/\\/g, '/')}`
  }
  const posix = s.replace(/\\/g, '/')
  if (posix.startsWith('/')) {
    return `file://${posix}`
  }
  return `file:///${posix}`
}

/** Ruta preferida para mostrar/copiar (UNC en Linux con mapeo, si no servidor). */
export function preferredClientPath(data, mode = 'select') {
  if (!data) return ''
  if (mode === 'folder') {
    return (
      data.client_path ||
      data.client_folder ||
      data.unc_folder ||
      data.server_path ||
      data.server_folder ||
      ''
    )
  }
  return (
    data.client_path ||
    data.client_file ||
    data.unc_file ||
    data.server_path ||
    data.server_file ||
    data.path ||
    ''
  )
}

/** Copia síncrona (funciona con clic del usuario en el mismo tick). */
export function copyTextSync(text) {
  if (!text) return false
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.cssText =
      'position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent;'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export async function copyText(text) {
  if (!text) return false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* ignore */
  }
  return copyTextSync(text)
}

function fetchSignedFilePath(nombre, apiFetch) {
  return apiFetch(`/api/firmados/path?n=${encodeURIComponent(nombre)}`)
    .then((res) => res.json())
    .then((data) => {
      const filePath = preferredClientPath(data, 'select')
      if (!filePath) throw new Error('No se obtuvo ruta del archivo')
      return filePath
    })
}

/** ClipboardItem permite copiar tras un fetch si write() se invoca en el mismo clic. */
function copyViaClipboardItem(textPromise) {
  if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
    return Promise.reject(new Error('clipboard-item-unavailable'))
  }
  const blobPromise = textPromise.then(
    (text) => new Blob([text], { type: 'text/plain' }),
  )
  return navigator.clipboard.write([
    new ClipboardItem({ 'text/plain': blobPromise }),
  ])
}

function showCopyPathDialog(filePath, toast) {
  const overlay = document.createElement('div')
  overlay.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px'

  const box = document.createElement('div')
  box.style.cssText =
    'background:#fff;color:#111;border-radius:10px;padding:16px;max-width:min(560px,96vw);width:100%;box-shadow:0 8px 32px rgba(0,0,0,.2)'

  const label = document.createElement('p')
  label.textContent = 'Ruta del archivo'
  label.style.cssText = 'margin:0 0 8px;font-size:14px;font-weight:600'

  const hint = document.createElement('p')
  hint.textContent = 'Usá el botón Copiar o Ctrl+C con el texto seleccionado.'
  hint.style.cssText = 'margin:0 0 8px;font-size:12px;color:#555'

  const input = document.createElement('input')
  input.value = filePath
  input.readOnly = true
  input.style.cssText =
    'width:100%;box-sizing:border-box;font-family:Consolas,monospace;font-size:12px;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:12px'

  const row = document.createElement('div')
  row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end'

  const copyBtn = document.createElement('button')
  copyBtn.type = 'button'
  copyBtn.textContent = 'Copiar'
  copyBtn.style.cssText =
    'padding:8px 14px;border:none;border-radius:6px;background:#0d9488;color:#fff;font-weight:600;cursor:pointer'

  const closeBtn = document.createElement('button')
  closeBtn.type = 'button'
  closeBtn.textContent = 'Cerrar'
  closeBtn.style.cssText =
    'padding:8px 14px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer'

  function close() {
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay)
  }

  copyBtn.onclick = () => {
    input.focus()
    input.select()
    if (copyTextSync(filePath)) {
      toast.success('Ruta copiada al portapapeles')
      close()
    } else {
      toast.message('Seleccioná el texto y usá Ctrl+C')
    }
  }
  closeBtn.onclick = close
  overlay.onclick = (e) => {
    if (e.target === overlay) close()
  }

  row.append(copyBtn, closeBtn)
  box.append(label, hint, input, row)
  overlay.appendChild(box)
  document.body.appendChild(overlay)
  input.focus()
  input.select()
}

/**
 * Copia la ruta del archivo firmado al portapapeles.
 * write() con ClipboardItem debe llamarse en el mismo clic (antes del await del fetch).
 */
export function copySignedFilePath(nombre, { apiFetch, toast } = {}) {
  if (!nombre || !apiFetch || !toast) return

  const pathPromise = fetchSignedFilePath(nombre, apiFetch)

  copyViaClipboardItem(pathPromise)
    .then(() => toast.success('Ruta copiada al portapapeles'))
    .catch(() => {
      pathPromise
        .then((filePath) => {
          if (copyTextSync(filePath)) {
            toast.success('Ruta copiada al portapapeles')
            return
          }
          showCopyPathDialog(filePath, toast)
        })
        .catch((e) =>
          toast.message(e.message || 'No se pudo obtener la ruta del archivo'),
        )
    })
}
