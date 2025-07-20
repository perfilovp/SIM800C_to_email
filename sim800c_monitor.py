import serial
import time
import re
import smtplib
import os
from email.message import EmailMessage
import datetime

# 🌍 Load environment variables
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")
SMS_TEXT = f"SIM800C is now online and monitoring SMS and calls {datetime.now()}."

# Keep track of last notified caller
last_call_number = None
last_call_time = 0

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
    print(send_at_command(ser, 'AT+CMGF=1'))
    print(send_at_command(ser, 'AT+CNMI=2,2,0,0,0'))
    print(send_at_command(ser, 'AT+CLIP=1'))

def send_sms(ser, number, message):
    print(f"[*] Sending test SMS to {number}")
    send_at_command(ser, f'AT+CMGS="{number}"')
    time.sleep(0.5)
    ser.write((message + chr(26)).encode())
    time.sleep(3)
    print("[✔️] Test SMS sent.")

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

        # ✅ Send test SMS on startup
        if TARGET_NUMBER:
            send_sms(ser, TARGET_NUMBER, SMS_TEXT)

        print("[*] Listening for SMS and calls... Press Ctrl+C to stop.")

        buffer = ""

        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting).decode(errors='ignore')
                buffer += data

                if "+CMT:" in buffer:
                    print("\n[📩 SMS RECEIVED]")
                    print(buffer.strip())
                    send_email("📩 New SMS Received", buffer.strip())
                    buffer = ""

                elif "+CLIP:" in buffer:
                    match = re.search(r'\+CLIP: "(\+?\d+)"', buffer)
                    if match:
                        number = match.group(1)
                        current_time = time.time()
                        if number != last_call_number or (current_time - last_call_time > 10):
                            print(f"\n[📞 INCOMING CALL FROM]: {number}")
                            subject = f"📞 Incoming call from {number}"
                            body = f"Incoming call detected from number: {number}"
                            send_email(subject, body)
                            last_call_number = number
                            last_call_time = current_time
                    buffer = ""

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n[*] Stopped by user.")
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
