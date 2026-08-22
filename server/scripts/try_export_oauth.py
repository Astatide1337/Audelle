import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from ytmusicapi.auth.oauth.credentials import OAuthCredentials

creds = OAuthCredentials(
    client_id=os.environ["YTMUSIC_OAUTH_CLIENT_ID"],
    client_secret=os.environ["YTMUSIC_OAUTH_CLIENT_SECRET"],
)

code = creds.get_code()
print("get_code() response keys:", list(code.keys()))
print("user_code:", code.get("user_code"))
print("verification_url:", code.get("verification_url"))
print("expires_in:", code.get("expires_in"))
print("interval:", code.get("interval"))

# Poll once immediately, without completing the browser step, to see the
# "still pending" response shape (this should NOT succeed).
result = creds.token_from_code(code["device_code"])
print("\ntoken_from_code() response keys:", list(result.keys()))
print("access_token present:", bool(result.get("access_token")))
print("refresh_token present:", bool(result.get("refresh_token")))
