"""
Run this yourself — it needs you to authorize in a real browser on your own
YouTube Music account. I (the agent) can't do that part.

It requests a device code, waits for you to approve it, then creates a small,
real, throwaway playlist on your account with a couple of known tracks so you
can confirm the whole export pipeline actually works end to end.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from app.export_service.errors import ExportDenied, ExportExpired, ExportPending
from app.export_service.youtube_music_export import create_playlist_for_user, poll_export_token, start_export

# A couple of well-known, stable video ids (from earlier live test runs) so this
# doesn't depend on catalog search working too.
TEST_TRACK_IDS = ["NmQAW7VtSHc", "KWLGyeg74es"]  # Timecop1983 - On the Run, Owl City - Fireflies


def main() -> None:
    start = start_export()
    print(f"\n1. Open {start.verification_url} in your browser")
    print(f"2. Enter this code: {start.user_code}")
    print(f"3. Approve access on your own YouTube Music / Google account")
    print(f"\nWaiting (code expires in {start.expires_in}s)...")

    deadline = time.time() + start.expires_in
    authorized_session_id = None
    while time.time() < deadline:
        try:
            authorized_session_id = poll_export_token(start.session_id)
            break
        except ExportPending:
            time.sleep(start.interval)
        except ExportExpired:
            print("Code expired before it was approved. Run this again.")
            return
        except ExportDenied:
            print("Authorization was denied.")
            return

    if not authorized_session_id:
        print("Timed out waiting for approval.")
        return

    print("Authorized! Creating a real test playlist on your account...")
    url = create_playlist_for_user(
        authorized_session_id,
        "Audelle Export Test (safe to delete)",
        "Created by try_export_live.py to verify the export pipeline.",
        TEST_TRACK_IDS,
    )
    print(f"\nSuccess: {url}")
    print("(Feel free to delete this playlist from your account afterward.)")


if __name__ == "__main__":
    main()
