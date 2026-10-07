-- Cross-faction mail for every player. The core gates it on RBAC permission 27
-- (MailHandler.cpp, MAIL_ERR_NOT_YOUR_TEAM), not on an AllowTwoSide.* config
-- key, and stock links 27 only to role 194 (moderator). Linking it to 195,
-- the role every security-level-0 account gets, matches the realm's other
-- AllowTwoSide.Interaction.* settings, which are all on.

INSERT IGNORE INTO `rbac_linked_permissions` (`id`, `linkedId`) VALUES (195, 27);
