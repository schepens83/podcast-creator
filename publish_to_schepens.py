#!/usr/bin/env python3
"""publish-to-schepens -- stage 3 of the podcast-creator chain.

Upload an MP3 (or a YouTube URL, transcoded via yt-dlp) to the schepens.cc
podcast. The MP3 is produced by `tts` (stage 2). Title/description/date are
read from the MP3's ID3 tags by the server, but can be overridden here.

Usage:
    publish-to-schepens books episode.mp3
    publish-to-schepens books episode.mp3 --title "Return to the Little Kingdom"
    publish-to-schepens books episode.mp3 --replace
    publish-to-schepens youtube "https://youtube.com/watch?v=..."

Reads SCHEPENS_API_TOKEN from the environment (or SCHEPENS_API_TOKEN_FILE).
Re-uploading identical audio is a no-op (the server dedupes by content hash);
use --replace to overwrite an existing episode with the same filename.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import quote

import requests

from pcommon import CHAIN_HELP, get_secret, preflight

OUT_DIR = pathlib.Path("/tmp/podcast-mp3s")
YT_DLP = pathlib.Path.home() / ".local/bin/yt-dlp"

PODCAST_URL = "https://schepens.cc/podcast/api/episodes"
EPISODES_PAGE = "https://schepens.cc/podcast/episodes"
PODCASTS = {"books", "youtube"}


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_secret('SCHEPENS_API_TOKEN')}",
        "Accept": "application/json",
    }


def download_all(urls: list[str]) -> None:
    for url in urls:
        print(f"[download] {url}")
        result = subprocess.run([
            str(YT_DLP),
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", str(OUT_DIR / "%(title)s.%(ext)s"),
            url,
        ])
        if result.returncode != 0:
            print(f"[error] Download failed: {url}", file=sys.stderr)
            sys.exit(1)


def sanitize(mp3s: list[pathlib.Path]) -> list[pathlib.Path]:
    cleaned = []
    for mp3 in mp3s:
        name = mp3.stem
        name = "".join(c if c.isalnum() or c in " -" else " " for c in name)
        name = " ".join(name.split())
        new_path = mp3.with_name(name + ".mp3")
        if new_path != mp3:
            mp3.rename(new_path)
        cleaned.append(new_path)
    return cleaned


def delete_episode(filename: str) -> None:
    url = f"{PODCAST_URL}/{quote(filename)}"
    resp = requests.delete(url, headers=auth_headers(), allow_redirects=False)
    if resp.status_code in (200, 204, 404):
        print(f"[replace] removed existing '{filename}' ({resp.status_code})")
    else:
        print(f"[warn] delete of '{filename}' returned {resp.status_code}: {resp.text}", file=sys.stderr)


def upload_one(mp3: pathlib.Path, podcast: str, title, description, date, replace: bool) -> None:
    filename = mp3.name
    if replace:
        delete_episode(filename)

    data = {"episode[podcast]": podcast}
    if title:
        data["episode[title]"] = title
    if description:
        data["episode[description]"] = description
    if date:
        data["episode[date]"] = date

    print(f"[upload] {filename} -> {podcast}")
    with mp3.open("rb") as f:
        resp = requests.post(
            PODCAST_URL,
            headers=auth_headers(),
            files={"episode[audio]": (filename, f, "audio/mpeg")},
            data=data,
            allow_redirects=False,
        )

    if resp.status_code in (200, 201):
        try:
            ep = (resp.json() or {}).get("episode", {})
        except ValueError:
            ep = {}
        title_out = ep.get("title", filename)
        dur = ep.get("duration")
        print(f"[upload] OK: \"{title_out}\"" + (f" ({dur})" if dur else ""))
        print(f"[upload] live at: {EPISODES_PAGE}")
        return

    # Idempotent: the server dedupes by content hash. A duplicate is success.
    if resp.status_code == 422 and "already" in resp.text.lower():
        print(f"[upload] already published (identical audio): {filename} -- skipping.")
        print("         Re-render changed audio, or pass --replace to overwrite.")
        return

    if resp.status_code in (302, 303):
        print(f"[upload] OK ({resp.status_code})")
        return

    print(f"[error] Upload failed: {resp.status_code} {resp.text}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog=CHAIN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("podcast", choices=sorted(PODCASTS), help="Which feed to publish to")
    ap.add_argument("sources", nargs="+", help="Local .mp3 path(s) and/or YouTube URL(s)")
    ap.add_argument("--title", help="Override the episode title (default: from the mp3's ID3 tag)")
    ap.add_argument("--description", help="Override the episode description")
    ap.add_argument("--date", help="Override the episode date (e.g. 2026-06-26)")
    ap.add_argument("--replace", action="store_true", help="Delete an existing episode with the same filename first")
    args = ap.parse_args()

    preflight(secrets=["SCHEPENS_API_TOKEN"])

    urls: list[str] = []
    local_files: list[pathlib.Path] = []
    for src in args.sources:
        p = pathlib.Path(src)
        if p.exists() and p.is_file():
            local_files.append(p.resolve())
        else:
            urls.append(src)

    if urls:
        preflight(binaries=[str(YT_DLP)] if YT_DLP.exists() else ["yt-dlp"])

    print(f"{len(urls)} URL(s), {len(local_files)} local file(s) -> {args.podcast}.")
    OUT_DIR.mkdir(exist_ok=True)

    try:
        if urls:
            download_all(urls)
        for src in local_files:
            shutil.copy2(src, OUT_DIR / src.name)

        mp3s = sorted(OUT_DIR.glob("*.mp3"))
        if not mp3s:
            print("[error] No MP3s found to upload.", file=sys.stderr)
            return 1

        mp3s = sanitize(mp3s)
        for mp3 in mp3s:
            upload_one(mp3, args.podcast, args.title, args.description, args.date, args.replace)
    finally:
        shutil.rmtree(OUT_DIR, ignore_errors=True)
        print("[cleanup] temp mp3s removed.")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
