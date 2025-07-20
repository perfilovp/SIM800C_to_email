import serial
import time
import re
import smtplib
from email.message import EmailMessage

# ✏️ Gmail credentials and destination
GMAIL_USER = "your_email@gmail.com"
GMAIL_APP_PASSWORD = "your_16char_apppassword"
EMAIL_TO = "destination_email@gmail.com"

# Optional test SMS
TARGET_NUMBER = "+1234567890"  # Change to your number
SMS_TEXT = "SIM800C is now online and monitoring SMS and calls."

# Email sending function
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
    print(send_at_command(ser, 'ATE0'))              # Turn off echo
    print(send_at_command(ser, 'AT+CMGF=1'))         # SMS text mode
    print(send_at_command(ser, 'AT+CNMI=2,2,0,0,0')) # Push SMS immediately
    print(send_at_command(ser, 'AT+CLIP=1'))         # Enable caller ID

def send_sms(ser, number, message):
    print(f"[*] Sending test SMS to {number}")
    send_at_command(ser, f'AT+CMGS="{number}"')
    time.sleep(0.5)
    ser.write((message + chr(26)).encode())  # Ctrl+Z to send SMS
    time.sleep(3)
    print("[✔️] Test SMS sent.")

def main():
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
                    match = re.search(r'\+CMT: "([^"]+)",.*?\n(.*)', buffer, re.DOTALL)
                    if match:
                        sender = match.group(1)
                        message = match.group(2).strip()
                        subject = f"📩 SMS from {sender}"
                        body = f"Sender: {sender}\n\nMessage:\n{message}"
                        send_email(subject, body)
                    buffer = ""

                elif "+CLIP:" in buffer:
                    match = re.search(r'\+CLIP: "(\+?\d+)"', buffer)
                    if match:
                        number = match.group(1)
                        print(f"\n[📞 INCOMING CALL FROM]: {number}")
                        subject = f"📞 Incoming call from {number}"
                        body = f"Incoming call detected from number: {number}"
                        send_email(subject, body)
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
