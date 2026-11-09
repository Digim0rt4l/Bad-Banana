# Security policy

## Supported versions

Only the latest release of Bad Banana receives security fixes.

| Version | Supported |
| ------- | --------- |
| 1.4.x   | Yes       |
| < 1.4   | No        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report them privately through GitHub's [private vulnerability reporting](../../security/advisories/new) instead. Include:

- what the problem is and what an attacker could do with it,
- steps or a proof of concept to reproduce it,
- the Bad Banana version, Python version and operating system.

You can expect an acknowledgement within a week. Once a fix is ready, a new release will be published and you will be credited unless you would rather stay anonymous.

## Deployment advice

Bad Banana is designed for a **trusted home network**.

- Use `--password` if anyone you do not trust can reach the server.
- Do not expose it directly to the internet. If you need remote access, put it behind a VPN (such as WireGuard or Tailscale) or a reverse proxy that adds HTTPS.
- Basic authentication sends the password with every request. Without HTTPS it can be read by anyone on the same network.
- Run it as an ordinary user, never as root. The included `bad_banana.service` adds systemd sandboxing.

## Built-in protections

- A strict Content Security Policy with hash-pinned inline script and styles, plus `X-Frame-Options: DENY`, `nosniff` and `no-referrer` headers.
- State-changing requests require a custom `X-BadBanana` header, which blocks cross-site request forgery.
- Only files indexed from the music folder can be streamed. Track IDs are hashes, so paths cannot be traversed.
- The tag reader limits how much it reads and decompresses, so malformed or malicious music files cannot exhaust memory.
- Album art downloads are limited in size and only accepted from the Cover Art Archive and archive.org, including after redirects.
