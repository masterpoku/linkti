import requests
import json
import re
import argparse


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="format: email|pass|refresh_token|client_id")
    parser.add_argument("--target", default="info@accounts.linktr.ee", help="filter sender")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        email, password, refresh_token, client_id = args.data.split("|", 3)
    except ValueError:
        print("❌ Format salah. Gunakan: email|pass|refresh_token|client_id")
        return

    url = "https://tools.dongvanfb.net/api/get_messages_oauth2"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://dongvanfb.net",
        "Referer": "https://dongvanfb.net/"
    }

    payload = {
        "email": email,
        "pass": password,
        "refresh_token": refresh_token,
        "client_id": client_id
    }

    response = requests.post(url, headers=headers, json=payload)

    try:
        data = response.json()
    except:
        print("❌ Gagal parse JSON")
        return

    if not data.get("status"):
        print("❌ Request gagal")
        return

    messages = data.get("messages", [])
    target = args.target.lower()

    for m in messages:
        sender = m.get("from", "").lower()
        subject = m.get("subject", "")

        # filter sender
        if target not in sender:
            continue

        # cari OTP
        match = re.search(r"\b\d{6}\b", subject)
        if match:
            print(match.group())
            return

    print("⚠️ OTP tidak ditemukan")


if __name__ == "__main__":
    main()