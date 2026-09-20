<?php
// SMTP relay used for verification and password-reset mail (see docker.env).
$mail_config = [
    'host'         => getenv('NEKO_SMTP_HOST') ?: 'localhost',
    'port'         => (int)(getenv('NEKO_SMTP_PORT') ?: 587),
    'encryption'   => getenv('NEKO_SMTP_ENCRYPTION') ?: 'starttls', // none | starttls | tls
    'username'     => getenv('NEKO_SMTP_USER') ?: '',
    'password'     => getenv('NEKO_SMTP_PASS') ?: '',
    'from_address' => getenv('NEKO_SMTP_FROM') ?: 'noreply@localhost',
    'from_name'    => getenv('NEKO_SMTP_FROM_NAME') ?: 'NekoCore',
];
