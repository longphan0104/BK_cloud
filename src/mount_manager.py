import subprocess
import time
import os
import sys

CONFIG_FILE = "rclone.conf"
MOUNT_POINT = "Z:"
rclone_process = None

# 👉 Hằng số để chạy ngầm (Windows only)
DETACHED_PROCESS = 0x00000008

def get_remote_name(user):
    return f"bkcloud_{user}".replace(" ", "_").lower()

def write_rclone_config(remote_name, user, password, project, auth_url):
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
"""
    with open(CONFIG_FILE, "w") as f:
        f.write(config.strip())

def mount_drive(user, password, project, auth_url):
    global rclone_process

    unmount_drive()

    remote_name = get_remote_name(user)
    write_rclone_config(remote_name, user, password, project, auth_url)

    try:
        rclone_process = subprocess.Popen(
            [
                "rclone", "mount", f"{remote_name}:", MOUNT_POINT,
                "--config", CONFIG_FILE,
                "--vfs-cache-mode", "full",
                "--dir-cache-time", "1s",
                "--volname", f"BK Cloud - {user}"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS  # ✅ Chạy nền, không bật console
        )
        time.sleep(2)
    except Exception as e:
        print("❌ Mount failed:", e)

def unmount_drive():
    global rclone_process
    if rclone_process and rclone_process.poll() is None:
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(rclone_process.pid)])
        rclone_process = None
