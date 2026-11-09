# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-11-09

The first public release.

### Added

- Single-file Python music server for the Raspberry Pi, using only the standard library.
- Retro terminal web interface with a typed command prompt, keyboard shortcuts and four colour themes.
- Album art rendered as live ASCII art in colour, block and monochrome styles.
- Real-time spectrum analyser with smoothed bars and fading peak markers.
- Gapless playback with background prefetching and an adjustable crossfade (8 seconds by default).
- Background playback and lock-screen / control-centre integration through the Media Session API.
- Built-in tag reader for MP3, FLAC, Ogg Vorbis, Opus, M4A/MP4/AAC and WAV.
- Online album art from MusicBrainz and the Cover Art Archive, deleted automatically when each track finishes.
- Whole-library shuffle that plays every track once before repeating and spreads albums apart.
- Optional password protection, a systemd service file and a quiet console.

### Security

- Strict Content Security Policy, CSRF protection and security headers.
- Limits on tag decompression to stop "zip bomb" files.
- Album art redirects only followed to the Cover Art Archive and archive.org.

[1.4.0]: https://github.com/YOUR-USERNAME/bad-banana/releases/tag/v1.4.0
