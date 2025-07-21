import serial
import time
import re
import smtplib
import os
import argparse
from email.message import EmailMessage

# 🌍 Environment variables
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")
SIM_NUMBER = os.getenv("SIM_NUMBER")
SMS_TEXT = "SIM800C is now online and monitoring SMS and calls."

# Track last call info and SMS buffers
last_call_number = None
last_call_time = 0
last_time=0
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
        # cleaned = bytes(text, "utf-8").decode("utf-16", errors="ignore")
        cleaned = ''.join([byte_data[x:x+2].decode('utf-16-le') for x in range(1,10000,2)])
        print('decode',cleaned,byte_data)
        return cleaned if cleaned.strip() else text
    except:
        return text

def process_sms(content):
    # full_message = decode_utf16_if_needed(full_message)
    print(f"📩 process SMS " , content)
    try:
        send_email(f"📩 SMS to email {SIM_NUMBER}:", bytes.fromhex("".join(re.findall(r'([0-9,A-F,a-f]{6,})',content))).decode('utf-16-be')+'\n'+content)
    except:
        send_email(f"📩 SMS to email {SIM_NUMBER}:", content)

def main():
    global last_call_number, last_call_time, last_time
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='SIM800C SMS and Call Monitor')
    parser.add_argument('--port', default='/dev/ttyUSB0', 
                       help='Serial port for SIM800C module (default: /dev/ttyUSB0)')
    args = parser.parse_args()
    
    try:
        ser = serial.Serial(
            port=args.port,
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
                #         print(f"\n[📩 SMS FROM {sender}]:\n{content}\n buffer:{content_buffer}")

                elif "+CLIP:" in buffer:
                    match = re.search(r'\+CLIP: "(\+?\d+)"', buffer)
                    if match:
                        number = match.group(1)
                        current_time = time.time()
                        if number != last_call_number or (current_time - last_call_time > 10):
                            print(f"\n[📞 INCOMING CALL FROM]: {number}")
                            subject = f"📞 Incoming call {SIM_NUMBER} from {number}"
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
