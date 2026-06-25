#!/usr/bin/env python3
"""YouTube Data API v3 uploader for the UPSC video pipeline.

Uploads a rendered ``digest.mp4`` to the channel's YouTube account and returns
the resulting video id + watch URL. Called from ``_kick_video`` in
``api/upsc_routes.py`` after the QC gate passes.

Public contract
---------------
    upload(video_path: str, meta: dict) -> {"youtube_id": str, "youtube_url": str}

``meta`` keys (all optional except where noted):
    title        str   video title (required, non-empty)
    description  str   video description
    tags         list[str] | str   tags (a comma-string is also accepted)
    privacy      str   one of "public" | "unlisted" | "private" (default "private")

Implementation notes
---------------------
- Uses a resumable ``MediaFileUpload`` so large MP4s survive transient network
  blips; ``request.next_chunk()`` is retried on the documented retriable HTTP
  status codes.
- ``snippet.categoryId`` is fixed to ``"27"`` (Education).
- ``status.privacyStatus`` comes straight from ``meta["privacy"]``.

Authentication — env vars (read from the process / ``.env``)
------------------------------------------------------------
    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN

These are fed to ``google.oauth2.credentials.Credentials`` with
``token_uri = https://oauth2.googleapis.com/token`` and the single scope
``https://www.googleapis.com/auth/youtube.upload``. The access token is
refreshed on use, so only the long-lived refresh token needs to be stored.

ONE-TIME OFFLINE OAUTH CONSENT — how to mint YOUTUBE_REFRESH_TOKEN
-----------------------------------------------------------------
Do this ONCE on a machine with a browser, then copy the refresh token into the
server's ``.env``. The YouTube Data API has no service-account upload path, so a
human must grant consent for the channel owner's Google account.

  1. In Google Cloud Console: create (or reuse) a project, enable the
     "YouTube Data API v3", and configure the OAuth consent screen. Add the
     channel-owner Google account as a Test User while the app is in "Testing"
     (otherwise refresh tokens expire after 7 days).
  2. Create an OAuth client of type "Desktop app". Note the Client ID and
     Client Secret -> these become YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET.
  3. Run the snippet below locally (needs ``google-auth-oauthlib``). It opens a
     browser, you log in as the channel owner and approve the upload scope, and
     it prints a refresh token:

        from google_auth_oauthlib.flow import InstalledAppFlow
        SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": "<YOUTUBE_CLIENT_ID>",
                    "client_secret": "<YOUTUBE_CLIENT_SECRET>",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            },
            scopes=SCOPES,
        )
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        print("YOUTUBE_REFRESH_TOKEN =", creds.refresh_token)

     ``access_type="offline"`` + ``prompt="consent"`` is what forces Google to
     hand back a refresh token (it is omitted on repeat consents otherwise).
  4. Put the three values in ``.env``:
        YOUTUBE_CLIENT_ID=...
        YOUTUBE_CLIENT_SECRET=...
        YOUTUBE_REFRESH_TOKEN=...

Manual smoke test:
    python scripts/youtube_upload.py path/to/digest.mp4 --title "Test" --privacy private
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

# Imports are deferred into helpers so that merely importing this module (e.g.
# during ``ast.parse`` / unit collection on a box without the Google libs
# installed) does not explode. The libs are only needed at upload time.

VALID_PRIVACY = {"public", "unlisted", "private"}
EDUCATION_CATEGORY_ID = "27"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# HTTP statuses YouTube documents as safe to retry on a resumable upload.
_RETRIABLE_STATUS_CODES = (500, 502, 503, 504)
_MAX_RETRIES = 5


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _build_credentials():
    """Build refreshable OAuth credentials from the three env vars."""
    from google.oauth2.credentials import Credentials  # type: ignore

    client_id = _env("YOUTUBE_CLIENT_ID")
    client_secret = _env("YOUTUBE_CLIENT_SECRET")
    refresh_token = _env("YOUTUBE_REFRESH_TOKEN")

    missing = [
        n
        for n, v in (
            ("YOUTUBE_CLIENT_ID", client_id),
            ("YOUTUBE_CLIENT_SECRET", client_secret),
            ("YOUTUBE_REFRESH_TOKEN", refresh_token),
        )
        if not v
    ]
    if missing:
        raise RuntimeError(
            "YouTube upload not configured; missing env var(s): "
            + ", ".join(missing)
            + ". See the module docstring for the one-time OAuth consent flow."
        )

    creds = Credentials(
        token=None,  # no access token yet; force a refresh on first use
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )

    # Mint a fresh access token up front so a bad config fails loudly here.
    from google.auth.transport.requests import Request  # type: ignore

    creds.refresh(Request())
    return creds


def _normalise_tags(raw: Any) -> List[str]:
    """Accept a list, a comma string, or None and return a clean list[str]."""
    if not raw:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    return [str(t).strip() for t in parts if str(t).strip()]


def _normalise_privacy(raw: Any) -> str:
    privacy = (str(raw).strip().lower() if raw else "") or "private"
    if privacy not in VALID_PRIVACY:
        privacy = "private"
    return privacy


def upload(video_path: str, meta: Dict[str, Any]) -> Dict[str, str]:
    """Upload ``video_path`` to YouTube and return ids.

    Returns ``{"youtube_id": str, "youtube_url": str}``.
    Raises ``RuntimeError`` on misconfiguration / missing file / upload failure.
    """
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"video_path does not exist: {video_path!r}")

    meta = meta or {}
    title = str(meta.get("title") or "").strip()
    if not title:
        raise RuntimeError("meta['title'] is required and must be non-empty")

    description = str(meta.get("description") or "").strip()
    tags = _normalise_tags(meta.get("tags"))
    privacy = _normalise_privacy(meta.get("privacy"))

    # ---- Google client imports (deferred) --------------------------------
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    from googleapiclient.http import MediaFileUpload  # type: ignore

    creds = _build_credentials()
    # cache_discovery=False avoids an oauth2client warning + a network/file hit.
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body: Dict[str, Any] = {
        "snippet": {
            "title": title[:100],  # YouTube hard-caps titles at 100 chars
            "description": description,
            "tags": tags,
            "categoryId": EDUCATION_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        chunksize=8 * 1024 * 1024,  # 8 MiB chunks for resumable upload
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    retries = 0
    while response is None:
        try:
            _status, response = request.next_chunk()
        except HttpError as exc:  # pragma: no cover - network dependent
            if exc.resp is not None and exc.resp.status in _RETRIABLE_STATUS_CODES:
                retries += 1
                if retries > _MAX_RETRIES:
                    raise RuntimeError(
                        f"YouTube upload failed after {_MAX_RETRIES} retries: {exc}"
                    ) from exc
                continue
            raise RuntimeError(f"YouTube upload failed: {exc}") from exc

    video_id = (response or {}).get("id")
    if not video_id:
        raise RuntimeError(f"YouTube upload returned no video id: {response!r}")

    return {
        "youtube_id": video_id,
        "youtube_url": f"https://youtu.be/{video_id}",
    }


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Upload a video to YouTube.")
    parser.add_argument("video_path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="", help="comma-separated")
    parser.add_argument(
        "--privacy", default="private", choices=sorted(VALID_PRIVACY)
    )
    args = parser.parse_args()

    result = upload(
        args.video_path,
        {
            "title": args.title,
            "description": args.description,
            "tags": args.tags,
            "privacy": args.privacy,
        },
    )
    print(result["youtube_url"])


if __name__ == "__main__":
    _cli()
