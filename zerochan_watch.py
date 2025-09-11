import os
import re
import time
import json
import pathlib
import shutil
from typing import List, Set, Dict, Optional
from urllib.parse import quote, unquote
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from playwright.sync_api import sync_playwright

# ================== CONFIG ==================

SCRIPT_DIR = Path(__file__).parent
SUBSCRIPTIONS_FILE = SCRIPT_DIR / "subscriptions.txt"  # lives next to the script
DEST_DIR = pathlib.Path.home() / "Pictures" / "Zerochan"
DEST_DIR.mkdir(parents=True, exist_ok=True)

# How many pages per tag to scan: page 1 = base URL, page 2 = ?p=2, etc.
MAX_PAGES_PER_TAG = 3

# Delay between HTTP requests (be gentle)
REQUEST_DELAY = 5

# Debug knobs
DEBUG = True
SAVE_HTML_DEBUG = False  # set True to dump fetched HTML into _debug/
DEBUG_DIR = DEST_DIR / "_debug"
if SAVE_HTML_DEBUG:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# HTTP session
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Referer": "https://www.zerochan.net/",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
TIMEOUT = 20

# ================== LOG ==================
def log(msg: str):
    if DEBUG:
        print(msg, flush=True)

# ================== HELPERS ==================
_illegal = r'[<>:"/\\|?*]'

def folder_name_from_subscription(sub_plus: str) -> str:
    """
    Make a readable, safe folder name on Windows:
    - decode %xx → unicode (UTF-8)
    - '+' → space
    - replace path-forbidden chars with space
    - collapse/trim spaces; strip trailing dots/spaces
    """
    s = unquote(sub_plus).replace("+", " ")
    s = re.sub(_illegal, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(". ")
    # avoid reserved device names (CON, PRN, AUX, NUL, COM1, LPT1, ...)
    reserved = {*(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
                "CON", "PRN", "AUX", "NUL"}
    if s.upper() in reserved:
        s = s + " _"
    return s or "Unnamed"

def get_soup_via_playwright(url: str) -> Optional[BeautifulSoup]:
    log(f"[PW] Launching headless to fetch: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # persist a profile to keep cookies across runs (optional):
            # context = browser.new_context(storage_state="pw_state.json")
            context = browser.new_context()
            page = context.new_page()
            page.set_extra_http_headers({"Referer": "https://www.zerochan.net/"})

            # Go and wait a bit for DOM to populate:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for thumbs container (best-effort, don’t hang forever)
            try:
                page.wait_for_selector("ul#thumbs2, ul#thumbs3, ul[id^=thumbs]", timeout=15000)
            except Exception:
                pass

            html = page.content()
            context.close()
            browser.close()
            return BeautifulSoup(html, "lxml")
    except Exception as e:
        log(f"[PW] Error: {e}")
        return None

# ---------- Preflight migration from root to per-character folders ----------

def migrate_root_files_to_char_folders(root_dir: Path, subs: List[str]) -> None:
    """
    Move files sitting directly in root_dir into their character subfolders
    if we can determine the character from the filename.
    Supports:
      1) <charDots>_<id>.(jpg|jpeg|png)
      2) <charDots>.full.<id>.(jpg|jpeg|png)
    Only moves when <charDots> matches a subscription (case-insensitive).
    """
    # map charDots -> subscription "+ form"
    dots_to_sub = { sub.replace("+", ".").lower(): sub for sub in subs }

    rx_pair   = re.compile(r"^(?P<char>.+?)_(?P<id>\d+)\.(?P<ext>jpg|jpeg|png)$", re.IGNORECASE)
    rx_static = re.compile(r"^(?P<char>.+?)\.full\.(?P<id>\d+)\.(?P<ext>jpg|jpeg|png)$", re.IGNORECASE)

    moved = 0
    for p in list(root_dir.iterdir()):
        if not p.is_file():
            continue

        m = rx_pair.match(p.name) or rx_static.match(p.name)
        if not m:
            continue

        char_dots = m.group("char")
        img_id    = m.group("id")
        ext       = "." + m.group("ext").lower().replace("jpeg","jpg")

        sub = dots_to_sub.get(char_dots.lower())
        if not sub:
            log(f"  [MIGR] skip (unknown char for this filename): {p.name}")
            continue

        # Destination folder and filename
        char_folder = (DEST_DIR / folder_name_from_subscription(sub))
        char_folder.mkdir(parents=True, exist_ok=True)
        dest = char_folder / f"{char_dots}_{img_id}{ext}"

        if dest.exists():
            log(f"  [MIGR] duplicate exists, removing source: {p.name}")
            try:
                p.unlink()  # remove the extra copy in root
            except Exception as e:
                log(f"  [MIGR] could not remove duplicate: {e}")
            continue

        try:
            shutil.move(str(p), str(dest))
            log(f"  [MIGR] moved → {char_folder.name}\\{dest.name}")
            moved += 1
        except Exception as e:
            log(f"  [MIGR] move failed for {p.name}: {e}")

    log(f"[MIGR] total moved: {moved}")


def build_existing_ids_for_char(char_folder: Path) -> Set[str]:
    """
    Scan a character's folder for IDs. Accepts either:
      <charDots>_<id>.jpg  OR  <id>.jpg
    Returns set of string IDs.
    """
    ids: Set[str] = set()
    rx_pair = re.compile(r"^.+?_(\d+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)
    rx_id   = re.compile(r"^(\d+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)
    if not char_folder.exists():
        return ids
    for p in char_folder.iterdir():
        if not p.is_file(): 
            continue
        m = rx_pair.match(p.name) or rx_id.match(p.name)
        if m:
            ids.add(m.group(1))
    return ids

# ================== PRE/POST ==================
def load_subscriptions(path: Path) -> List[str]:
    if not path.exists():
        print(f"[ERROR] Subscriptions file not found: {path}")
        return []
    subs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            subs.append(s)
    log(f"[INFO] Loaded {len(subs)} subscriptions: {subs}")
    return subs

# ================== HTTP / PARSE ==================
def get_soup(url: str, dump_name: Optional[str] = None) -> Optional[BeautifulSoup]:
    log(f"[HTTP] GET {url}")
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        log(f"[HTTP] -> {r.status_code} ({len(r.content)} bytes)")
        text_lower = r.text.lower() if r.status_code == 200 else ""

        if r.status_code == 200 and ("just a moment" not in text_lower and "checking your browser" not in text_lower):
            return BeautifulSoup(r.text, "lxml")

        # 503/guard page fallback:
        if r.status_code in (429, 503) or "just a moment" in text_lower or "checking your browser" in text_lower:
            log("[HTTP] Guard detected → trying Playwright fallback…")
            return get_soup_via_playwright(url)

        return None
    except Exception as e:
        log(f"[ERR ] GET {url}: {e}")
        # last-ditch Playwright try:
        return get_soup_via_playwright(url)


def find_thumbs_ul(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    for sel in ("#thumbs2", "#thumbs3", "#thumbs", "ul[id^=thumbs]"):
        ul = soup.select_one(sel)
        if ul:
            log(f"[DEBUG] Found thumbs container via '{sel}' (id={ul.get('id')})")
            return ul
    log("[DEBUG] No thumbs container found")
    return None

def extract_ids_from_ul(ul: BeautifulSoup) -> List[str]:
    ids: Set[str] = set()
    lis = ul.find_all("li", recursive=False) or ul.find_all("li")

    for li in lis:
        # A: /1234567 in a.thumb href
        a_thumb = li.select_one("div > a.thumb")
        if a_thumb:
            href = a_thumb.get("href", "")
            m = re.search(r"/(\d+)(?:[/?#]|$)", href)
            if m:
                ids.add(m.group(1))
                continue

        # B: a.fav[data-id]
        a_fav = li.select_one("a.fav")
        if a_fav:
            did = a_fav.get("data-id")
            if did and did.isdigit():
                ids.add(did)
                continue

        # C: any [data-id]
        node = li.select_one("[data-id]")
        if node:
            did = node.get("data-id")
            if did and did.isdigit():
                ids.add(did)
                continue

        # D: any <a href="/123…">
        for a in li.select("a[href]"):
            m = re.search(r"/(\d+)(?:[/?#]|$)", a["href"])
            if m:
                ids.add(m.group(1))
                break

    log(f"[DEBUG] Extracted {len(ids)} IDs from container")
    return sorted(ids)

# ================== CORE ==================
def page_urls_for_subscription(sub_plus: str, max_pages: int) -> List[str]:
    """
    Build: page 1 = https://www.zerochan.net/<slug>
           page n = …?p=n
    Neutralize pre-encoded %xx, normalize spaces to '+', then quote with '+' safe.
    """
    normalized = unquote(sub_plus).replace(" ", "+")
    slug = quote(normalized, safe="+")  # prevents % -> %25 double-encoding
    base = f"https://www.zerochan.net/{slug}"
    urls = [base]
    for i in range(2, max_pages + 1):
        urls.append(f"{base}?p={i}")
    return urls

def static_candidates(sub_plus: str, img_id: str) -> List[str]:
    """
    Make .jpg first, then .png
    https://static.zerochan.net/<Name.Dots>.full.<id>.jpg
    """
    name_dots = sub_plus.replace("+", ".")
    base = f"https://static.zerochan.net/{name_dots}.full.{img_id}"
    return [base + ".jpg", base + ".png"]

def download(url: str, dest: pathlib.Path) -> bool:
    try:
        with SESSION.get(url, stream=True, timeout=TIMEOUT) as r:
            log(f"    [DL ] GET {url} -> {r.status_code}")
            if r.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        log(f"    [OK ] saved: {dest.name}")
        return True
    except Exception as e:
        log(f"    [ERR] download: {e}")
        return False

def run():
    print("Zerochan tag-scraper starting…")
    subs = load_subscriptions(SUBSCRIPTIONS_FILE)
    if not subs:
        print("[ABORT] No subscriptions found.")
        return

    # >>> PRE-FLIGHT: migrate any legacy files from the root into per-character folders
    migrate_root_files_to_char_folders(DEST_DIR, subs)

    total_new = 0

    for sub in subs:
        # Folder per character
        char_folder_name = folder_name_from_subscription(sub)
        char_folder = DEST_DIR / char_folder_name
        char_folder.mkdir(parents=True, exist_ok=True)

        # Filenames continue to use dotted form for consistency
        char_dots = sub.replace("+", ".")
        log(f"\n[SUB] {sub}  → folder: {char_folder_name}")

        # Preflight: only scan this character's folder
        have_ids = build_existing_ids_for_char(char_folder)
        log(f"  [INFO] Stored IDs in folder: {len(have_ids)}")

        # Gather IDs from the first N pages
        all_found_ids: Set[str] = set()
        for url in page_urls_for_subscription(sub, MAX_PAGES_PER_TAG):
            soup = get_soup(url, dump_name=re.sub(r"[^\w]+", "_", url))
            if not soup:
                continue
            ul = find_thumbs_ul(soup)
            if not ul:
                continue
            ids = extract_ids_from_ul(ul)
            all_found_ids.update(ids)
            time.sleep(REQUEST_DELAY)

        if not all_found_ids:
            log("  [INFO] No IDs found on tag pages.")
            continue

        # Filter to only missing IDs for this character
        missing_ids = [i for i in sorted(all_found_ids) if i not in have_ids]
        log(f"  [INFO] Found {len(all_found_ids)} ids; missing {len(missing_ids)} new")

        # Download into the character's folder
        for img_id in missing_ids:
            candidates = static_candidates(sub, img_id)
            saved = False
            for cand in candidates:
                ext = ".jpg" if cand.endswith(".jpg") else ".png"
                dest = char_folder / f"{char_dots}_{img_id}{ext}"
                if dest.exists():
                    log(f"    [SKIP] exists: {dest.name}")
                    saved = True
                    break
                # one GET (no HEAD) to be gentler
                if download(cand, dest):
                    saved = True
                    break
            if not saved:
                log(f"    [MISS] Could not fetch id={img_id} as jpg/png")
            time.sleep(REQUEST_DELAY)

        total_new += len(missing_ids)

    print(f"\n[SUMMARY] New images downloaded this run: {total_new}")
    print("[DONE]")

if __name__ == "__main__":
    run()
