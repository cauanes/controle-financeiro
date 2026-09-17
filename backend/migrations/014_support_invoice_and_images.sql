-- Migration 014: Add support for image and document messages and invoice OCR ingestion

ALTER TABLE conversation_messages DROP CONSTRAINT IF EXISTS conversation_messages_kind_check;
ALTER TABLE conversation_messages ADD CONSTRAINT conversation_messages_kind_check 
  CHECK(kind IN ('TEXT', 'AUDIO', 'IMAGE', 'DOCUMENT'));

ALTER TABLE conversation_messages DROP CONSTRAINT IF EXISTS conversation_messages_processing_status_check;
ALTER TABLE conversation_messages ADD CONSTRAINT conversation_messages_processing_status_check 
  CHECK(processing_status IN ('RECEIVED', 'TRANSCRIBING', 'PROCESSING_OCR', 'READY', 'PROCESSED', 'FAILED'));

ALTER TABLE transaction_sources DROP CONSTRAINT IF EXISTS transaction_sources_source_type_check;
ALTER TABLE transaction_sources ADD CONSTRAINT transaction_sources_source_type_check 
  CHECK(source_type IN ('MANUAL', 'WHATSAPP', 'OFX', 'CSV', 'XLSX', 'PROVIDER', 'CONVERSATION', 'INVOICE_OCR'));
