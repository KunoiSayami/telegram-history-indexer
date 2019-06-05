/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping structure for table document_index
DROP TABLE IF EXISTS `document_index`;
CREATE TABLE IF NOT EXISTS `document_index` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `forward_from` bigint(20) DEFAULT NULL,
  `message_id` int(11) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `type` enum('document','photo','video','animation','voice') CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `file_id` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table dup_check
DROP TABLE IF EXISTS `dup_check`;
CREATE TABLE IF NOT EXISTS `dup_check` (
  `hash` varchar(64) COLLATE utf8_unicode_ci NOT NULL,
  PRIMARY KEY (`hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table edit_history
DROP TABLE IF EXISTS `edit_history`;
CREATE TABLE IF NOT EXISTS `edit_history` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `message_id` int(10) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table index
DROP TABLE IF EXISTS `index`;
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
DROP TABLE IF EXISTS `indexed_dialogs`;
CREATE TABLE IF NOT EXISTS `indexed_dialogs` (
  `user_id` bigint(20) NOT NULL,
  `started_indexed` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `indexed` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `last_message_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table media_cache
DROP TABLE IF EXISTS `media_cache`;
CREATE TABLE IF NOT EXISTS `media_cache` (
  `id` varchar(64) COLLATE utf8_unicode_ci NOT NULL,
  `file_id` varchar(64) COLLATE utf8_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table query_history
DROP TABLE IF EXISTS `query_history`;
CREATE TABLE IF NOT EXISTS `query_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `type` enum('document','photo','video','animation','voice') CHARACTER SET utf8 COLLATE utf8_unicode_ci DEFAULT NULL,
  `args` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hash` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `max_count` int(10) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table search_history
DROP TABLE IF EXISTS `search_history`;
CREATE TABLE IF NOT EXISTS `search_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `args` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `max_count` int(10) unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table settings
DROP TABLE IF EXISTS `settings`;
CREATE TABLE IF NOT EXISTS `settings` (
  `user_id` bigint(20) NOT NULL COMMENT 'reserved',
  `force_query` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_user` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_group` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `show_info_detail` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `except_forward` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `except_bot` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `is_specify_id` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `is_specify_chat` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `specify_id` bigint(20) NOT NULL DEFAULT '0',
  `page_limit` tinyint(4) NOT NULL DEFAULT '5',
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;

-- Dumping structure for table username_history
DROP TABLE IF EXISTS `username_history`;
CREATE TABLE IF NOT EXISTS `username_history` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `username` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table user_history
DROP TABLE IF EXISTS `user_history`;
CREATE TABLE IF NOT EXISTS `user_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `first_name` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `photo_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'big_file_id',
  `last_update` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table user_index
DROP TABLE IF EXISTS `user_index`;
CREATE TABLE IF NOT EXISTS `user_index` (
  `user_id` bigint(20) NOT NULL,
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
