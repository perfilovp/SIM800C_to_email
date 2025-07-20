SIM800C USB (CH340) on Raspberry Pi with Python

This guide explains how to set up a SIM800C USB GPRS modem (CH340 serial) on a Raspberry Pi, receive SMS, detect incoming calls, and forward all events to Gmail using a Python script.
##🔧 Hardware Required

    Raspberry Pi (any model with USB)

    SIM800C USB GPRS modem (CH340 USB-to-Serial chip)

    A working SIM card with SMS/call capability

    Internet connection for the Pi (for email forwarding)

##📦 Installation
1. Update System
```
sudo apt update
sudo apt upgrade -y
```
2. Install Python Libraries
```
sudo apt install python3-pip -y
pip3 install pyserial
```
3. Verify USB Device

Plug in your SIM800C USB modem and run:
```
lsusb
```
You should see something like:
```
QinHeng Electronics CH340 serial converter
```
Now check the serial port:
```
dmesg | grep ttyUSB
```
Expected output:

... ch341-uart converter now attached to ttyUSB0

Your device will be accessible via /dev/ttyUSB0.
##📧 Gmail Setup (Required for Email Forwarding)

    ⚠️ You need a Gmail account with App Passwords enabled.

Steps:

    Enable 2-Step Verification on your Gmail account.

    Go to https://myaccount.google.com/apppasswords

    Create a new App Password (choose Mail and Other (Raspberry Pi)).

    Save the 16-character password.

##🚀 Using the Python Script
1. Clone or Download This Repository
```
git clone https://github.com/perfilovp/SIM800C_to_email.git
cd sim800c-monitor
```
##2. Edit the Script

Open sim800c_monitor.py and update:

GMAIL_USER = "your_email@gmail.com"
GMAIL_APP_PASSWORD = "your_16char_apppassword"
EMAIL_TO = "recipient_email@gmail.com"

TARGET_NUMBER = "+1234567890"  # optional test SMS number
SMS_TEXT = "Hello from Raspberry Pi!"

3. Run the Script
```
python3 sim800c_monitor.py
```
The script will:

    Send a test SMS on startup

    Print and forward incoming SMS

    Detect incoming calls and forward caller number

📤 Example Email Output

Subject: 📩 SMS from +447700900123
Body:

Sender: +447700900123

Message:
Your code is 1234

Subject: 📞 Incoming call from +447700900123
Body:

Incoming call detected from number: +447700900123

❓ Troubleshooting
Issue	Fix
Permission denied /dev/ttyUSB0	Run: sudo usermod -a -G dialout $USER && reboot
Not receiving SMS	Ensure SIM has signal & SMS credits
No email sent	Check Gmail credentials & network connection
Device not found	Run `dmesg
📃 License

MIT License
