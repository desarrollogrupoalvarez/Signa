-- Ruta absoluta del PDF indexado (pendiente o firmado)
-- Ejecutar: psql -d remitos -f migrations/002_comprobante_tango_ruta.sql

ALTER TABLE comprobante_tango
  ADD COLUMN IF NOT EXISTS ruta TEXT;
