/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping structure for table date_count
DROP TABLE IF EXISTS `date_count`;
CREATE TABLE IF NOT EXISTS `date_count` (
  `date` date NOT NULL,
  `count` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for table index
DROP TABLE IF EXISTS `index`;
CREATE TABLE IF NOT EXISTS `index` (
  `_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `chat_id` bigint(20) NOT NULL,
  `from_user` bigint(20) NOT NULL,
  `forward_from` bigint(20) DEFAULT NULL,
  `message_id` int(10) unsigned NOT NULL,
  `text` text COLLATE utf8mb4_unicode_ci,
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dumping structure for event update_count
DROP EVENT IF EXISTS `update_count`;
DELIMITER //
CREATE DEFINER=`root`@`localhost` EVENT `update_count` ON SCHEDULE EVERY 1 DAY STARTS '1970-01-02 00:00:00' ON COMPLETION PRESERVE ENABLE DO BEGIN
	INSERT INTO
		`date_count` (`date`, `count`)
	SELECT
		DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY),
		COUNT(*) AS `count`
	FROM
		`index`
	WHERE
		DATE(`timestamp`) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
END//
DELIMITER ;

-- Dumping structure for table user_history
DROP TABLE IF EXISTS `user_history`;
CREATE TABLE IF NOT EXISTS `user_history` (
  `_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `username` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
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
