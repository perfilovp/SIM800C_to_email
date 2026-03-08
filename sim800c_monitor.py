import serial
import time
import re
import smtplib
import os
import argparse
import requests
import codecs 
import logging
import random
from email.message import EmailMessage
from pathlib import Path

# 🌍 Environment variables
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")
SIM_NUMBER = os.getenv("SIM_NUMBER")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SMS_TEXT = "SIM800C is now online and monitoring SMS and calls."
CODE = os.getenv("CODE", "113")  # Default USSD code if not set
WHOAMI = os.getenv("WHOAMI", os.uname().nodename)  # Get the hostname for identification in messages
# Operator numeric MCC+MNC to lock onto, e.g. "23415" (Vodafone UK), "27201" (Vodafone IE),
# "26202" (Vodafone DE), "22210" (Vodafone IT). Leave empty for automatic selection.
OPERATOR_NUMERIC = os.getenv("OPERATOR_NUMERIC", "")

# SIM800C is 2G/GSM only — act=0
_ACT_NAMES = {0: "2G/GSM", 2: "3G/UTRAN", 7: "4G/LTE"}

PORT = ""  # Set at startup from --port arg

# Track last call info and SMS buffers
last_call_number = None
last_call_time = 0
last_time=0
sms_buffer = {}

# Connection self-monitoring state
last_connection_check = 0
connection_ok = True

def send_email(subject, body):
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = GMAIL_USER
        msg['To'] = EMAIL_TO

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        logging.info("[📧] Email sent successfully.")
    except Exception as e:
        logging.error(f"[!] Email sending failed: {e}")

def send_telegram(message):
    """Send message via Telegram Bot API"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("[!] Telegram credentials not configured. Skipping Telegram notification.")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            logging.info("[📱] Telegram message sent successfully.")
        else:
            logging.error(f"[!] Telegram sending failed: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"[!] Telegram sending failed: {e}")

def send_notification(subject, body):
    """Send notification via both email and Telegram"""
    # Send email
    send_email(subject, body)
    
    # Send Telegram message
    telegram_message = f"<b>{subject}</b>\n\n{body}"
    send_telegram(telegram_message)

def send_at_command(ser, command, timeout=1.0):
    ser.write((command + '\r').encode())
    time.sleep(timeout)
    return ser.read_all().decode(errors='ignore')

def _at_ok(ser, command, timeout=1.0):
    """Send an AT command and return (response, success) where success means 'OK' was in the response."""
    resp = send_at_command(ser, command, timeout)
    ok = 'OK' in resp
    return resp, ok

def scan_networks(ser):
    """Scan for all visible networks. Warning: takes 30-60 seconds.
    Returns list of dicts with keys: stat, long_name, short_name, numeric, act, act_name.
    stat: 0=unknown, 1=available, 2=current, 3=forbidden
    """
    logging.info("[*] Scanning for available networks (may take up to 60s)...")
    resp = send_at_command(ser, 'AT+COPS=?', timeout=65.0)
    logging.debug(f"COPS scan raw: {repr(resp)}")

    networks = []
    for m in re.finditer(r'\((\d+),"([^"]*?)","([^"]*?)","(\d+)",(\d+)\)', resp):
        stat, long_name, short_name, numeric, act = m.groups()
        act_name = _ACT_NAMES.get(int(act), f"unknown({act})")
        networks.append({
            "stat": int(stat), "long_name": long_name, "short_name": short_name,
            "numeric": numeric, "act": int(act), "act_name": act_name,
        })
        logging.info(f"  [{['unknown','available','current','forbidden'][min(int(stat),3)]}] "
                     f"{long_name} ({numeric}) [{act_name}]")

    if not networks:
        logging.warning("[!] No networks parsed from scan response.")
    return networks


def register_network(ser, operator_numeric, act=0):
    """Manually register to a specific operator.
    operator_numeric: MCC+MNC string, e.g. '23415' for Vodafone UK.
    act: 0=2G/GSM (only valid value for SIM800C).
    Returns True on success.
    """
    act_name = _ACT_NAMES.get(act, str(act))
    logging.info(f"[*] Registering to {operator_numeric} ({act_name})...")
    resp, ok = _at_ok(ser, f'AT+COPS=1,2,"{operator_numeric}",{act}', timeout=30.0)
    if ok:
        logging.info(f"[✓] Registered to {operator_numeric} ({act_name})")
    else:
        logging.error(f"[!] Registration to {operator_numeric} failed: {repr(resp)}")
    return ok


def initialize_modem(ser):
    """Initialize the modem. Returns True on success, False on failure."""
    global imei
    logging.info("[*] Initializing modem...")

    # Flush any stale data before starting
    ser.reset_input_buffer()

    # Wait for modem to respond to AT — retry up to 10 times with backoff
    for attempt in range(1, 11):
        resp, ok = _at_ok(ser, 'AT', timeout=1.0)
        if ok:
            logging.debug(f"AT OK on attempt {attempt}")
            break
        logging.warning(f"[!] AT not ready (attempt {attempt}/10): {repr(resp)}")
        time.sleep(min(2 ** (attempt - 1), 30))  # exponential backoff, cap at 30s
    else:
        logging.error("[!] Modem did not respond to AT after 10 attempts — giving up.")
        return False

    # Disable echo
    resp, ok = _at_ok(ser, 'ATE0')
    logging.debug(f"ATE0: {repr(resp)}, ok={ok}")

    # Text mode
    resp, ok = _at_ok(ser, 'AT+CMGF=1')
    if not ok:
        logging.error(f"[!] AT+CMGF=1 failed: {repr(resp)}")
        return False

    # Instant message delivery
    resp, ok = _at_ok(ser, 'AT+CNMI=2,2,0,0,0')
    if not ok:
        logging.error(f"[!] AT+CNMI=2,2,0,0,0 failed: {repr(resp)}")
        return False

    # Caller ID
    resp, ok = _at_ok(ser, 'AT+CLIP=1')
    if not ok:
        logging.warning(f"[!] AT+CLIP=1 failed (non-fatal): {repr(resp)}")

    # Lock to a specific operator/network if configured
    if OPERATOR_NUMERIC:
        if not register_network(ser, OPERATOR_NUMERIC, act=0):
            logging.warning("[!] Could not register to configured operator — scanning available networks...")
            scan_networks(ser)
    else:
        # Ensure automatic selection is active
        _at_ok(ser, 'AT+COPS=0', timeout=5.0)

    # IMEI
    imei_raw = send_at_command(ser, 'AT+GSN', timeout=1.0)
    imei = imei_raw.replace('\n', '').replace('\r', '').replace('\\', '').strip()
    logging.info(f"IMEI: {imei}")

    logging.info("[*] Modem initialized successfully.")
    return True


def send_ussd(ser, code, timeout=5.0):
    """Send a USSD code and return the response text.
    Example: send_ussd(ser, '*100#')
    """
    logging.info(f"[*] Sending USSD: {code}")
    response = send_at_command(ser, f'AT+CUSD=1,"{code}",15', timeout=timeout)

    logging.debug(f"USSD raw response: {response}")

    logging.warning(f"[!] No USSD response parsed from: {response}")
    return response


def send_sms(ser, number, message):
    logging.info(f"[*] Sending test SMS to {number}")
    send_at_command(ser, f'AT+CMGS="{number}"')
    time.sleep(0.5)
    ser.write((message + chr(26)).encode())
    time.sleep(3)
    logging.info("[✔️] Test SMS sent.")

def decode_cusd_line(line: str) -> str:
    m = re.search(r'\+CUSD:\s*\d+,"([^"]+)"', line)
    if not m:
        raise ValueError("No quoted hex payload found")
    hex_payload = m.group(1)
    raw = bytes.fromhex(hex_payload)
    return raw.decode('utf-16-be', errors='replace')


def process_sms(content):
    logging.info(f"📩 Processing SMS: {content}")
    bstring = bytes.fromhex("".join(re.findall(r'([0-9,A-F,a-f]{20,})',content)))
    logging.debug(f"Hex decoded bytes: {bstring}")
    decoded=''

    try:
        decoded+=str(codecs.utf_16_be_decode(bstring))
    except Exception as e:
        logging.error(f"UTF-16 BE decoding failed: {e}, content: {content}")
        pass

    # try:
    #     decoded+='\n' + str(codecs.utf_16_le_decode(bstring))
    # except Exception as e:
    #     logging.error(f"UTF-16 LE decoding failed: {e}, content: {content}")
    #     pass
        
    # try:
    #     send_email(f"📩 SMS to email {imei}:", decoded +'\n' + content)
    # except Exception as e:
    #     send_email(f"📩 SMS to email {imei}:", content)

    try:
        send_telegram(f"📩 SMS received {WHOAMI} {PORT} {imei}:\n{decoded}\nRaw content:\n{content}")
    except Exception as e:
        send_telegram(f"📩 Exception {WHOAMI} {PORT} {imei}:\n\nRaw content:\n{content}")
        
def setup_logging(port):
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create log filename based on port name (remove /dev/ if present)
    port_name = port.replace("/dev/", "").replace("/", "_")
    log_file = log_dir / f"sim800c_{port_name}.log"
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()  # Also log to console
        ]
    )

def check_connection(ser, send_to_telegram=False):
    """Query modem for signal strength, network registration, and operator.
    Returns dict with keys: registered (bool), rssi (int), operator (str).
    """
    # Signal quality
    csq_resp = send_at_command(ser, 'AT+CSQ', timeout=1.0)
    rssi = 99
    m = re.search(r'\+CSQ:\s*(\d+),', csq_resp)
    if m:
        rssi = int(m.group(1))

    # Network registration
    creg_resp = send_at_command(ser, 'AT+CREG?', timeout=1.0)
    registered = False
    m = re.search(r'\+CREG:\s*\d+,(\d+)', creg_resp)
    if m:
        stat = int(m.group(1))
        registered = stat in (1, 5)  # 1=home, 5=roaming

    # Operator
    cops_resp = send_at_command(ser, 'AT+COPS?', timeout=2.0)
    operator = cops_resp
    m = re.search(r'\+COPS:\s*\d+,\d+,"([^"]+)"', cops_resp)
    if m:
        operator = m.group(1)

    logging.info(f"[📶] Connection check — RSSI: {rssi}/31, Registered: {registered}, Operator: {operator}")
    if send_to_telegram:
        send_telegram(f"📶 {WHOAMI} {PORT} — RSSI: {rssi}/31, Registered: {registered}, Operator: {operator}")

    return {"registered": registered, "rssi": rssi, "operator": operator}


def handle_connection_check(ser):
    """Run a connection check and alert/reinitialize if the modem is offline."""
    global connection_ok
    status = check_connection(ser)
    is_ok = status["registered"] and status["rssi"] != 99

    if not is_ok:
        if connection_ok:
            # State just changed to bad — alert once
            subject = f"⚠️ {WHOAMI} {PORT} connection lost ({imei})"
            body = (
                f"RSSI: {status['rssi']}/31\n"
                f"Operator: {status['operator']}\n"
                f"Attempting modem reinitialization..."
            )
            logging.warning(f"[⚠️] {subject}")
            send_notification(subject, body)
        connection_ok = False
        logging.info("[🔄] Reinitializing modem after connection loss...")
        try:
            if not initialize_modem(ser):
                logging.error("[!] Reinitialization failed — scanning available networks for diagnosis...")
                scan_networks(ser)
        except Exception as e:
            logging.error(f"[!] Reinitialization failed: {e}")
    else:
        if not connection_ok:
            # State just recovered — notify once
            subject = f"✅ {WHOAMI} {PORT} connection restored ({imei})"
            body = (
                f"Mobile connection restored.\n"
                f"RSSI: {status['rssi']}/31\n"
                f"Operator: {status['operator']}"
            )
            logging.info(f"[✅] {subject}")
            send_notification(subject, body)

        connection_ok = True


def main():
    global last_call_number, last_call_time, last_time, last_connection_check, connection_ok, imei, PORT
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='SIM800C SMS and Call Monitor')
    parser.add_argument('--port', default='/dev/ttyUSB0', 
                       help='Serial port for SIM800C module (default: /dev/ttyUSB0)')
    args = parser.parse_args()
    PORT = args.port

    # Setup logging with the port name
    setup_logging(args.port)
    
    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=19200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0
        )

        if not initialize_modem(ser):
            logging.error("[!] Modem initialization failed. Exiting.")
            return
        if CODE:
            balance = send_ussd(ser, f'*{CODE}#')  # Example USSD to check balance (adjust as needed)
        else: 
            balance = "No USSD code configured"
        send_telegram(f"✅ {WHOAMI} {PORT} with IMEI: {imei}\ {balance}")
        check_connection(ser, send_to_telegram=True)  # Initial connection check on startup

        # if TARGET_NUMBER:
            # send_sms(ser, TARGET_NUMBER, SMS_TEXT)

        logging.info("[*] Listening for SMS and calls... Press Ctrl+C to stop.")
        buffer = ""
        content=""
        content_buffer=""
        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting).decode(errors='ignore')
                buffer += data
                if "+CMT:" in buffer:
                    if last_time==0:
                        last_time=time.time()
                
                #     match = re.search(r'\+CMT: "(.+?)",".*?"\r\n(.*)', buffer, re.DOTALL)
                #     if match:
                #         sender = match.group(1)
                #         content = match.group(2).strip()
                #         if content.startswith('00'):
                #             content=content[1:]
                #         content_buffer += content
                #         logging.info(f"[📩 SMS FROM {sender}]:\n{content}\n buffer:{content_buffer}")

                elif "+CLIP:" in buffer:
                    match = re.search(r'\+CLIP: "(\+?\d+)"', buffer)
                    if match:
                        number = match.group(1)
                        current_time = time.time()
                        if number != last_call_number or (current_time - last_call_time > 10):
                            logging.info(f"[📞 INCOMING CALL FROM]: {number}")
                            subject = f"📞 Incoming call {WHOAMI} {PORT} {SIM_NUMBER} from {number}"
                            body = f"Incoming call detected from number: {number}\n\nRaw buffer data:\n{buffer}"
                            send_email(subject, body)
                            last_call_number = number
                            last_call_time = current_time
                    buffer = ""
                    
            if buffer and last_time and time.time()-last_time>10:
                process_sms(buffer)
                buffer = ""
                content_buffer=""
                last_time=0

            if time.time() - last_connection_check >= random.randint(300, 600):  # Check connection every 5-10 minutes
                handle_connection_check(ser)
                last_connection_check = time.time()

            time.sleep(0.2)

    except KeyboardInterrupt:
        logging.info("\n[*] Stopped by user.")
    except Exception as e:
        logging.error(f"[!] Error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
