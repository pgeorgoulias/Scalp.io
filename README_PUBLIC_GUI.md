# Public Monitor HUD

A local browser control panel for `public1.py`. It uses only Python plus the existing project dependencies; there is no Node/npm build step.

## Start the HUD

### macOS
Double-click:

```text
run_public_gui.command
```

or run:

```bash
cd /Users/your_username/Documents/Projects/scrape.io
python3 public_gui.py
```

### Windows
Double-click:

```text
run_public_gui.bat
```

or run from Command Prompt / PowerShell:

```bat
cd path\to\scrape.io
py -3 public_gui.py
```

### Linux
Run:

```bash
cd /path/to/scrape.io
chmod +x run_public_gui.sh
./run_public_gui.sh
```

The HUD opens at:

```text
http://127.0.0.1:8787
```

If Chrome shows the text of `run_public_gui.command`, it means the launcher file was opened as a document. Double-click the launcher in Finder or run it from Terminal, then open `http://127.0.0.1:8787` in Chrome.

If Chrome does not show the HUD page, make sure the terminal window running `public_gui.py` is still open. The page only works while the local HUD server is running.

If the HUD is already running, launching it again will reuse the existing `http://127.0.0.1:8787` page instead of crashing with "Address already in use".

## What the HUD controls

- Start and stop `public1.py`
- Edit watchlist products
- Change scan/check intervals
- View recent availability state
- Watch live monitor logs

Editable settings are stored in `public_monitor_config.json`. `public1.py` reloads that file on every monitor cycle, so saved GUI changes apply without manually editing Python code.

## Dependencies

Install the existing requirements once per device:

```bash
pip install -r requirements.txt
playwright install chromium
```

On Windows, use `py -3 -m pip install -r requirements.txt` if `pip` is not recognized.
