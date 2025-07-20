import serial
import time
import re
import smtplib
import os
from email.message import EmailMessage

# 🌍 Environment variables
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")
SMS_TEXT = "SIM800C is now online and monitoring SMS and calls."

# Track last call info and SMS buffers
last_call_number = None
last_call_time = 0
sms_buffer = {}

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
        print("[📧] Email sent successfully.")
    except Exception as e:
        print(f"[!] Email sending failed: {e}")

def send_at_command(ser, command, timeout=1.0):
    ser.write((command + '\r').encode())
    time.sleep(timeout)
    return ser.read_all().decode(errors='ignore')

def initialize_modem(ser):
    print("[*] Initializing modem...")
    print(send_at_command(ser, 'AT'))
    print(send_at_command(ser, 'ATE0'))
    print(send_at_command(ser, 'AT+CMGF=1'))  # Text mode
    print(send_at_command(ser, 'AT+CNMI=2,2,0,0,0'))  # Instant message delivery
    print(send_at_command(ser, 'AT+CLIP=1'))  # Caller ID

def send_sms(ser, number, message):
    print(f"[*] Sending test SMS to {number}")
    send_at_command(ser, f'AT+CMGS="{number}"')
    time.sleep(0.5)
    ser.write((message + chr(26)).encode())
    time.sleep(3)
    print("[✔️] Test SMS sent.")

def decode_utf16_if_needed(text):
    try:
        # Try decoding text that might be in UTF-16
        cleaned = bytes(text, "utf-8").decode("utf-16", errors="ignore")
        return cleaned if cleaned.strip() else text
    except:
        return text

def process_sms(sender, content):
    now = time.time()
    if sender in sms_buffer and now - sms_buffer[sender]['time'] < 10:
        sms_buffer[sender]['messages'].append(content)
        sms_buffer[sender]['time'] = now
    else:
        if sender in sms_buffer:
            full_message = "".join([x.replace(',','') for x in sms_buffer[sender]['messages']])
            #full_message = decode_utf16_if_needed(full_message)
            send_email(f"📩 SMS from {sender}", full_message, decode_utf16_if_needed(full_message))
        sms_buffer[sender] = {'messages': [content], 'time': now}

def flush_sms_buffers():
    for sender in list(sms_buffer.keys()):
        full_message = "".join([x.replace(',','') for x in sms_buffer[sender]['messages'].replace(',','')])
        #full_message = decode_utf16_if_needed(full_message)
        send_email(f"📩 SMS from {sender}", full_message, decode_utf16_if_needed(full_message))
        print(f"📩 SMS from {sender}", full_message)
        del sms_buffer[sender]

def main():
    global last_call_number, last_call_time
    try:
        ser = serial.Serial(
            port='/dev/ttyUSB0',
            baudrate=19200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0
        )

        initialize_modem(ser)

        if TARGET_NUMBER:
            send_sms(ser, TARGET_NUMBER, SMS_TEXT)

        print("[*] Listening for SMS and calls... Press Ctrl+C to stop.")
        buffer = ""

        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting).decode(errors='ignore')
                buffer += data

                if "+CMT:" in buffer:
                    match = re.search(r'\+CMT: "(.+?)",".*?"\r\n(.*)', buffer, re.DOTALL)
                    if match:
                        sender = match.group(1)
                        content = match.group(2).strip()
                        print(f"\n[📩 SMS FROM {sender}]:\n{content}")
                        process_sms(sender, content)
                    buffer = ""

                elif "+CLIP:" in buffer:
                    match = re.search(r'\+CLIP: "(\+?\d+)"', buffer)
                    if match:
                        number = match.group(1)
                        current_time = time.time()
                        if number != last_call_number or (current_time - last_call_time > 10):
                            print(f"\n[📞 INCOMING CALL FROM]: {number}")
                            subject = f"📞 Incoming call from {number}\n {buffer}"
                            body = f"Incoming call detected from number: {number}"
                            send_email(subject, body)
                            last_call_number = number
                            last_call_time = current_time
                    buffer = ""

            for sender in list(sms_buffer):
                if time.time() - sms_buffer[sender]['time'] > 10:
                    flush_sms_buffers()

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n[*] Stopped by user.")
        flush_sms_buffers()
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
