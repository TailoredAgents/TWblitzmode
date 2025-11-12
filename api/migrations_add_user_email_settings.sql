-- Add sender_email and sender_name columns to users table
ALTER TABLE users ADD COLUMN sender_email TEXT;
ALTER TABLE users ADD COLUMN sender_name TEXT;