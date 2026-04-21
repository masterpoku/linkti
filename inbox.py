#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import requests
import time
import jwt
import imaplib
import email
from email.header import decode_header
from datetime import datetime

# =======================================================
# CONFIG
# =======================================================

TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993

GRAPH_MAIL = (
    "https://graph.microsoft.com/v1.0/me/messages"
    "?$top=10"
    "&$orderby=receivedDateTime desc"
)

CREDS_FILE = "creds.txt"
MAX_EMAILS_PER_ACCOUNT = 10
LINKTREE_FROM = "info@accounts.linktr.ee"

# =======================================================
# ARGUMENTS
# =======================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="XOAUTH2 Linktree OTP Reader (All folders)"
    )
    parser.add_argument(
        "--email",
        help="Scan only this email address (must exist in creds.txt)",
        default=None
    )
    return parser.parse_args()

# =======================================================
# HELPERS
# =======================================================

def decode_mime_header(raw):
    if not raw:
        return ""
    parts = decode_header(raw)
    result = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                result += text.decode(enc or "utf-8", errors="replace")
            except:
                result += text.decode("utf-8", errors="replace")
        else:
            result += text
    return result

def load_creds(path=CREDS_FILE):
    creds = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or "|" not in s:
                continue
            parts = s.split("|")
            if len(parts) < 4:
                continue
            creds.append({
                "email": parts[0].strip(),
                "refresh_token": parts[2].strip(),
                "client_id": parts[3].strip(),
            })
    return creds

def is_jwt(token):
    return token.count('.') == 2

def show_scopes(access_token):
    if is_jwt(access_token):
        try:
            decoded = jwt.decode(access_token, options={"verify_signature": False})
            print(f"     • aud: {decoded.get('aud')}")
            print(f"     • scp: {decoded.get('scp')}")
        except:
            pass

# =======================================================
# TOKEN SYSTEM
# =======================================================

def get_imap_token(refresh_token, client_id):
    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": (
            "offline_access "
            "https://outlook.office.com/IMAP.AccessAsUser.All"
        )
    }
    r = requests.post(TOKEN_URL, data=data)
    if r.status_code != 200:
        return None, r.text
    return r.json().get("access_token"), None

def get_graph_token(refresh_token, client_id):
    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "offline_access Mail.Read"
    }
    r = requests.post(TOKEN_URL, data=data)
    if r.status_code != 200:
        return None
    return r.json().get("access_token")

# =======================================================
# IMAP
# =======================================================

def build_xoauth2_string(email_addr, access_token):
    return f"user={email_addr}\1auth=Bearer {access_token}\1\1"

def fetch_all_folders_imap(email_addr, access_token, max_messages=MAX_EMAILS_PER_ACCOUNT):
    msgs = []
    imap = None

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        sasl = build_xoauth2_string(email_addr, access_token)
        imap.authenticate("XOAUTH2", lambda _: sasl.encode())

        status, boxes = imap.list()
        if status != "OK":
            return msgs

        for box in boxes:
            try:
                folder = box.decode(errors="ignore").split(' "/" ')[-1]
                status, _ = imap.select(folder, readonly=True)
                if status != "OK":
                    continue

                status, data = imap.search(
                    None,
                    'FROM', f'"{LINKTREE_FROM}"'
                )
                if status != "OK" or not data or not data[0]:
                    continue

                ids = data[0].split()[-max_messages:]

                for num in reversed(ids):
                    status, msg_data = imap.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    subj = decode_mime_header(msg.get("Subject", ""))

                    msgs.append({
                        "folder": folder,
                        "subject": subj
                    })

            except:
                continue

    except Exception as e:
        print(f"  ❌ IMAP error: {e}")
    finally:
        try:
            if imap:
                imap.logout()
        except:
            pass

    return msgs

# =======================================================
# GRAPH (FALLBACK)
# =======================================================

def fetch_graph_inbox(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(GRAPH_MAIL, headers=headers)
    if r.status_code != 200:
        return []

    msgs = []
    for m in r.json().get("value", []):
        frm = m.get("from", {}).get("emailAddress", {}).get("address", "")
        if frm.lower() != LINKTREE_FROM:
            continue
        msgs.append({
            "subject": m.get("subject", "")
        })
    return msgs

# =======================================================
# MAIN
# =======================================================

def main():
    args = parse_args()
    creds_list = load_creds()

    if args.email:
        creds_list = [
            c for c in creds_list
            if c["email"].lower() == args.email.lower()
        ]
        if not creds_list:
            print(f"❌ Email tidak ditemukan: {args.email}")
            return

    for acc in creds_list:
        email_addr = acc["email"]
        refresh_token = acc["refresh_token"]
        client_id = acc["client_id"]

        # print("=" * 60)
        # print(f"📨 {email_addr}")

        access_token, error_raw = get_imap_token(refresh_token, client_id)

        if not access_token:
            access_token = get_graph_token(refresh_token, client_id)
            if not access_token:
                print("  ❌ Token gagal")
                continue
            msgs = fetch_graph_inbox(access_token)
        else:
            msgs = fetch_all_folders_imap(email_addr, access_token)

        for m in msgs:
            subject = m.get("subject", "")
            match = re.search(r"\b\d{6}\b", subject)
            if match:
                print(f"{match.group()}")
                return

        print("  ⚠️ OTP tidak ditemukan")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
