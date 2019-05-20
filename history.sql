/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping structure for table bot_track
DROP TABLE IF EXISTS `bot_track`;
CREATE TABLE IF NOT EXISTS `bot_track` (
  `user_id` int(11) NOT NULL,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table document_index
DROP TABLE IF EXISTS `document_index`;
CREATE TABLE IF NOT EXISTS `document_index` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `forward_from` bigint(20) NOT NULL DEFAULT '0',
  `message_id` int(11) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `type` enum('document','photo','video','animation') CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `file_id` varchar(64) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
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

-- Dumping structure for table search_history
DROP TABLE IF EXISTS `search_history`;
CREATE TABLE IF NOT EXISTS `search_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `args` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table settings
DROP TABLE IF EXISTS `settings`;
CREATE TABLE IF NOT EXISTS `settings` (
  `user_id` bigint(20) NOT NULL COMMENT 'reserved',
  `force_query` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_user` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `only_group` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `include_forward` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
  `include_bot` enum('Y','N') COLLATE utf8_unicode_ci NOT NULL DEFAULT 'N',
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
  `hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
