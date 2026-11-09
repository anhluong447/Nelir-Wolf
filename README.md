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

### 4. Khóa Logic Tự Động (không còn dịch "gãy" game)
* Chỉ các loại hiển thị cho người chơi mới được dịch: `Message`, `Choice`, `SetString`, `Picture`, `DBName`, `DBField`, `GameTitle`.
* Các lệnh logic của engine (`Database`, `StringCondition`, `JumpLabel`, `SetLabel`, `CommonEvent`, `CommonEventByName`, `Comment`, `DebugMessage`) luôn bị khóa 🔒.
* Một chuỗi `SetString` / `DBName` / `DBField` mà lệnh khác dùng để tra cứu / so sánh (ví dụ tên nhân vật được so sánh để chọn ảnh chân dung) cũng bị khóa và luôn được vá bằng bản gốc, tránh lỗi `the data name does not exist` hoặc rẽ nhánh sai.
* `CDataBase` (bộ nhớ runtime của engine) không bao giờ được bóc tách hay vá.

### 5. Kiểm Tra Chất Lượng (QA) & Trạng Thái Rõ Ràng
* Trạng thái: `○` chưa dịch · `~` AI dịch (chưa duyệt) · `✓` đã duyệt · `⚠` AI dịch lỗi QA · `🔒` bị khóa.
* QA tự động: bản dịch giống câu gốc, còn sót chữ Nhật/Hán, sai số dòng, thiếu mã điều khiển (`\c[]`, `\s[]`, `\E`, `<C>`, `@1`...), dòng quá dài (cảnh báo).
* AI lỗi / hết quota thì dòng giữ nguyên, **không bao giờ** lưu câu tiếng Nhật thành "đã dịch".

### 6. Bộ Nhớ Dịch & Bảng Thuật Ngữ
* Câu gốc trùng nhau chỉ gửi lên AI một lần, rồi điền cho mọi chỗ trùng (tiết kiệm quota, dịch thống nhất).
* Câu đã từng dịch được tái sử dụng ngay (ưu tiên bản đã duyệt).
* Glossary theo dự án (`🛠️ Công cụ → 📖 Bảng thuật ngữ`) được gửi kèm prompt khi câu có chứa thuật ngữ.
* `♻️ Đồng bộ bản dịch của các câu trùng nhau` gom các bản dịch lệch nhau của cùng một câu gốc.

### 7. Vá Bản Dịch An Toàn (Patch to Game)
* Mỗi dự án giữ một bản dump gốc tiếng Nhật (`dump_original/`); mỗi lần Patch, dump làm việc được dựng lại từ bản gốc + bản dịch, rồi chạy `WolfTL --patch --inplace`.
* Trước khi ghi, mỗi dòng được đối chiếu `path` ↔ câu gốc; dòng lệch (game đã cập nhật) bị bỏ qua và báo lại.
* Patch bị **chặn** nếu bản dịch tạo ra lỗi logic mới (tra cứu Database / nhãn nhảy) so với game gốc.
* Lần Patch đầu tiên tự sao lưu `Data/BasicData` + `Data/MapData` vào `projects/<id>/game_backup/`.
* `↩️ Khôi phục văn bản gốc` ghi lại toàn bộ tiếng Nhật vào game bất cứ lúc nào; dữ liệu dịch không mất.
* Trích xuất lại (khi game cập nhật) gộp theo `(file, path, câu gốc)`, giữ nguyên bản dịch của các câu không đổi.

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

### Kiểm tra & test:
```bash
python -m unittest discover -s tests -v      # test tự động (không cần mạng / WolfTL)
python validator.py --project <project_id>   # kiểm tra logic một dự án
```
Biến môi trường `NELIR_DATA_DIR` cho phép chạy với một thư mục dữ liệu khác (chứa `projects/` và `global_settings.db`).

---

## 📁 Cấu Trúc Thư Mục

```
Nelir-Wolf/
├── bin/
│   └── WolfTL.exe                  # Công cụ bóc tách & vá game WOLF RPG
├── projects/                       # Thư mục chứa các dự án game
│   └── <Tên_Game>/
│       ├── project.json            # Thông tin game, đường dẫn cài đặt
│       ├── translation.db          # Bản dịch, glossary, meta (SQLite)
│       ├── dump_original/          # Dump gốc tiếng Nhật (không bao giờ bị sửa)
│       ├── dump/                   # Dump làm việc, dựng lại mỗi lần Patch
│       └── game_backup/            # Sao lưu BasicData/MapData trước lần Patch đầu
├── static/                         # Giao diện người dùng (HTML, CSS, JS)
├── tests/                          # Test tự động (unittest)
├── config.py                       # Đường dẫn, giá trị mặc định, quy tắc loại chuỗi
├── db.py                           # Kết nối SQLite & schema
├── extractor.py                    # Bóc tách dump, đồng bộ DB, khóa logic, gọi WolfTL
├── qa.py                           # Kiểm tra chất lượng bản dịch
├── pipeline.py                     # Luồng dịch: bộ nhớ dịch → AI → QA → DB
├── validator.py                    # Kiểm tra logic (nhãn / tra cứu DB / khóa)
├── bridge.py                       # Dự án đang mở: chuẩn bị, Patch, khôi phục
├── project_manager.py              # Quản lý đa dự án & xuất/nạp gói .nel
├── openrouter.py                   # Client AI (OpenAI-compatible), xoay key & model
└── server.py                       # FastAPI Backend Server
```

---

## 📜 Giấy Phép & Bản Quyền
Dự án được phát triển phục vụ cộng đồng dịch thuật game RPG độc lập.
