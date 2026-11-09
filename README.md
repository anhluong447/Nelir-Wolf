# 🐺 Nelir WOLF RPG Translator

Nền tảng hỗ trợ dịch thuật và bản địa hóa game phát triển trên engine **WOLF RPG Editor** sang tiếng Việt, tích hợp AI đa luồng (Google Gemini, OpenRouter, Kaggle / Local LLM), cơ chế xoay API Key tự động khi đạt giới hạn hạn mức (Rate Limit / Quota), kiến trúc Đa Dự Án (Multi-Project) độc lập và định dạng đóng gói dự án chuyên dụng **`.nel`**.

---

## 🚀 Tính Năng Nổi Bật

### 1. Kiến Trúc Đa Dự Án (Multi-Project)
* Quản lý cùng lúc nhiều game WOLF RPG trên cùng một giao diện.
* Mỗi game sở hữu một không gian độc lập: cơ sở dữ liệu dịch thuật SQLite riêng (`translation.db`), thư mục dump kịch bản riêng, và cấu hình đường dẫn cài đặt game riêng.
* Cấu hình AI (API Keys, danh sách model, prompt hệ thống, theme) được lưu tập trung trong `global_settings.db`, dùng chung cho toàn bộ các game mà không cần nhập lại.

### 2. Định Dạng Gói Dự Án `.nel` (Nelir Project Package)
* Đóng gói toàn bộ tiến độ dịch thuật (hàng chục nghìn câu thoại, trạng thái dịch, metadata) thành một tệp `.nel` nén nhỏ gọn (~1–2 MB).
* **Xuất (`💾 Lưu .nel`)**: Tải về tệp sao lưu chỉ với 1 cú click.
* **Nạp (`📂 Nạp .nel`)**: Dễ dàng chia sẻ dự án cho người khác hoặc khôi phục tiến độ dịch trên máy mới.

### 3. Hệ Thống Dịch AI Thông Minh & Xoay Tua Hạn Mức (Key & Model Rotation)
* **Google Gemini (AI Studio Free Tier)**: Hỗ trợ cấu hình danh sách nhiều API Key. Tự động xoay sang Key tiếp theo khi Key hiện tại đạt giới hạn quota ngày (429 / ResourceExhausted).
* **Xoay tua Model đa cấp độ**: Thiết lập danh sách nguyện vọng model ưu tiên (NV1 ➔ NV2 ➔ NV3). Khi model NV1 dính giới hạn RPM/TPM, hệ thống tạm thời chuyển sang NV2/NV3 cho batch đó và lập tức ưu tiên lại NV1 ngay khi quota hồi phục.
* **Hỗ trợ Kaggle / Local LLM & OpenRouter**: Dễ dàng kết nối với các model mã nguồn mở chạy local (Qwen 2.5 32B, Llama 3) hoặc hàng trăm model trên OpenRouter.

### 4. Công Cụ Lọc & Xóa Rủi Ro Chuyên Sâu (Safe / Risky Filtering)
* Phân loại tự động các loại chuỗi dịch thuật an toàn (`Message`, `Choice`, `DBName`, `DBField`, `SetString`, `Picture`) và các nhãn nhạy cảm của engine (`Database`, `JumpLabel`, `SetLabel`, `CommonEvent`).
* Bảo vệ tuyệt đối các file bộ nhớ runtime của engine (như `CDataBase.dat`) để không bị AI dịch nhầm gây lỗi `the data name does not exist`.

### 5. Vá Bản Dịch Vào Game 1 Chạm (Patch to Game)
* Tích hợp công cụ `WolfTL` biên dịch trực tiếp các chuỗi đã dịch vào game (`WolfTL --patch --inplace`).
* Tự động khôi phục các dòng chưa dịch hoặc đã xóa về nguyên bản tiếng Nhật gốc của game.

---

## 🛠️ Cài Đặt & Khởi Chạy

### Yêu Cầu Hệ Thống:
* Python 3.10 trở lên.
* Windows OS.

### Cài đặt thư viện:
```bash
pip install fastapi uvicorn requests python-multipart
```

### Khởi chạy ứng dụng:
Chạy file `run.bat` hoặc lệnh:
```bash
python server.py
```
Sau đó truy cập giao diện web tại: **`http://127.0.0.1:8765`**

---

## 📁 Cấu Trúc Thư Mục

```
Nelir-Wolf/
├── bin/
│   └── WolfTL.exe                  # Công cụ bóc tách & vá game WOLF RPG
├── projects/                       # Thư mục chứa các dự án game
│   └── <Tên_Game>/
│       ├── project.json            # Thông tin game, đường dẫn cài đặt
│       ├── translation.db          # Database dịch thuật SQLite riêng biệt
│       └── dump/                   # File JSON bóc tách kịch bản
├── static/                         # Giao diện người dùng (HTML, CSS, JS)
├── bridge.py                       # Cầu nối điều khiển WolfTL & xử lý kịch bản
├── project_manager.py              # Quản lý đa dự án & xuất/nạp gói .nel
├── openrouter.py                   # Bộ dịch AI đa luồng, xoay key & fallback model
└── server.py                       # FastAPI Backend Server
```

---

## 📜 Giấy Phép & Bản Quyền
Dự án được phát triển phục vụ cộng đồng dịch thuật game RPG độc lập.
