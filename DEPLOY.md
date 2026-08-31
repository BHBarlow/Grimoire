# Deploying Grimoire to a Raspberry Pi

The whole app is Python + SQLite. Nothing to compile, no external services.
The DB is disposable, so you don't migrate it — you rebuild it on the Pi.

## What transfers and what doesn't

| Thing            | Transfer it?                                              |
|------------------|----------------------------------------------------------|
| Code (this repo) | Yes — `git pull` on the Pi.                               |
| `web/pdfjs/`     | Yes — committed (~12M), so `git pull` brings the reader.  |
| `.venv/`         | **No.** Never copy a Mac venv to ARM Linux. Recreate it. |
| `grimoire.db`    | No — rebuild with the indexer. It's disposable.          |
| `books/`         | Copy via `rsync`/USB, or point `BOOKS_DIR` at a mount.   |

## First-time setup on the Pi

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
git clone <your-repo> grimoire && cd grimoire

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # PyMuPDF ships aarch64 wheels — no build

cp .env.example .env                 # then edit BOOKS_DIR if books live elsewhere
python -m indexer.index              # build the index
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` makes it reachable from other machines on your LAN at
`http://<pi-ip>:8000`. On the Mac you can drop that and just use `--reload`.

### If a wheel ever fails to install on the Pi
64-bit Raspberry Pi OS has prebuilt wheels for everything here. If you're on a
32-bit OS (armv7) a wheel may be missing; the fix is the system package, e.g.
`sudo apt install python3-fitz` or `python3-lxml`, then reinstall the rest.

## Getting books onto the Pi

```bash
# from the Mac, repo root:
rsync -av --progress books/ pi@<pi-ip>:/home/pi/grimoire/books/
```

Or keep books on an external drive and set `BOOKS_DIR=/mnt/books` in `.env`.

## Keep the index fresh (cron)

```
*/30 * * * * cd /home/pi/grimoire && .venv/bin/python -m indexer.index
```

## Run it as a service (survives reboots)

`/etc/systemd/system/grimoire.service`:

```ini
[Unit]
Description=Grimoire book search
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/grimoire
ExecStart=/home/pi/grimoire/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now grimoire
```

## Bundled PDF reader

`web/pdfjs/` is Mozilla pdf.js **v6.3.289 (legacy build)**, committed to the repo
so deep links open the exact page in a consistent viewer everywhere. Sourcemaps
and the demo PDF were stripped to keep it lean. To update it later, download a
newer `pdfjs-<ver>-legacy-dist.zip` from github.com/mozilla/pdf.js/releases and
replace the folder — no code changes needed.

Grimoire **full-text searches PDFs**; EPUBs are catalogued in the library for
download only (no keyword search inside them).

## Your normal workflow

1. Add/remove books in `books/` (Mac or Pi).
2. `python -m indexer.index` — hashes files, only touches what changed.
3. Search at `http://localhost:8000` (Mac) or `http://<pi-ip>:8000` (Pi).
