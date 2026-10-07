# SportsHero Project Notes

## Architecture

- `sport-hero.py` is the official Discord bot. It handles slash commands, XMLTV lookups, the IPTV API, autocomplete, and stream session lifecycle.
- `streambot/src/index.ts` is the Discord selfbot that joins voice and sends the video stream. Python starts it as a child process and sends JSON lines over stdin.
- `stream_control.py` defines the Python-side JSON command format; keep it compatible with `StreamCommand` in `streambot/src/index.ts`.
- `channel_search.py` contains pure, dependency-free normalization and ranking functions for programme and IPTV channel search.

## Runtime And Build

- The supported deployment is Docker Compose: `docker compose up -d --build`.
- The selfbot currently uses `@dank074/discord-video-stream` 6.x with `discord.js-selfbot-v13` 3.7.x on Node 22.
- v7 requires a newer glibc native addon than Debian Bookworm provides. v6's `@lng2004/node-datachannel` addon was verified to load on Bookworm; do not upgrade without checking native dependencies in the final image.
- `.dockerignore` must exclude both `streambot/node_modules/` and `streambot/dist/`. Otherwise the final `COPY . .` can overwrite the dependencies and compiled bundle installed by the builder stage.
- The Compose mount `./test_media:/app/test_media:ro` is a local test fixture, not a production stream override. No `STREAM_TEST_FILE` override should be enabled for normal IPTV mode.

## Search And EPG

- `/watch` searches currently airing XMLTV programme titles first, then falls back to matching IPTV catalog names such as dedicated 24/7 show streams.
- `/watch_channel` searches IPTV catalog display names, XMLTV IDs, custom SIDs, and supported affiliate aliases. It is intended for station queries such as `CBS Sacramento` or station callsigns such as `KOVR`.
- The IPTV API channel records expose `name`, `stream_id`, `stream_type`, and `epg_channel_id`; many dedicated 24/7 streams have an empty EPG ID.
- The configured `EPG_URL` may be invalid or unavailable. The bot tries it first and falls back to the provider XMLTV endpoint, derived from `M3U_URL` credentials.
- Discord application-command autocomplete is limited to 25 choices per response. Improve ranking and relevance rather than attempting to return 200 choices in one autocomplete response.
- Keep logs free of IPTV URLs with credentials and selfbot tokens. Redact voice-server tokens in gateway logs.

## Validation

- Run focused Python tests with `python3 -m unittest tests.test_stream_control`.
- Compile Python modules with `python3 -m py_compile sport-hero.py channel_search.py`.
- Build the selfbot through Docker to match its required Node runtime: `docker compose build sport-hero`.
- Inspect runtime diagnostics with `docker compose logs --since=10m --no-color`.
