import cv2
import numpy as np
import snap7

# ==================== 1. CẤU HÌNH KẾT NỐI PLC SIEMENS S7-1200 ====================
PLC_IP = "192.168.0.1"  
RACK = 0
SLOT = 1

plc = snap7.client.Client()
plc_connected = False

try:
    plc.connect(PLC_IP, RACK, SLOT)
    plc_connected = plc.get_connected()
    print(f" [OK] Đã kết nối thành công với PLC S7-1200 tại IP: {PLC_IP}")
except Exception as e:
    print(f" [WARNING] Không thể kết nối PLC: {e}. Hệ thống chạy mô phỏng camera.")

# ==================== 2. CẤU HÌNH CAMERA ĐỒ ÁN ====================
CAMERA_INDEX = 0  
cap = cv2.VideoCapture(CAMERA_INDEX)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    print(f" [ERROR] Không thể mở camera ở index {CAMERA_INDEX}!")
    exit()

def send_signal_to_plc(color_id):
    """
    Gửi mã màu (Color_ID) và bật cờ Trigger_Read = TRUE xuống DB1 của PLC.
    Mã màu: 1 (Đỏ), 2 (Cam), 3 (Vàng), 4 (Xanh lá), 5 (Hàng Lỗi)
    """
    if not plc_connected:
        return
    try:
        data = bytearray(3)
        data[0] = (color_id >> 8) & 0xFF
        data[1] = color_id & 0xFF
        data[2] = 0x01 
        
        plc.write_area(0x84, 1, 0, data)
    except Exception as e:
        print(f" [ERROR] Lỗi truyền dữ liệu xuống PLC: {e}")

print(" [INFO] Hệ thống phân loại đang chạy. Nhấn phím 'q' để thoát.")

# ==================== 3. BIẾN TRẠNG THÁI (STATE MACHINE) ====================
is_object_in_roi = False  

# ==================== 4. VÒNG LẶP XỬ LÝ CHÍNH ====================
try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print(" [WARNING] Không nhận được khung hình từ camera.")
            break

        height, width, _ = frame.shape

        # --- ĐỊNH NGHĨA VÙNG QUÉT (ROI) ---
        roi_x1, roi_y1 = int(width * 0.3), int(height * 0.2)
        roi_x2, roi_y2 = int(width * 0.7), int(height * 0.8)
        
        cv2.rectangle(frame, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 255), 2)
        cv2.putText(frame, "VUNG QUET ROI", (roi_x1, roi_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        
        # --- LỌC 4 MÀU CHUẨN (HỆ HSV) ---
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        
        lower_red = np.array([0, 120, 120])
        upper_red = np.array([10, 255, 255])
        mask_red = cv2.inRange(hsv, lower_red, upper_red)

        lower_orange = np.array([11, 120, 120])
        upper_orange = np.array([21, 255, 255])
        mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)

        lower_yellow = np.array([22, 120, 120])
        upper_yellow = np.array([32, 255, 255])
        mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)

        lower_green = np.array([35, 80, 80])
        upper_green = np.array([85, 255, 255])
        mask_green = cv2.inRange(hsv, lower_green, upper_green)

        # --- LỌC HÀNG LỖI BẰNG ẢNH XÁM ---
        # Băng tải tối màu, phôi sáng màu. Bất cứ vật gì sáng màu đi qua đều bị tóm gọn
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, mask_any = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY) 

        # --- TÍNH DIỆN TÍCH ---
        area_red = cv2.countNonZero(mask_red)
        area_orange = cv2.countNonZero(mask_orange)
        area_yellow = cv2.countNonZero(mask_yellow)
        area_green = cv2.countNonZero(mask_green)
        area_any = cv2.countNonZero(mask_any)

        min_threshold = 4000  
        max_valid_area = max(area_red, area_orange, area_yellow, area_green)
        
        detected_color = "Khong co san pham"
        color_id = 0

        # --- THUẬT TOÁN MÁY TRẠNG THÁI & RA QUYẾT ĐỊNH ---
        if max_valid_area > min_threshold:
            # ---> TÌM THẤY 1 TRONG 4 MÀU CHUẨN
            if max_valid_area == area_red:
                detected_color, color_id = "Mau Do (Loai 1)", 1
            elif max_valid_area == area_orange:
                detected_color, color_id = "Mau Cam (Loai 2)", 2
            elif max_valid_area == area_yellow:
                detected_color, color_id = "Mau Vang (Loai 3)", 3
            elif max_valid_area == area_green:
                detected_color, color_id = "Mau Xanh La (Loai 4)", 4
            
            if not is_object_in_roi:
                send_signal_to_plc(color_id)
                print(f" [SEND] Phân loại: {detected_color} - Gửi PLC thành công.")
                is_object_in_roi = True 

        elif area_any > min_threshold:
            # ---> CÓ VẬT THỂ NHƯNG KHÔNG ĐẠT MÀU CHUẨN -> HÀNG LỖI
            detected_color, color_id = "San pham LOI", 5
            
            if not is_object_in_roi:
                send_signal_to_plc(color_id)
                print(f" [SEND] Phát hiện {detected_color} - Gửi PLC thành công.")
                is_object_in_roi = True 

        else:
            # ---> BĂNG TẢI TRỐNG
            if is_object_in_roi:
                is_object_in_roi = False 
                print(" [INFO] Vùng quét trống, sẵn sàng nhận phôi tiếp theo.")

        # --- HIỂN THỊ TRỰC QUAN GIAO DIỆN ---
        # Đổi màu text thành Đỏ nếu là hàng lỗi, Xanh lá nếu hàng chuẩn
        text_color = (0, 0, 255) if color_id == 5 else (0, 255, 0)
        cv2.putText(frame, f"Trang thai: {detected_color}", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2)
        
        cv2.imshow("He thong phan loai san pham", frame)
        
        # Gộp chung mặt nạ hàng chuẩn để dễ quan sát (Tùy chọn hiển thị)
        mask_valid_all = cv2.bitwise_or(mask_red, cv2.bitwise_or(mask_orange, cv2.bitwise_or(mask_yellow, mask_green)))
        cv2.imshow("Anh Mat Na (Chuan)", mask_valid_all)
        cv2.imshow("Anh Mat Na (Quet Loi)", mask_any)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    if plc_connected:
        plc.disconnect()
        print(" [INFO] Đã ngắt kết nối an toàn với PLC.")