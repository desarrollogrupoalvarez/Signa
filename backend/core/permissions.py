"""Catálogo de permisos por vista."""

# Pendientes
PERM_PENDIENTES_VER = "pendientes:ver"
PERM_PENDIENTES_VER_TODOS = "pendientes:ver_todos"
PERM_PENDIENTES_FIRMAR = "pendientes:firmar"

# Digitalizados
PERM_DIGITALIZADOS_VER = "digitalizados:ver"
PERM_DIGITALIZADOS_VER_TODO = "digitalizados:ver_todo"
PERM_DIGITALIZADOS_VER_ARCHIVO = "digitalizados:ver_archivo"

# Registros
PERM_REGISTROS_VER = "registros:ver"

# Roles
PERM_ROLES_ELIMINAR = "roles:eliminar"

RESERVED_ROLE_NAMES = frozenset({"superadmin", "firmante", "consulta", "administrador"})

PERMISSIONS = [
    (PERM_PENDIENTES_VER, "Ver vista Pendientes y documentos propios", "pendientes", "ver"),
    (PERM_PENDIENTES_VER_TODOS, "Ver documentos pendientes de todos los usuarios", "pendientes", "ver_todos"),
    (PERM_PENDIENTES_FIRMAR, "Firmar y editar documentos pendientes", "pendientes", "firmar"),
    (PERM_DIGITALIZADOS_VER, "Ver vista Digitalizados", "digitalizados", "ver"),
    (PERM_DIGITALIZADOS_VER_TODO, "Ver todas las carpetas en Digitalizados", "digitalizados", "ver_todo"),
    (PERM_DIGITALIZADOS_VER_ARCHIVO, "Abrir y descargar archivos digitalizados", "digitalizados", "ver_archivo"),
    (PERM_REGISTROS_VER, "Ver vista Registros", "registros", "ver"),
    ("usuarios:listar", "Listar usuarios del sistema", "usuarios", "listar"),
    ("usuarios:crear", "Crear un nuevo usuario", "usuarios", "crear"),
    ("usuarios:editar", "Editar datos de un usuario", "usuarios", "editar"),
    ("usuarios:eliminar", "Desactivar un usuario", "usuarios", "eliminar"),
    ("roles:listar", "Listar roles disponibles", "roles", "listar"),
    ("roles:gestionar", "Crear / editar roles", "roles", "gestionar"),
    (PERM_ROLES_ELIMINAR, "Eliminar roles personalizados", "roles", "eliminar"),
    ("configuracion:rutas", "Gestionar rutas de archivos (bandeja, transferencias)", "configuracion", "rutas"),
    ("apartados:gestionar", "Acceso total a apartados (crear, editar todos, eliminar)", "apartados", "gestionar"),
    ("apartados:crear", "Dar de alta apartados nuevos", "apartados", "crear"),
    ("apartados:editar", "Editar configuración de apartados asignados al usuario", "apartados", "editar"),
]

OLD_TO_NEW_PERMISSION = {
    "documentos:listar": PERM_PENDIENTES_VER,
    "documentos:firmar": PERM_PENDIENTES_FIRMAR,
    "firmados:listar": PERM_DIGITALIZADOS_VER,
    "firmados:ver": PERM_DIGITALIZADOS_VER_ARCHIVO,
    "metricas:ver": PERM_REGISTROS_VER,
}

LEGACY_PERMISSION_NAMES = frozenset(OLD_TO_NEW_PERMISSION.keys())


def effective_permissions(perm_names: list[str]) -> list[str]:
    """Excluye permisos legacy ya reemplazados por los de vista."""
    return [n for n in (perm_names or []) if n not in LEGACY_PERMISSION_NAMES]


def user_puede_ver_todos_pendientes(perms: set[str]) -> bool:
    return PERM_PENDIENTES_VER_TODOS in perms


def user_puede_ver_todo_digitalizado(perms: set[str]) -> bool:
    return PERM_DIGITALIZADOS_VER_TODO in perms
