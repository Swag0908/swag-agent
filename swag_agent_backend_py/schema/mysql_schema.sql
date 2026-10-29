
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `SPRING_AI_CHAT_MEMORY`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `SPRING_AI_CHAT_MEMORY` (
  `conversation_id` varchar(36) COLLATE utf8mb4_general_ci NOT NULL,
  `content` text COLLATE utf8mb4_general_ci NOT NULL,
  `type` enum('USER','ASSISTANT','SYSTEM','TOOL') COLLATE utf8mb4_general_ci NOT NULL,
  `timestamp` timestamp NOT NULL,
  `sequence_id` bigint NOT NULL,
  KEY `SPRING_AI_CHAT_MEMORY_CONVERSATION_ID_TIMESTAMP_IDX` (`conversation_id`,`timestamp`),
  KEY `SPRING_AI_CHAT_MEMORY_CONVERSATION_ID_SEQUENCE_ID_IDX` (`conversation_id`,`sequence_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `app_register_setting`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `app_register_setting` (
  `id` tinyint NOT NULL,
  `register_code` varchar(64) NOT NULL,
  `registration_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` bigint DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `app_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `app_user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `password_hash` varchar(128) NOT NULL,
  `display_name` varchar(64) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `role` varchar(16) NOT NULL DEFAULT 'USER',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_app_user_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `audit_confirmation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_confirmation` (
  `confirmation_id` char(36) NOT NULL,
  `audit_id` char(36) NOT NULL,
  `tool_call_id` varchar(128) DEFAULT NULL,
  `tenant_id` varchar(128) DEFAULT NULL,
  `actor_id` varchar(256) DEFAULT NULL,
  `tool_name` varchar(128) NOT NULL,
  `canonical_input` longtext NOT NULL,
  `action_digest` char(64) NOT NULL,
  `status` varchar(32) NOT NULL,
  `decision_reason` varchar(512) DEFAULT NULL,
  `requested_at` datetime(6) NOT NULL,
  `decided_at` datetime(6) DEFAULT NULL,
  `expires_at` datetime(6) NOT NULL,
  `consumed_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`confirmation_id`),
  KEY `idx_audit_confirmation_audit` (`audit_id`),
  KEY `idx_audit_confirmation_status_expiry` (`status`,`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `audit_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_event` (
  `event_id` char(36) NOT NULL,
  `audit_id` char(36) NOT NULL,
  `request_id` varchar(128) DEFAULT NULL,
  `source_event_id` varchar(128) DEFAULT NULL,
  `trace_id` varchar(64) DEFAULT NULL,
  `span_id` varchar(32) DEFAULT NULL,
  `parent_span_id` varchar(32) DEFAULT NULL,
  `parent_event_id` char(36) DEFAULT NULL,
  `tenant_id` varchar(128) DEFAULT NULL,
  `session_id` varchar(128) DEFAULT NULL,
  `actor_type` varchar(32) NOT NULL,
  `actor_id` varchar(256) DEFAULT NULL,
  `actor_display_name` varchar(256) DEFAULT NULL,
  `event_type` varchar(64) NOT NULL,
  `execution_status` varchar(32) DEFAULT NULL,
  `agent_name` varchar(128) DEFAULT NULL,
  `agent_version` varchar(64) DEFAULT NULL,
  `model_name` varchar(128) DEFAULT NULL,
  `tool_name` varchar(128) DEFAULT NULL,
  `tool_call_id` varchar(128) DEFAULT NULL,
  `confirmation_id` char(36) DEFAULT NULL,
  `action_digest` char(64) DEFAULT NULL,
  `input_ref` varchar(512) DEFAULT NULL,
  `input_digest` char(64) DEFAULT NULL,
  `output_ref` varchar(512) DEFAULT NULL,
  `output_digest` char(64) DEFAULT NULL,
  `event_data` json DEFAULT NULL,
  `error_code` varchar(128) DEFAULT NULL,
  `error_message` text,
  `occurred_at` datetime(6) NOT NULL,
  `recorded_at` datetime(6) NOT NULL,
  `schema_version` int NOT NULL DEFAULT '1',
  `previous_hash` char(64) DEFAULT NULL,
  `event_hash` char(64) DEFAULT NULL,
  `conversation_id` varchar(64) DEFAULT NULL,
  PRIMARY KEY (`event_id`),
  UNIQUE KEY `uk_audit_source_event` (`source_event_id`),
  KEY `idx_audit_event_audit_time` (`audit_id`,`occurred_at`),
  KEY `idx_audit_event_trace` (`trace_id`),
  KEY `idx_audit_event_user_time` (`tenant_id`,`actor_id`,`occurred_at`),
  KEY `idx_audit_event_tool_call` (`tool_call_id`),
  KEY `idx_audit_event_confirmation` (`confirmation_id`),
  KEY `idx_audit_event_conversation` (`conversation_id`,`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `audit_payload`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_payload` (
  `payload_id` char(36) NOT NULL,
  `audit_id` char(36) NOT NULL,
  `payload_type` varchar(32) NOT NULL,
  `storage_uri` varchar(1024) NOT NULL,
  `content_digest` char(64) NOT NULL,
  `media_type` varchar(128) DEFAULT NULL,
  `size_bytes` bigint DEFAULT NULL,
  `encryption_key_id` varchar(256) DEFAULT NULL,
  `redaction_version` varchar(64) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `expires_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`payload_id`),
  KEY `idx_audit_payload_audit` (`audit_id`),
  KEY `idx_audit_payload_expires` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `audit_request_summary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_request_summary` (
  `audit_id` char(36) NOT NULL,
  `request_id` varchar(128) DEFAULT NULL,
  `tenant_id` varchar(128) DEFAULT NULL,
  `user_id` varchar(256) DEFAULT NULL,
  `trace_id` varchar(64) DEFAULT NULL,
  `request_type` varchar(64) DEFAULT NULL,
  `request_summary` text,
  `final_status` varchar(32) DEFAULT NULL,
  `risk_level` varchar(16) DEFAULT NULL,
  `tool_call_count` int NOT NULL DEFAULT '0',
  `confirmation_count` int NOT NULL DEFAULT '0',
  `failed_event_count` int NOT NULL DEFAULT '0',
  `started_at` datetime(6) DEFAULT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `duration_ms` bigint DEFAULT NULL,
  `last_event_at` datetime(6) DEFAULT NULL,
  `retention_until` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`audit_id`),
  KEY `idx_audit_summary_user_time` (`tenant_id`,`user_id`,`started_at`),
  KEY `idx_audit_summary_status_time` (`final_status`,`started_at`),
  KEY `idx_audit_summary_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `auth_token`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_token` (
  `token` char(36) NOT NULL,
  `user_id` bigint NOT NULL,
  `expires_at` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`token`),
  KEY `idx_auth_token_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `chat_conversation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_conversation` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `title` varchar(120) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `favorite` tinyint(1) NOT NULL DEFAULT '0',
  `favorite_note` varchar(120) DEFAULT NULL,
  `favorite_order` int DEFAULT NULL,
  `favorited_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_chat_conv_user` (`user_id`,`updated_at`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `chat_message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_message` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `conversation_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `role` varchar(16) NOT NULL,
  `content` mediumtext NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_chat_msg_conv` (`conversation_id`,`id`)
) ENGINE=InnoDB AUTO_INCREMENT=124 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `chat_user_memory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_user_memory` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `content` text NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user_memory_user` (`user_id`,`updated_at`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `chat_user_memory_setting`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_user_memory_setting` (
  `user_id` bigint NOT NULL,
  `enabled` tinyint(1) NOT NULL DEFAULT '1',
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `flyway_schema_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `flyway_schema_history` (
  `installed_rank` int NOT NULL,
  `version` varchar(50) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `description` varchar(200) COLLATE utf8mb4_general_ci NOT NULL,
  `type` varchar(20) COLLATE utf8mb4_general_ci NOT NULL,
  `script` varchar(1000) COLLATE utf8mb4_general_ci NOT NULL,
  `checksum` int DEFAULT NULL,
  `installed_by` varchar(100) COLLATE utf8mb4_general_ci NOT NULL,
  `installed_on` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `execution_time` int NOT NULL,
  `success` tinyint(1) NOT NULL,
  PRIMARY KEY (`installed_rank`),
  KEY `flyway_schema_history_s_idx` (`success`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `skill_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `skill_state` (
  `skill_name` varchar(128) NOT NULL COMMENT '技能名（kebab-case，与 SKILL.md frontmatter 的 name 一致）',
  `enabled` tinyint(1) NOT NULL DEFAULT '1' COMMENT '1=启用，0=停用',
  `updated_at` datetime(6) NOT NULL COMMENT '最后修改时间',
  PRIMARY KEY (`skill_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='技能包启停状态';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `todo_daily_stat`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `todo_daily_stat` (
  `stat_date` date NOT NULL,
  `user_id` bigint NOT NULL,
  `created_count` int NOT NULL DEFAULT '0',
  `completed_count` int NOT NULL DEFAULT '0',
  `pending_count` int NOT NULL DEFAULT '0',
  `deferred_count` int NOT NULL DEFAULT '0',
  `completion_rate` decimal(5,2) DEFAULT NULL,
  PRIMARY KEY (`user_id`,`stat_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `todo_defer_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `todo_defer_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `item_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `from_date` date NOT NULL,
  `to_date` date NOT NULL,
  `deferred_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_defer_user_from` (`user_id`,`from_date`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `todo_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `todo_item` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `title` varchar(255) NOT NULL,
  `note` text,
  `due_date` date NOT NULL,
  `due_time` time DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'TODO',
  `source` varchar(16) NOT NULL DEFAULT 'CHAT',
  `created_at` datetime(6) NOT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_todo_user_due_status` (`user_id`,`due_date`,`status`),
  KEY `idx_todo_user_created` (`user_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=42 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'id',
  `user_name` varchar(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户昵称',
  PRIMARY KEY (`id`),
  KEY `idx_userName` (`user_name`)
) ENGINE=InnoDB AUTO_INCREMENT=1907068537007288325 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `website_bookmark`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `website_bookmark` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `folder_id` bigint DEFAULT NULL,
  `name` varchar(128) NOT NULL,
  `url` varchar(1024) NOT NULL,
  `description` varchar(512) DEFAULT NULL,
  `icon_url` varchar(1024) DEFAULT NULL,
  `sort_order` int NOT NULL DEFAULT '0',
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `icon_data` mediumblob,
  `icon_content_type` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_bookmark_user_folder` (`user_id`,`folder_id`),
  KEY `idx_bookmark_user_created` (`user_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `website_folder`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `website_folder` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `name` varchar(64) NOT NULL,
  `parent_id` bigint DEFAULT NULL,
  `sort_order` int NOT NULL DEFAULT '0',
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_folder_user_parent` (`user_id`,`parent_id`),
  KEY `idx_folder_user_created` (`user_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;
