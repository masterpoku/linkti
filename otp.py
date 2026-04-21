#!/usr/bin/env python3
import argparse
import base64
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ================================
# CONFIG
# ================================
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
ROOT = Path(__file__).resolve().parent
CREDENTIALS = ROOT / "apikey.json"
TOKENS_DIR = ROOT / "tokens"
TOKENS_DIR.mkdir(exist_ok=True)

OTP_RE = re.compile(r"\b(\d{4,8})\b")  # OTP 4–8 digit

# ================================
# TOKEN MANAGEMENT
# ================================
def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name)

def _token_path(hint: str) -> Path:
    return TOKENS_DIR / f"{_safe(hint)}.json"

def get_service(user_hint: str):
    creds = None
    tpath = _token_path(user_hint)

    if tpath.exists():
        creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS.exists():
                raise SystemExit("apikey.json tidak ditemukan.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")

        tpath.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)

# ================================
# GMAIL QUERY (TODAY)
# ================================
def gmail_query_today():
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return f'after:{start.strftime("%Y/%m/%d")} before:{end.strftime("%Y/%m/%d")}'

# ================================
# LIST MESSAGE IDS
# ================================
def list_ids(service, query, max_results=10):
    ids = []
    page_token = None

    while True:
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(100, max_results - len(ids)),
            pageToken=page_token
        ).execute()

        ids.extend([m["id"] for m in resp.get("messages", [])])
        page_token = resp.get("nextPageToken")

        if not page_token or len(ids) >= max_results:
            break

    return ids

# ================================
# READ SUBJECT ONLY
# ================================
def read_subject(service, msg_id: str) -> str:
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["Subject"]
    ).execute()

    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name") == "Subject":
            return h.get("value", "")
    return ""

# ================================
# EXTRACT OTP FROM SUBJECT
# ================================
def extract_otp_from_subject(subject: str):
    m = OTP_RE.search(subject)
    return m.group(1) if m else None

# ================================
# PROCESS SINGLE EMAIL
# ================================
def get_otp_single(
    gmail_account: str,
    target_email: str,
    max_results: int,
    wait: int,
    interval: int
):
    service = get_service(gmail_account)
    deadline = time.time() + wait

    query = f'in:inbox to:{target_email}'

    while time.time() < deadline:
        # print("[OTP] checking inbox...")
        ids = list_ids(service, query, max_results=max_results)

        for msg_id in ids:
            subject = read_subject(service, msg_id)
            otp = extract_otp_from_subject(subject)
            if otp:
                # print(f"[OTP] FOUND → {otp}")
                # print(f"[SUBJECT] {subject}")
                return otp

        time.sleep(interval)

    raise TimeoutError("OTP tidak ditemukan (timeout)")

# ================================
# MAIN
# ================================
def main():
    ap = argparse.ArgumentParser(description="Ambil OTP dari SUBJECT Gmail (Single)")
    ap.add_argument("--user", default="wafi.clouds.ide@gmail.com", help="Akun Gmail")
    ap.add_argument("--target", required=True, help="Email tujuan (to:)")
    ap.add_argument("--wait", type=int, default=60, help="Max tunggu OTP (detik)")
    ap.add_argument("--interval", type=int, default=5, help="Interval cek inbox")
    ap.add_argument("--max", type=int, default=10, help="Max email dicek")
    args = ap.parse_args()


    otp = get_otp_single(
        gmail_account=args.user,
        target_email=args.target,
        max_results=args.max,
        wait=args.wait,
        interval=args.interval
    )

    print(otp)

if __name__ == "__main__":
    main()
