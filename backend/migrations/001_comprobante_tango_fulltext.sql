-- Fulltext search sobre contenido de PDFs en comprobante_tango
-- Ejecutar: psql -d remitos -f migrations/001_comprobante_tango_fulltext.sql

ALTER TABLE comprobante_tango
  ADD COLUMN IF NOT EXISTS texto_contenido TEXT;

ALTER TABLE comprobante_tango
  ADD COLUMN IF NOT EXISTS texto_search TSVECTOR
  GENERATED ALWAYS AS (to_tsvector('spanish', coalesce(texto_contenido, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_comprobante_tango_texto_search
  ON comprobante_tango USING GIN (texto_search);
