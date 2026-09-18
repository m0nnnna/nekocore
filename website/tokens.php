<?php
// Verification / password-reset token helpers.
//
// The raw token only ever exists in the emailed URL and briefly in memory.
// Only its SHA-256 hash is stored in the database, so a database leak alone
// never yields a usable token.

function generate_token(): string {
    return bin2hex(random_bytes(32));
}

function hash_token(string $token): string {
    return hash('sha256', $token);
}
?>
