-- Migration: 058_message_media_support.sql
-- Description: Add media_path and mime_type to messages table
ALTER TABLE messages ADD COLUMN media_path TEXT;
ALTER TABLE messages ADD COLUMN mime_type TEXT;
