import subprocess
import time
import os
import sys
import tempfile
from secure_json import secure_json_load, secure_json_dump

MOUNT_POINT = "Z:"
rclone_process = None
DETACHED_PROCESS = 0x00000008  # Windows only

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_remote_name(user):
    return f"bkcloud_{user}".replace(" ", "_").lower()

def save_rclone_config(user, password, project, auth_url):
    remote_name = get_remote_name(user)
    cleaned_auth_url = auth_url.replace("/auth/tokens", "").rstrip("/")

    config = f"""
[{remote_name}]
type = swift
user = {user}
key = {password}
auth = {cleaned_auth_url}
tenant = {project}
domain = default
tenant_domain = default
endpoint_type = public
region = RegionOne
""".strip()

    secure_json_dump(config, "rclone.sec")

def mount_drive(user, password, project, auth_url):
    global rclone_process
    unmount_drive()

    # Lấy đường dẫn tới rclone.exe (trong thư mục tools)
    rclone_exe = resource_path(os.path.join("tools", "rclone.exe"))

    remote_name = get_remote_name(user)
    conf_data = secure_json_load("rclone.sec")

    if not conf_data:
        save_rclone_config(user, password, project, auth_url)
        conf_data = secure_json_load("rclone.sec")

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".conf") as tmp_conf:
        tmp_conf.write(conf_data)
        tmp_conf_path = tmp_conf.name

    try:
        rclone_process = subprocess.Popen(
            [
                rclone_exe, "mount", f"{remote_name}:", MOUNT_POINT,
                "--config", tmp_conf_path,
                "--vfs-cache-mode", "full",
                "--dir-cache-time", "1s",
                "--volname", f"BK Cloud - {user}"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS
        )
        time.sleep(2)
    finally:
        try:
            os.remove(tmp_conf_path)  # Xóa file tạm
        except:
            pass

def unmount_drive():
    global rclone_process
    if rclone_process and rclone_process.poll() is None:
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(rclone_process.pid)])
        rclone_process = None
