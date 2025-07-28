# BK Cloud
---- Hướng dẫn cài đặt app BK Cloud ----

Bước 1 : Cài đặt Sever Swift bằng Devstack hoặc Openstack để có địa chỉ URL đến Openstack Horizon Dashboard.

Bước 2 : Cài đặt 2 phần mềm phụ trong mục Supporting software.

Bước 3 : Thiết lập System environment theo như hướng dẫn trong hình.

Mở phần tìm kiếm tìm "Edit the system environment variables".
![instruc1.png](src/photos/instruc1.png)
Theo như hướng dẫn từ 1 đến 4 trỏ đến thư mục đã cài 2 phần mềm ở bước hai như sau: Disk:\WinFsp\bin, Disk:\rclone\rclone-v1.70.2-windows-amd64
![instruc2.png](src/photos/instruc2.png)

Bước 4: Khởi động app trong phần "src" bằng cách chạy file login.py. Người dùng cần phải thay đổi URL trong phần "Help" tại trang Login tùy theo cài đặt của người dùng ở bước 1.

* Trong phần Help của trang Login, người dùng có thể xem "User manual" để hiểu rõ hơn về app.

* Người dùng có thể build app thành 1 file duy nhất bằng cách:

pyinstaller --onefile --noconsole --add-data "photos;photos" --name BKcloud --icon=photos/applogo.ico login.py

# BK Cloud Architecture

```mermaid
flowchart TD
    subgraph Start
        LWin[LoginWindow - login.py]
    end

    LWin -->|Nhập user/pass/project| Auth[OpenStack Swift Auth API]
    Auth -->|Thành công| SaveUser[secure_json.py<br/>Luu user vao saved_users.json]
    Auth -->|Thất bại| ErrorMsg[Hien thi thong bao loi]

    SaveUser --> MainWin[MainWindow - main.py]

    subgraph MainWin [MainWindow giao dien chinh]
        Sidebar[Sidebar: Help, Logout, Switch User]
        Tabs[TabWidget: Dashboard - MyFile - Backup - DICOM]
        Charts[Dashboard: PieChart + LineChart]
        MyFile[MyFile: Upload / Download / Delete / Drag-Drop]
        Backup[Backup: Dat lich backup, backup ngay]
        DICOM[DICOM Bridge: Lay study tu Orthanc, upload len Swift]
    end

    MainWin --> Sidebar
    Sidebar --> HelpDlg[Help Dialog]
    HelpDlg -->|User manual| ManualWin[Manual Window - manual.py]
    HelpDlg -->|Change Swift URL| ChangeURL[Nhap URL Swift moi]
    HelpDlg -->|Change password| ChangePW[Doi mat khau User hien tai]

    MainWin --> Charts
    MainWin --> MyFile
    MyFile -->|Upload/Download/Delete| SwiftObj[Object Storage API]

    MainWin --> Backup
    Backup -->|Chay backup theo lich| LocalFS[File System]
    Backup --> SwiftObj

    MainWin --> DICOM
    DICOM -->|Fetch Studies| Orthanc[DICOM Orthanc Server]
    DICOM -->|Upload study| SwiftObj

    subgraph Mount [Mount Manager - mount_manager.py]
        MountDrive[mount_drive: goi rclone]
        UnmountDrive[unmount_drive: dung rclone]
    end

    SaveUser --> MountDrive
    Sidebar -->|Logout| UnmountDrive
```