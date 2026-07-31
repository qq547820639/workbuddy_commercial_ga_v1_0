-- WorkBuddy 邮件归档表
CREATE TABLE IF NOT EXISTS mail_archive (
  message_id VARCHAR(255) PRIMARY KEY,
  subject TEXT,
  from_name VARCHAR(255),
  from_mail VARCHAR(255),
  received_at DATETIME,
  body_preview TEXT,
  labels VARCHAR(500),
  processing_status VARCHAR(32) DEFAULT 'NEW',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 配置表
CREATE TABLE IF NOT EXISTS config (
  config_key VARCHAR(64) PRIMARY KEY,
  config_value TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Worker 运行状态（单行表，id 固定为 1）
CREATE TABLE IF NOT EXISTS worker_status (
  id INT PRIMARY KEY DEFAULT 1,
  is_running BOOLEAN DEFAULT FALSE,
  last_poll_at DATETIME,
  total_notified INT DEFAULT 0,
  error_count INT DEFAULT 0,
  CHECK (id = 1)
);

-- 运行日志表
CREATE TABLE IF NOT EXISTS worker_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  log_level VARCHAR(16) DEFAULT 'INFO',
  message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 预填配置默认值
INSERT INTO config (config_key, config_value) VALUES
  ('NOTIFY_CHAT_ID', 'oc_716f4d911915d3e3d91a053e1a80f4a8'),
  ('POLL_INTERVAL', '60'),
  ('MAX_RECONNECT_BACKOFF', '300')
ON DUPLICATE KEY UPDATE config_value = config_value;

-- 预填 worker_status 单行
INSERT INTO worker_status (id, is_running) VALUES (1, FALSE)
ON DUPLICATE KEY UPDATE id = id;
