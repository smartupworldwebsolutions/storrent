# STorrent Pro

Free, ad-free BitTorrent client for Windows by [Smartupworld](https://smartupworld.com).
No ads, no trackers, no telemetry.

## Download
Get the latest installer from the [Releases](../../releases) page.

## Features
- Single window: opening a .torrent or magnet link sends it to the running app
- Starts with Windows (minimized to tray), light / dark / system theme
- Choose files, folder and label when adding; drag & drop; .torrent URLs
- Torrent creator, sequential streaming, per-torrent speed limits, queue control
- RSS feeds with auto-download filters
- Bandwidth scheduler, 🐢 speed limiter, transfer cap (daily/monthly)
- Seeding goals (ratio / time), move completed downloads, watch folders
- Proxy (SOCKS/HTTP), VPN/interface binding, IP blocklists, encryption

## Build from source
Windows: install Python 3.11 and Inno Setup 6, then run `build.bat`.
GitHub Actions builds the installer automatically on every push (see `.github/workflows/build.yml`).

## License
GPL-3.0 — see [LICENSE](LICENSE).
