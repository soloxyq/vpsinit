ALTER TABLE `message` ADD `read_at` integer;--> statement-breakpoint
-- 手写的一句（drizzle-kit 只生成表结构的改动）：这个功能上线之前的邮件都算已读，否则它们会一下子全部变成未读
UPDATE `message` SET `read_at` = `received_at` WHERE `read_at` IS NULL;--> statement-breakpoint
CREATE INDEX `message_email_id_read_at_idx` ON `message` (`emailId`,`read_at`);
