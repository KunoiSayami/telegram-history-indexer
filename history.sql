/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping structure for table deleted_message
CREATE TABLE IF NOT EXISTS `deleted_message` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `message_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table document_index
CREATE TABLE IF NOT EXISTS `document_index` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `forward_from` bigint(20) DEFAULT NULL,
  `message_id` int(11) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `type` enum('document','photo','video','animation','voice') CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `file_id` varchar(80) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `file_ref` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table dup_check
CREATE TABLE IF NOT EXISTS `dup_check` (
  `hash` varchar(64) COLLATE utf8_unicode_ci NOT NULL,
  PRIMARY KEY (`hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table edit_history
CREATE TABLE IF NOT EXISTS `edit_history` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `message_id` int(10) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table group_history
CREATE TABLE IF NOT EXISTS `group_history` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `user_id` int(11) NOT NULL,
  `message_id` int(11) NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table index
CREATE TABLE IF NOT EXISTS `index` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `forward_from` bigint(20) DEFAULT NULL,
  `message_id` int(10) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table indexed_dialogs
CREATE TABLE IF NOT EXISTS `indexed_dialogs` (
  `user_id` bigint(20) NOT NULL,
  `started_indexed` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `indexed` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `last_message_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table media_cache
CREATE TABLE IF NOT EXISTS `media_cache` (
  `id` varchar(64) COLLATE utf8_unicode_ci NOT NULL,
  `file_id` varchar(64) COLLATE utf8_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table media_store
CREATE TABLE IF NOT EXISTS `media_store` (
  `file_id` varchar(80) NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `body` mediumblob NOT NULL,
  PRIMARY KEY (`file_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Dumping structure for table online_records
CREATE TABLE IF NOT EXISTS `online_records` (
  `user_id` int(10) unsigned NOT NULL,
  `online_timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `is_offline` char(1) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'N'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table pending_mapping
CREATE TABLE IF NOT EXISTS `pending_mapping` (
  `file_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`file_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table query_result_cache
CREATE TABLE IF NOT EXISTS `query_result_cache` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `hash` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `cache_hash` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `type` enum('document','photo','video','animation','voice','') CHARACTER SET utf8 COLLATE utf8_unicode_ci DEFAULT NULL,
  `args` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `cache` mediumtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `cache_timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `step` int(10) unsigned NOT NULL DEFAULT '0',
  `max_count` int(10) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table settings
CREATE TABLE IF NOT EXISTS `settings` (
  `user_id` bigint(20) NOT NULL COMMENT 'reserved',
  `force_query` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_user` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_group` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `show_info_detail` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `except_forward` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `except_bot` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `use_specify_user_id` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `use_specify_chat_id` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `specify_user_id` bigint(20) NOT NULL DEFAULT '0',
  `specify_chat_id` bigint(20) NOT NULL DEFAULT '0',
  `page_limit` tinyint(4) NOT NULL DEFAULT '5',
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table username_history
CREATE TABLE IF NOT EXISTS `username_history` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `username` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table user_history
CREATE TABLE IF NOT EXISTS `user_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `first_name` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `full_name` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT '',
  `photo_id` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci DEFAULT NULL COMMENT 'big_file_id',
  `last_update` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table user_index
CREATE TABLE IF NOT EXISTS `user_index` (
  `user_id` bigint(20) NOT NULL,
  `peer_id` bigint(20) DEFAULT NULL,
  `last_refresh` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Record getuser',
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `first_name` varchar(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_group` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `is_bot` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `photo_id` varchar(64) COLLATE utf8_unicode_ci DEFAULT NULL,
  `hash` varchar(64) COLLATE utf8_unicode_ci NOT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
