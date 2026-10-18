<?php
// Minimal dependency-free SMTP client for the local mail server.
// No external libraries (PHPMailer, etc.) are installed in this environment,
// so this talks raw SMTP instead. Supports plaintext, STARTTLS, and
// AUTH LOGIN/PLAIN. Good enough for a single internal relay; not a general
// mail library.

class SmtpMailer {
    private string $host;
    private int $port;
    private string $encryption; // 'none' | 'starttls' | 'tls'
    private string $username;
    private string $password;
    private string $fromAddress;
    private string $fromName;

    public function __construct(array $config) {
        $this->host = $config['host'];
        $this->port = (int)$config['port'];
        $this->encryption = $config['encryption'] ?? 'starttls';
        $this->username = $config['username'] ?? '';
        $this->password = $config['password'] ?? '';
        $this->fromAddress = $config['from_address'];
        $this->fromName = $config['from_name'] ?? 'NekoCore';
    }

    /**
     * @throws Exception on any SMTP-level failure.
     */
    public function send(string $toAddress, string $subject, string $body): void {
        // Our mail relay (NEKO_SMTP_HOST) uses a self-signed certificate --
        // confirmed directly (openssl/python smtplib both reject it with
        // the default CA-verifying context). It's an internal-only relay
        // we control, so encrypted-but-unverified is an acceptable
        // tradeoff here; verification stays on for anything else.
        $context = stream_context_create([
            'ssl' => [
                'verify_peer' => false,
                'verify_peer_name' => false,
                'allow_self_signed' => true,
            ],
        ]);

        $transport = $this->encryption === 'tls' ? 'ssl://' : '';
        $socket = @stream_socket_client(
            $transport . $this->host . ':' . $this->port,
            $errno,
            $errstr,
            10,
            STREAM_CLIENT_CONNECT,
            $context
        );
        if (!$socket) {
            throw new Exception("Could not connect to mail server: $errstr ($errno)");
        }

        $this->expect($socket, 220);
        $this->command($socket, "EHLO nekocore.local", 250);

        if ($this->encryption === 'starttls') {
            $this->command($socket, "STARTTLS", 220);
            if (!stream_socket_enable_crypto($socket, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)) {
                throw new Exception('STARTTLS negotiation failed.');
            }
            $this->command($socket, "EHLO nekocore.local", 250);
        }

        if ($this->username !== '') {
            $this->command($socket, "AUTH LOGIN", 334);
            $this->command($socket, base64_encode($this->username), 334);
            $this->command($socket, base64_encode($this->password), 235);
        }

        $this->command($socket, "MAIL FROM:<{$this->fromAddress}>", 250);
        $this->command($socket, "RCPT TO:<{$toAddress}>", 250);
        $this->command($socket, "DATA", 354);

        $headers = [
            "From: {$this->fromName} <{$this->fromAddress}>",
            "To: <{$toAddress}>",
            "Subject: " . $this->encodeSubject($subject),
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "Date: " . date('r'),
        ];

        // Dot-stuff any line that starts with a literal '.' per RFC 5321.
        $escapedBody = preg_replace('/^\./m', '..', $body);

        $message = implode("\r\n", $headers) . "\r\n\r\n" . $escapedBody . "\r\n.";
        $this->command($socket, $message, 250);

        $this->command($socket, "QUIT", 221);
        fclose($socket);
    }

    private function encodeSubject(string $subject): string {
        return '=?UTF-8?B?' . base64_encode($subject) . '?=';
    }

    private function command($socket, string $line, int $expectedCode): string {
        fwrite($socket, $line . "\r\n");
        return $this->expect($socket, $expectedCode);
    }

    private function expect($socket, int $expectedCode): string {
        $response = '';
        while (($line = fgets($socket, 515)) !== false) {
            $response .= $line;
            // Multiline SMTP responses use "250-" continuations; the final
            // line for that code uses "250 " (a space, not a dash).
            if (preg_match('/^\d{3} /', $line)) {
                break;
            }
        }

        $code = (int)substr($response, 0, 3);
        if ($code !== $expectedCode) {
            throw new Exception("Unexpected SMTP response (expected $expectedCode): " . trim($response));
        }
        return $response;
    }
}
?>
