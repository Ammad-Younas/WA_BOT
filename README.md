# MADI Agent

An all-in-one WhatsApp agent built on the WhatsApp Agent Platform API. It
downloads media, extracts audio, searches and downloads from YouTube, makes
stickers and QR codes, and provides text, calculator, weather, dictionary,
notes, reminders, and fun commands -- all through plain WhatsApp messages.

The bot ships with no binaries. On first run it downloads the required tools
(yt-dlp, ffmpeg, ffprobe, ffplay) for the host operating system directly from
their official sources and keeps them up to date in the background.

## Features

- Video download as MP4 (YouTube, TikTok, Instagram, Facebook, X/Twitter,
  Reddit, and most sites supported by yt-dlp)
- YouTube search: top 5 most-viewed matches, sent as the queried thumbnail
  image with the result list as its caption
- Audio extraction / MP3 conversion
- Image-to-sticker (512x512 WebP WhatsApp sticker)
- QR code generation
- Media technical info (ffprobe)
- Calculator / math engine with safe evaluation
- Text tools: base64, hashes, case conversion, reverse, count, URL
  encode/decode, pretty JSON, password and UUID generation
- Date & time: current time, world city times, Unix conversion, day diff,
  countdowns
- Weather (wttr.in), dictionary (Datamuse)
- Notes/TODO per conversation (persisted locally)
- Reminders (persisted locally, fired on schedule)
- Random & fun: dice, coin, choices, magic 8-ball, prime/even/odd checks,
  quotes, jokes, facts

## Requirements

- Python 3.10 or newer
- Internet access to the WhatsApp Agent Platform API and the binary sources
- An `AGENT_API_KEY` for the WhatsApp Agent Platform

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

## Setup

1. Clone or copy the project into a folder.
2. Create a `.env` file next to `main.py`:

   ```
   AGENT_API_KEY=your_token_here
   ```

3. Start the bot:

   ```bash
   python main.py
   ```

Only one instance of `main.py` should run at a time. A second poller causes
HTTP 409 conflicts with the WhatsApp Agent Platform API.

## Configuring the bot

Configuration lives in `config/configure_bot.py`. Environment variables:

| Variable                    | Default | Description                                  |
| --------------------------- | ------- | -------------------------------------------- |
| `AGENT_API_KEY`             | -       | API token for the WhatsApp Agent Platform    |
| `MADI_NO_BOOTSTRAP`         | off     | Set to `1` to skip binary download/updates   |
| `MADI_BIN_UPDATE_HOURS`     | `24`    | How often the background updater re-checks   |
| `MADI_BIN_UPDATE_FIRST_MIN` | `5`     | Delay (minutes) before the first update check|

## Binary management

Nothing is bundled. `utilities/bootstrap.py` downloads the toolchain for the
host OS:

- yt-dlp from GitHub releases
- ffmpeg / ffprobe / ffplay from BtbN (Windows), johnvansickle (Linux), or
  evermeet.cx (macOS; no ffplay build is published there)

Files land in `binaries/`. A background thread (`bin-updater`) checks the
upstream "latest" URLs periodically and replaces the binaries when a newer
build is detected. Set `MADI_NO_BOOTSTRAP=1` to disable this and provide the
binaries yourself.

## Commands

The full menu is available by sending `menu`. Main menu numbers 1-17 also work.

| Command                       | Description                                 |
| ----------------------------- | ------------------------------------------- |
| `menu` / `help` / `start`     | Show the main menu                          |
| `about` / `status`            | Bot info and capabilities                   |
| `dl <url>`                    | Download a video as MP4                     |
| `mp3 <url>`                   | Download/convert audio to MP3               |
| `yt <query>`                  | YouTube search: top 5 most-viewed matches   |
| `convert`                     | Reply flow: send a file, get MP3            |
| `sticker`                     | Turn an image into a WhatsApp sticker       |
| `info`                        | Technical details of a sent media file      |
| `qr <text>`                   | Generate a QR code image                    |
| `calc <expression>`           | Safe calculator (`calc 2^10`, `calc sqrt(144)`) |
| `weather <city>`              | Current weather for a city                  |
| `dict <word>`                 | Dictionary definition                       |
| `time`                        | Current time                                |
| `now <city>`                  | Time in a world city                        |
| `unix <timestamp>`            | Convert a Unix timestamp to a date          |
| `days <date> <date>`          | Days between two dates                      |
| `countdown <unix>`            | Countdown to a Unix timestamp               |
| `upper/lower/title <text>`    | Case conversion                             |
| `reverse <text>`              | Reverse a string                            |
| `count <text>`                | Word and character count                    |
| `b64 <text>` / `unb64 <text>` | Base64 encode / decode                      |
| `md5/sha1/sha256 <text>`      | Hash generation                             |
| `url <text>` / `unurl <text>` | URL encode / decode                         |
| `json:<text>`                 | Pretty-print JSON                           |
| `password <len>`              | Generate a password (default 16)            |
| `uuid`                        | Generate a UUID                             |
| `random <min> <max>`          | Random number                               |
| `dice`, `coin`, `choice a,b`  | Random & fun                                |
| `even/odd/prime <n>`          | Number checks                               |
| `ask <question>`              | Magic 8-ball                                |
| `quote`, `joke`, `fact`       | One-liners                                  |
| `note add <text>`             | Add a note                                  |
| `note <n>` / `note del <n>`   | View / delete a note                        |
| `notes`                       | List all notes                              |
| `note clear`                  | Delete all notes                            |
| `remind in <min> <text>`      | Set a reminder                              |
| `remind at <HH:MM> <text>`    | Reminder at a clock time                    |
| `reminders`                   | List active reminders                       |
| `cancel reminder <n>`         | Remove a reminder                           |
| `clear reminders`             | Remove all reminders                        |
| `ping`                        | Liveness check (pong)                       |

## Project layout

```
main.py                     entry point; poller/worker/sender/updater/cleaner
requirements.txt            Python dependencies
.env                        API key (ignored by git)
binaries/                   runtime binaries (auto-downloaded, ignored)
config/configure_bot.py     settings, paths, API constants
menu/menu.py                menu texts and command registry
utilities/api_client.py     rate-limited WhatsApp Agent Platform API client
utilities/handlers.py       intent routing and per-user state machine
utilities/media_tools.py    yt-dlp/ffmpeg pipelines, search, thumbnails
utilities/tools.py          text, math, time, weather, dictionary, notes, QR
utilities/scheduler.py      reminders engine
utilities/bootstrap.py      binary download and background self-update
data/                       runtime state and files (ignored by git)
```

## Runtime data

The bot keeps offsets, notes, reminders, and profiles under `data/`. Downloaded
media and transcode artifacts go to `data/downloads` and `data/tmp`; a cleaner
thread removes files older than 6 hours, so temporary files are removed
automatically. The `data/` directory is excluded from git.

## License

Private project. Use at your own risk.