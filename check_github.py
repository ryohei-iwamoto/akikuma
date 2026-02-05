#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GitHub Actions用 MW WP Form チェッカー
"""

import os
import re
import csv
import base64
import requests
from io import StringIO

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://aki-kumazawa.com/_wp"


def load_config():
    """環境変数またはローカルファイルから設定を読み込む"""
    config = {
        "WP_USERNAME": os.environ.get("WP_USERNAME"),
        "WP_PASSWORD": os.environ.get("WP_PASSWORD"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "LINE_CHANNEL_TOKEN": os.environ.get("LINE_CHANNEL_TOKEN"),
        "LINE_TARGET_ID": os.environ.get("LINE_TARGET_ID"),
    }

    # ローカルファイルから読み込み（環境変数が未設定の場合）
    id_pass_file = os.path.join(SCRIPT_DIR, "id_pass.txt")
    if os.path.exists(id_pass_file) and (not config["WP_USERNAME"] or not config["WP_PASSWORD"]):
        with open(id_pass_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if "ユーザー名" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        config["WP_USERNAME"] = parts[-1]
                elif "パスワード" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        config["WP_PASSWORD"] = parts[-1]

    line_config_file = os.path.join(SCRIPT_DIR, "line_config.txt")
    if os.path.exists(line_config_file):
        with open(line_config_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "CHANNEL_ACCESS_TOKEN" and not config["LINE_CHANNEL_TOKEN"]:
                    config["LINE_CHANNEL_TOKEN"] = value
                elif key == "TARGET_ID" and not config["LINE_TARGET_ID"]:
                    config["LINE_TARGET_ID"] = value
                elif key == "OPENAI_API_KEY" and not config["OPENAI_API_KEY"]:
                    config["OPENAI_API_KEY"] = value

    return config


# 設定読み込み
CONFIG = load_config()
WP_USERNAME = CONFIG["WP_USERNAME"]
WP_PASSWORD = CONFIG["WP_PASSWORD"]
OPENAI_API_KEY = CONFIG["OPENAI_API_KEY"]
LINE_CHANNEL_TOKEN = CONFIG["LINE_CHANNEL_TOKEN"]
LINE_TARGET_ID = CONFIG["LINE_TARGET_ID"]
STATE_FILE = os.path.join(SCRIPT_DIR, "last_max_id.txt")


def get_last_max_id():
    """最後にチェックしたIDを取得"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                pass
    return 0


def save_last_max_id(max_id):
    """最後にチェックしたIDを保存"""
    with open(STATE_FILE, "w") as f:
        f.write(str(max_id))
    print(f"last_max_id更新: {max_id}")


def recognize_captcha(image_bytes):
    """OpenAI GPT-5でCAPTCHA認識"""
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY未設定")
        return None

    # オリジナル画像を保存
    original_path = os.path.join(SCRIPT_DIR, "captcha_original.png")
    with open(original_path, "wb") as f:
        f.write(image_bytes)
    print(f"オリジナル画像保存: {original_path}")

    # GPT-5は高性能なので前処理なしでそのまま送る
    image_content = base64.b64encode(image_bytes).decode("utf-8")

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        },
        json={
            "model": "gpt-5",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "この画像にはひらがな4文字が書かれています。濁点や半濁点、小文字は含まれません。清音のみです。その4文字だけを出力してください。"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_content}",
                            "detail": "high"
                        }
                    }
                ]
            }]
        }
    )

    if resp.status_code != 200:
        print(f"OpenAI API エラー: {resp.status_code} - {resp.text[:200]}")
        return None

    text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    hiragana = "".join(c for c in text if "\u3041" <= c <= "\u3096")
    if len(hiragana) >= 4:
        return hiragana[:4]
    return None


def auto_login(max_retries=3):
    """CAPTCHA認識で自動ログイン"""
    if not WP_USERNAME or not WP_PASSWORD:
        print("WP_USERNAME/WP_PASSWORD未設定")
        return None

    for attempt in range(1, max_retries + 1):
        print(f"ログイン試行 {attempt}/{max_retries}")
        session = requests.Session()
        login_url = f"{BASE_URL}/login_09645"
        resp = session.get(login_url)

        captcha_match = re.search(r'<img[^>]*src="([^"]*captcha[^"]*)"', resp.text)
        prefix_match = re.search(r'siteguard_captcha_prefix[^>]*value="([^"]+)"', resp.text)

        if not captcha_match or not prefix_match:
            print("CAPTCHA not found")
            return None

        captcha_url = captcha_match.group(1)
        if not captcha_url.startswith("http"):
            captcha_url = "https://aki-kumazawa.com" + captcha_url

        img_resp = session.get(captcha_url)
        captcha_answer = recognize_captcha(img_resp.content)

        if not captcha_answer:
            print("CAPTCHA認識失敗")
            continue

        print(f"CAPTCHA認識: {captcha_answer}")

        resp = session.post(login_url, data={
            "log": WP_USERNAME,
            "pwd": WP_PASSWORD,
            "siteguard_captcha": captcha_answer,
            "siteguard_captcha_prefix": prefix_match.group(1),
            "wp-submit": "ログイン",
            "redirect_to": f"{BASE_URL}/wp-admin/",
            "testcookie": "1"
        }, allow_redirects=True)

        if "wp-admin" in resp.url and "login" not in resp.url.lower():
            print("ログイン成功!")
            return session

        print("ログイン失敗")

    return None


def download_csv(session):
    """CSVダウンロード"""
    url = f"{BASE_URL}/wp-admin/edit.php?post_type=mwf_285"
    resp = session.get(url)

    print(f"CSV page URL: {resp.url}")
    print(f"Status: {resp.status_code}")

    if "wp-login" in resp.url:
        print("セッション切れ - 再ログインが必要")
        return None

    # デバッグ: HTMLの一部を表示
    if "_wpnonce" not in resp.text:
        print("DEBUG: _wpnonce がページに存在しない")
        print(f"ページタイトル: {re.search(r'<title>([^<]*)</title>', resp.text)}")
        # HTMLを保存して確認
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("debug_page.html に保存しました")

    nonces = re.findall(r'name="_wpnonce"\s*value="([^"]+)"', resp.text)
    if not nonces:
        print("nonce not found")
        return None

    resp = session.post(url, data={
        "post_type": "mwf_285",
        "paged": "1",
        "download-all": "true",
        "mw-wp-form-csv-download": "1",
        "_wpnonce": nonces[-1],
        "_wp_http_referer": "/_wp/wp-admin/edit.php?post_type=mwf_285"
    })

    if resp.content.startswith(b'"ID"'):
        print("CSVダウンロード成功")
        return resp.content

    print("CSVダウンロード失敗")
    return None


def parse_csv(content):
    """CSV解析"""
    records = {}
    for enc in ["cp932", "utf-8-sig", "utf-8"]:
        try:
            text = content.decode(enc)
            break
        except:
            continue
    else:
        text = content.decode("utf-8", errors="replace")

    reader = csv.DictReader(StringIO(text))
    for row in reader:
        rid = row.get("ID", "")
        if rid:
            records[rid] = row
    return records


def send_line(message):
    """LINE送信"""
    if not LINE_CHANNEL_TOKEN or not LINE_TARGET_ID:
        print("LINE設定未完了")
        return False

    if len(message) > 5000:
        message = message[:4990] + "..."

    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"
        },
        json={
            "to": LINE_TARGET_ID,
            "messages": [{"type": "text", "text": message}]
        }
    )

    if resp.status_code == 200:
        print("LINE送信成功")
        return True
    print(f"LINE送信失敗: {resp.status_code}")
    return False


def format_record(record):
    """レコードをフォーマット"""
    lines = ["【新規お問い合わせ】"]
    priority = ["ID", "post_date", "お名前", "名前", "メールアドレス", "電話番号"]

    for key in priority:
        if key in record and record[key]:
            lines.append(f"{key}: {record[key][:100]}")

    skip = set(priority) | {"管理者メール送信先", "post_modified", "post_title", "対応状況"}
    for key, val in record.items():
        if key not in skip and val:
            lines.append(f"{key}: {val[:200]}")

    return "\n".join(lines)


def main():
    print("=" * 50)
    print("MW WP Form チェッカー (GitHub Actions)")
    print("=" * 50)

    # 1. ログイン
    session = auto_login()
    if not session:
        print("ログイン失敗、終了")
        return

    # 2. CSV取得
    csv_content = download_csv(session)
    if not csv_content:
        print("CSV取得失敗、終了")
        return

    # 3. 解析
    records = parse_csv(csv_content)
    print(f"総レコード数: {len(records)}")

    if not records:
        return

    # 4. 比較
    max_id = max(int(rid) for rid in records.keys())
    last_max_id = get_last_max_id()
    print(f"前回のmax_id: {last_max_id}")
    print(f"今回のmax_id: {max_id}")

    new_entries = [
        records[rid] for rid in records
        if int(rid) > last_max_id
    ]

    print(f"新規: {len(new_entries)} 件")

    # 5. LINE通知
    if new_entries:
        for entry in sorted(new_entries, key=lambda x: int(x.get("ID", 0)), reverse=True):
            msg = format_record(entry)
            print("-" * 40)
            print(msg)
            print("-" * 40)
            send_line(msg)

        # 6. 状態保存
        save_last_max_id(max_id)
    else:
        print("新規問い合わせなし")


if __name__ == "__main__":
    main()
