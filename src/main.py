import json, os, sys, requests, mimetypes, re
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from urllib.parse import quote
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QLineEdit,
    QHBoxLayout, QTableWidget, QTableWidgetItem, QMessageBox, QMenu,
    QLabel, QHeaderView, QProgressBar, QSizePolicy, QApplication, QInputDialog, QAbstractItemView,
    QComboBox, QListWidgetItem, QAction, QStackedWidget, QFrame, QTextEdit, QMainWindow, QTabWidget, QDialog,
    QDialogButtonBox, QRadioButton, QSpacerItem, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QRunnable, QThreadPool, QObject, pyqtSlot, QTimer, QEvent
from PyQt5.QtGui import QIcon, QDropEvent, QPixmap, QPalette, QBrush

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from concurrent.futures import ThreadPoolExecutor
from secure_json import secure_json_load, secure_json_dump

import manual

from utils import resource_path
from mount_manager import mount_drive, unmount_drive

#Hai bảng pie chart và line chart ở tab Dashboard
class PieChartCanvas(FigureCanvas):
    def __init__(self, data_dict, parent=None):
        fig = Figure(figsize=(4, 4))
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.plot(data_dict)

    def plot(self, data_dict):
        self.axes.clear()

        labels = []
        sizes = []

        total = sum(data_dict.values())
        for label, size in data_dict.items():
            if size > 0:
                percent = (size / total) * 100 if total > 0 else 0
                label_with_percent = f"{label} ({percent:.1f}%)"
                labels.append(label_with_percent)
                sizes.append(size)

        wedges, texts = self.axes.pie(sizes, startangle=140, radius=1)

        self.axes.legend(
            wedges,
            labels,
            title="File Types",
            loc="upper right",
            bbox_to_anchor=(1.3, 1.0),
        )

        self.axes.set_position([0.05, 0.1, 0.65, 0.8])
        self.axes.axis('equal')

        if hasattr(self, 'usage_text') and self.usage_text:
            self.axes.text(
                0, -1.3,
                self.usage_text,
                ha='center',
                fontsize=10,
                color='black'
            )

        self.draw()

class LineChartCanvas(FigureCanvas):
    def __init__(self, timestamps, parent=None):
        fig = Figure(figsize=(5, 4))
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.plot(timestamps)

    def plot(self, timestamps):
        from collections import Counter
        import matplotlib.dates as mdates
        from datetime import datetime, timedelta

        self.axes.clear()

        if not timestamps:
            self.axes.text(0.5, 0.5, "No data in last 1h", ha='center', va='center')
            self.draw()
            return

        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        one_hour_ago = now - timedelta(hours=1)

        # Lọc timestamps trong 1h gần nhất
        recent = [dt for dt in timestamps if dt >= one_hour_ago]

        # Làm tròn xuống từng phút và đếm
        minutes = [dt.replace(second=0, microsecond=0) for dt in recent]
        counter = Counter(minutes)

        # Dữ liệu chỉ gồm các phút có upload
        sorted_minutes = sorted(counter.keys())
        counts = [counter[m] for m in sorted_minutes]

        self.axes.plot(sorted_minutes, counts, marker='o', color='#007acc')
        self.axes.set_title("Upload count in last 1h")
        self.axes.set_xlabel("Time")
        self.axes.set_ylabel("File count")
        self.axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        self.axes.grid(True)

        # Định dạng trục X theo HH:MM
        self.axes.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=ZoneInfo("Asia/Ho_Chi_Minh")))
        self.axes.xaxis.set_major_locator(mdates.AutoDateLocator())

        self.figure.autofmt_xdate()
        self.draw()
#Các luồng để xử lý upload,delete,download
class UploadWorkerSignals(QObject):
    progress = pyqtSignal(int)
    error = pyqtSignal(str)
    done = pyqtSignal()

class UploadWorker(QRunnable):
    def __init__(self, token, storage_url, container, filepath, object_name, index, total):
        super().__init__()
        self.token = token
        self.storage_url = storage_url
        self.container = container
        self.filepath = filepath
        self.object_name = object_name
        self.index = index
        self.total = total
        self.signals = UploadWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            url = f"{self.storage_url}/{self.container}/{self.object_name}"
            mime_type, _ = mimetypes.guess_type(self.filepath)
            headers = {
                "X-Auth-Token": self.token,
                "Content-Type": mime_type or "application/octet-stream"
            }

            with open(self.filepath, "rb") as f:
                response = requests.put(url, headers=headers, data=f)

            if response.status_code not in [201, 202]:
                self.signals.error.emit(f"Error uploading {self.object_name} - HTTP {response.status_code}")
        except Exception as e:
            self.signals.error.emit(f"Error uploading {self.object_name}: {str(e)}")

        self.signals.done.emit()
        if self.index + 1 == self.total:
            self.signals.done.emit()

class DeleteWorker(QRunnable):
    def __init__(self, token, storage_url, container, object_name, index, total):
        super().__init__()
        self.token = token
        self.storage_url = storage_url
        self.container = container
        self.object_name = object_name
        self.index = index
        self.total = total
        self.signals = UploadWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            url = f"{self.storage_url}/{self.container}/{self.object_name}"
            headers = {"X-Auth-Token": self.token}
            response = requests.delete(url, headers=headers)

            if response.status_code not in [204, 404]:
                self.signals.error.emit(f"Cannot delete {self.object_name} - HTTP {response.status_code}")
        except Exception as e:
            self.signals.error.emit(f"Error deleting {self.object_name}: {str(e)}")
        self.signals.done.emit()

class DownloadWorker(QRunnable):
    def __init__(self, token, storage_url, container, object_name, save_path, index, total):
        super().__init__()
        self.token = token
        self.storage_url = storage_url
        self.container = container
        self.object_name = object_name
        self.save_path = save_path
        self.index = index
        self.total = total
        self.signals = UploadWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            url = f"{self.storage_url}/{self.container}/{self.object_name}"
            headers = {"X-Auth-Token": self.token}
            response = requests.get(url, headers=headers, stream=True)

            if response.status_code == 200:
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                with open(self.save_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            else:
                self.signals.error.emit(f"Error downloading '{self.object_name}' - HTTP {response.status_code}")
        except Exception as e:
            self.signals.error.emit(f"Error downloading '{self.object_name}': {str(e)}")

        self.signals.done.emit()

#Luồng truyền thông tin DICOM từ web về app
class StudyListWorkerSignals(QObject):
    finished = pyqtSignal(list)  # list of (study_id, patient_name, study_date)
    error = pyqtSignal(str)

class StudyListWorker(QRunnable):
    def __init__(self, dicom_url, study_ids, offset=0, limit=10):
        super().__init__()
        self.signals = StudyListWorkerSignals()
        self.dicom_url = dicom_url
        self.study_ids = study_ids
        self.offset = offset
        self.limit = limit

    def run(self):
        try:
            results = []

            # Bước 1: chọn subset cần load
            study_subset = self.study_ids[self.offset : self.offset + self.limit]

            # Bước 2: hàm tải từng study
            def fetch_study(study_id):
                try:
                    info = requests.get(f"{self.dicom_url}/studies/{study_id}").json()
                    tags = info.get("MainDicomTags", {})
                    patient_id = info.get("PatientMainDicomTags", {}).get("PatientID", "Unknown")
                    patient_name = info.get("PatientMainDicomTags", {}).get("PatientName", "Unknown")
                    study_desc = tags.get("StudyDescription", "Unknown")
                    study_date = tags.get("StudyDate", "Unknown")
                    return (patient_id, patient_name, study_desc, study_date, study_id)
                except Exception as e:
                    print(f"[!] Error loading study {study_id}: {e}")
                    return None

            # Bước 3: chạy song song
            with ThreadPoolExecutor(max_workers=4) as executor:
                for result in executor.map(fetch_study, study_subset):
                    if result:
                        results.append(result)

            # Bước 4: gửi kết quả về UI
            self.signals.finished.emit(results)

        except Exception as e:
            self.signals.error.emit(str(e))

#Luồng truyền ảnh DICOM trong tab DICOM Bridge
class DownloadDicomWorkerSignals(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self):
        super().__init__()

class DownloadDicomWorker(QRunnable):
    def __init__(self, dicom_url, instance_ids, temp_dir):
        super().__init__()
        self.dicom_url = dicom_url
        self.instance_ids = instance_ids
        self.temp_dir = temp_dir
        self.signals = DownloadDicomWorkerSignals()

    def run(self):
        try:
            import os, requests
            os.makedirs(self.temp_dir, exist_ok=True)

            def download_one(instance_id):
                try:
                    url = f"{self.dicom_url}/instances/{instance_id}/file"
                    dcm = requests.get(url).content
                    path = os.path.join(self.temp_dir, f"{instance_id}.dcm")
                    with open(path, "wb") as f:
                        f.write(dcm)
                    return path
                except Exception as e:
                    print(f"[!] Failed to download {instance_id}: {e}")
                    return None

            filepaths = []
            total = len(self.instance_ids)
            with ThreadPoolExecutor(max_workers=4) as executor:
                for idx, path in enumerate(executor.map(download_one, self.instance_ids)):
                    if path:
                        filepaths.append(path)
                    percent = int(((idx + 1) / total) * 50)  # Chiếm 50% tiến độ
                    self.signals.progress.emit(percent)

            self.signals.finished.emit(filepaths)

        except Exception as e:
            self.signals.error.emit(str(e))

#Chức năng mở và edit nhiều file .txt
class FileViewerWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Viewer")
        self.setGeometry(200, 200, 800, 600)
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint| Qt.WindowCloseButtonHint)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)

    def open_file(self, filename, content, save_callback):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == filename:
                self.tab_widget.setCurrentIndex(i)
                return

        tab = QWidget()
        layout = QVBoxLayout(tab)

        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        layout.addWidget(text_edit)

        save_btn = QPushButton("💾 Save")
        layout.addWidget(save_btn)

        self.tab_widget.addTab(tab, filename)
        self.tab_widget.setCurrentWidget(tab)

        # Gán sự kiện Save
        save_btn.clicked.connect(lambda: save_callback(filename, text_edit.toPlainText()))

    def close_tab(self, index):
        self.tab_widget.removeTab(index)
        # Nếu không còn tab nào nữa, tự đóng cửa sổ
        if self.tab_widget.count() == 0:
            self.close()

#Kéo thả file vào folder để upload
class DraggableTableWidget(QTableWidget):
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.main_window = main_window

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QTableWidget { border: 4px dashed #0078d7; }")

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        if self.main_window:
            self.main_window.handle_drop_event(event)

#Kéo thả folder vào để tạo folder mới
class DraggableContainerTableWidget(QTableWidget):
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.main_window = main_window

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QTableWidget { border: 3px dashed #0078d7; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        if self.main_window:
            self.main_window.handle_drop_to_container_table(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

#Định dạng ngày giờ và dung lượng file
def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

def format_datetime(date_str):
    try:
        dt_utc = datetime.fromisoformat(date_str).replace(tzinfo=ZoneInfo("UTC"))
        dt_local = dt_utc.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        return dt_local.strftime("%d-%m-%Y %H:%M")
    except Exception:
        return date_str

class MainWindow(QWidget):
    #Phần UI của app
    def __init__(self, token=None, storage_url=None, login_window=None):
        super().__init__()

        self.login_window = login_window
        self.logging_out = False
        self.token = token
        self.storage_url = storage_url

        self.viewer_window = None

        self.total_quota_bytes = 0.1 * 1024 ** 3  # usage limit
        self.used_bytes = 0
        self.container_sort_state = {"column": 0, "ascending": True}
        self.object_sort_state = {"column": 0, "ascending": True}
        self.object_sort_order = {}
        self.selected_container = None
        self.threadpool = QThreadPool()
        self.completed_tasks = 0
        self.total_tasks = 0

        self.study_ids = []  # Toàn bộ danh sách study ID đã lấy từ Orthanc
        self.loaded_offset = 0  # Bao nhiêu study đã được load

        icon_path = resource_path(os.path.join("photos", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("BK Cloud")
        self.setMinimumSize(800, 600)
        self.resize(1440, 900)

        self.update_background()

        # Main layout
        main_layout = QHBoxLayout(self)
        self.setLayout(main_layout)

        # === Sidebar ===
        sidebar = QFrame()
        sidebar.setStyleSheet("background-color: transparent;")
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 30, 10, 10)

        # Logout button (moved above BK Cloud)
        footer_layout = QHBoxLayout()
        logout_btn = QPushButton("Logout")
        help_btn = QPushButton("Help")

        logout_btn.setStyleSheet("color: white;")
        help_btn.setStyleSheet("color: white;")

        logout_btn.clicked.connect(self.logout)
        help_btn.clicked.connect(self.show_help_dialog)  # 👈 Sẽ tạo hàm này bên dưới

        footer_layout.addWidget(help_btn)
        footer_layout.addStretch()
        footer_layout.addWidget(logout_btn)

        sidebar_layout.addLayout(footer_layout)

        title_label = QLabel("BK Cloud")
        title_label.setStyleSheet("font-size: 35px; font-weight: bold; color: white;")
        title_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(title_label)


        sidebar_layout.addSpacing(30)
        self.saved_user_dropdown = QComboBox()
        self.saved_user_dropdown.setFixedWidth(200)
        self.saved_user_dropdown.currentIndexChanged.connect(self.switch_saved_user)
        self.delete_user_btn = QPushButton("\ud83d\uddd1\ufe0f")
        self.delete_user_btn.setToolTip("Delete saved user")
        self.delete_user_btn.clicked.connect(self.delete_selected_user)
        user_layout = QHBoxLayout()
        user_layout.addWidget(self.saved_user_dropdown)
        user_layout.addWidget(self.delete_user_btn)
        sidebar_layout.addLayout(user_layout)
        sidebar_layout.addSpacing(30)
        self.saved_user_dropdown.setStyleSheet("""
            QComboBox {
                color: white;
                background-color: #333;
                border: 1px solid #666;
                padding: 2px;
            }
            QComboBox QAbstractItemView {
                background-color: #222;
                color: white;
            }
        """)

        self.delete_user_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background-color: transparent;
                border: none;
                font-size: 18px;
            }
            QPushButton:hover {
                color: red;
            }
        """)

        btn_dashboard = QPushButton("🏠 Dashboard")
        btn_myfile = QPushButton("📁 My File")
        btn_backup = QPushButton("🛡️ Backup")
        btn_dicom = QPushButton("📰 DICOM Bridge")

        for btn in [btn_dashboard, btn_myfile, btn_backup, btn_dicom]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    font-size: 16px;
                    text-align: left;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #444444;
                }
            """)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)

        self.list_btn = QPushButton("Refresh")
        self.create_container_btn = QPushButton("New Folder")
        self.upload_btn = QPushButton("Upload File/Folder")

        self.myfile_buttons_widget = QFrame()
        myfile_buttons_layout = QVBoxLayout(self.myfile_buttons_widget)
        myfile_buttons_layout.setSpacing(10)
        myfile_buttons_layout.setContentsMargins(0, 5, 0, 0)

        # Thêm nút
        myfile_buttons_layout.addWidget(self.list_btn)
        myfile_buttons_layout.addWidget(self.create_container_btn)
        myfile_buttons_layout.addWidget(self.upload_btn)

        btn_style = """
                    QPushButton {
                        color: white;
                        background-color: transparent;
                        border: none;
                        font-size: 14px;
                        padding: 2px;
                        text-align: left;
                    }
                    QPushButton:hover {
                        background-color: #444;
                    }
                """
        self.list_btn.setStyleSheet(btn_style)
        self.create_container_btn.setStyleSheet(btn_style)
        self.upload_btn.setStyleSheet(btn_style)
        for btn in [self.list_btn, self.create_container_btn, self.upload_btn]:
            line = QHBoxLayout()
            line.addSpacing(35)  # 👈 khoảng cách bên trái
            line.addWidget(btn)
            myfile_buttons_layout.addLayout(line)

        self.myfile_buttons_widget.setVisible(False)  # Ẩn mặc định

        main_menu_label = QLabel("Main menu")
        main_menu_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white; padding-top: 20px;")
        main_menu_label.setAlignment(Qt.AlignLeft)

        sidebar_layout.addWidget(main_menu_label)
        sidebar_layout.addWidget(btn_dashboard)
        sidebar_layout.addWidget(btn_myfile)
        sidebar_layout.addWidget(self.myfile_buttons_widget)
        sidebar_layout.addWidget(btn_backup)
        sidebar_layout.addWidget(btn_dicom)

        sidebar_layout.addStretch()

        # === Pages ===
        self.stack = QStackedWidget()


        # Page wrapper frame (rounded white background)
        def create_page_container():
            container = QFrame()
            container.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border-radius: 5px;
                }
            """)

            container_layout = QVBoxLayout(container)
            return container, container_layout


        # Dashboard page with title
        dashboard_page, dashboard_layout = create_page_container()
        self.stack.addWidget(dashboard_page)
        # === DASHBOARD CONTENT ===

        title_dashboard = QLabel("My storage")
        title_dashboard.setStyleSheet("font-size: 24px; font-weight: bold;")
        dashboard_layout.addWidget(title_dashboard)

        # Grid layout cho các block
        storage_block_layout = QHBoxLayout()
        dashboard_layout.addLayout(storage_block_layout)

        self.file_type_stats = {
            "Documents": {"extensions": [".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx"], "count": 0, "icon": "📄"},
            "Videos": {"extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv"], "count": 0, "icon": "🎞️"},
            "Images": {"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".dcm"], "count": 0, "icon": "🖼️"},
            "Audios": {"extensions": [".mp3", ".wav", ".aac", ".ogg"], "count": 0, "icon": "🎵"},
            "Others": {"extensions": [], "count": 0, "icon": "📦"},
        }

        self.file_type_cards = {}

        for file_type, info in self.file_type_stats.items():
            card = QFrame()
            card.setFixedSize(200, 120)
            card.setStyleSheet("""
                QFrame {
                    background-color: #f0f0f0;
                    border-radius: 12px;
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setAlignment(Qt.AlignCenter)

            icon_label = QLabel(info["icon"])
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet("font-size: 32px;")
            card_layout.addWidget(icon_label)

            title_label = QLabel(file_type)
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
            card_layout.addWidget(title_label)

            count_label = QLabel("0 Files")
            count_label.setAlignment(Qt.AlignCenter)
            count_label.setStyleSheet("color: gray; font-size: 14px;")
            card_layout.addWidget(count_label)

            self.file_type_cards[file_type] = count_label
            storage_block_layout.addWidget(card)

        dashboard_layout.addSpacing(80)
        chart_container = QHBoxLayout()

        # 🔁 Pie chart (không cần QLabel bên ngoài nữa)
        self.pie_chart = PieChartCanvas({})
        self.pie_chart.usage_text = "0 B / 0 B"  # ✅ Text sẽ được vẽ trực tiếp bên dưới pie

        # Wrapper vẫn cần để giữ layout
        pie_chart_layout = QVBoxLayout()
        pie_chart_layout.addWidget(self.pie_chart)

        pie_chart_wrapper = QWidget()
        pie_chart_wrapper.setLayout(pie_chart_layout)

        # Line chart như cũ
        self.line_chart = LineChartCanvas([])

        chart_container.addWidget(pie_chart_wrapper)
        chart_container.addWidget(self.line_chart)

        dashboard_layout.addLayout(chart_container)

        dashboard_layout.addSpacing(70)

        # My File page start
        myfile_page, self.myfile_layout = create_page_container()
        self.stack.addWidget(myfile_page)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stack)

        # === UI chuyển vào My File layout ===
        logout_layout = QHBoxLayout()

        # 🔎 Search All Box
        self.search_all_box = QLineEdit()
        self.search_all_box.setPlaceholderText("Search all files...")
        self.search_all_box.setMinimumWidth(175)  # Chiều rộng tối thiểu
        self.search_all_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_all_box.textChanged.connect(self.filter_all_containers_and_objects)

        clear_icon = QIcon(resource_path(os.path.join("photos", "clear.png")))
        clear_action = QAction(clear_icon, "", self.search_all_box)
        clear_action.setToolTip("Clear Search Input")
        clear_action.triggered.connect(self.search_all_box.clear)
        self.search_all_box.addAction(clear_action, QLineEdit.TrailingPosition)

        logout_layout.addWidget(self.search_all_box)

        # 🔁 Spacer co giãn ở giữa
        spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        logout_layout.addItem(spacer)

        # 📊 Usage Bar
        self.usage_bar = QProgressBar()
        self.usage_bar.setMaximum(100)
        self.usage_bar.setValue(0)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setMinimumWidth(175)
        self.usage_bar.setFixedHeight(25)
        self.usage_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        logout_layout.addWidget(self.usage_bar)

        # 🏷️ Usage Label
        self.usage_label = QLabel(f"0 B / {self.format_size(self.total_quota_bytes)}")
        self.usage_label.setMinimumWidth(100)
        self.usage_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        logout_layout.addWidget(self.usage_label)

        self.myfile_layout.addLayout(logout_layout)

        container_header_layout = QHBoxLayout()
        container_header_layout.addWidget(QLabel("Folder list"))
        container_header_layout.addStretch()
        self.myfile_layout.addLayout(container_header_layout)

        self.container_table = DraggableContainerTableWidget(main_window=self)
        self.container_table.setColumnCount(2)
        self.container_table.setHorizontalHeaderLabels(["Folder", "Size"])
        self.container_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.container_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.container_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.container_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.container_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.container_table.cellClicked.connect(self.on_container_clicked)
        self.container_table.horizontalHeader().sectionClicked.connect(self.on_container_header_clicked)
        self.myfile_layout.addWidget(self.container_table)

        self.container_search = self.create_search_box("Search Folder...", self.filter_containers)
        self.myfile_layout.insertWidget(self.myfile_layout.indexOf(self.container_table), self.container_search)

        object_header_layout = QHBoxLayout()
        object_header_layout.addWidget(QLabel("File list in Folder"))
        object_header_layout.addStretch()
        self.myfile_layout.addLayout(object_header_layout)

        self.table = DraggableTableWidget(main_window=self)
        self.object_search = self.create_search_box("Search File...", self.filter_objects)
        self.myfile_layout.addWidget(self.object_search)

        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["File Name", "Size", "Last Updated"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().resizeSection(1, 160)
        self.table.horizontalHeader().resizeSection(2, 230)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.horizontalHeader().sectionClicked.connect(self.on_object_header_clicked)
        self.myfile_layout.addWidget(self.table)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.myfile_layout.addWidget(self.progress_bar)

        self.list_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.list_btn.clicked.connect(self.list_containers)

        self.create_container_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.create_container_btn.clicked.connect(self.create_container_dialog)

        self.upload_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.upload_btn.clicked.connect(self.upload_file_or_folder)

        self.container_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.container_table.customContextMenuRequested.connect(self.container_context_menu)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.object_context_menu)

        self.container_table.setStyleSheet("""
            QTableWidget {
                background-color: #fafafa;
                border: 1px solid #ccc;
                gridline-color: #ddd;
            }
            QHeaderView::section {
                background-color: #fafafa;
                border: 1px solid #ccc;
                padding-left: 8px;
            }
        """)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #fafafa;
                border: 1px solid #ccc;
                gridline-color: #ddd;
            }
            QHeaderView::section {
                background-color: #fafafa;
                border: 1px solid #ccc;
                padding-left: 8px;
            }
        """)

        self.container_table.horizontalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: #f5f5f5;
                color: black;
                font-weight: bold;
                font-size: 20px;
            }
        """)

        self.table.horizontalHeader().setStyleSheet("""
                    QHeaderView::section {
                        background-color: #f5f5f5;
                        color: black;
                        font-weight: bold;
                        font-size: 20px;
                    }
                """)

        backup_page, backup_layout = create_page_container()
        self.stack.addWidget(backup_page)

        title_backup = QLabel("🛡️ Backup")
        title_backup.setStyleSheet("font-size: 24px; font-weight: bold;")
        backup_layout.addWidget(title_backup)

        backup_layout.addSpacing(25)

        self.backup_info_label = QLabel("Backup is not set up yet")
        self.backup_info_label.setStyleSheet("font-size: 14px; color: gray;")

        self.btn_set_time = QPushButton("🕒 Set backup time")
        self.btn_choose_folder = QPushButton("📂 Select backup folder")
        self.btn_backup_now = QPushButton("⚡ Backup now")
        self.btn_clear_setting = QPushButton("🗑️ Clear backup setting")

        # Style nút con
        btn_style = """
            QPushButton {
                background-color: white;
                color: black;
                border: 1px solid #888;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border: 1px solid #555;
            }
        """

        for btn in [self.btn_set_time, self.btn_choose_folder, self.btn_backup_now, self.btn_clear_setting]:
            btn.setFixedHeight(40)
            btn.setStyleSheet(btn_style)

        backup_layout.addWidget(self.btn_set_time)
        backup_layout.addSpacing(15)
        backup_layout.addWidget(self.btn_choose_folder)
        backup_layout.addSpacing(15)
        backup_layout.addWidget(self.btn_backup_now)
        backup_layout.addSpacing(15)
        backup_layout.addWidget(self.btn_clear_setting)
        backup_layout.addSpacing(15)
        backup_layout.addWidget(QLabel("Current setup status:"))
        backup_layout.addWidget(self.backup_info_label)
        backup_layout.addStretch()

        dicom_page, dicom_layout = create_page_container()
        self.stack.addWidget(dicom_page)
        # Tiêu đề
        title_dicom = QLabel("📰 DICOM Bridge (Orthanc → Swift)")
        title_dicom.setStyleSheet("font-size: 24px; font-weight: bold;")
        dicom_layout.addWidget(title_dicom)
        dicom_layout.addSpacing(15)
        # === Nút chức năng giống My File ===
        self.dicom_refresh_btn = QPushButton("🔄 Refresh Study List")
        self.dicom_upload_btn = QPushButton("⬆️ Upload Selected Study")
        self.dicom_load_more_btn = QPushButton("➕ Load More")

        self.dicom_buttons_widget = QFrame()
        dicom_buttons_layout = QVBoxLayout(self.dicom_buttons_widget)
        dicom_buttons_layout.setSpacing(10)
        dicom_buttons_layout.setContentsMargins(0, 5, 0, 0)

        # Hàng: Refresh + Load More
        refresh_load_row = QHBoxLayout()
        refresh_load_row.addSpacing(35)
        self.dicom_refresh_btn.setStyleSheet(btn_style)
        self.dicom_load_more_btn.setStyleSheet(btn_style)
        refresh_load_row.addWidget(self.dicom_refresh_btn)
        refresh_load_row.addSpacing(10)
        refresh_load_row.addWidget(self.dicom_load_more_btn)
        dicom_buttons_layout.addLayout(refresh_load_row)

        # Hàng: Upload
        upload_row = QHBoxLayout()
        upload_row.addSpacing(35)
        self.dicom_upload_btn.setStyleSheet(btn_style)
        upload_row.addWidget(self.dicom_upload_btn)
        dicom_buttons_layout.addLayout(upload_row)

        dicom_layout.addWidget(self.dicom_buttons_widget)
        dicom_layout.addSpacing(20)

        self.study_list = QTableWidget()
        self.study_list.setColumnCount(5)
        self.study_list.setHorizontalHeaderLabels([
            "Patient ID", "Patient Name", "Study Description", "Study Date", "Study ID (Hidden)"
        ])
        self.study_list.setColumnHidden(4, True)  # 👈 Ẩn cột chứa Study ID
        self.study_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.study_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.study_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.study_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.study_list.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #ccc;
                gridline-color: #aaa;
            }
            QHeaderView::section {
                background-color: #eee;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #bbb;
            }
            QTableWidget::item {
                padding: 4px;
            }
        """)
        dicom_layout.addWidget(self.study_list)

        #new TAB

        self.dicom_progress_bar = QProgressBar()
        self.dicom_progress_bar.setValue(0)
        self.dicom_progress_bar.setVisible(False)  # Ẩn mặc định
        dicom_layout.addWidget(self.dicom_progress_bar)

        btn_dashboard.clicked.connect(lambda: self.switch_tab(0))
        btn_myfile.clicked.connect(lambda: (self.switch_tab(1),self.list_containers()))
        btn_backup.clicked.connect(lambda: (self.switch_tab(2), self.update_backup_status_label()))
        btn_dicom.clicked.connect(lambda: self.switch_tab(3))

        self.calculate_total_used_bytes()
        self.list_containers()
        self.update_file_type_stats()

        self.usage_timer = QTimer(self)
        self.usage_timer.timeout.connect(self.calculate_total_used_bytes)
        self.usage_timer.start(10000)

        self.backup_dir = os.path.join(os.getcwd(), "backup")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.backup_timer = QTimer(self)
        self.backup_timer.setSingleShot(True)
        self.next_backup_time = None
        self.btn_set_time.clicked.connect(self.show_backup_time_dialog)

        self.btn_choose_folder.clicked.connect(self.choose_backup_folders)
        self.btn_clear_setting.clicked.connect(self.clear_backup_setting)
        self.btn_backup_now.clicked.connect(self.backup_now)

        self.dicom_refresh_btn.clicked.connect(self.load_studies_from_orthanc)
        self.dicom_upload_btn.clicked.connect(self.upload_selected_study_to_swift)
        self.dicom_load_more_btn.clicked.connect(self.load_more_studies)

        self.study_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.study_list.customContextMenuRequested.connect(self.show_study_context_menu)
        self.load_studies_from_orthanc()

#Xử lý chung
    # Scale hình nền khi thu phóng cửa sổ
    def update_background(self):
        bg_path = resource_path(os.path.join("photos", "black.jpg"))
        if os.path.exists(bg_path):
            self.setAutoFillBackground(True)
            palette = self.palette()
            pixmap = QPixmap(bg_path).scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            palette.setBrush(QPalette.Window, QBrush(pixmap))
            self.setPalette(palette)

    def resizeEvent(self, event):
        self.update_background()
        return super().resizeEvent(event)
    # Chuyển đổi giữa các tab trong app
    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        self.myfile_buttons_widget.setVisible(index == 1)

#Help function
    # Hiện dialog Help
    def show_help_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        layout = QVBoxLayout(dialog)

        label = QLabel("Select an action to support:")
        layout.addWidget(label)

        user_manual_radio = QRadioButton("User manual")
        change_dicom_radio = QRadioButton("Change DICOMweb URL")
        change_password_radio = QRadioButton("Change user password")

        user_manual_radio.setChecked(True)
        layout.addWidget(user_manual_radio)
        layout.addWidget(change_dicom_radio)
        layout.addWidget(change_password_radio)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        def on_accept():
            if user_manual_radio.isChecked():
                self.manual_dialog = QDialog()
                self.manual_dialog.setMinimumSize(1280, 720)
                self.manual_dialog.setWindowTitle("User Manual")
                self.manual_dialog.setWindowFlags(
                    Qt.Window
                    | Qt.WindowCloseButtonHint
                    | Qt.WindowMinimizeButtonHint
                    | Qt.WindowMaximizeButtonHint
                )
                self.manual_dialog.setAttribute(Qt.WA_DeleteOnClose)

                icon_path = resource_path(os.path.join("photos", "logo.ico"))
                if os.path.exists(icon_path):
                    self.manual_dialog.setWindowIcon(QIcon(icon_path))

                manual_layout = QVBoxLayout(self.manual_dialog)

                text = QTextEdit()
                text.setReadOnly(True)
                text.setHtml(manual.get_help_text())
                manual_layout.addWidget(text)

                button_box = QDialogButtonBox(QDialogButtonBox.Ok)
                button_box.accepted.connect(self.manual_dialog.close)
                manual_layout.addWidget(button_box)

                def handle_change(event):
                    if event.type() == QEvent.WindowStateChange:
                        if self.manual_dialog.windowState() & Qt.WindowMaximized:
                            self.manual_dialog.showFullScreen()
                    return QDialog.changeEvent(self.manual_dialog, event)

                self.manual_dialog.changeEvent = handle_change

                self.manual_dialog.show()

            elif change_dicom_radio.isChecked():
                current_url = self.get_dicom_url()
                new_url, ok = QInputDialog.getText(self, "Change DICOMweb URL", "Enter new DICOMweb URL:", QLineEdit.Normal, current_url)
                if ok and new_url.strip():
                    self.set_dicom_url(new_url.strip())
                    QMessageBox.information(self, "Success", "DICOM URL has been updated.")

            elif change_password_radio.isChecked():
                self.show_change_password_dialog()

            dialog.accept()

        button_box.accepted.connect(on_accept)
        button_box.rejected.connect(dialog.reject)

        dialog.exec_()
    # Chức năng thay đổi mật khẩu người dùng
    def show_change_password_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Password")
        dialog.setMinimumSize(400, 250)

        layout = QVBoxLayout(dialog)

        current_user = self.get_current_username()
        layout.addWidget(QLabel(f"Change user '{current_user}' password:"))

        old_pass = QLineEdit()
        old_pass.setPlaceholderText("Current Password")
        old_pass.setEchoMode(QLineEdit.Password)

        new_pass = QLineEdit()
        new_pass.setPlaceholderText("New Password")
        new_pass.setEchoMode(QLineEdit.Password)

        confirm_pass = QLineEdit()
        confirm_pass.setPlaceholderText("Confirm New Password")
        confirm_pass.setEchoMode(QLineEdit.Password)

        layout.addWidget(old_pass)
        layout.addWidget(new_pass)
        layout.addWidget(confirm_pass)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        def on_accept():
            old = old_pass.text()
            new = new_pass.text()
            confirm = confirm_pass.text()

            if not old or not new or not confirm:
                QMessageBox.warning(dialog, "Missing info", "Please fill in all fields.")
                return
            if new != confirm:
                QMessageBox.warning(dialog, "Mismatch", "New passwords do not match.")
                return

            try:
                user = getattr(self, "current_user", {})
                user_id = user.get("user_id")
                auth_url = user.get("auth_url", "").rstrip("/")

                if not user_id or not auth_url:
                    raise Exception("Missing user info")

                if auth_url.endswith("/v3"):
                    url = f"{auth_url}/users/{user_id}/password"
                else:
                    url = f"{auth_url}/v3/users/{user_id}/password"

                headers = {
                    "X-Auth-Token": self.token,
                    "Content-Type": "application/json"
                }
                payload = {
                    "user": {
                        "original_password": old,
                        "password": new
                    }
                }

                response = requests.post(url, headers=headers, json=payload)

                if response.status_code == 204:
                    # ✅ Cập nhật mật khẩu mới trong saved_users.json
                    try:
                        from secure_json import secure_json_load, secure_json_dump
                        path = "saved_users.json"
                        if os.path.exists(path):
                            users = secure_json_load(path)
                            updated = False
                            for u in users:
                                if u.get("user_display") == user.get("user_display"):
                                    u["password"] = new
                                    updated = True
                                    break
                            if updated:
                                secure_json_dump(users, path)
                    except Exception as e:
                        QMessageBox.warning(dialog, "Warning",
                                            f"Password changed but failed to update saved_users.json:\n{e}")

                    QMessageBox.information(dialog, "Success", "Password changed successfully.")
                    dialog.accept()

                elif response.status_code == 401:
                    QMessageBox.critical(dialog, "Error", "Incorrect current password.")
                elif response.status_code == 400:
                    QMessageBox.critical(
                        dialog,
                        "Error",
                        "Failed to change password.\nPossible causes:\n"
                        "- Incorrect current password\n"
                        "- New password was used recently and cannot be reused"
                    )
                else:
                    QMessageBox.critical(dialog, "Error", f"Failed to change password: HTTP {response.status_code}")

            except Exception as e:
                QMessageBox.critical(dialog, "Error", str(e))

        button_box.accepted.connect(on_accept)
        button_box.rejected.connect(dialog.reject)

        dialog.exec_()

#Logout và Close
    # Xử lí và phân biệt giữa logout và đóng app
    def logout(self):
        confirm = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to log out ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.logging_out = True  # 👈 Đánh dấu là đang logout
            self.perform_logout()

    def perform_logout(self):
        self.backup_timer.stop()
        self.next_backup_time = None
        unmount_drive()
        self.close()  # Gọi close, nhưng đã đánh dấu là logout
        if self.login_window:
            self.login_window.show()

    def closeEvent(self, event):
        if self.logging_out:
            # Nếu là logout, không hỏi lại
            event.accept()
        else:
            reply = QMessageBox.question(
                self,
                'Exit',
                'Are you sure you want to exit ?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.backup_timer.stop()
                self.next_backup_time = None
                unmount_drive()
                event.accept()
            else:
                event.ignore()

#Lưu thông tin login và switch user
    # Lấy thông tin user hiện tại hiển thị lên app
    def get_current_username(self):
        try:
            index = self.saved_user_dropdown.currentIndex()
            return self.saved_users[index]["username"]
        except:
            return "default"
    # Load thông tin user đã lưu trong file .json
    def load_saved_users(self, select_user_display=None):
        path = "saved_users.json"
        self.saved_users = []

        if os.path.exists(path):
            all_users = secure_json_load(path)

            if select_user_display:
                selected_user = None
                remaining_users = []
                for user in all_users:
                    if user["user_display"] == select_user_display:
                        selected_user = user
                    else:
                        remaining_users.append(user)

                if selected_user:
                    self.saved_users = [selected_user] + remaining_users
                else:
                    self.saved_users = all_users
            else:
                self.saved_users = all_users

        self.saved_user_dropdown.blockSignals(True)
        self.saved_user_dropdown.clear()

        for user in self.saved_users:
            self.saved_user_dropdown.addItem(user["user_display"])

        self.saved_user_dropdown.setCurrentIndex(0)
        self.current_user_index = 0  # ✅ Ghi nhớ user đang chọn
        self.saved_user_dropdown.blockSignals(False)

        self.update_backup_status_label()
        self.schedule_backup_from_config()
    # Chuyển đổi user đã lưu
    def switch_saved_user(self, index):
        if index < 0 or index >= len(self.saved_users):
            return

        user = self.saved_users[index]

        # 🔐 Xác nhận mật khẩu
        password_input, ok = QInputDialog.getText(
            self,
            "Confirm Password",
            f"Enter password for {user['user_display']}:",
            QLineEdit.Password
        )

        if not ok:
            # Người dùng cancel → rollback dropdown
            self.saved_user_dropdown.blockSignals(True)
            self.saved_user_dropdown.setCurrentIndex(self.current_user_index)
            self.saved_user_dropdown.blockSignals(False)
            return

        if password_input != user["password"]:
            QMessageBox.warning(self, "Incorrect Password", "The password you entered is incorrect.")
            self.saved_user_dropdown.blockSignals(True)
            self.saved_user_dropdown.setCurrentIndex(self.current_user_index)
            self.saved_user_dropdown.blockSignals(False)
            return

        # ✅ Nếu đúng, tiếp tục chuyển user
        try:
            unmount_drive()
            token, storage_url = self.re_authenticate_user(user)
            self.token = token
            self.storage_url = storage_url
            self.selected_container = None
            self.list_containers()
            self.calculate_total_used_bytes()

            mount_drive(
                user["username"],
                user["password"],
                user["project_name"],
                user["auth_url"],
            )

            # ✅ Đổi thành công → cập nhật index và UI
            self.current_user_index = 0  # Vì sẽ load lại và đưa user mới lên đầu
            self.load_saved_users(select_user_display=user["user_display"])  # ⬅️ Reorder UI dropdown

            QMessageBox.information(self, "Switch user", f"Switched to user {user['user_display']} successfully")
            self.update_backup_status_label()
            self.schedule_backup_from_config()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot switch: {str(e)}")
            # Trả lại dropdown nếu lỗi
            self.saved_user_dropdown.blockSignals(True)
            self.saved_user_dropdown.setCurrentIndex(self.current_user_index)
            self.saved_user_dropdown.blockSignals(False)

    # Đăng nhập lại sau khi chuyển user
    def re_authenticate_user(self, user):
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": user["username"],
                            "domain": {"id": "default"},
                            "password": user["password"]
                        }
                    }
                },
                "scope": {
                    "project": {
                        "name": user["project_name"],
                        "domain": {"id": "default"}
                    }
                }
            }
        }

        headers = {'Content-Type': 'application/json'}
        url = user["auth_url"].rstrip("/") + "/auth/tokens"
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            token = response.headers.get("X-Subject-Token")

            # ✅ Tìm đúng object-store service
            catalog = response.json()["token"]["catalog"]
            object_store = next((svc for svc in catalog if svc["type"] == "object-store"), None)
            if not object_store:
                raise Exception("Object-store service not found in catalog")

            # ✅ Lấy đúng endpoint "public"
            public_endpoint = next((ep for ep in object_store["endpoints"] if ep["interface"] == "public"), None)
            if not public_endpoint:
                raise Exception("Public endpoint for object-store not found")

            storage_url = public_endpoint["url"]
            return token, storage_url

        else:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")
    # Xóa user đã lưu
    def delete_selected_user(self):
        index = self.saved_user_dropdown.currentIndex()
        if index < 0:
            return

        user = self.saved_users[index]
        confirm = QMessageBox.question(
            self,
            "Delete saved user",
            f"Delete user '{user['user_display']}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            del self.saved_users[index]
            secure_json_dump(self.saved_users, "saved_users.json")
            self.load_saved_users()

#Tab Dashboard
    # Lấy các extension file để cập nhật vào Dashboard
    def get_file_type_sizes(self):
        result = {key: 0 for key in self.file_type_stats.keys()}
        containers = self.get_all_containers()

        for container in containers:
            objects = self.list_objects(container)
            for obj in objects:
                name = obj.get("name")
                size = int(obj.get("bytes", 0))
                ext = os.path.splitext(name)[1].lower()

                matched = False
                for file_type, info in self.file_type_stats.items():
                    if ext in info["extensions"]:
                        result[file_type] += size
                        matched = True
                        break
                if not matched:
                    result["Others"] += size
        return result

    def update_file_type_stats(self):
        # Reset count
        for info in self.file_type_stats.values():
            info["count"] = 0

        # Lấy danh sách tất cả containers
        containers = self.get_all_containers()  # Cần có hàm này

        for container in containers:
            # Lấy danh sách file trong từng container
            objects = self.list_objects(container)  # Cần có hàm này

            for obj in objects:
                filename = obj.get("name")  # hoặc obj.name tùy kiểu dữ liệu
                if not filename:
                    continue

                ext = os.path.splitext(filename)[1].lower()
                matched = False
                for file_type, info in self.file_type_stats.items():
                    if ext in info["extensions"]:
                        info["count"] += 1
                        matched = True
                        break
                if not matched:
                    self.file_type_stats["Others"]["count"] += 1

        # Cập nhật lại UI
        for file_type, label in self.file_type_cards.items():
            count = self.file_type_stats[file_type]["count"]
            label.setText(f"{count} Files")

    # Lấy mốc thời gian để upload vào linechart
    def get_upload_timestamps_last_1h(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        threshold = now - timedelta(hours=1)
        timestamps = []

        containers = self.get_all_containers()
        for container in containers:
            for obj in self.list_objects(container):
                last_modified = obj.get("last_modified")
                if last_modified:
                    try:
                        dt = datetime.fromisoformat(last_modified).replace(tzinfo=ZoneInfo("UTC")).astimezone(
                            ZoneInfo("Asia/Ho_Chi_Minh"))
                        if dt >= threshold:
                            timestamps.append(dt)
                    except Exception:
                        pass
        return timestamps

    #Tab My file
        #Xử lý logic

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def filter_all_containers_and_objects(self, text):
        keyword = text.strip().lower()
        self.container_table.setRowCount(0)
        self.table.setRowCount(0)
        self.selected_container = None

        if not keyword:
            self.list_containers()
            return

        headers = {"X-Auth-Token": self.token}
        matched_containers = []

        for container in self.get_all_containers():
            try:
                url = f"{self.storage_url}/{container}?format=json"
                response = requests.get(url, headers=headers)
                if response.status_code != 200:
                    continue

                objects = response.json()
                matched_objects = [obj for obj in objects if keyword in obj.get("name", "").lower()]

                if matched_objects:
                    # Hiển thị container nếu có object trùng
                    total_size = sum(int(obj.get("bytes", 0)) for obj in objects)
                    row = self.container_table.rowCount()
                    self.container_table.insertRow(row)
                    self.container_table.setItem(row, 0, QTableWidgetItem(container))
                    self.container_table.setItem(row, 1, QTableWidgetItem(format_bytes(total_size)))
                    matched_containers.append((container, matched_objects))

            except Exception as e:
                print(f"Error searching in container {container}: {e}")

        # Nếu có container khớp đầu tiên → load luôn object của container đầu tiên
        if matched_containers:
            container_name, matched_objects = matched_containers[0]
            self.selected_container = container_name
            for obj in matched_objects:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(obj["name"]))
                self.table.setItem(row, 1, QTableWidgetItem(format_bytes(int(obj.get("bytes", 0)))))
                self.table.setItem(row, 2, QTableWidgetItem(format_datetime(obj.get("last_modified", ""))))

    def get_all_containers(self):
        return getattr(self, "containers", [])

    def create_search_box(self, placeholder_text, clear_callback=None):
        search_box = QLineEdit()
        search_box.setPlaceholderText(placeholder_text)

        clear_icon = QIcon(resource_path(os.path.join("photos", "clear.png")))
        clear_action = QAction(clear_icon, "", search_box)
        clear_action.setToolTip("Clear Search Input")
        clear_action.triggered.connect(search_box.clear)

        search_box.addAction(clear_action, QLineEdit.TrailingPosition)

        if clear_callback:
            search_box.textChanged.connect(clear_callback)

        return search_box

    def update_usage_display(self):
        percent = int(self.used_bytes / self.total_quota_bytes * 100)
        self.usage_bar.setValue(percent)

        # Cảnh báo màu khi trên 90%
        if percent >= 90:
            self.usage_bar.setStyleSheet("QProgressBar::chunk { background-color: red; }")
        else:
            self.usage_bar.setStyleSheet("")

        # Format hiển thị text
        used_str = self.format_size(self.used_bytes)
        total_str = self.format_size(self.total_quota_bytes)
        self.usage_label.setText(f"{used_str} / {total_str}")
        if hasattr(self, 'pie_chart'):
            self.pie_chart.usage_text = f"{used_str} / {total_str}"
            self.pie_chart.plot(self.get_file_type_sizes())  # Gọi lại để vẽ lại text

    def calculate_total_used_bytes(self):
        self.used_bytes = 0

        try:
            headers = {"X-Auth-Token": self.token}
            containers_url = f"{self.storage_url}"
            r = requests.get(containers_url, headers=headers, params={"format": "json"})
            r.raise_for_status()

            containers = r.json()

            for container in containers:
                name = container["name"]
                container_url = f"{self.storage_url}/{name}"
                r2 = requests.get(container_url, headers=headers, params={"format": "json"})
                r2.raise_for_status()

                objects = r2.json()
                for obj in objects:
                    self.used_bytes += int(obj.get("bytes", 0))

        except Exception as e:
            print("Error calculating usage:", e)

        self.update_usage_display()
        self.auto_free_space_if_needed()

    def auto_free_space_if_needed(self):
        if self.used_bytes <= self.total_quota_bytes:
            return  # Still under quota

        headers = {"X-Auth-Token": self.token}
        all_files = []

        for container in self.get_all_containers():
            objects = self.list_objects(container)
            for obj in objects:
                name = obj.get("name")
                size = int(obj.get("bytes", 0))
                modified = obj.get("last_modified")
                if name and modified:
                    try:
                        dt = datetime.fromisoformat(modified).replace(tzinfo=ZoneInfo("UTC"))
                        all_files.append({
                            "container": container,
                            "name": name,
                            "size": size,
                            "modified": dt
                        })
                    except:
                        pass  # Skip if timestamp is invalid

        # Sort by newest first
        all_files.sort(key=lambda x: x["modified"], reverse=True)

        files_deleted = 0

        for file in all_files:
            if self.used_bytes <= self.total_quota_bytes:
                break

            try:
                url = f"{self.storage_url}/{file['container']}/{file['name']}"
                response = requests.delete(url, headers=headers)

                if response.status_code in [204, 404]:
                    self.used_bytes -= file["size"]
                    files_deleted += 1
                else:
                    print(f"Failed to delete {file['name']} - HTTP {response.status_code}")
            except Exception as e:
                print(f"Error deleting {file['name']}: {e}")

        self.update_usage_display()

        # Show notification if any file was deleted
        if files_deleted > 0:
            QMessageBox.warning(
                self,
                "Storage Limit Reached",
                f"Storage exceeded quota. {files_deleted} most recent file(s) were deleted automatically."
            )

    def upload_file_or_folder(self):
        if not self.selected_container:
            QMessageBox.warning(self, "No folder selected", "Please select a folder before uploading")
            return

        choice, ok = QInputDialog.getItem(
            self, "Select upload type", "What would you like to upload ?", ["File", "Folder"], 0, False
        )
        if not ok:
            return

        file_tasks = []
        total_upload_size = 0

        if choice == "File":
            files, _ = QFileDialog.getOpenFileNames(self, "Select file to upload")
            if not files:
                return
            for f in files:
                object_name = os.path.basename(f)
                file_tasks.append((f, object_name))
                total_upload_size += os.path.getsize(f)

        elif choice == "Folder":
            selected_folders = []

            while True:
                folder_path = QFileDialog.getExistingDirectory(self, "Select folder to upload")
                if folder_path:
                    selected_folders.append(folder_path)

                reply = QMessageBox.question(self, "Add another folder ?", "Would you like to select another folder ?",
                                             QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    break

            for folder_path in selected_folders:
                base_folder = os.path.basename(folder_path)
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, os.path.dirname(folder_path))
                        object_name = rel_path.replace("\\", "/")
                        file_tasks.append((full_path, object_name))
                        total_upload_size += os.path.getsize(full_path)

        # 🔴 Kiểm tra quota
        available_space = self.total_quota_bytes - self.used_bytes
        if total_upload_size > available_space:
            QMessageBox.critical(self, "Insufficient Storage", "There is not enough storage to upload the selected files")
            return

        # Bắt đầu upload
        self.completed_tasks = 0
        self.total_tasks = len(file_tasks)
        if self.total_tasks == 0:
            return

        self.progress_bar.setValue(0)

        for idx, (filepath, object_name) in enumerate(file_tasks):
            worker = UploadWorker(
                token=self.token,
                storage_url=self.storage_url,
                container=self.selected_container,
                filepath=filepath,
                object_name=object_name,
                index=idx,
                total=self.total_tasks
            )
            worker.signals.progress.connect(self.progress_bar.setValue)
            worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Uploading error", msg))
            worker.signals.done.connect(self.on_work_done)
            self.threadpool.start(worker)

    def on_work_done(self):
        self.completed_tasks += 1
        percent = int((self.completed_tasks / self.total_tasks) * 100)
        self.progress_bar.setValue(percent)

        if self.completed_tasks == self.total_tasks:
            self.progress_bar.setValue(100)
            self.calculate_total_used_bytes()
            self.list_containers()
            self.update_file_type_stats()
            QTimer.singleShot(1000, lambda: self.progress_bar.setValue(0))

        #Xử lý folder

    def filter_containers(self, text):
        for row in range(self.container_table.rowCount()):
            item = self.container_table.item(row, 0)  # cột 0 là tên container
            if item:
                match = text.lower() in item.text().lower()
                self.container_table.setRowHidden(row, not match)

    def dragEnterEvent_for_container_table(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.container_table.setStyleSheet("QTableWidget { border: 3px dashed #0078d7; }")

    def handle_drop_to_container_table(self, event):
        self.container_table.setStyleSheet("")

        urls = event.mimeData().urls()
        if not urls:
            return

        file_tasks = []
        containers_to_create = set()
        system_containers = {"backup", "dicom"}  # lowercase để so sánh

        existing_containers = set(self.get_all_containers())

        for url in urls:
            local_path = url.toLocalFile()
            if not os.path.exists(local_path):
                continue

            if os.path.isfile(local_path):
                QMessageBox.critical(self, "Error", "Cannot create folder with file.\nPlease drop folders only.")
                return

            container_name = os.path.basename(local_path)

            if container_name.lower() in system_containers:
                QMessageBox.critical(self, "Error", f"Cannot create folder with system name '{container_name}'")
                return

            if container_name in existing_containers:
                QMessageBox.critical(self, "Error", f"Already have container with name '{container_name}'")
                return

            containers_to_create.add(container_name)

            for root, _, files in os.walk(local_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, local_path).replace("\\", "/")
                    object_name = rel_path
                    file_tasks.append((container_name, full_path, object_name))

        if not containers_to_create:
            return

            # ✅ Thêm kiểm tra quota
        total_size = sum(os.path.getsize(path) for _, path, _ in file_tasks)
        if self.used_bytes + total_size > self.total_quota_bytes:
            QMessageBox.critical(self, "Storage Exceeded", "Not enough storage to upload these folders.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Upload",
            f"Create {len(containers_to_create)} folder(s) and upload {len(file_tasks)} file(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        # Tạo container (kể cả rỗng)
        headers = {"X-Auth-Token": self.token}
        for container_name in containers_to_create:
            url = f"{self.storage_url}/{container_name}"
            resp = requests.put(url, headers=headers)
            if resp.status_code not in [201, 202, 204]:
                QMessageBox.warning(self, "Error", f"Failed to create container '{container_name}'")

        # Nếu có file thì upload
        if file_tasks:
            self.upload_files_to_new_containers(file_tasks)

        QTimer.singleShot(2000, self.list_containers)

    def upload_files_to_new_containers(self, file_tasks):
        headers = {"X-Auth-Token": self.token}

        grouped = {}
        for container, path, obj_name in file_tasks:
            grouped.setdefault(container, []).append((path, obj_name))

        for container_name, items in grouped.items():
            url = f"{self.storage_url}/{container_name}"
            resp = requests.put(url, headers=headers)
            if resp.status_code not in [201, 202, 204]:
                QMessageBox.warning(self, "Error", f"Failed to create container '{container_name}'")
                continue

            total = len(items)
            self.completed_tasks = 0
            self.total_tasks = total
            self.progress_bar.setValue(0)

            for idx, (filepath, object_name) in enumerate(items):
                worker = UploadWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=container_name,
                    filepath=filepath,
                    object_name=object_name,
                    index=idx,
                    total=total
                )
                worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Upload Error", msg))
                worker.signals.done.connect(self.on_work_done)
                self.threadpool.start(worker)

        QTimer.singleShot(2000, self.list_containers)

    def sort_container_table(self):
        col = self.container_sort_state["column"]
        ascending = self.container_sort_state["ascending"]

        data = []
        for row in range(self.container_table.rowCount()):
            row_data = [
                self.container_table.item(row, 0).text(),
                self.container_table.item(row, 1).text()
            ]
            data.append(row_data)

        def parse_size(size_str):
            try:
                num, unit = size_str.split()
                num = float(num)
                unit_map = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
                return num * unit_map.get(unit, 1)
            except:
                return 0

        if col == 1:
            key_func = lambda row: parse_size(row[col])
        else:
            key_func = lambda row: row[col].lower()

        data.sort(key=key_func, reverse=not ascending)

        self.container_table.setRowCount(0)
        for row_data in data:
            row = self.container_table.rowCount()
            self.container_table.insertRow(row)
            for col_idx, val in enumerate(row_data):
                self.container_table.setItem(row, col_idx, QTableWidgetItem(val))

    def list_containers(self):
        self.calculate_total_used_bytes()
        try:
            headers = {"X-Auth-Token": self.token}
            response = requests.get(self.storage_url, headers=headers)

            self.container_table.setRowCount(0)
            self.table.setRowCount(0)

            self.containers = []  # 🔥 Thêm dòng này để reset danh sách container

            if response.status_code == 200:
                containers = response.text.strip().split('\n')
                for container in containers:
                    if not container:
                        continue

                    self.containers.append(container)  # 🔥 Lưu container vào self.containers

                    try:
                        container_url = f"{self.storage_url}/{container}"
                        r2 = requests.get(container_url, headers=headers, params={"format": "json"})
                        r2.raise_for_status()
                        objects = r2.json()
                        total_size = sum(int(obj.get("bytes", 0)) for obj in objects)
                        formatted_size = format_bytes(total_size)
                    except Exception:
                        formatted_size = "?"

                    row = self.container_table.rowCount()
                    self.container_table.insertRow(row)
                    self.container_table.setItem(row, 0, QTableWidgetItem(container))
                    self.container_table.setItem(row, 1, QTableWidgetItem(formatted_size))
            else:
                QMessageBox.information(self, "Notification", "There are currently no folders")
        except Exception as e:
            self.container_table.setRowCount(0)
            self.table.setRowCount(0)
            QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

        if hasattr(self, 'pie_chart') and hasattr(self, 'line_chart'):
            self.pie_chart.plot(self.get_file_type_sizes())
            self.line_chart.plot(self.get_upload_timestamps_last_1h())

    def on_container_clicked(self, row, column):
        self.list_containers()
        container_name_item = self.container_table.item(row, 0)
        if not container_name_item:
            return
        container_name = container_name_item.text()
        self.selected_container = container_name

        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{container_name}?format=json"
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                objects = response.json()
                self.table.setRowCount(0)
                for obj in objects:
                    name = obj.get("name", "")
                    size_bytes = obj.get("bytes", 0)
                    last_modified = obj.get("last_modified", "")

                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self.table.setItem(row, 0, QTableWidgetItem(name))
                    self.table.setItem(row, 1, QTableWidgetItem(format_bytes(size_bytes)))
                    self.table.setItem(row, 2, QTableWidgetItem(format_datetime(last_modified)))
            else:
                QMessageBox.information(self, "Notification", f"Unable to load files in the folder {container_name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

    def on_container_header_clicked(self, column_index):
        current_order = self.container_sort_state.get("ascending", True)
        self.container_sort_state["column"] = column_index
        self.container_sort_state["ascending"] = not current_order
        self.sort_container_table()

    def create_container_dialog(self):
        name, ok = QInputDialog.getText(self, "Create Folder", "Enter new folder name")
        if ok and name:
            name = name.strip()

            reserved_names = ["backup", "dicom"]
            if name.lower() in reserved_names:
                QMessageBox.warning(self, "Invalid name", "This name cannot be used. It is a system folder.")
                return

            try:
                headers = {
                    "X-Auth-Token": self.token,
                    "Content-Length": "0"
                }
                url = f"{self.storage_url}/{name}"
                response = requests.put(url, headers=headers)

                if response.status_code in [201, 202]:
                    QMessageBox.information(self, "Success", f"Folder '{name}' has been created")
                    self.list_containers()
                elif response.status_code == 409:
                    QMessageBox.warning(self, "Failure", f"Folder '{name}' already exists")
                else:
                    QMessageBox.warning(self, "Failure", f"Unable to create folder\nHTTP {response.status_code}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

    def container_context_menu(self, pos):
        item = self.container_table.itemAt(pos)
        if item:
            row = item.row()  # lấy đúng dòng
            container_item = self.container_table.item(row, 0)  # cột 0 là tên container
            if not container_item:
                return
            container_name = container_item.text()

            menu = QMenu()
            delete_action = menu.addAction("❌ Delete Folder")
            download_action = menu.addAction("📥 Download Folder")
            rename_action = menu.addAction("✏️ Rename Folder")

            action = menu.exec_(self.container_table.viewport().mapToGlobal(pos))

            if action == delete_action:
                self.delete_container_with_objects(container_name)
            elif action == download_action:
                self.download_container(container_name)
            elif action == rename_action:
                self.rename_container(container_name)

    def download_container(self, container_name):
        save_dir = QFileDialog.getExistingDirectory(self, "Select path to save the folder")
        if not save_dir:
            return

        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{container_name}?format=json"
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                QMessageBox.warning(self, "Error",
                                    f"Unable to retrieve object for download\nHTTP {response.status_code}")
                return

            objects = response.json()
            self.total_tasks = len(objects)
            self.completed_tasks = 0
            self.progress_bar.setValue(0)

            for idx, obj in enumerate(objects):
                object_name = obj.get("name", "")
                save_path = os.path.join(save_dir, container_name, object_name.replace("/", os.sep))

                worker = DownloadWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=container_name,
                    object_name=object_name,
                    save_path=save_path,
                    index=idx,
                    total=self.total_tasks
                )
                worker.signals.done.connect(self.on_work_done)
                worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Downloading error", msg))
                self.threadpool.start(worker)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error downloading folder: {str(e)}")

    def delete_container_with_objects(self, container_name):
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete folder '{container_name}' and all its contents?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return  # Người dùng bấm No => thoát luôn

        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{container_name}?format=json"
            response = requests.get(url, headers=headers)

            objects = response.json() if response.status_code == 200 else []
            num_objects = len(objects)

            self.total_tasks = num_objects + 1  # +1 là container
            self.completed_tasks = 0
            self.progress_bar.setValue(0)

            # Biến nội bộ đếm số lượng object đã xóa xong
            self.object_delete_done = 0

            def delete_container():
                try:
                    url = f"{self.storage_url}/{container_name}"
                    del_response = requests.delete(url, headers=headers)
                    if del_response.status_code == 204:
                        print(f"Đã xóa container: {container_name}")
                    elif del_response.status_code == 409:
                        QMessageBox.warning(self, "Error", "Unable to delete folder: Files still exist")
                    else:
                        QMessageBox.information(self, "Notification",
                                                f"Folder '{container_name}' still exists or encountered an error")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Error deleting folder: {str(e)}")
                self.on_work_done()
                self.calculate_total_used_bytes()  # Cập nhật dung lượng

            if num_objects == 0:
                # Nếu không có object, xóa luôn container
                delete_container()
                return

            # Khi từng object được xóa xong
            def on_object_deleted():
                self.object_delete_done += 1
                self.on_work_done()
                if self.object_delete_done == num_objects:
                    delete_container()

            for idx, obj in enumerate(objects):
                object_name = obj.get("name")
                worker = DeleteWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=container_name,
                    object_name=object_name,
                    index=idx,
                    total=self.total_tasks
                )
                worker.signals.done.connect(on_object_deleted)
                worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Delete Error", msg))
                self.threadpool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting folder: {str(e)}")

        #Xử lý file

    def filter_objects(self, text):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)  # Cột 0 là tên object
            if item:
                item_text = item.text().lower()
                self.table.setRowHidden(row, text.lower() not in item_text)

    def on_file_double_clicked(self, item):
        row = item.row()
        object_name = self.table.item(row, 0).text()

        # Kiểm tra phần mở rộng
        ext = os.path.splitext(object_name)[1].lower()
        if ext in ['.txt', '.json', '.xml']:
            try:
                headers = {"X-Auth-Token": self.token}
                url = f"{self.storage_url}/{self.selected_container}/{object_name}"
                response = requests.get(url, headers=headers)

                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")

                content = response.content.decode("utf-8", errors="replace")  # hỗ trợ UTF-8 lỗi nhẹ
                self.show_text_viewer(object_name, content)

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error reading file:\n{str(e)}")

        elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']:
            self.show_image_viewer(object_name)

        else:
            QMessageBox.warning(self, "Unsupported file", "Cannot open this file")

    def show_image_viewer(self, object_name):
        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{self.selected_container}/{object_name}"
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            data = response.content
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                raise Exception("Cannot display this image")

            label = QLabel()
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)

            viewer = QMainWindow(self)
            viewer.setWindowTitle(object_name)
            viewer.setCentralWidget(label)
            viewer.resize(min(pixmap.width() + 100, 1000), min(pixmap.height() + 100, 800))
            viewer.show()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading image:\n{str(e)}")

    def show_text_viewer(self, filename, content):
        if self.viewer_window is None or not self.viewer_window.isVisible():
            self.viewer_window = FileViewerWindow(self)
            self.viewer_window.show()

        self.viewer_window.open_file(filename, content, self.save_text_file)

    def save_text_file(self, filename, updated_content):
        if not self.selected_container:
            QMessageBox.warning(self, "Error", "No folder selected")
            return

        try:
            headers = {
                "X-Auth-Token": self.token,
                "Content-Type": "text/plain"
            }
            url = f"{self.storage_url}/{self.selected_container}/{filename}"
            response = requests.put(url, headers=headers, data=updated_content.encode('utf-8'))

            if response.status_code not in [201, 202]:
                raise Exception(f"HTTP {response.status_code}")
            QMessageBox.information(self, "Success", f"File '{filename}' saved successfully.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{str(e)}")

    def list_objects(self, container_name):
        try:
            headers = {"X-Auth-Token": self.token}
            container_url = f"{self.storage_url}/{container_name}"
            response = requests.get(container_url, headers=headers, params={"format": "json"})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return []

    def handle_drop_event(self, event: QDropEvent):
        if not self.selected_container:
            QMessageBox.warning(self, "No folder selected", "Please select a folder before uploading")
            return

        urls = event.mimeData().urls()
        if not urls:
            return

        file_tasks = []
        total_upload_size = 0

        for url in urls:
            local_path = url.toLocalFile()
            if os.path.isdir(local_path):
                for root, _, files in os.walk(local_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, os.path.dirname(local_path))
                        object_name = rel_path.replace("\\", "/")
                        file_tasks.append((full_path, object_name))
                        total_upload_size += os.path.getsize(full_path)
            elif os.path.isfile(local_path):
                object_name = os.path.basename(local_path)
                file_tasks.append((local_path, object_name))
                total_upload_size += os.path.getsize(local_path)

        available_space = self.total_quota_bytes - self.used_bytes
        if total_upload_size > available_space:
            QMessageBox.critical(self, "Insufficient storage", "Not enough storage to upload")
            return

        self.completed_tasks = 0
        self.total_tasks = len(file_tasks)
        if self.total_tasks == 0:
            return

        self.progress_bar.setValue(0)

        for idx, (filepath, object_name) in enumerate(file_tasks):
            worker = UploadWorker(
                token=self.token,
                storage_url=self.storage_url,
                container=self.selected_container,
                filepath=filepath,
                object_name=object_name,
                index=idx,
                total=self.total_tasks
            )
            worker.signals.progress.connect(self.progress_bar.setValue)
            worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Uploading error", msg))
            worker.signals.done.connect(self.on_work_done)
            self.threadpool.start(worker)

    def sort_object_table(self):
        col = self.object_sort_state["column"]
        ascending = self.object_sort_state["ascending"]

        data = []
        for row in range(self.table.rowCount()):
            row_data = [self.table.item(row, c).text() for c in range(self.table.columnCount())]
            data.append(row_data)

        def parse_size(size_str):
            try:
                num, unit = size_str.split()
                num = float(num)
                unit_map = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
                return num * unit_map.get(unit, 1)
            except:
                return 0

        def parse_datetime(dt_str):
            try:
                return datetime.strptime(dt_str, "%d-%m-%Y %H:%M")
            except:
                return datetime.min

        if col == 1:
            key_func = lambda row: parse_size(row[col])
        elif col == 2:
            key_func = lambda row: parse_datetime(row[col])
        else:
            key_func = lambda row: row[col]

        data.sort(key=key_func, reverse=not ascending)

        self.table.setRowCount(0)
        for row_data in data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col_idx, val in enumerate(row_data):
                self.table.setItem(row, col_idx, QTableWidgetItem(val))

    def on_object_header_clicked(self, column_index):
        # Đảo thứ tự tăng/giảm cho cột đó
        current_order = self.object_sort_order.get(column_index, True)
        self.object_sort_order[column_index] = not current_order

        self.object_sort_state["column"] = column_index
        self.object_sort_state["ascending"] = current_order

        self.sort_object_table()

    def object_context_menu(self, pos):
        selected_rows = list(set(index.row() for index in self.table.selectionModel().selectedRows()))
        if not selected_rows:
            # Nếu chưa chọn thì fallback dùng item tại vị trí click
            item = self.table.itemAt(pos)
            if item:
                selected_rows = [item.row()]
            else:
                return

        menu = QMenu()

        if len(selected_rows) == 1:
            object_name = self.table.item(selected_rows[0], 0).text()
            download_action = menu.addAction("📥 Download file")
            delete_action = menu.addAction("❌ Delete file")
            rename_action = menu.addAction("✏️ Rename file")

            # ✅ Nếu object nằm trong "folder tree" thì mới thêm menu folder
            if "/" in object_name.strip("/"):
                menu.addSeparator()
                download_folder_action = menu.addAction("📁 Download folder")
                delete_folder_action = menu.addAction("🗑️ Delete folder")
        else:
            download_action = menu.addAction(f"📥 Download {len(selected_rows)} file")
            delete_action = menu.addAction(f"❌ Delete {len(selected_rows)} file")

        action = menu.exec_(self.table.viewport().mapToGlobal(pos))

        if action == download_action:
            self.download_selected_objects(selected_rows)
        elif action == delete_action:
            self.delete_selected_objects(selected_rows)
        elif len(selected_rows) == 1 and action == rename_action:
            self.rename_object(selected_rows[0])
        elif len(selected_rows) == 1 and "/" in self.table.item(selected_rows[0], 0).text().strip("/"):
            object_name = self.table.item(selected_rows[0], 0).text()
            if action == download_folder_action:
                self.download_object_folder(object_name)
            elif action == delete_folder_action:
                self.delete_object_folder(object_name)

    def download_object_folder(self, object_name):
        if '/' not in object_name:
            QMessageBox.information(self, "Invalid", "Selected file is not inside any folder.")
            return

        folder_prefix = object_name.rsplit('/', 1)[0] + '/'  # ví dụ: codau/test/
        folder_name = folder_prefix.rstrip('/').split('/')[-1]  # ví dụ: test

        # 🗂️ Hỏi user chọn nơi lưu folder
        save_root = QFileDialog.getExistingDirectory(self, "Select folder to save")
        if not save_root:
            return

        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{self.selected_container}?format=json"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            objects = response.json()

            to_download = [obj["name"] for obj in objects if obj["name"].startswith(folder_prefix)]

            if not to_download:
                QMessageBox.information(self, "Not Found", f"No files found in folder '{folder_name}'")
                return

            self.completed_tasks = 0
            self.total_tasks = len(to_download)
            self.progress_bar.setValue(0)

            def on_download_done():
                self.completed_tasks += 1
                percent = int((self.completed_tasks / self.total_tasks) * 100)
                self.progress_bar.setValue(percent)

                if self.completed_tasks == self.total_tasks:
                    QMessageBox.information(self, "Download Completed",
                                            f"Folder '{folder_name}' downloaded successfully.")
                    self.progress_bar.setValue(0)

            def on_download_error(msg):
                QMessageBox.warning(self, "Download Error", msg)

            for idx, obj_name in enumerate(to_download):
                relative_path = obj_name[len(folder_prefix):]  # phần còn lại sau prefix
                save_path = os.path.join(save_root, folder_name, relative_path)

                worker = DownloadWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=self.selected_container,
                    object_name=obj_name,
                    save_path=save_path,
                    index=idx,
                    total=self.total_tasks
                )
                worker.signals.done.connect(on_download_done)
                worker.signals.error.connect(on_download_error)
                self.threadpool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error downloading folder:\n{str(e)}")

    def delete_object_folder(self, object_name):
        if '/' not in object_name:
            QMessageBox.information(self, "Invalid", "Selected file is not inside any folder.")
            return

        # ✅ Lấy folder chứa file (cấp ngay trên)
        folder_prefix = object_name.rsplit('/', 1)[0] + '/'  # ví dụ: codau/test/
        folder_name = folder_prefix.rstrip('/').split('/')[-1]  # ví dụ: test

        confirm = QMessageBox.question(
            self,
            "Delete Folder",
            f"Are you sure you want to delete folder '{folder_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            headers = {"X-Auth-Token": self.token}
            url = f"{self.storage_url}/{self.selected_container}?format=json"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            objects = response.json()

            # ✅ Lọc các object có prefix đúng folder cần xoá
            to_delete = [obj["name"] for obj in objects if obj["name"].startswith(folder_prefix)]

            if not to_delete:
                QMessageBox.information(self, "Not Found", f"No files found in folder '{folder_name}'")
                return

            self.completed_tasks = 0
            self.total_tasks = len(to_delete)
            self.progress_bar.setValue(0)

            def on_delete_done():
                self.completed_tasks += 1
                percent = int((self.completed_tasks / self.total_tasks) * 100)
                self.progress_bar.setValue(percent)

                if self.completed_tasks == self.total_tasks:
                    QMessageBox.information(self, "Deleted", f"Folder '{folder_name}' deleted successfully.")
                    self.progress_bar.setValue(0)
                    self.on_container_clicked(self.container_table.currentRow(), 0)

            def on_delete_error(msg):
                QMessageBox.warning(self, "Delete Error", msg)

            for idx, obj_name in enumerate(to_delete):
                worker = DeleteWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=self.selected_container,
                    object_name=obj_name,
                    index=idx,
                    total=self.total_tasks
                )
                worker.signals.done.connect(on_delete_done)
                worker.signals.error.connect(on_delete_error)
                self.threadpool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting folder:\n{str(e)}")

    def download_selected_objects(self, rows):
        for row in rows:
            object_name = self.table.item(row, 0).text()
            self.download_single_object(object_name)

    def delete_selected_objects(self, rows):
        confirm = QMessageBox.question(
            self,
            "Confirm",
            f"Are you sure you want to delete {len(rows)} File ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.total_tasks = len(rows)
            self.completed_tasks = 0
            self.progress_bar.setValue(0)

            for row in sorted(rows, reverse=True):
                object_name = self.table.item(row, 0).text()
                self.delete_single_object(object_name, confirm=False, is_batch=True)

    def download_single_object(self, object_name):
        if not self.selected_container:
            QMessageBox.warning(self, "Error", "No container selected")
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "Save File As", object_name)
        if not save_path:
            return

        self.total_tasks = 1
        self.completed_tasks = 0
        self.progress_bar.setValue(0)

        worker = DownloadWorker(
            token=self.token,
            storage_url=self.storage_url,
            container=self.selected_container,
            object_name=object_name,
            save_path=save_path,
            index=0,
            total=1
        )
        worker.signals.done.connect(self.on_work_done)
        worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Downloading error", msg))
        self.threadpool.start(worker)

    def delete_single_object(self, object_name, confirm=True, is_batch=False):
        if not self.selected_container:
            QMessageBox.warning(self, "Error", "No folder selected")
            return

        if confirm:
            user_confirm = QMessageBox.question(
                self,
                "Delete file",
                f"Are you sure you want to delete the file '{object_name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            if user_confirm != QMessageBox.Yes:
                return

        if not is_batch:
            self.total_tasks = 1
            self.completed_tasks = 0
            self.progress_bar.setValue(0)

        worker = DeleteWorker(
            token=self.token,
            storage_url=self.storage_url,
            container=self.selected_container,
            object_name=object_name,
            index=0,
            total=1
        )
        worker.signals.done.connect(self.on_work_done)
        worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Delete error", msg))
        self.threadpool.start(worker)

    def rename_container(self, old_container_name):
        new_name, ok = QInputDialog.getText(self, "Rename folder", "Enter new folder name:")
        if not ok or not new_name or new_name.strip() == old_container_name:
            return

        new_name = new_name.strip()

        try:
            # Tạo container mới
            create_url = f"{self.storage_url}/{quote(new_name)}"
            headers = {"X-Auth-Token": self.token}
            create_resp = requests.put(create_url, headers=headers)
            if create_resp.status_code not in (201, 202):
                raise Exception("Unable to create new folder")

            # Lấy danh sách object từ container cũ
            list_url = f"{self.storage_url}/{quote(old_container_name)}?format=json"
            list_resp = requests.get(list_url, headers=headers)
            if list_resp.status_code != 200:
                raise Exception("Unable to retrieve file list from the old folder")
            objects = list_resp.json()

            # Copy từng object
            for obj in objects:
                object_name = obj["name"]
                copy_url = f"{self.storage_url}/{quote(new_name)}/{quote(object_name)}"
                headers_copy = {
                    "X-Auth-Token": self.token,
                    "X-Copy-From": f"/{quote(old_container_name)}/{quote(object_name)}"
                }
                copy_resp = requests.put(copy_url, headers=headers_copy)
                if copy_resp.status_code not in (201, 202):
                    raise Exception(f"Unable to copy object: {object_name}")

            # Xóa container cũ (gồm cả object)
            self.delete_container_with_objects(old_container_name)

            QMessageBox.information(self, "Success", "Folder renamed successfully")
            self.list_containers()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def rename_object(self, row):
        old_object_name = self.table.item(row, 0).text()
        base_name, ext = os.path.splitext(old_object_name)  # 👈 Tách tên và phần mở rộng

        new_name, ok = QInputDialog.getText(self, "Rename Object", "Enter new object name (without extension):")
        if not ok or not new_name:
            return

        new_name = new_name.strip()

        # Nếu người dùng không nhập đuôi, thì tự nối đuôi cũ vào
        if not os.path.splitext(new_name)[1]:
            new_name += ext

        if new_name == old_object_name:
            return

        try:
            container = self.selected_container
            if not container:
                raise Exception("No folder selected")

            headers = {
                "X-Auth-Token": self.token,
                "X-Copy-From": f"/{quote(container)}/{quote(old_object_name)}"
            }

            # Copy object với tên mới
            copy_url = f"{self.storage_url}/{quote(container)}/{quote(new_name)}"
            copy_resp = requests.put(copy_url, headers=headers)
            if copy_resp.status_code not in (201, 202):
                raise Exception("Failed to copy file")

            # Xoá object cũ
            delete_url = f"{self.storage_url}/{quote(container)}/{quote(old_object_name)}"
            delete_resp = requests.delete(delete_url, headers={"X-Auth-Token": self.token})
            if delete_resp.status_code not in (204, 404):
                raise Exception("Failed to delete old file")

            QMessageBox.information(self, "Success", "File renamed successfully")
            self.on_container_clicked(QListWidgetItem(self.selected_container))

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

#Tab Backup
    # Hàm thực hiện backup chính
    def do_backup(self, is_now=True):
        username = self.get_current_username()
        json_path = os.path.join(self.backup_dir, f"{username}_backup.json")

        if not os.path.exists(json_path):
            QMessageBox.warning(self, "Missing information", "No backup configuration found")
            return

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            folders = config.get("folders", [])
            if not folders:
                QMessageBox.warning(self, "No folder selected", "You haven't chosen a folder to back up")
                return

            # === 1. Tạo container "Backup" nếu chưa có
            headers = {"X-Auth-Token": self.token}
            backup_container = "Backup"
            container_url = f"{self.storage_url}/{backup_container}"
            response = requests.put(container_url, headers=headers)
            if response.status_code not in [201, 202, 204]:  # 204 nếu đã tồn tại
                raise Exception(f"Unable to create Backup container: HTTP {response.status_code}")

            # === 2. Định dạng tên folder
            now = datetime.now()
            folder_name = f"NOW.{now.strftime('%d.%m.%Y.%H.%M.%S')}" if is_now else now.strftime('%d.%m.%Y.%H.%M.%S')

            file_tasks = []
            for folder_path in folders:
                base_name = os.path.basename(folder_path)
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, folder_path).replace("\\", "/")
                        object_name = f"{folder_name}/{base_name}/{rel_path}"
                        file_tasks.append((full_path, object_name))

            if not file_tasks:
                QMessageBox.information(self, "No data available", "The selected folders do not contain any files")
                return

            # === 3. Thực hiện upload (dùng lại UploadWorker)
            self.completed_tasks = 0
            self.total_tasks = len(file_tasks)
            self.progress_bar.setValue(0)

            for idx, (filepath, object_name) in enumerate(file_tasks):
                worker = UploadWorker(
                    token=self.token,
                    storage_url=self.storage_url,
                    container=backup_container,
                    filepath=filepath,
                    object_name=object_name,
                    index=idx,
                    total=self.total_tasks
                )
                worker.signals.progress.connect(self.progress_bar.setValue)
                worker.signals.done.connect(self.on_backup_task_done)
                worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Backup Error", msg))
                self.threadpool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Backup error: {str(e)}")
    # Thanh progress sau khi backup xong
    def on_backup_task_done(self):
        self.completed_tasks += 1
        percent = int((self.completed_tasks / self.total_tasks) * 100)
        self.progress_bar.setValue(percent)

        if self.completed_tasks == self.total_tasks:
            QMessageBox.information(self, "Backup successful", "Backup completed successfully.")
            self.progress_bar.setValue(100)
            QTimer.singleShot(1500, lambda: self.progress_bar.setValue(0))
    # Chọn thư mục backup
    def choose_backup_folders(self):
        folders = []

        while True:
            folder = QFileDialog.getExistingDirectory(self, "Select folders to back up",options=QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
            if folder:
                folders.append(folder)

            reply = QMessageBox.question(
                self,
                "Add another folder",
                "Would you like to select another folder to back up?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                break

        if folders:
            username = self.get_current_username()
            json_path = os.path.join(self.backup_dir, f"{username}_backup.json")
            config = {}

            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}

            config["folders"] = folders  # Giữ lại các field khác

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

            self.update_backup_status_label()
            QMessageBox.information(self, "Notification", f"{len(folders)} folders selected for backup.")
        else:
            QMessageBox.information(self, "Notification", "No folders have been selected")
    # Xóa setting backup hiện tại
    def clear_backup_setting(self):
        reply = QMessageBox.question(self, "Confirmation", "Are you sure you want to delete all backup settings ?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            username = self.get_current_username()
            json_path = os.path.join(self.backup_dir, f"{username}_backup.json")
            try:
                if os.path.exists(json_path):
                    os.remove(json_path)
                    self.backup_timer.stop()
                    self.next_backup_time = None
                    self.update_backup_status_label()
                    QMessageBox.information(self, "Deleted", "Backup settings have been deleted")
                else:
                    QMessageBox.information(self, "Notification", "There are no settings to delete")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Unable to delete file: {str(e)}")
    # Thực hiện backup ngay
    def backup_now(self):
        msg = "Would you like to back up now?"
        if self.next_backup_time:
            msg = f"You have a scheduled backup at {self.next_backup_time.strftime('%H:%M %d/%m/%Y')}.\nWould you like to back up now?"

        confirm = QMessageBox.question(self, "Confirm Backup", msg, QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.do_backup(is_now=True)
    # Thực hiện backup đúng lịch hẹn đã lên trước đó.
    def perform_scheduled_backup(self):
        QMessageBox.information(self, "Backup", "Performing automatic backup")
        self.do_backup(is_now=False)

        # Nếu mode là "once" → xoá file
        username = self.get_current_username()
        json_path = os.path.join(self.backup_dir, f"{username}_backup.json")
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if config.get("mode") == "once":
            os.remove(json_path)
            self.update_backup_status_label()
        else:
            self.schedule_backup_from_config()
    # Đọc file cấu hình .json và tính toán thời gian kế tiếp cần backup, rồi hẹn giờ bằng QTimer.
    def schedule_backup_from_config(self):
        self.backup_timer.stop()
        self.next_backup_time = None

        username = self.get_current_username()
        config_path = os.path.join(self.backup_dir, f"{username}_backup.json")
        if not os.path.exists(config_path):
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            mode = config.get("mode")
            hour_str = config.get("hour")
            hour, minute = map(int, hour_str.split(":"))
            now = datetime.now()
            next_time = None

            if mode == "once":
                date_str = config.get("date")
                backup_dt = datetime.combine(datetime.strptime(date_str, "%d-%m-%Y").date(), dt_time(hour, minute))
                if now >= backup_dt:
                    # Quá hạn => xoá
                    os.remove(config_path)
                    self.update_backup_status_label()
                    return
                else:
                    next_time = backup_dt

            elif mode == "daily":
                next_time = datetime.combine(now.date(), dt_time(hour, minute))
                if next_time <= now + timedelta(seconds=1):
                    next_time += timedelta(days=1)

            elif mode == "weekly":
                weekday = config.get("weekday", 0)  # 0 = Monday
                days_ahead = (weekday - now.weekday()) % 7
                next_time = datetime.combine((now + timedelta(days=days_ahead)).date(), dt_time(hour, minute))
                if next_time <= now:
                    next_time += timedelta(weeks=1)

            if next_time:
                delay_ms = int((next_time - now).total_seconds() * 1000)
                self.next_backup_time = next_time
                try:
                    self.backup_timer.timeout.disconnect()
                except TypeError:
                    pass
                self.backup_timer.timeout.connect(self.perform_scheduled_backup)
                self.backup_timer.start(delay_ms)
                print(f"[⏱️] Backup scheduled for: {next_time}")

        except Exception as e:
            print("Error in scheduling backup:", e)
    # Cài đặt setting backup
    def show_backup_time_dialog(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTimeEdit, QDateEdit, QRadioButton, QDialogButtonBox, QLabel, \
            QComboBox
        from PyQt5.QtCore import QTime, QDate

        dialog = QDialog(self)
        dialog.setWindowTitle("Set backup schedule")
        layout = QVBoxLayout(dialog)

        label_time = QLabel("Select backup time:")
        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setTime(QTime.currentTime())

        layout.addWidget(label_time)
        layout.addWidget(time_edit)

        daily_radio = QRadioButton("Daily")
        weekly_radio = QRadioButton("Weekly")
        once_radio = QRadioButton("Specific date")
        daily_radio.setChecked(True)

        layout.addWidget(daily_radio)
        layout.addWidget(weekly_radio)
        layout.addWidget(once_radio)

        weekday_combo = QComboBox()
        weekday_combo.addItems(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        layout.addWidget(QLabel("Select starting day for weekly"))
        layout.addWidget(weekday_combo)

        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDate(QDate.currentDate())
        layout.addWidget(QLabel("Select day for specific day"))
        layout.addWidget(date_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btn_box)

        def on_accept():
            mode = "daily" if daily_radio.isChecked() else "weekly" if weekly_radio.isChecked() else "once"
            time_str = time_edit.time().toString("HH:mm")

            # Đọc dữ liệu cũ nếu có
            username = self.get_current_username()
            json_path = os.path.join(self.backup_dir, f"{username}_backup.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    old_config = json.load(f)
            else:
                old_config = {}

            # Gộp dữ liệu cũ với dữ liệu mới
            old_config["mode"] = mode
            old_config["hour"] = time_str

            if mode == "weekly":
                old_config["weekday"] = weekday_combo.currentIndex()
                old_config.pop("date", None)
            elif mode == "once":
                old_config["date"] = date_edit.date().toString("dd-MM-yyyy")
                old_config.pop("weekday", None)
            else:
                old_config.pop("weekday", None)
                old_config.pop("date", None)

            # Ghi lại toàn bộ config (kèm theo folders cũ nếu có)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(old_config, f, indent=2)

            self.update_backup_status_label()
            self.schedule_backup_from_config()
            dialog.accept()

        btn_box.accepted.connect(on_accept)
        btn_box.rejected.connect(dialog.reject)
        dialog.exec_()
    # Countdown thời gian backup
    def update_backup_status_label(self):
        username = self.get_current_username()
        json_path = os.path.join(self.backup_dir, f"{username}_backup.json")

        if not os.path.exists(json_path):
            self.backup_info_label.setText("No backup settings found")
            return

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            mode = config.get("mode")
            hour = config.get("hour", "")
            message_lines = []

            # Thời gian
            if mode == "daily":
                message_lines.append(f"🕒 Backup daily at {hour}")
            elif mode == "weekly":
                weekday = config.get("weekday", 0)
                weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                message_lines.append(f"🕒 Backup weekly on {weekdays[weekday]} at {hour}")
            elif mode == "once":
                date = config.get("date", "?")
                message_lines.append(f"🕒 Backup once at {hour} on {date}")
            else:
                message_lines.append("⚠️ Invalid backup settings")

            # Danh sách thư mục
            folders = config.get("folders", [])
            if folders:
                message_lines.append("📂 Selected folders:")
                for folder in folders:
                    message_lines.append(f"  - {folder}")
            else:
                message_lines.append("❌ No backup folder selected")

            # Countdown (nếu có)
            if self.next_backup_time:
                delta = self.next_backup_time - datetime.now()
                if delta.total_seconds() > 0:
                    days = delta.days
                    hours, remainder = divmod(delta.seconds, 3600)
                    minutes = remainder // 60
                    countdown_str = f"{days} days {hours} hours {minutes} minutes" if days > 0 else f"{hours} hours {minutes} minutes"
                    message_lines.append(f"⏳ Time remaining: {countdown_str}")
                else:
                    message_lines.append("⚠️ Backup schedule has expired")

            self.backup_info_label.setText("\n".join(message_lines))

        except Exception as e:
            self.backup_info_label.setText("Error reading backup settings")

#Tab DICOM Bridge
    # Thay đổi đường dẫn của web orthanc khi cần thiết
    def get_dicom_url(self):
        try:
            with open("dicomurl.json", "r") as f:
                return json.load(f).get("url", "http://localhost:8042")
        except Exception:
            return "http://localhost:8042"

    def set_dicom_url(self, new_url):
        try:
            with open("dicomurl.json", "w") as f:
                json.dump({"url": new_url}, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot save DICOM URL:\n{str(e)}")

    # Hiển thị thông tin metadata của file
    def show_study_context_menu(self, pos):
        index = self.study_list.indexAt(pos)
        if not index.isValid():
            return

        menu = QMenu(self.study_list)
        metadata_action = QAction("📋 View Metadata", self.study_list)
        metadata_action.triggered.connect(self.show_study_metadata)
        menu.addAction(metadata_action)
        menu.exec_(self.study_list.viewport().mapToGlobal(pos))

    def show_study_metadata(self):
        row = self.study_list.currentRow()
        if row < 0:
            return

        study_id = self.study_list.item(row, 4).text()
        dicom_url = self.get_dicom_url()

        try:
            response = requests.get(f"{dicom_url}/studies/{study_id}")
            response.raise_for_status()
            data = response.json()

            dialog = QDialog(self)
            dialog.setWindowTitle("Study Metadata Details")
            dialog.setMinimumSize(600, 700)
            layout = QVBoxLayout(dialog)

            def add_group(title, tag_dict):
                group = QGroupBox(title)
                form_layout = QFormLayout()
                for key, value in tag_dict.items():
                    form_layout.addRow(f"{key}:", QLabel(str(value)))
                group.setLayout(form_layout)
                layout.addWidget(group)

            # Patient Info
            patient_info = data.get("PatientMainDicomTags", {})
            if patient_info:
                add_group("👤 Patient Information", patient_info)

            # Study Info
            study_info = data.get("MainDicomTags", {})
            if study_info:
                add_group("📄 Study Information", study_info)

            # Series list
            series = data.get("Series", [])
            if series:
                series_box = QGroupBox("📦 Series")
                series_layout = QVBoxLayout()

                def fetch_series_info(series_id):
                    try:
                        resp = requests.get(f"{dicom_url}/series/{series_id}")
                        resp.raise_for_status()
                        instance_count = len(resp.json().get("Instances", []))
                        return (series_id, instance_count)
                    except:
                        return (series_id, "?")

                with ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(fetch_series_info, series))

                for idx, (series_id, instance_count) in enumerate(results):
                    label = QLabel(f"{idx + 1}. Series ID: {series_id} (Instance count: {instance_count})")
                    series_layout.addWidget(label)

                series_box.setLayout(series_layout)
                layout.addWidget(series_box)

            button_box = QDialogButtonBox(QDialogButtonBox.Ok)
            button_box.accepted.connect(dialog.accept)
            layout.addWidget(button_box)

            dialog.exec_()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load metadata:\n{str(e)}")

    # Hiển thị những file đang có bên web về app
    def load_studies_from_orthanc(self):
        self.study_list.setRowCount(0)
        self.study_ids = []
        self.loaded_offset = 0

        try:
            r = requests.get(f"{self.get_dicom_url()}/studies")
            r.raise_for_status()
            self.study_ids = sorted(r.json(), reverse=True)  # hoặc sort theo nhu cầu
            self.load_more_studies()  # Tải 10 study đầu tiên

        except Exception as e:
            QMessageBox.critical(
                self,
                "Orthanc Error",
                "Orthanc DICOMweb service is currently unavailable.\n"
                "Please check your server connection or change the URL in the Help menu."
            )

    def populate_study_list(self, study_data):
        self.study_list.setRowCount(0)
        for patient_id, patient_name, study_desc, study_date, study_id in study_data:
            row = self.study_list.rowCount()
            self.study_list.insertRow(row)
            self.study_list.setItem(row, 0, QTableWidgetItem(patient_id))
            self.study_list.setItem(row, 1, QTableWidgetItem(patient_name))
            self.study_list.setItem(row, 2, QTableWidgetItem(study_desc))
            self.study_list.setItem(row, 3, QTableWidgetItem(study_date))
            self.study_list.setItem(row, 4, QTableWidgetItem(study_id))  # 👈 Cột ẩn
    # Upload file đang chọn lên app cloud
    def upload_selected_study_to_swift(self):
        self.dicom_progress_bar.setVisible(True)
        self.dicom_progress_bar.setValue(0)
        QApplication.processEvents()

        dicom_url = self.get_dicom_url()
        row = self.study_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a study to upload.")
            return

        study_id = self.study_list.item(row, 4).text()

        try:
            study_info = requests.get(f"{dicom_url}/studies/{study_id}")
            study_info.raise_for_status()
            study_info = study_info.json()

            patient_name = study_info.get("PatientMainDicomTags", {}).get("PatientName", "Unknown")
            study_date = study_info.get("MainDicomTags", {}).get("StudyDate", "Unknown")

            # Làm sạch tên thư mục
            safe_patient_name = re.sub(r'[^a-zA-Z0-9_-]', '_', patient_name)
            safe_study_date = re.sub(r'[^0-9]', '', study_date)[:8]  # yyyyMMdd
            folder_name = f"{safe_patient_name}.{safe_study_date}"

            # Lấy danh sách instance
            series_ids = study_info.get("Series", [])
            instance_ids = []
            for series_id in series_ids:
                series_info = requests.get(f"{dicom_url}/series/{series_id}").json()
                instance_ids += series_info.get("Instances", [])

            if not instance_ids:
                QMessageBox.warning(self, "Empty Study", "No DICOM instances found in the selected study.")
                return

            # Tạo thư mục tạm & worker tải DICOM
            temp_dir = os.path.join(os.getcwd(), "temp_dicom")
            worker = DownloadDicomWorker(dicom_url, instance_ids, temp_dir)

            def on_download_done(filepaths):
                self.start_upload_dicom(filepaths, folder_name, temp_dir)

            worker.signals.progress.connect(self.dicom_progress_bar.setValue)
            worker.signals.error.connect(lambda msg: QMessageBox.critical(self, "Download Error", msg))
            worker.signals.finished.connect(on_download_done)

            self.threadpool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Upload failed:\n{str(e)}")

    def start_upload_dicom(self, filepaths, folder_name, temp_dir):
        container = "DICOM"
        container_url = f"{self.storage_url}/{container}"
        headers = {"X-Auth-Token": self.token}
        create_resp = requests.put(container_url, headers=headers)
        if not create_resp.ok:
            QMessageBox.critical(self, "Error", f"Failed to create/access container '{container}'")
            return

        self.completed_tasks = 0
        self.total_tasks = len(filepaths)

        def on_upload_step_done():
            self.completed_tasks += 1
            percent = int(50 + (self.completed_tasks / self.total_tasks) * 50)
            self.dicom_progress_bar.setValue(percent)
            if self.completed_tasks == self.total_tasks:
                self.dicom_progress_bar.setValue(100)
                QTimer.singleShot(2000, lambda: self.dicom_progress_bar.setVisible(False))

        def on_all_done():
            try:
                for f in os.listdir(temp_dir):
                    fp = os.path.join(temp_dir, f)
                    if os.path.isfile(fp):
                        os.remove(fp)
            except Exception as cleanup_err:
                print("Cleanup error:", cleanup_err)

        for idx, filepath in enumerate(filepaths):
            object_name = f"{folder_name}/{os.path.basename(filepath)}"
            worker = UploadWorker(
                token=self.token,
                storage_url=self.storage_url,
                container=container,
                filepath=filepath,
                object_name=object_name,
                index=idx,
                total=self.total_tasks
            )
            worker.signals.error.connect(lambda msg: QMessageBox.warning(self, "Upload Error", msg))
            worker.signals.done.connect(on_upload_step_done)
            if idx == len(filepaths) - 1:
                worker.signals.done.connect(on_all_done)
            self.threadpool.start(worker)

    def load_more_studies(self):
        if self.loaded_offset >= len(self.study_ids):
            QMessageBox.information(self, "Done", "No more studies to load")
            return

        worker = StudyListWorker(
            dicom_url=self.get_dicom_url(),
            study_ids=self.study_ids,
            offset=self.loaded_offset,
            limit=10
        )
        worker.signals.finished.connect(self.append_studies_to_table)
        worker.signals.error.connect(lambda msg: QMessageBox.critical(self, "Error", msg))
        self.threadpool.start(worker)
        self.loaded_offset += 10

    def append_studies_to_table(self, study_data_list):
        for data in study_data_list:
            row = self.study_list.rowCount()
            self.study_list.insertRow(row)
            for col, value in enumerate(data):
                self.study_list.setItem(row, col, QTableWidgetItem(str(value)))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
