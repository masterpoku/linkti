import csv
import time
import re
import requests
import random
from pathlib import Path
from typing import List, Optional

# GANTI INI: Pakai seleniumwire biar bisa sadap traffic
import random
from seleniumwire import webdriver 
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC



def get_final_linktree_url(driver):
    print("?? Mengambil URL Linktree yang sudah jadi...")
    try:
        # Kita pakai selector yang lu kasih dari screenshot (elemen div di dalam button)
        final_url = driver.execute_script("""
            const el = document.querySelector('button[aria-label="Open share menu"] div.truncate');
            if (el) {
                let text = el.innerText.trim();
                // Kalau formatnya cuma 'linktr.ee/username', kita tambahin https://
                return text.startsWith('http') ? text : 'https://' + text;
            }
            return null;
        """)
        
        if final_url:
            print(f"?? URL Linktree Lu: {final_url}")
            return final_url
        else:
            print("?? Elemen URL nggak ketemu, coba selector backup...")
            # Backup: cari tag <a> atau div lain yang mengandung linktr.ee
            return driver.execute_script("return document.querySelector('div.truncate.text-primary')?.innerText.trim();")
            
    except Exception as e:
        print(f"? Gagal ambil URL: {e}")
        return None
# =============================
# ADDITIONAL HELPER: AUTO-TOKEN
# =============================
def get_bearer_token_automatically(driver):
    """
    Menyadap request headers yang lewat ke domain graph.linktr.ee
    untuk mendapatkan Authorization Bearer yang valid.
    """
    print("? Mencari Bearer Token dari traffic...")
    # Loop request yang sudah terjadi
    for request in reversed(driver.requests):
        if 'graph.linktr.ee' in request.url:
            auth = request.headers.get('authorization') or request.headers.get('Authorization')
            if auth and 'Bearer' in auth:
                # Pastikan token tidak terpotong (kadang ada char aneh di logs)
                clean_token = auth.strip()
                print(f"? Token Ditemukan: {clean_token[:30]}...")
                return clean_token
    return None

def add_link_pure_api(driver, title, link_url, image_path=None):
    print(f"?? Menambahkan Link via API: {title}")
    
    try:
        bearer_token = get_bearer_token_automatically(driver)

        if not bearer_token:
            token_raw = driver.execute_script("return window.localStorage.getItem('auth_token')")
            if token_raw:
                bearer_token = f"Bearer {token_raw}"

        if not bearer_token:
            print("? Gagal ambil token!")
            return

        # ?? AMBIL PROXY
        proxy = get_proxy()
        if not proxy:
            return

        proxies = {
            "http": f"http://{proxy}",
            "https": f"http://{proxy}"
        }

        api_url = "https://graph.linktr.ee/graphql"

        headers = {
            "Authorization": bearer_token,
            "Content-Type": "application/json",
            "x-graphql-client-name": "ui-link-editor",
            "x-graphql-client-version": "1.0.0",
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Origin": "https://linktr.ee",
            "Referer": "https://linktr.ee/"
        }

        payload = {
            "operationName": "addLink",
            "variables": {
                "type": "CLASSIC",
                "input": {
                    "url": link_url,
                    "title": title,
                    "active": True,
                    "meta": {"source": "admin", "channel": "internal_app"},
                    "modifiers": {
                        "thumbnailUrl": image_path,
                        "layoutOption": "stack"
                    },
                }
            },
            "query": """
            mutation addLink($type: LinkType!, $input: AddLinkInput) {
              addLink(type: $type, input: $input) {
                id
                title
                url
              }
            }
            """
        }

        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            proxies=proxies,
            timeout=30
        )

        if response.status_code == 200:
            res_json = response.json()
            if "errors" in res_json:
                print(f"? API Error: {res_json['errors'][0]['message']}")
            else:
                data = res_json.get('data', {}).get('addLink', {})
                print(f"? Berhasil Insert API: {data.get('title')} (ID: {data.get('id')})")
        else:
            print(f"? Server Reject: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"? Error API: {str(e)}")
# =============================
# CONFIG
# =============================
CSV_FILE = "data.csv"
SIGNUP_URL = "https://linktr.ee/universal-login#/register"
ADMIN_URL = "https://linktr.ee/admin"
AVATAR_PATH = str(Path("janda.jpg").absolute())
WAIT_TIME = 20


# =============================
# JS HELPERS (REACT SAFE)
# =============================
JS_SET_VALUE = """
const el = document.querySelector(arguments[0]);
if (!el) return false;

let proto = null;
if (el.tagName === 'TEXTAREA') {
  proto = HTMLTextAreaElement.prototype;
} else if (el.tagName === 'INPUT') {
  proto = HTMLInputElement.prototype;
} else {
  return false;
}

const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
el.focus();
setter.call(el, arguments[1]);
el.dispatchEvent(new Event('input', { bubbles: true }));
el.dispatchEvent(new Event('change', { bubbles: true }));
el.blur();
return true;
"""

JS_CLICK = """
const el = document.querySelector(arguments[0]);
if (!el) return false;
el.scrollIntoView({block:'center'});
el.click();
return true;
"""

def js_set_value(driver, selector, value):
    if not driver.execute_script(JS_SET_VALUE, selector, value):
        raise Exception(f"FAILED SET VALUE: {selector}")

def js_click(driver, selector):
    if not driver.execute_script(JS_CLICK, selector):
        raise Exception(f"FAILED CLICK: {selector}")


# =============================
# VALIDATION API
# =============================
HEADERS_VALIDATE = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://auth.linktr.ee",
}

def validate_email(email: str) -> dict:
    r = requests.post(
        "https://linktr.ee/validate/email",
        headers=HEADERS_VALIDATE,
        json={"email": email},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "ok": data.get("result") == "success",
        "can_signup": data.get("isEligibleForPasswordlessSignup", False),
    }

def validate_username(username: str, email: str) -> bool:
    r = requests.post(
        "https://linktr.ee/validate/username",
        headers=HEADERS_VALIDATE,
        json={
            "username": username,
            "email": email,
            "returnSuggestions": False,
        },
        timeout=15,
    )
    return r.status_code == 200 and r.json().get("result") == "success"


def js_set_otp(driver, selector, value, timeout=15):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

        driver.execute_script("""
            arguments[0].focus();
            arguments[0].value = '';
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        """, el, value)

        return True

    except Exception as e:
        print(f"? FAILED SET VALUE: {selector} | {e}")
        return False

def get_otp_from_email(email, timeout=60, interval=3):
    """
    Poll OTP Linktree dari email (return string atau None)
    """
    start = time.time()

    while time.time() - start < timeout:
        try:
            # ?? PANGGIL SCRIPT inbox.py ATAU FUNGSI INTERNAL
            # Contoh: subprocess (paling simple & stabil)
            import subprocess

            cmd = [
                "python", "otp.py",
                "--target", email
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            # Cari OTP di output
            match = re.search(r"\b\d{6}\b", result.stdout)
            if match:
                return match.group()

        except Exception:
            pass

        time.sleep(interval)

    return None

# =============================
# USERNAME CANDIDATES
# =============================
import re
from typing import List, Optional
import time

VOWELS = set("aiueoAIUEO")

def normalize_username(u: str) -> str:
    s = re.sub(r"[+\s]+", "_", u.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def with_trailing_underscore(s: str) -> str:
    return s if s.endswith("_") else s + "_"

# ================= VOWEL =================
def double_vowel_variants(s: str) -> List[str]:
    return [
        s[:i] + ch + ch + s[i+1:]
        for i, ch in enumerate(s)
        if ch in VOWELS
    ]

# ================= NUMBER =================
def number_underscore_variants(s: str) -> List[str]:
    results = set()

    digit_indices = [i for i, c in enumerate(s) if c.isdigit()]

    # underscore sebelum angka pertama
    if digit_indices:
        first = digit_indices[0]
        results.add(s[:first] + "_" + s[first:])

    # underscore antar angka
    for i in range(len(s) - 1):
        if s[i].isdigit() and s[i+1].isdigit():
            results.add(s[:i+1] + "_" + s[i+1:])

    # underscore tiap digit
    temp = []
    for c in s:
        if c.isdigit():
            temp.append(c + "_")
        else:
            temp.append(c)
    results.add("".join(temp).rstrip("_"))

    # underscore akhir
    results.add(s + "_")

    return list(results)

# ================= SHORT USERNAME =================
def short_username_variants(s: str) -> List[str]:
    results = set()

    if len(s) <= 2:
        results.add(f"{s}_{s}")   # m7_m7

        if any(c.isdigit() for c in s):
            temp = []
            for c in s:
                if c.isdigit():
                    temp.append("_" + c)
                else:
                    temp.append(c)
            variant = "".join(temp)
            results.add(f"{variant}_{s}")  # m_7_m7

    return list(results)

# ================= MAIN BUILDER =================
def build_username_candidates(original: str) -> List[str]:
    base = normalize_username(original)
    seen, out = set(), []

    def add(x):
        if x not in seen:
            seen.add(x)
            out.append(x)

    # base
    add(base)
    add(with_trailing_underscore(base))

    # short username rule
    if len(base) <= 2:
        for v in short_username_variants(base):
            add(v)

    # number variants
    num_vars = number_underscore_variants(base)
    for v in num_vars:
        add(v)

    # vowel variants + combine
    vowel_vars = double_vowel_variants(base)
    for v in vowel_vars:
        add(v)
        add(with_trailing_underscore(v))

        for nv in number_underscore_variants(v):
            add(nv)

    return out

# ================= PICK VALID =================
def pick_valid_username(original: str, email: str) -> Optional[str]:
    for u in build_username_candidates(original):
        print(f"?? Check username: {u}")
        try:
            if validate_username(u, email):
                print(f"? Username OK: {u}")
                return u
        except:
            pass
        time.sleep(1)
    return None

# =============================
# BIO BUILDER
# =============================
def build_bio_safe(display: str, max_len=160) -> str:
    parts = [
        f"{display} ?????????????????????????????!",
    ]
    bio = []
    for p in parts:
        candidate = " | ".join(bio + [p]) if bio else p
        if len(candidate) <= max_len:
            bio.append(p)
        else:
            break
    return " | ".join(bio)

def is_avatar_set(driver, reload_if_missing=True, max_reload=10) -> bool:
    """
    Return True jika avatar sudah di-set (bukan blank-avatar.svg)
    Jika element tidak ada:
      - optional reload page
      - retry beberapa kali
    """

    for attempt in range(max_reload + 1):
        try:
            result = driver.execute_script("""
            const img = document.querySelector('img.aspect-square');
            if (!img) return null;
            const src = img.getAttribute('src') || '';
            return src && !src.includes('blank-avatar.svg');
            """)
        except Exception:
            result = None

        # avatar sudah ada & bukan blank
        if result is True:
            return True

        # avatar element ada tapi masih blank
        if result is False:
            return False

        # result == null ? element belum ada
        if result is None and reload_if_missing and attempt < max_reload:
            print("?? Avatar element not found \Uffffffff reloading page\Uffffffff")
            driver.refresh()
            time.sleep(3)
            continue

        break

    return False


def upload_avatar_and_wait(driver, image_path, timeout=10):
    # klik avatar
    driver.execute_script("document.querySelector('.aspect-square')?.click()")
    time.sleep(1)

    # pilih avatar upload
    driver.execute_script(
        "document.querySelector('#media-picker-option-avatar_media')?.click()"
    )
    time.sleep(1)

    # upload file
    file_input = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input.h-full"))
    )
    file_input.send_keys(image_path)
    time.sleep(1)

    # klik Save
    driver.execute_script("""
    [...document.querySelectorAll('button')]
      .find(b => b.innerText.trim() === 'Save')
      ?.click();
    """)

    # tunggu Save hilang
    end = time.time() + timeout
    while time.time() < end:
        still = driver.execute_script("""
        return [...document.querySelectorAll('button')]
          .some(b => b.innerText.trim() === 'Save');
        """)
        if not still:
            print("? Avatar upload SUCCESS")
            return True
        time.sleep(0.3)

    raise Exception("? Avatar upload TIMEOUT")

# =============================
# WAIT ONBOARDING START (FIX UTAMA)
# =============================
def wait_onboarding_start(driver, timeout=60):
    WebDriverWait(driver, timeout).until(
        lambda d: (
            "/register/select-" in d.current_url
            or "/register/do-more" in d.current_url
            or "/register/create/" in d.current_url
        )
    )
    return driver.current_url
def js_click_safe(driver, selector, retry=2, reload=True):
    for i in range(retry + 1):
        try:
            ok = driver.execute_script("""
            const el = document.querySelector(arguments[0]);
            if (!el) return false;
            el.scrollIntoView({block:'center'});
            el.click();
            return true;
            """, selector)

            if ok:
                return True
        except Exception as e:
            print(f"?? JS error: {e}")

        if reload and i < retry:
            print("?? Element not found \Uffffffff reload page")
            driver.refresh()
            time.sleep(3)

    raise Exception(f"? FAILED CLICK after retry: {selector}")
def wait_and_click_template(driver, timeout=20):
    end = time.time() + timeout

    while time.time() < end:
        try:
            ok = driver.execute_script("""
            const el = document.querySelector(
              "div.animate-fade-in-up:nth-child(4) > div:nth-child(1) > button:nth-child(1)"
            );
            if (!el) return false;
            el.scrollIntoView({block:'center'});
            el.click();
            return true;
            """)
            if ok:
                return True
        except:
            pass

        time.sleep(1)

    print("?? Template not found ? reload")
    driver.refresh()
    time.sleep(5)

    # coba sekali lagi setelah reload
    return driver.execute_script("""
    const el = document.querySelector(
      "div.animate-fade-in-up:nth-child(4) > div:nth-child(1) > button:nth-child(1)"
    );
    if (!el) return false;
    el.scrollIntoView({block:'center'});
    el.click();
    return true;
    """)

def wait_after_username(driver, timeout=15):
    end = time.time() + timeout
    last_url = ""

    while time.time() < end:
        url = driver.current_url
        if url != last_url:
            print("?? URL:", url)
            last_url = url

        # sukses ? OTP
        if driver.execute_script("""
            return !!document.querySelector("input[data-input-otp='true']");
        """):
            return "otp"

        # balik ke username
        if driver.execute_script("""
            return !!document.querySelector("input[placeholder='username']");
        """):
            return "username"

        time.sleep(0.5)

    return "timeout"

def is_otp_failed(driver) -> bool:
    return driver.execute_script("""
    const err = document.querySelector('p.text-red-600');
    if (!err) return false;
    return err.innerText.toLowerCase().includes('failed to verify');
    """)

def resend_otp(driver):
    print("?? Resend OTP")

    driver.execute_script("""
    [...document.querySelectorAll('button')]
      .find(b => b.innerText.trim() === 'Resend code')
      ?.click();
    """)

def wait_otp_result(driver, timeout=30) -> str:
    """
    return:
    - 'success' ? URL berubah
    - 'failed'  ? muncul error text-red-600
    """
    start_url = driver.current_url
    end = time.time() + timeout

    while time.time() < end:
        if driver.current_url != start_url:
            return "success"

        if is_otp_failed(driver):
            return "failed"

        time.sleep(0.5)

    return "timeout"
def is_otp_page(driver) -> bool:
    return driver.execute_script("""
    return !!document.querySelector("input[data-input-otp='true']");
    """)
def is_username_page(driver) -> bool:
    return driver.execute_script("""
    const el = document.querySelector("input[placeholder='username']");
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
    """)
def js_click_optional(driver, selector):
    driver.execute_script("""
    const el = document.querySelector(arguments[0]);
    if (el && !el.disabled) {
        el.scrollIntoView({block:'center'});
        el.click();
        return true;
    }
    return false;
    """, selector)
def wait_otp_input(driver, timeout=15):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[data-input-otp='true']")
        )
    )



def fill_linktree_otp_precise(driver, otp, timeout=15):
    otp = otp.strip()
    if len(otp) != 6:
        print("? OTP harus 6 digit")
        return False

    wait = WebDriverWait(driver, timeout)

    for i, digit in enumerate(otp, start=1):
        selector = f"div.gap-2 > div:nth-child({i}) > input"

        try:
            el = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )

            driver.execute_script("""
                arguments[0].focus();
                arguments[0].value = '';
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            """, el)

            el.send_keys(digit)
            time.sleep(0.1)

        except Exception as e:
            print(f"? Gagal isi OTP digit ke-{i}: {e}")
            return False

    return True

def get_proxy():
    with open("proxy.txt", "r") as f:
        proxies = [p.strip() for p in f if p.strip()]

    if not proxies:
        print("? Proxy habis")
        return None

    proxy = random.choice(proxies)

    # hapus proxy yang dipakai
    proxies.remove(proxy)

    with open("proxy.txt", "w") as f:
        for p in proxies:
            f.write(p + "\n")

    return proxy
def run(email, data, username, link_url):
    print("?? Validating username dulu...")
    display = username

    driver = None
    avatar_url = None
    success = False

    try:
        # ================= USERNAME VALIDATION =================
        temp_email = "test@gmail.com"
        picked = pick_valid_username(username, temp_email)

        if not picked:
            print("? No valid username")
            return

        username = picked
        email = f"{username}@bulusari.id"

        print(f"? Username OK: {username}")
        print(f"?? Email jadi: {email}")

        # email_check = validate_email(email)
        # if not email_check["ok"] or not email_check["can_signup"]:
        #     print(f"? Email invalid: {email}")
        #     return

        # ================= PROXY =================
        proxy = get_proxy()
        if not proxy:
            return

        seleniumwire_options = {
            'proxy': {
                'http': f'http://{proxy}',
                'https': f'https://{proxy}',
            }
        }

        # ================= DRIVER =================
        driver = webdriver.Firefox(seleniumwire_options=seleniumwire_options)
        wait = WebDriverWait(driver, WAIT_TIME)

        driver.get("https://www.myip.com")

        # ================= SIGNUP =================
        driver.get(SIGNUP_URL)

        print("??? Menyetujui Cookie...")
        try:
            time.sleep(4)
            driver.execute_script("""
                try {
                    const shadowHost = document.querySelector('aside.dg-consent-banner');
                    if (shadowHost && shadowHost.shadowRoot) {
                        const btn = shadowHost.shadowRoot.querySelector('button.accept_all');
                        if (btn) btn.click();
                    }
                } catch(e){}
            """)
            time.sleep(2)
        except:
            pass

        # ================= INPUT EMAIL =================
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
        js_set_value(driver, "input[type='email']", email)
        js_click(driver, "button")

        # ================= USERNAME =================
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='username']")))
        js_set_value(driver, "input[placeholder='username']", username)
        js_click(driver, "span.label:nth-child(1)")
        js_click(driver, "button")

        time.sleep(3)

        # ================= WAIT OTP =================
        print("? Menentukan step\Uffffffff")
        while True:
            if is_otp_page(driver):
                print("?? OTP page detected")
                break

            if is_username_page(driver):
                js_set_value(driver, "input[placeholder='username']", username)
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.trim() === 'Continue')
                      ?.click();
                """)
                time.sleep(2)
                continue

            time.sleep(0.5)

        # ================= OTP LOOP =================
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[data-input-otp='true']")))

        last_otp = None
        otp_page_url = driver.current_url

        while True:
            if driver.current_url != otp_page_url:
                print("? OTP SUCCESS (redirect)")
                break

            otp = get_otp_from_email(email)

            if otp == last_otp or not otp:
                time.sleep(2)
                continue

            print(f"?? OTP: {otp}")
            js_set_value(driver, "input[data-input-otp='true']", otp)
            last_otp = otp
            time.sleep(2)

            result = wait_otp_result(driver)

            if result == "success":
                break

            if result in ["failed", "timeout"]:
                resend_otp(driver)
                time.sleep(2)
                otp_page_url = driver.current_url

        print("? Waiting onboarding\Uffffffff")
        wait_onboarding_start(driver)

        # ================= MAIN FLOW =================
        while True:
            url = driver.current_url
            print("?? URL:", url)

            if "/register/select-categories" in url:
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.includes('Personal'))?.click();
                """)
                time.sleep(1)
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.trim() === 'Continue')?.click();
                """)

            elif "/register/select-intents" in url:
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.includes("I'm building my link in bio"))?.click();
                """)
                time.sleep(2)
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.trim() === 'Continue')?.click();
                """)

            elif "/register/do-more" in url or "/register/add-links" in url:
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.trim() === 'Skip')?.click();
                """)

            elif "/register/select-plan" in url:
                js_click(driver, "button.ml-6")

            elif "/register/select-template" in url:
                driver.execute_script("""
                    const t = document.querySelectorAll('button[class*="block overflow-hidden"]');
                    if (t.length > 0) {
                        const r = Math.floor(Math.random()*t.length);
                        t[r].click();
                    }
                """)
                time.sleep(2)
                driver.execute_script("""
                    [...document.querySelectorAll('button')]
                      .find(b => b.innerText.includes('Start with this template'))?.click();
                """)

            elif "/register/name-image-bio" in url:
                print("?? Memproses Name, Bio, dan Avatar...")
                
                # Kita coba maksimal 3 kali jika avatar gagal
                # --- Bagian Upload Avatar ---
                avatar_url = None # Variable buat nampung URL gambar
                
                for attempt in range(3):
                    try:
                        # 1. Cek apakah avatar sudah terisi & ambil URL-nya
                        avatar_data = driver.execute_script("""
                            const img = document.querySelector('img[alt="Profile avatar"]');
                            if (img && !img.src.includes('blank-avatar')) {
                                return img.src;
                            }
                            return null;
                        """)
                        
                        if avatar_data:
                            avatar_url = avatar_data
                            print(f"? Avatar terdeteksi: {avatar_url}")
                            break
                            
                        print(f"?? Percobaan Upload Avatar ke-{attempt + 1}...")

                        # 2. Klik Avatar untuk buka modal
                        driver.execute_script("""
                            const avatar = document.querySelector('span[role="radio"]') || document.querySelector('.avatar-wrapper');
                            if (avatar) avatar.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                        """)
                        time.sleep(3)

                        # 3. Inject Gambar
                        input_file = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
                        input_file.send_keys(AVATAR_PATH)
                        time.sleep(5)

                        # 4. Klik Crop
                        driver.execute_script("""
                            const cropBtn = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Crop');
                            if (cropBtn) cropBtn.click();
                        """)
                        time.sleep(3)

                        # 5. Klik Upload (Final Modal)
                        driver.execute_script("""
                            const uploadBtn = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Upload' || b.innerText.trim() === 'Save');
                            if (uploadBtn) uploadBtn.click();
                        """)

                        # 6. Tunggu modal hilang & VERIFIKASI LINK ASLI (Bukan Blank)
                        wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
                        print("? Menunggu sinkronisasi gambar ke CDN...")
                        
                        # Polling: Cek tiap detik sampai link berubah dari blank ke ugc
                        verified_url = None
                        for _ in range(15): # Max nunggu 15 detik
                            temp_url = driver.execute_script("""
                                const img = document.querySelector('img[alt="Profile avatar"]');
                                const src = img ? img.src : "";
                                // Syarat: Ada src, bukan blank, dan sudah masuk domain ugc/production
                                if (src && !src.includes('blank-avatar') && src.includes('production.linktr.ee')) {
                                    return src;
                                }
                                return null;
                            """)
                            if temp_url:
                                verified_url = temp_url
                                break
                            time.sleep(1)

                        if verified_url:
                            avatar_url = verified_url
                            print(f"? Avatar Berhasil Diupload & Terverifikasi: {avatar_url}")
                            break # Sukses, keluar dari loop attempt
                        else:
                            print("?? Gambar belum tersinkron, mencoba upload ulang...")
                            raise Exception("Upload gagal (Link masih blank)")

                    except Exception as e:
                        print(f"?? Error di percobaan {attempt + 1}: {e}")


                # Sekarang lu punya variable 'avatar_url' yang isinya link gambarnya
                # --- Bagian Akhir: Isi Bio & Continue ---
                print("?? Mengisi Display Name & Bio...")
                js_set_value(driver, "#name", display)
                time.sleep(1)
                js_set_value(driver, "#bio", build_bio_safe(display))
                time.sleep(2)

                print("?? Klik Continue Final...")
                driver.execute_script("""
                    const finalBtn = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Continue');
                    if (finalBtn && !finalBtn.disabled) {
                        finalBtn.scrollIntoView();
                        finalBtn.click();
                    }
                """)
                time.sleep(5)
            elif "/admin" in url:
                titles = [
                    f"{display} ???????????",
                    f"{display} ????????????????",
                    f"{display} ???????????"
                ]

                for title in titles:
                    add_link_pure_api(driver, title, link_url, avatar_url)

                final_link = get_final_linktree_url(driver)

                if final_link:
                    with open("hasil_linktree.txt", "a") as f:
                        f.write(f"{username}|{email}|{data}|{link_url}|{final_link}\n")

                print("?? DONE")
                success = True
                break
            elif "/register/select-platforms" in url:
                driver.execute_script("""
    const skipBtn = document.querySelector('button[data-testid="skip-button"]');
    if (skipBtn) {
        skipBtn.click();
    } else {
        // Backup: Cari berdasarkan teks jika data-testid tidak ditemukan
        const backupBtn = [...document.querySelectorAll('button')]
                          .find(b => b.innerText.trim() === 'Skip');
        if (backupBtn) backupBtn.click();
    }
""")

            elif "/register/complete" in url:
                driver.get(ADMIN_URL)

                titles = [
                    f"{display} ???????????",
                    f"{display} ????????????????",
                    f"{display} ???????????"
                ]

                for title in titles:
                    add_link_pure_api(driver, title, link_url, avatar_url)

                final_link = get_final_linktree_url(driver)

                if final_link:
                    with open("hasil_linktree.txt", "a") as f:
                        f.write(f"{display}|{email}|{data}|{link_url}|{final_link}\n")

                print("?? DONE")
                success = True
                break

            time.sleep(2)

    except Exception as e:
        print(f"? ERROR: {e}")

    finally:
        if driver:
            if success:
                print("?? Closing browser...")
                driver.quit()
            else:
                print("?? Browser tetap terbuka (debug)")

# =============================
# ENTRY
# =============================


def pop_first_row(csv_file):
    with open(csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return None, []

    first = rows[0]
    remaining = rows[1:]

    # tulis ulang file tanpa baris pertama
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=first.keys())
        writer.writeheader()
        writer.writerows(remaining)

    return first


if __name__ == "__main__":
    while True:
        row = pop_first_row(CSV_FILE)

        if not row:
            print("? Semua data sudah diproses")
            break

        try:
            run(
                email="test@gmail.com",
                data=row["key"].strip(),
                username=row["username"].strip(),
                link_url=row["url"].strip(),
            )
        except Exception as e:
            print(f"? Error: {e}")