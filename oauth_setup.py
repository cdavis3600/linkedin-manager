"""
oauth_setup.py — One-time LinkedIn OAuth 2.0 setup script.

Run this ONCE to authorize the app with your LinkedIn account.
It will:
  1. Open the LinkedIn authorization URL in your browser
  2. Start a local server to catch the OAuth callback
  3. Exchange the code for an access token
  4. Save LINKEDIN_ACCESS_TOKEN and LINKEDIN_MEMBER_ID to your .env file

Usage:
  python oauth_setup.py
"""
import os
import sys
import webbrowser
import http.server
import urllib.parse
import threading
import requests
from dotenv import load_dotenv, set_key

load_dotenv()

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback")
SCOPES = "openid profile email w_member_social"

ENV_FILE = ".env"
AUTH_CODE = None
SERVER_DONE = threading.Event()


# ─────────────────────────────────────────────
#  Local callback server
# ─────────────────────────────────────────────

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:50px">
                <h2>&#10003; Authorization successful!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {error}</h2></body></html>".encode())

        SERVER_DONE.set()

    def log_message(self, format, *args):
        pass  # suppress server log spam


def start_callback_server():
    port = int(REDIRECT_URI.split(":")[-1].split("/")[0])
    server = http.server.HTTPServer(("localhost", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


# ─────────────────────────────────────────────
#  OAuth flow
# ─────────────────────────────────────────────

def get_auth_url() -> str:
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "linkedin_manager_setup",
    })
    return f"https://www.linkedin.com/oauth/v2/authorization?{params}"


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_member_id(access_token: str) -> str:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["sub"]


def save_to_env(key: str, value: str):
    """Update or add a key in the .env file."""
    set_key(ENV_FILE, key, value)
    print(f"  ✅ Saved {key} to .env")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  LinkedIn Manager — OAuth Setup")
    print("="*55)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\n❌ LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env first.")
        sys.exit(1)

    print(f"\n→ Client ID: {CLIENT_ID[:8]}...")
    print(f"→ Redirect URI: {REDIRECT_URI}")
    print(f"→ Scopes: {SCOPES}\n")

    # Start callback server
    server = start_callback_server()
    print("→ Local callback server started.")

    # Open browser
    auth_url = get_auth_url()
    print(f"\nOpening LinkedIn authorization in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for callback
    print("Waiting for authorization...")
    SERVER_DONE.wait(timeout=120)
    server.shutdown()

    if not AUTH_CODE:
        print("\n❌ Authorization failed or timed out.")
        sys.exit(1)

    print(f"\n✅ Authorization code received.")

    # Exchange for token
    print("→ Exchanging code for access token...")
    try:
        token_data = exchange_code_for_token(AUTH_CODE)
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")
        sys.exit(1)

    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", "unknown")
    print(f"✅ Access token received (expires in {expires_in}s)")

    # Get member ID
    print("→ Fetching your LinkedIn member ID...")
    try:
        member_id = get_member_id(access_token)
    except Exception as e:
        print(f"❌ Failed to fetch member ID: {e}")
        sys.exit(1)

    print(f"✅ Member ID: {member_id}")

    # Save to .env
    print("\nSaving credentials to .env...")
    save_to_env("LINKEDIN_ACCESS_TOKEN", access_token)
    save_to_env("LINKEDIN_MEMBER_ID", member_id)

    print("\n" + "="*55)
    print("  ✅ OAuth setup complete!")
    print("="*55)
    print("\nYou can now run the LinkedIn Manager:")
    print("  python main.py\n")


if __name__ == "__main__":
    main()
