import os, json, requests
from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFrame, QSizePolicy, QApplication, QFileDialog, QDialog,
    QTextEdit, QDialogButtonBox, QRadioButton
)
from PyQt5.QtGui import QFont, QPixmap, QPalette, QBrush, QIcon
from PyQt5.QtCore import Qt

from main import MainWindow
from mount_manager import mount_drive
from utils import resource_path
from secure_json import secure_json_load, secure_json_dump
import manual


#Lưu thông tin đăng nhập sau khi login thành công
def get_saved_auth_url():
    default_url = "http://192.168.1.106"  # fallback mặc định
    try:
        with open("loginurl.json", "r") as f:
            data = json.load(f)
            return data.get("auth_url", default_url)
    except:
        return default_url

def save_auth_url(url):
    data = {"auth_url": url.rstrip("/")}
    with open("loginurl.json", "w") as f:
        json.dump(data, f, indent=2)

def save_successful_login(username, password, project_name, auth_url):
    path = "saved_users.json"
    cleaned_url = auth_url.replace("/auth/tokens", "").rstrip("/")

    user_entry = {
        "username": username,
        "password": password,
        "project_name": project_name,
        "auth_url": cleaned_url,
        "user_display": f"{username}@{project_name}"
    }

    users = []
    if os.path.exists(path):
        users = secure_json_load(path)  # ✅ Mã hóa

    if not any(u["user_display"] == user_entry["user_display"] for u in users):
        users.append(user_entry)
        secure_json_dump(users, path)  # ✅ Mã hóa



class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()

        app_font = QFont("Roboto", 12, QFont.DemiBold)
        QApplication.setFont(app_font)

        icon_path = resource_path(os.path.join("photos", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("BK Cloud")
        self.resize(1440, 900)
        self.setMinimumSize(800, 600)

        bg_path = resource_path(os.path.join("photos", "back.jpg"))
        if os.path.exists(bg_path):
            self.setAutoFillBackground(True)
            palette = self.palette()
            bg_pixmap = QPixmap(bg_path).scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            palette.setBrush(QPalette.Window, QBrush(bg_pixmap))
            self.setPalette(palette)

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)

        login_frame = QFrame()
        login_frame.setMinimumWidth(400)
        login_frame.setMaximumWidth(800)
        login_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 230);
                border-radius: 20px;
            }
        """)
        login_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        login_layout = QVBoxLayout()
        login_layout.setContentsMargins(40, 40, 40, 40)
        login_layout.setSpacing(20)
        login_layout.setAlignment(Qt.AlignTop)

        label_title = QLabel("BK Cloud")
        label_title.setFont(QFont("Arial Rounded MT Bold", 30, QFont.Bold))
        label_title.setAlignment(Qt.AlignCenter)
        label_title.setStyleSheet("background: transparent;")

        label_sub = QLabel("Login")
        label_sub.setFont(QFont("Arial Rounded MT Bold", 16, QFont.Bold))
        label_sub.setAlignment(Qt.AlignCenter)
        label_sub.setStyleSheet("background: transparent;")

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setFixedHeight(50)
        self.username_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #a0c4ff;
                border-radius: 10px;
                padding-left: 8px;
                background-color: white;
            }
        """)

        password_container = QHBoxLayout()
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setFixedHeight(50)
        self.password_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #a0c4ff;
                border-radius: 10px;
                padding-left: 8px;
                background-color: white;
            }
        """)

        self.show_password_button = QPushButton("🔒")
        self.show_password_button.setCheckable(True)
        self.show_password_button.setFixedSize(40, 40)
        self.show_password_button.setStyleSheet("""
            QPushButton {
                border: none;
                background-color: transparent;
            }
        """)
        self.show_password_button.toggled.connect(self.toggle_password)

        password_container.addWidget(self.password_input)
        password_container.addWidget(self.show_password_button)

        self.project_input = QLineEdit()
        self.project_input.setPlaceholderText("Project Name")
        self.project_input.setFixedHeight(50)
        self.project_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #a0c4ff;
                border-radius: 10px;
                padding-left: 8px;
                background-color: white;
            }
        """)

        self.login_button = QPushButton("Login")
        self.login_button.setFixedHeight(50)
        self.login_button.setFixedWidth(160)
        self.login_button.setStyleSheet("""
            QPushButton {
                background-color: #0077b6;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 8px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #0096c7;
            }
        """)
        self.login_button.clicked.connect(self.login)

        help_button = QPushButton("Help")
        help_button.setFixedWidth(100)
        help_button.clicked.connect(self.show_help_dialog)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("""
            QLabel {
                color: red;
                background-color: transparent;
                font-weight: bold;
            }
        """)
        self.error_label.setAlignment(Qt.AlignCenter)

        login_layout.addWidget(label_title)
        login_layout.addWidget(label_sub)
        login_layout.addWidget(self.username_input)
        login_layout.addLayout(password_container)
        login_layout.addWidget(self.project_input)
        button_row = QHBoxLayout()
        button_row.setSpacing(20)
        button_row.setAlignment(Qt.AlignCenter)
        button_row.addWidget(self.login_button)
        button_row.addWidget(help_button)
        login_layout.addLayout(button_row)
        login_layout.addWidget(self.error_label)

        login_frame.setLayout(login_layout)
        main_layout.addWidget(login_frame, alignment=Qt.AlignCenter)

        help_button.setFixedHeight(50)
        help_button.setFixedWidth(160)
        help_button.setStyleSheet("""
            QPushButton {
                background-color: #0077b6;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 8px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #0096c7;
            }
        """)
    # Ẩn và hiện password
    def toggle_password(self, checked):
        if checked:
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.show_password_button.setText("👁️")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.show_password_button.setText("🔒")
    # Scale hình nền khi thu phóng cửa sổ
    def resizeEvent(self, event):
        bg_path = resource_path(os.path.join("photos", "back.jpg"))
        if os.path.exists(bg_path):
            palette = self.palette()
            bg_pixmap = QPixmap(bg_path).scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            palette.setBrush(QPalette.Window, QBrush(bg_pixmap))
            self.setPalette(palette)

    def login(self):
        self.error_label.setText("")

        username = self.username_input.text()
        password = self.password_input.text()
        project = self.project_input.text()

        if not username or not password or not project:
            self.error_label.setText("Please enter full username, password and project name")
            return

        base_url = get_saved_auth_url()
        auth_url = base_url.rstrip("/") + "/identity/v3/auth/tokens"

        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": username,
                            "domain": {"id": "default"},
                            "password": password
                        }
                    }
                },
                "scope": {
                    "project": {
                        "name": project,
                        "domain": {"id": "default"}
                    }
                }
            }
        }

        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(auth_url, json=payload, headers=headers)
            if resp.status_code == 201:
                token = resp.headers["X-Subject-Token"]
                catalog = resp.json()["token"]["catalog"]
                project_id = resp.json()["token"]["project"]["id"]
                user_id = resp.json()["token"]["user"]["id"]

                storage_url = None
                for service in catalog:
                    if service["type"] == "object-store":
                        for ep in service["endpoints"]:
                            if ep["interface"] == "public":
                                storage_url = ep["url"]
                                break
                        break

                if not storage_url:
                    self.error_label.setText("Swift endpoint not found")
                    return

                if "/v1/" not in storage_url:
                    storage_url = storage_url.rstrip("/") + f"/v1/AUTH_{project_id}"

                save_successful_login(username, password, project, auth_url)
                mount_drive(username, password, project, auth_url)

                user = {
                    "username": username,
                    "password": password,
                    "project_name": project,
                    "auth_url": auth_url.replace("/auth/tokens", "").rstrip("/"),
                    "user_display": f"{username}@{project}",
                    "user_id": user_id
                }

                self.main_window = MainWindow(token, storage_url, login_window=self)
                self.main_window.current_user = user
                self.main_window.load_saved_users(select_user_display=user["user_display"])
                self.main_window.show()
                self.hide()

            elif resp.status_code == 401:
                self.error_label.setText("Wrong Username or Password")
            else:
                self.error_label.setText(f"Login error: HTTP {resp.status_code}")

        except Exception as e:
            self.error_label.setText(f"Connection error: {str(e)}")

    #Thay đổi đường dẫn đăng nhập swift
    def show_change_url_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Swift Auth URL")
        dialog.setFixedSize(500, 200)

        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setPlainText(get_saved_auth_url())

        layout.addWidget(QLabel("Enter New Swift Auth URL:"))
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        buttons.accepted.connect(lambda: self.save_new_auth_url(dialog, text_edit.toPlainText()))
        buttons.rejected.connect(dialog.reject)

        dialog.exec_()

    def save_new_auth_url(self, dialog, new_url):
        if not new_url.strip().startswith("http"):
            QMessageBox.warning(self, "Invalid", "Please enter a valid HTTP(S) URL.")
            return
        save_auth_url(new_url.strip())
        QMessageBox.information(self, "Saved", "Auth URL saved successfully.")
        dialog.accept()

    def show_help_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        dialog.setMinimumSize(500, 200)
        layout = QVBoxLayout(dialog)

        label = QLabel("Select an action:")
        layout.addWidget(label)

        # Radio buttons
        manual_radio = QRadioButton("User manual")
        manual_radio.setChecked(True)  # mặc định chọn
        change_url_radio = QRadioButton("Change Swift Auth URL")

        layout.addWidget(manual_radio)
        layout.addWidget(change_url_radio)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        def on_accept():
            if manual_radio.isChecked():
                manual_dialog = QDialog(self)
                manual_dialog.setMinimumSize(1280, 720)
                manual_dialog.setWindowTitle("User Manual")
                manual_layout = QVBoxLayout(manual_dialog)

                text = QTextEdit()
                text.setReadOnly(True)
                text.setHtml(manual.get_help_text())
                manual_layout.addWidget(text)

                close_btn = QDialogButtonBox(QDialogButtonBox.Ok)
                close_btn.accepted.connect(manual_dialog.accept)
                manual_layout.addWidget(close_btn)

                manual_dialog.exec_()

            elif change_url_radio.isChecked():
                self.show_change_url_dialog()

            dialog.accept()

        button_box.accepted.connect(on_accept)
        button_box.rejected.connect(dialog.reject)

        dialog.exec_()


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    login_window = LoginWindow()
    login_window.show()
    sys.exit(app.exec_())
