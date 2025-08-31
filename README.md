# Zerochan Tag Scraper (Windows-friendly)

A tiny Python script that downloads **full-size** images from Zerochan for a list of characters/tags you care about.
No homepage crawling—just straight to each tag page like `https://www.zerochan.net/Saber.%28Fate%2Fstay.night%29`, collect the image **IDs**, and fetch:

```
https://static.zerochan.net/<Name.Dots>.full.<ID>.jpg   (fallbacks to .png)
```

Files are saved as:

```
<Name.Dots>_<ID>.<ext>
e.g. Artoria.Caster_4572543.jpg
```

The script does a pre-flight scan of your download folder to **skip duplicates** automatically.

---

## Quickstart

### 1) Requirements

* Windows 10/11
* Python **3.9+**
* Internet connection

### 2) Clone & enter the folder

```powershell
git clone https://github.com/<you>/<repo>.git
cd <repo>
```

### 3) Create your `subscriptions.txt`

Create a file named `subscriptions.txt` **in the same folder** as the script with one tag per line.
Use `+` between words, exactly like Zerochan:

```
Saber+Alter
Oguri+Cap
Air+Groove
Artoria+Caster
Saber+%28Fate%2Fstay+night%29
```

> You can add/remove lines anytime—re-running the script will only fetch **new** IDs for each character.

### 4) Set up a virtual environment (first time)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If you don’t have a `requirements.txt`, install directly:
>
> ```powershell
> pip install requests beautifulsoup4 lxml
> ```

### 5) Run

```powershell
python .\zerochan_watch.py
```

Downloaded images will appear at:

```
C:\Users\<You>\Pictures\Zerochan
```

Re-runs are safe: the script **skips** images it already has (by scanned IDs and existing filenames).

---

## How it works (short)

* For each subscription (e.g., `Air+Groove`) the script requests:

  * `https://www.zerochan.net/Air+Groove`
  * `?p=2`, `?p=3`, … up to `MAX_PAGES_PER_TAG`
* Parses the thumbnails list to extract the **image IDs**.
* Builds static links:
  `https://static.zerochan.net/Air.Groove.full.<ID>.jpg` (then tries `.png` if needed).
* Saves to `Pictures\Zerochan` as `Air.Groove_<ID>.jpg`.
* Before downloading, it scans the folder to keep a `{character → set(ids)}` and **skips duplicates**.

---

## Configuration (optional)

Open `zerochan_watch.py` and tweak:

```python
# Where images go (default: ~/Pictures/Zerochan)
DEST_DIR = pathlib.Path.home() / "Pictures" / "Zerochan"

# How many pages per tag to scan (page 1 is the base URL, page 2 is ?p=2, etc.)
MAX_PAGES_PER_TAG = 3

# Delay between requests (be polite to their servers)
REQUEST_DELAY = 0.8

# Debug logging
DEBUG = True
SAVE_HTML_DEBUG = False
```

---

## Run on startup (Windows)

### Option A — Simple `.bat` file (good for Startup folder)

Create `run_zerochan.bat` next to the script:

```bat
@echo off
set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%zerochan_watch.py"
```

Put a shortcut to this `.bat` in your Startup folder:

1. Press `Win + R` → `shell:startup` → Enter
2. Right-click → **New → Shortcut**
3. Target: the path to `run_zerochan.bat`

### Option B — Task Scheduler (more reliable)

```powershell
$py = "$PWD\.venv\Scripts\python.exe"
$sc = "$PWD\zerochan_watch.py"
schtasks /Create /SC ONLOGON /RL LIMITED /TN "Zerochan Auto Fetch" /TR "`"$py`" `"$sc`""
```

---

## Updating subscriptions

* Edit `subscriptions.txt`
* Run the script again
* It will fetch only the **new** IDs per character

---

## Troubleshooting

* **Nothing downloads?**

  * Ensure `subscriptions.txt` is in the **same folder** as `zerochan_watch.py`.
  * Try increasing `MAX_PAGES_PER_TAG`.
  * Keep `DEBUG = True` to see which URLs/IDs are detected.
* **403/404 on static links?**

  * The script already sets a `Referer: https://www.zerochan.net/`.
    Some items may still be restricted or removed; those will be skipped.
* **Too many requests?**

  * Increase `REQUEST_DELAY`.

---

## Notes & Etiquette

* This project performs polite scraping (delay between requests, minimal hits).
  Please respect Zerochan’s **ToS** and robots policies.
* For personal use only. Don’t hammer their servers.

---

## License

MIT — do whatever you like, but be nice.
