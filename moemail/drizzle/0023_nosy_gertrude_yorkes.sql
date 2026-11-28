CREATE TABLE `daily_usage` (
	`day` text NOT NULL,
	`scope` text NOT NULL,
	`count` integer DEFAULT 0 NOT NULL,
	PRIMARY KEY(`day`, `scope`)
);
--> statement-breakpoint
CREATE INDEX `message_with_attachments_idx` ON `message` (`id`) WHERE `attachments` IS NOT NULL;