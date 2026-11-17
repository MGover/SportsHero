# SportsHero Project Notes

## Architecture

- `sport-hero.py` is the official Discord bot. It handles slash commands, XMLTV lookups, the IPTV API, autocomplete, and stream session lifecycle.
- `streambot/src/index.ts` is the Discord selfbot that joins voice and sends the video stream. Python starts it as a child process and sends JSON lines over stdin.
- `stream_control.py` defines the Python-side JSON command format; keep it compatible with `StreamCommand` in `streambot/src/index.ts`.
- `channel_search.py` contains pure, dependency-free normalization and ranking functions for programme and IPTV channel search.

## Runtime And Build

- The supported deployment is Docker Compose: `docker compose up -d --build`.
- For deployment on the 2018 Mac mini, first verify macOS, CPU architecture, Docker Desktop installation, and that Docker is running; do not assume any of these. Prefer Compose initially because the image pins the Linux runtime and native dependencies. Do not switch to a native macOS build without checking dependency compatibility.
- If working through a remote VS Code session, operate only in the connected workspace and its terminal. Do not request SSH credentials or claim access to another machine; give the user commands to run if it is not connected.
- Preserve the existing working tree during migration. Check `git status --short` and carry over needed tracked edits and untracked fixtures such as `test_media/`; do not replace the checkout with a clean clone unless the user approves.
- The selfbot currently uses `@dank074/discord-video-stream` 6.x with `discord.js-selfbot-v13` 3.7.x on Node 22.
- v7 requires a newer glibc native addon than Debian Bookworm provides. v6's `@lng2004/node-datachannel` addon was verified to load on Bookworm; do not upgrade without checking native dependencies in the final image.
- `.dockerignore` must exclude both `streambot/node_modules/` and `streambot/dist/`. Otherwise the final `COPY . .` can overwrite the dependencies and compiled bundle installed by the builder stage.
- The Compose mount `./test_media:/app/test_media:ro` is a local test fixture, not a production stream override. No `STREAM_TEST_FILE` override should be enabled for normal IPTV mode.

## Mac Mini Migration And Startup

- Keep the Mac plugged in and confirm its sleep settings support the user's intended uptime. Do not change system power settings without the user's approval.
- Never ask the user to paste tokens, passwords, IPTV URLs, `.env` contents, SSH keys, or other credentials into chat or logs. Have them transfer secret files to the new host over a secure channel, keep them out of Git, and do not print their contents.
- The root `.env` supplies the Python bot's configuration and is the `env_file` declared by Compose. `streambot/.env` supplies the selfbot's `TOKEN` and other streambot settings; the Node child runs with `streambot/` as its working directory and loads dotenv there. Inspect both `.dockerignore` and Compose before launch to ensure secrets are neither baked into the image nor omitted from the runtime. Compose currently explicitly declares only the root `.env`; verify how the child receives its required configuration without printing values.
- From the repository root, build and start with `docker compose up -d --build`, then check `docker compose ps`. Do not use `docker compose config` in a way that prints resolved secret values.
- When join or stream fails, inspect recent service logs locally and share only sanitized excerpts. Check selfbot login/readiness, configured guild and channel lookup, join timeout/error, FFmpeg/encoder errors, and whether streaming actually begins. Do not assume Docker networking or host hardware is the cause without evidence; the current stream encoder uses software encoding by default.
- Validate the end-to-end voice join and video stream before calling migration complete. For runtime diagnostics use `docker compose logs --since=10m --no-color`, taking care not to disclose credentials or tokens.

## Search And EPG

- `/watch` and `/search` search currently airing XMLTV programme titles first, then fall back to matching IPTV catalog names such as dedicated 24/7 show streams.
- `/watch_channel` and `/search_channel` search IPTV catalog display names, XMLTV IDs, custom SIDs, and supported affiliate aliases. They are intended for station queries such as `CBS Sacramento` or station callsigns such as `KOVR`.
- The IPTV API channel records expose `name`, `stream_id`, `stream_type`, and `epg_channel_id`; many dedicated 24/7 streams have an empty EPG ID.
- The configured `EPG_URL` may be invalid or unavailable. The bot tries it first and falls back to the provider XMLTV endpoint, derived from `M3U_URL` credentials.
- Discord application-command autocomplete is limited to 25 choices per response. Improve ranking and relevance rather than attempting to return 200 choices in one autocomplete response.
- Keep logs free of IPTV URLs with credentials and selfbot tokens. Redact voice-server tokens in gateway logs.

## Validation

- Run focused Python tests with `python3 -m unittest tests.test_stream_control`.
- Compile Python modules with `python3 -m py_compile sport-hero.py channel_search.py`.
- Build the selfbot through Docker to match its required Node runtime: `docker compose build sport-hero`.
- Inspect runtime diagnostics with `docker compose logs --since=10m --no-color`.
