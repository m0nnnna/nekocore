<?php
// SRP6 registration data, shared by registration and password reset.
// Requires the GMP extension.

function GetSRP6RegistrationData($username, $password) {
    $salt = random_bytes(32);
    return [
        'salt' => $salt,
        'verifier' => CalculateSRP6Verifier($username, $password, $salt)
    ];
}

function CalculateSRP6Verifier($username, $password, $salt) {
    if (!extension_loaded('gmp')) {
        throw new Exception('GMP extension is required for SRP6 calculations.');
    }

    $g = gmp_init(7);
    $N = gmp_init('0x894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7');

    $username = strtoupper($username);
    $password = strtoupper($password);

    $h1 = sha1($username . ':' . $password, true);
    $h2 = sha1($salt . $h1, true);

    $x = gmp_import(strrev($h2));
    $verifier_int = gmp_powm($g, $x, $N);

    $verifier_bytes = gmp_export($verifier_int, 1, GMP_MSW_FIRST | GMP_BIG_ENDIAN);
    $verifier_bytes = str_pad($verifier_bytes, 32, "\0", STR_PAD_LEFT);
    $verifier_bytes = strrev($verifier_bytes);

    return $verifier_bytes;
}
?>
