-- Áreas / Depósitos que agrupan apartados
-- Ejecutar: psql -d remitos -f migrations/004_areas.sql

CREATE TABLE IF NOT EXISTS areas (
  id SERIAL PRIMARY KEY,
  codigo VARCHAR(64) NOT NULL UNIQUE,
  nombre VARCHAR(200) NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  orden INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_area (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  area_id INTEGER NOT NULL REFERENCES areas(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, area_id)
);

CREATE INDEX IF NOT EXISTS idx_user_area_area ON user_area(area_id);

ALTER TABLE apartados ADD COLUMN IF NOT EXISTS area_id INTEGER REFERENCES areas(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_apartados_area ON apartados(area_id);
