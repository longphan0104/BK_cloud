import os
import re

from utils import resource_path

HELP_TEXT = """

<div style="text-align: center;">
<h1>Hướng dẫn sử dụng app BK Cloud</h1>
</div>

<h2>1. Đăng nhập vào app</h2>

<div style="text-align: center;">
    <img src="file:photos/manual1.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Người dùng cần nhập đầy đủ Username, Password và Project name để đăng nhập vào app, nếu không sẽ báo lỗi.</li>
    <li>-Trong phần Help bao gồm 2 phần: Dùng để thay đổi đường dẫn đến server Object storage Openstack Swift tùy vào setup của người dùng.</li>
    <li>+ Change Swift Auth URL:Dùng để thay đổi đường dẫn đến server Object storage Openstack Swift tùy vào setup của người dùng.</li>
    <li>+ User manual: hướng dẫn người dùng sử dụng app.</li>

</ul>

<h2>2. Giao diện chính của app</h2>

<div style="text-align: center;">
    <img src="file:photos/manual2.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-App gồm hai phần chính:</li>
    <li>+ Phần bên trái chứa: Tên app, các nút Help, Logout, phần chuyển đổi User, 4 tab chức năng chính.</li>
    <li>+ Phần bên phải dùng để thể hiện nội dung của từng tab chức năng khi người dùng bấm vào.</li>
</ul>
<h2>3. Tab Dashboard</h2>
<div style="text-align: center;">
    <img src="file:photos/manual2.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Tab Dashboard bao gồm:</li>
    <li>+ Thống kế các loại file hiện có trên app dựa vào phần mở rộng của file. </li>
    <li>+ Sơ đồ Piechart để thống kê phần trăm dung lượng các file đang có, sơ đồ Linechart cho biết số files được upload trong vòng 1h qua.</li>
</ul>

<h2>4. Tab My File</h2>

<div style="text-align: center;">
    <img src="file:photos/manual3.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>Tab My File bao gồm:</li>
    <li>-3 nút chức năng chính:</li>
    <li>+ Refresh: Làm mới, cập nhật danh sách folder và file trong bảng.</li>
    <li>+ New Folder: Tạo folder mới.</li>
    <li>+ Upload File/Folder: Upload file hoặc folder con vào trong folder mẹ đã tạo trước đó.</li>

    <li>-Ngoài 3 nút chức năng chính kể trên còn có các chức năng phụ sau:</li>
    
<div style="text-align: center;">
    <img src="file:photos/manual4.png" width="1000" />
</div>    
    <li>+ Người dùng có thể Download, Delete, Rename folder đã tạo, chức năng này cũng áp dụng với file.</li>
    <li>+ Người dùng có thể tìm kiếm bằng thanh search bar trong vùng folder hoặc file, hoặc có thể tìm kiếm toàn bộ bằng thanh search all trên cùng.</li>
    <li>+ Bên cạnh thanh search all là thanh usage bar, nó cho biết dung lượng khả dụng của cloud hiện tại.</li>
    <li>+ Người dùng có thể bấm vào phần Header trong bảng Folder hoặc file để sort từng thuộc tính theo dạng Ascending hoặc Descending.</li>
    <li>+ Người dùng có thể kéo thả file vào bảng File để upload file hoặc kéo thả folder vào bảng Folder để tạo folder chứa file trong đó.</li>
    <li>+ Người dùng có thể bấm đúp vào file ảnh (.jpg, .png,...) để xem file.</li>
    <li>+ Người dùng có thể mở để đọc hoặc edit file .txt và bấm save để lưu.</li>
</ul>

<h2>5. Tab Backup</h2>
<div style="text-align: center;">
    <img src="file:photos/manual5.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Tab Backup bao gồm 4 phần chính:</li>
    <li>+ Set backup time: Thực hiện chọn thời gian backup bao gồm: thời gian backup, ngày backup. Người dùng có thể chọn mỗi ngày (daily), mỗi tuần (weekly) hoặc ngày cụ thể (specific day). </li>
    <li>+ Select backup folder: Thực hiện chọn những phần mà người dùng muốn backup trên máy. </li>
    <li>+ Backup now: Thực hiện backup ngay lập tức với backup setting đã chọn </li>
    <li>+ Clear backup setting: Xóa backup setting hiện tại trong current setup status.</li>
    <li>Khi đã chọn xong backup setting thì hệ thống sẽ hiện thời gian còn lại đến thời gian backup ở phần current setup status.</li>

</ul>
<h2>6. Tab DICOM Bridge</h2>
<div style="text-align: center;">
    <img src="file:photos/manual6.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Tab DICOM Bridge bao gồm:</li>
    <li>+ Refresh study list: Làm mới danh sách study hiện tại.</li>
    <li>+ Load more: Thực hiện tải thêm study, mặc định của hệ thống là 10 study để tránh quá tải.</li>
    <li>+ Upload Selected study: Upload study đã chọn vào cloud.</li>

</ul>

<h2>7. Help (Trợ giúp)</h2>
<div style="text-align: center;">
    <img src="file:photos/manual8.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Dialog Help bao gồm:</li>
    <li>+ User manual: Phần hướng dẫn người dùng. </li>
    <li>+ Change DICOMweb URL: Thay đổi đường dẫn đển trang Dicomweb Orthanc tùy vào setup của người dùng </li>
    <li>+ Change User password: Dùng để thay đổi password của User hiện tại (Lưu ý: không thể đổi trùng mật khẩu với mật khẩu cũ gần nhất.)</li>
    <li>+ Change cloud storage limit: Dùng để thay đổi limit của cloud, mặc định là 1GB </li>

</ul>

<h2>8. Window file explorer</h2>
<div style="text-align: center;">
    <img src="file:photos/manual7.png" width="1000" />
</div>

<ul style="list-style-type: none; padding-left: 20px; line-height: 1.5;">
    <li>-Khi người dùng đăng nhập vào app thành công thì trên hệ thống sẽ xuất hiện một ổ đĩa Z: có dạng:</li>
    <li>BK Cloud - "User"</li>
    <li>-Trong đó "User" là User hiện tại của người dùng, khi người dùng thực hiện chuyển đổi User thì app cũng sẽ tự động chuyển user trên ổ đĩa Z:</li>
</ul>
"""
def get_help_text():
    def replace_img_src(match):
        filename = match.group(1)
        abs_path = resource_path(os.path.join("photos", filename))
        return f'src="file:///{abs_path}"'

    return re.sub(r'src=["\']file:photos/([^"\']+)["\']', replace_img_src, HELP_TEXT)