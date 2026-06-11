-- Permisos por vista + carpetas digitalizados por rol
-- Ejecutar: psql -d remitos -f migrations/003_permisos_por_vista.sql

CREATE TABLE IF NOT EXISTS role_digitalizado_carpetas (
  role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  apartado_id INTEGER NOT NULL REFERENCES apartados(id) ON DELETE CASCADE,
  carpeta     VARCHAR(128) NOT NULL,
  categoria   VARCHAR(128) NOT NULL DEFAULT '',
  PRIMARY KEY (role_id, apartado_id, carpeta, categoria)
);

CREATE INDEX IF NOT EXISTS idx_role_digitalizado_carpetas_role
  ON role_digitalizado_carpetas(role_id);
