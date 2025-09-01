import os
import re
import time
import json
import pathlib
from typing import List, Set, Dict, Optional
from urllib.parse import quote, unquote
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# ================== CONFIG ==================

SCRIPT_DIR = Path(__file__).parent
SUBSCRIPTIONS_FILE = SCRIPT_DIR / "subscriptions.txt"  # <- lives next to the script
DEST_DIR = pathlib.Path.home() / "Pictures" / "Zerochan"
DEST_DIR.mkdir(parents=True, exist_ok=True)

# How many pages per tag to scan: page 1 = base URL, page 2 = ?p=2, etc.
MAX_PAGES_PER_TAG = 3

# Delay between HTTP requests (be gentle)
REQUEST_DELAY = 2

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

# ================== PRE/POST ==================
def load_subscriptions(path: str) -> List[str]:
    if not os.path.exists(path):
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

def build_existing_index(folder: pathlib.Path) -> Dict[str, Set[str]]:
    """
    Build {character_dots_lower -> set(ids)} by scanning filenames like
    Artoria.Caster_4572543.jpg  (or .png)
    """
    idx: Dict[str, Set[str]] = {}
    rx = re.compile(r"^(?P<char>.+?)_(?P<id>\d+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)
    for p in folder.iterdir():
        if not p.is_file():
            continue
        m = rx.match(p.name)
        if not m:
            continue
        char_dots = m.group("char").lower()
        img_id = m.group("id")
        idx.setdefault(char_dots, set()).add(img_id)
    log(f"[INFO] Preflight index built for {len(idx)} characters")
    return idx

# ================== HTTP / PARSE ==================
def get_soup(url: str, dump_name: Optional[str] = None) -> Optional[BeautifulSoup]:
    log(f"[HTTP] GET {url}")
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        log(f"[HTTP] -> {r.status_code} ({len(r.content)} bytes)")
        if SAVE_HTML_DEBUG and dump_name:
            try:
                (DEBUG_DIR / (dump_name + ".html")).write_bytes(r.content)
            except Exception as e:
                log(f"[WARN] Could not write debug HTML: {e}")
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log(f"[ERROR] GET failed: {e}")
        return None

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
        # Strategy A: /1234567 in a.thumb href
        a_thumb = li.select_one("div > a.thumb")
        if a_thumb:
            href = a_thumb.get("href", "")
            m = re.search(r"/(\d+)(?:[/?#]|$)", href)
            if m:
                ids.add(m.group(1))
                continue

        # Strategy B: a.fav[data-id]
        a_fav = li.select_one("a.fav")
        if a_fav:
            did = a_fav.get("data-id")
            if did and did.isdigit():
                ids.add(did)
                continue

        # Strategy C: any element with data-id
        node = li.select_one("[data-id]")
        if node:
            did = node.get("data-id")
            if did and did.isdigit():
                ids.add(did)
                continue

        # Strategy D: any <a href="/123…"> inside the li
        for a in li.select("a[href]"):
            m = re.search(r"/(\d+)(?:[/?#]|$)", a["href"])
            if m:
                ids.add(m.group(1))
                break

    log(f"[DEBUG] Extracted {len(ids)} IDs from container")
    return sorted(ids)


def head_or_get_exists(url: str) -> bool:
    try:
        hr = SESSION.head(url, timeout=TIMEOUT, allow_redirects=True)
        log(f"    [HEAD] {url} -> {hr.status_code}")
        if hr.status_code == 200:
            return True
        if hr.status_code in (403, 404):
            return False
    except Exception as e:
        log(f"    [HEAD] error: {e}")
    # fallback GET (some servers don’t HEAD properly)
    try:
        gr = SESSION.get(url, stream=True, timeout=TIMEOUT)
        log(f"    [GET?] {url} -> {gr.status_code}")
        return gr.status_code == 200
    except Exception as e:
        log(f"    [GET?] error: {e}")
        return False

# ================== CORE ==================
def page_urls_for_subscription(sub_plus: str, max_pages: int) -> List[str]:
    """
    Build: page 1 = https://www.zerochan.net/<slug>
           page n = …?p=n
    We first unquote to neutralize any pre-encoded %xx, normalize spaces to '+',
    then quote again with '+' kept as is.
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
    https://static.zerochan.net/<Name.Dot9s>.full.<id>.jpg
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

    existing = build_existing_index(DEST_DIR)
    total_new = 0

    for sub in subs:
        char_dots = sub.replace("+", ".")
        char_key = char_dots.lower()
        have_ids = existing.get(char_key, set())
        log(f"\n[SUB] {sub}  (stored IDs: {len(have_ids)})")

        all_found_ids: Set[str] = set()

        # Gather IDs from the first N pages
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

        # Try downloading only the missing ones
        for img_id in missing_ids:
            # Build destination filename using your scheme: <char>_<id>.<ext>
            candidates = static_candidates(sub, img_id)
            saved = False
            for cand in candidates:
                ext = ".jpg" if cand.endswith(".jpg") else ".png"
                dest = DEST_DIR / f"{char_dots}_{img_id}{ext}"
                if dest.exists():
                    log(f"    [SKIP] exists: {dest.name}")
                    saved = True
                    break
                if head_or_get_exists(cand) and download(cand, dest):
                    saved = True
                    break
            if not saved:
                log(f"    [MISS] Could not fetch id={img_id} as jpg/png")
            time.sleep(REQUEST_DELAY)

        # Update in-memory index so later subs in this run see these IDs too
        existing.setdefault(char_key, set()).update(missing_ids)
        total_new += len(missing_ids)

    print(f"\n[SUMMARY] New images downloaded this run: {total_new}")
    print("[DONE]")

if __name__ == "__main__":
    run()
