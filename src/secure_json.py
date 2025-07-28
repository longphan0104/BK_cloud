# secure_json.py
import json
from cryptography.fernet import Fernet

# Key cố định gắn trong app — đủ dùng với yêu cầu của bạn
APP_SECRET_KEY = b'Qrx1vABMmq_S-HB5bRpTj0R8kP2AxOPv6eAZ1YEGyYg='
fernet = Fernet(APP_SECRET_KEY)

def secure_json_load(path):
    try:
        with open(path, "rb") as f:
            encrypted = f.read()
        decrypted = fernet.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except Exception as e:
        print(f"[!] Failed to read {path}: {e}")
        return {}

def secure_json_dump(data, path):
    try:
        raw = json.dumps(data).encode("utf-8")
        encrypted = fernet.encrypt(raw)
        with open(path, "wb") as f:
            f.write(encrypted)
    except Exception as e:
        print(f"[!] Failed to write {path}: {e}")
