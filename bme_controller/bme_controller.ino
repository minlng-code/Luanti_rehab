// ============================================================
//  BME REHABILITATION CONTROLLER — Firmware v6.1
//  Board: Arduino Mega 2560 Pro (ATmega2560)
//
//  PHẦN CỨNG TAY TRÁI (Gross Motor):
//    Joystick X/Y  → WASD (analog, A0/A1)
//    B1 (D2)       → tap<300ms=Space(nhảy) | hold>=300ms=Shift(sneak)
//    B2 (D3)       → tap<500ms=Hotbar | hold>=500ms=Inventory(UI mode)
//    FSR406 (A2)   → Static Grip — Fatigue monitor ONLY (không gửi game)
//
//  PHẦN CỨNG TAY PHẢI (Fine Motor):
//    MPU6050       → xoay Camera (Pitch/Roll)
//    FSR402 (A3)   → TAY PHẢI, thay thế nút grip digital hoàn toàn
//                    tap<300ms = Click RMB (đặt block / tấn công)
//                    hold>=300ms = giữ LMB (đào / khai thác)
//                    vẫn ghi lực bóp kg song song
//
//  FLIGHT STICK (Digital Joystick + Nút):
//    FS_UP    (D4)  → khớp chân 35 (D4) trên Schematic
//    FS_DOWN  (D6)  → khớp chân 34 (D6) trên Schematic
//    FS_RIGHT (D8)  → khớp chân 33 (D8) trên Schematic
//    FS_LEFT  (D9)  → câu dây từ H8 pin5 → D9  [v6.2: D11 lỗi pullup]
//    TRIGGER  (D7)  → câu dây từ H8 pin7 → D7  [v6.2: D13 lỗi 0V]
//    THUMB    (D10) → khớp chân 32 (D10) trên Schematic
//    SERVO    (D5)  → dời từ D7 [v6.2: D7 nhường cho TRIGGER]
//    VIBRATION(D44) → dời từ D5 [v6.2: D5 nhường cho SERVO]
//
//  PACKET FORMAT → Python (18 trường, 50Hz):
//    D,JX,JY,B1_DUR,B2_DUR,FSR_R_GRIP,PITCH,ROLL,
//    FSR_L_KG,FSR_R_KG,VIB,SERVO,
//    FS_UP,FS_DOWN,FS_LEFT,FS_RIGHT,FS_TRIGGER,FS_THUMB
//
//    B1_DUR     : 0=không bấm, N=giữ Nms, 65535=vừa nhả (sentinel)
//    B2_DUR     : tương tự B1_DUR
//    FSR_R_GRIP : 0/1 — FSR402 vượt ngưỡng lực
//    FSR_L_KG   : float — lực bóp tay trái (FSR406, Fatigue)
//    FSR_R_KG   : float — lực bóp tay phải (FSR402, action)
//    FS_*       : 0/1 — trạng thái flight stick (debounced)
//
//  LỆNH SERIAL:
//    CALIB_ZERO / CALIB_SPAN,L,R / CALIB_SAVE / CALIB_LOAD
//    CALIB_RESET / CALIB_STATUS / FILTER_STATUS
//    VIB,<pwm>  / SERVO,<angle> / BETA,<val>
// ============================================================

#include <Wire.h>
#include <EEPROM.h>
#include <Servo.h>
#include <math.h>

// ════════════════════════════════════════════════════════════
//  PIN MAP
// ════════════════════════════════════════════════════════════

// ── ANALOG: Joystick & FSR ───────────────────────────────────
#define PIN_JOY_X       A0
#define PIN_JOY_Y       A1
#define PIN_FSR_LEFT    A2   // FSR406 — tay trái, Static Grip / Fatigue
#define PIN_FSR_RIGHT   A3   // FSR402 — tay phải, action (tap/hold)

// ── DIGITAL: Nút bấm tay trái ────────────────────────────────
#define PIN_BTN1        22   // B1 tay trái: tap=Jump, hold=Sneak  [v6.2: D2→D22, tránh Timer3]
#define PIN_BTN2        24   // B2 tay trái: tap=Hotbar, hold=Inventory [v6.2: D3→D24, tránh Timer3]

// ── DIGITAL: FLIGHT STICK ────────────────────────────────────
// Tất cả dùng INPUT_PULLUP — LOW khi bấm
// v6.2 remap: FS_LEFT D11→D9 (câu dây H8 pin5→D9)
//             FS_TRIGGER D13→D7 (câu dây H8 pin7→D7)
#define FS_UP_PIN        4   // Chân 35 (D4)  — giữ nguyên
#define FS_DOWN_PIN      6   // Chân 34 (D6)  — giữ nguyên
#define FS_RIGHT_PIN     8   // Chân 33 (D8)  — giữ nguyên
#define FS_LEFT_PIN      9   // D11→D9: câu dây H8 pin5 → D9
#define FS_TRIGGER_PIN   7   // D13→D7: câu dây H8 pin7 → D7
#define FS_THUMB_PIN    10   // Chân 32 (D10) — giữ nguyên

// ── PWM: Ngoại vi phản hồi ───────────────────────────────────
// v6.2 remap: SERVO D7→D5 (nhường D7 cho FS_TRIGGER)
//             VIB D5→D44 (nhường D5 cho SERVO, D44 PWM trên Mega)
#define PIN_VIBRATION   44   // PWM motor rung — dời sang D44
#define PIN_SERVO        5   // PWM Servo — dời sang D5

// MPU6050 — Hardware I2C: SDA=20, SCL=21

#define MPU_ADDR         0x68
#define MPU_PWR_REG      0x6B
#define MPU_ACCEL_REG    0x3B
#define MPU_GYRO_CFG     0x1B
#define MPU_ACCEL_CFG    0x1C
#define MPU_DLPF_CFG     0x1A

// ════════════════════════════════════════════════════════════
//  EEPROM LAYOUT (giữ nguyên từ v3.0)
// ════════════════════════════════════════════════════════════
#define EEPROM_MAGIC           0xBE
#define EEPROM_ADDR_MAGIC         0
#define EEPROM_ADDR_JOY_X_ZERO    2
#define EEPROM_ADDR_JOY_X_MIN     4
#define EEPROM_ADDR_JOY_X_MAX     6
#define EEPROM_ADDR_JOY_Y_ZERO    8
#define EEPROM_ADDR_JOY_Y_MIN    10
#define EEPROM_ADDR_JOY_Y_MAX    12
#define EEPROM_ADDR_FSR_L_ZERO   14
#define EEPROM_ADDR_FSR_L_SPAN   16
#define EEPROM_ADDR_FSR_L_FSPAN  18
#define EEPROM_ADDR_FSR_R_ZERO   22
#define EEPROM_ADDR_FSR_R_SPAN   24
#define EEPROM_ADDR_FSR_R_FSPAN  26
#define EEPROM_ADDR_MPU_AX_OFF   30
#define EEPROM_ADDR_MPU_AY_OFF   34
#define EEPROM_ADDR_MPU_AZ_OFF   38
#define EEPROM_ADDR_MPU_GX_OFF   42
#define EEPROM_ADDR_MPU_GY_OFF   46
#define EEPROM_ADDR_MPU_GZ_OFF   50

// ════════════════════════════════════════════════════════════
//  CALIBRATION STRUCT
// ════════════════════════════════════════════════════════════
struct CalibData {
    int   joy_x_zero, joy_x_min, joy_x_max;
    int   joy_y_zero, joy_y_min, joy_y_max;
    int   fsr_l_zero, fsr_l_span_adc; float fsr_l_span_n;
    int   fsr_r_zero, fsr_r_span_adc; float fsr_r_span_n;
    float mpu_ax_off, mpu_ay_off, mpu_az_off;
    float mpu_gx_off, mpu_gy_off, mpu_gz_off;
};

CalibData calib = {
    512, 0, 1023,
    512, 0, 1023,
    0, 800, 10.0f,
    0, 800, 10.0f,
    0.0f, 0.0f, 0.0f,
    0.0f, 0.0f, 0.0f
};

// ════════════════════════════════════════════════════════════
//  RUNTIME TUNING PARAMETERS
// ════════════════════════════════════════════════════════════

// ── Madgwick AHRS ──────────────────────────────────────────
// Beta lớn → hội tụ nhanh nhưng nhạy nhiễu gia tốc
// Beta nhỏ → mượt hơn nhưng hội tụ chậm
// Dải khuyến nghị: 0.01 (rất mượt) – 0.1 (phản hồi nhanh)
float MADGWICK_BETA = 0.033f;

// ── Pre-filter IMU (EMA trên raw accel/gyro trước Madgwick) ─
// Alpha nhỏ → lọc mạnh hơn, trễ nhiều hơn
// 0.3 = lọc vừa phải cho ứng dụng phục hồi chức năng 50Hz
const float IMU_EMA_ALPHA    = 0.3f;

// ── Gyro drift compensation ────────────────────────────────
// Khi tổng |gyro| < threshold này → coi là đứng yên → zero drift
const float GYRO_STILL_THRESHOLD = 0.5f;  // °/s
const float GYRO_DRIFT_GAIN      = 0.001f; // tốc độ hiệu chỉnh drift

// ── Joystick ───────────────────────────────────────────────
// EMA alpha: 0.4 = cân bằng giữa mượt và lag
const float JOY_EMA_ALPHA        = 0.4f;
const int   JOY_DEADZONE_PCT     = 8;

// ── FSR (Force Sensitive Resistor) ────────────────────────
// IIR low-pass alpha: nhỏ = lọc mạnh, chậm đáp ứng
const float FSR_IIR_ALPHA        = 0.25f;
// Hysteresis: bao nhiêu % phải GIẢM để grip tắt sau khi bật
const int   FSR_GRIP_ON_PCT      = 20;   // ngưỡng bật
const int   FSR_GRIP_OFF_PCT     = 12;   // ngưỡng tắt (hysteresis)

// ── Nút bấm debounce ──────────────────────────────────────
const unsigned long DEBOUNCE_MS  = 20;   // ms

// ── Servo ──────────────────────────────────────────────────
const int SERVO_NEUTRAL          = 90;
const int SERVO_MIN_ANGLE        = 10;
const int SERVO_MAX_ANGLE        = 170;
const int SERVO_MAX_RATE         = 3;    // °/loop tối đa (rate limiter)
const int SERVO_DEADBAND         = 2;    // °, không di chuyển nếu sai số < này

// ── Vibration ─────────────────────────────────────────────
const int VIB_GRIP_PWM           = 180;
const int VIB_QUEST_PWM          = 140;

// ── Packet rate ───────────────────────────────────────────
const int SEND_INTERVAL_MS       = 20;   // 50 Hz

// ════════════════════════════════════════════════════════════
//  HỆ SỐ HIỆU CHUẨN VẬT LÝ (TỪ ĐỒ THỊ EXCEL)
// ════════════════════════════════════════════════════════════
const float MPU_A_SLOPE     = 1.0664; // Hệ số góc nội suy MPU
const float MPU_B_INTERCEPT = 0.202;  // Sai số điểm 0 của MPU

// TAY TRÁI (LEFT) ĐANG DÙNG FSR 406
const float FSR_L_A_SLOPE     = 0.0023;  // Hệ số góc FSR 406
const float FSR_L_B_INTERCEPT = -0.0062; // Sai số điểm 0 FSR 406

// TAY PHẢI (RIGHT) ĐANG DÙNG FSR 402
const float FSR_R_A_SLOPE     = 0.0037;  // Hệ số góc FSR 402
const float FSR_R_B_INTERCEPT = 0.0045;  // Sai số điểm 0 FSR 402

const float R_PULLUP        = 10000.0; // Điện trở chốt 10k Ohm
const float GRAVITY_CONST   = 9.81;    // Gia tốc trọng trường (m/s2)

// ════════════════════════════════════════════════════════════
//  BỘ LỌC: MEDIAN-3 (inline, không dùng sort)
//  Loại bỏ spike đơn lẻ — phù hợp cho ADC 10-bit
// ════════════════════════════════════════════════════════════
// Giữ ring buffer 3 mẫu, trả về median
template<typename T>
struct Median3 {
    T buf[3] = {0, 0, 0};
    uint8_t idx = 0;
    T update(T val) {
        buf[idx] = val;
        idx = (idx + 1) % 3;
        T a = buf[0], b = buf[1], c = buf[2];
        // Branchless median of 3
        if (a > b) { T t=a; a=b; b=t; }
        if (b > c) { T t=b; b=c; c=t; }
        if (a > b) { T t=a; a=b; b=t; }
        return b;   // phần tử giữa
    }
};

// ════════════════════════════════════════════════════════════
//  BỘ LỌC: MEDIAN-5
//  Mạnh hơn Median-3, dùng cho FSR (nhiều noise vật lý hơn)
// ════════════════════════════════════════════════════════════
struct Median5 {
    int buf[5] = {0,0,0,0,0};
    uint8_t idx = 0;
    int update(int val) {
        buf[idx] = val;
        idx = (idx + 1) % 5;
        // Sort copy để tìm median
        int s[5];
        memcpy(s, buf, sizeof(s));
        // Insertion sort (5 phần tử — rất nhẹ trên MCU)
        for (int i = 1; i < 5; i++) {
            int key = s[i]; int j = i - 1;
            while (j >= 0 && s[j] > key) { s[j+1] = s[j]; j--; }
            s[j+1] = key;
        }
        return s[2];  // median
    }
};

// ════════════════════════════════════════════════════════════
//  BỘ LỌC: EMA (Exponential Moving Average)
//  y[n] = alpha * x[n] + (1-alpha) * y[n-1]
//  Float version — dùng cho Joystick, IMU pre-filter
// ════════════════════════════════════════════════════════════
struct EMAf {
    float val  = 0.0f;
    bool  init = false;
    float alpha;
    EMAf(float a = 0.3f) : alpha(a) {}
    float update(float x) {
        if (!init) { val = x; init = true; return val; }
        val = alpha * x + (1.0f - alpha) * val;
        return val;
    }
};

// ════════════════════════════════════════════════════════════
//  BỘ LỌC: IIR LOW-PASS cho FSR
//  Tương đương RC low-pass: fc = alpha * fs / (2*pi*(1-alpha))
//  Với alpha=0.25, fs=50Hz → fc ≈ 2.65 Hz (loại nhiễu cơ học)
// ════════════════════════════════════════════════════════════
struct IIRLowPass {
    float val  = 0.0f;
    bool  init = false;
    float alpha;
    IIRLowPass(float a = 0.25f) : alpha(a) {}
    float update(float x) {
        if (!init) { val = x; init = true; return val; }
        val = alpha * x + (1.0f - alpha) * val;
        return val;
    }
};

// ════════════════════════════════════════════════════════════
//  BỘ LỌC: SOFTWARE DEBOUNCE cho nút bấm
// ════════════════════════════════════════════════════════════
struct Debounce {
    bool state       = false;
    bool lastRaw     = false;
    unsigned long t  = 0;
    // Trả về trạng thái đã debounce
    bool update(bool raw, unsigned long now) {
        if (raw != lastRaw) { t = now; lastRaw = raw; }
        if ((now - t) >= DEBOUNCE_MS) state = lastRaw;
        return state;
    }
};

// ════════════════════════════════════════════════════════════
//  MADGWICK AHRS
//  Nguồn gốc: Sebastian Madgwick (2010), tối ưu cho MCU
//  Quaternion q = [q0, q1, q2, q3] đại diện orientation
//  Output: pitch, roll (Euler angles)
//
//  Ưu điểm so với Complementary filter:
//    - Không bị gimbal lock ở góc cực
//    - Hội tụ nhanh hơn sau reset
//    - Xử lý đúng khi pitch gần ±90°
//    - Có thể thêm từ trường (magnetometer) sau này
// ════════════════════════════════════════════════════════════
struct MadgwickAHRS {
    float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;

    // ax,ay,az: đơn vị g (đã chuẩn hóa nội bộ)
    // gx,gy,gz: °/s → chuyển sang rad/s bên trong
    // dt: giây
    void update(float ax, float ay, float az,
                float gx, float gy, float gz,
                float dt, float beta) {

        // Chuyển gyro sang rad/s
        gx *= 0.017453f; gy *= 0.017453f; gz *= 0.017453f;

        float norm;
        float s0, s1, s2, s3;
        float qDot0, qDot1, qDot2, qDot3;
        float _2q0, _2q1, _2q2, _2q3;
        float _4q0, _4q1, _4q2;
        float _8q1, _8q2;
        float q0q0, q1q1, q2q2, q3q3;

        // Tốc độ thay đổi quaternion từ gyro
        qDot0 = 0.5f * (-q1*gx - q2*gy - q3*gz);
        qDot1 = 0.5f * ( q0*gx + q2*gz - q3*gy);
        qDot2 = 0.5f * ( q0*gy - q1*gz + q3*gx);
        qDot3 = 0.5f * ( q0*gz + q1*gy - q2*gx);

        // Hiệu chỉnh bằng accelerometer (nếu có tín hiệu hợp lệ)
        float aMag = sqrtf(ax*ax + ay*ay + az*az);
        if (aMag > 0.1f) {
            // Chuẩn hóa gia tốc
            ax /= aMag; ay /= aMag; az /= aMag;

            _2q0 = 2.0f*q0; _2q1 = 2.0f*q1;
            _2q2 = 2.0f*q2; _2q3 = 2.0f*q3;
            _4q0 = 4.0f*q0; _4q1 = 4.0f*q1; _4q2 = 4.0f*q2;
            _8q1 = 8.0f*q1; _8q2 = 8.0f*q2;
            q0q0 = q0*q0; q1q1 = q1*q1; q2q2 = q2*q2; q3q3 = q3*q3;

            // Hàm mục tiêu gradient descent
            s0 = _4q0*q2q2 + _2q2*ax + _4q0*q1q1 - _2q1*ay;
            s1 = _4q1*q3q3 - _2q3*ax + 4.0f*q0q0*q1 - _2q0*ay
                 - _4q1 + _8q1*q1q1 + _8q1*q2q2 + _4q1*az;
            s2 = 4.0f*q0q0*q2 + _2q0*ax + _4q2*q3q3 - _2q3*ay
                 - _4q2 + _8q2*q1q1 + _8q2*q2q2 + _4q2*az;
            s3 = 4.0f*q1q1*q3 - _2q1*ax + 4.0f*q2q2*q3 - _2q2*ay;

            // Chuẩn hóa gradient
            norm = sqrtf(s0*s0 + s1*s1 + s2*s2 + s3*s3);
            if (norm > 1e-10f) {
                norm = 1.0f / norm;
                s0 *= norm; s1 *= norm; s2 *= norm; s3 *= norm;

                // Áp gradient
                qDot0 -= beta * s0;
                qDot1 -= beta * s1;
                qDot2 -= beta * s2;
                qDot3 -= beta * s3;
            }
        }

        // Tích phân quaternion
        q0 += qDot0 * dt;
        q1 += qDot1 * dt;
        q2 += qDot2 * dt;
        q3 += qDot3 * dt;

        // Chuẩn hóa quaternion
        norm = sqrtf(q0*q0 + q1*q1 + q2*q2 + q3*q3);
        if (norm < 1e-10f) { q0=1; q1=q2=q3=0; return; }
        norm = 1.0f / norm;
        q0 *= norm; q1 *= norm; q2 *= norm; q3 *= norm;
    }

    // Trả về Pitch (°) — xoay quanh trục Y (gập/duỗi cổ tay)
    float get_pitch() {
        return atan2f(2.0f*(q0*q1 + q2*q3),
                      1.0f - 2.0f*(q1*q1 + q2*q2)) * 57.2958f;
    }

    // Trả về Roll (°) — xoay quanh trục X (nghiêng cổ tay)
    float get_roll() {
        float sinp = 2.0f*(q0*q2 - q3*q1);
        sinp = constrain(sinp, -1.0f, 1.0f);
        return asinf(sinp) * 57.2958f;
    }

    void reset() { q0=1.0f; q1=q2=q3=0.0f; }
};

// ════════════════════════════════════════════════════════════
//  INSTANCES BỘ LỌC
// ════════════════════════════════════════════════════════════

MadgwickAHRS madgwick;

// IMU pre-filter (EMA trên raw signal trước khi vào Madgwick)
EMAf ema_ax(IMU_EMA_ALPHA), ema_ay(IMU_EMA_ALPHA), ema_az(IMU_EMA_ALPHA);
EMAf ema_gx(IMU_EMA_ALPHA), ema_gy(IMU_EMA_ALPHA), ema_gz(IMU_EMA_ALPHA);

// Joystick: Median-3 spike reject → EMA smooth
Median3<int> med_jx, med_jy;
EMAf         ema_jx(JOY_EMA_ALPHA), ema_jy(JOY_EMA_ALPHA);

// FSR: Median-5 spike reject → IIR low-pass
Median5      med_fsr_l, med_fsr_r;
IIRLowPass   iir_fsr_l(FSR_IIR_ALPHA), iir_fsr_r(FSR_IIR_ALPHA);

// Nút: debounce
Debounce     deb_btn1, deb_btn2, deb_grip;

// Flight stick: debounce cho 6 đầu vào digital
Debounce     deb_fs_up, deb_fs_down, deb_fs_left, deb_fs_right;
Debounce     deb_fs_trigger, deb_fs_thumb;

// Gyro drift accumulator
float gyroDriftX = 0.0f, gyroDriftY = 0.0f, gyroDriftZ = 0.0f;

// ════════════════════════════════════════════════════════════
//  SERVO & VIBRATION STATE
// ════════════════════════════════════════════════════════════
Servo         servoMotor;
int           servoTarget = SERVO_NEUTRAL;
int           servoActual = SERVO_NEUTRAL;
unsigned long lastVibEnd  = 0;

// FSR grip hysteresis state
bool          gripState_L = false;
bool          gripState_R = false;

// Prev states cho edge detection
bool prevBtn1 = false, prevBtn2 = false, prevGrip = false;

// ── B1 hold-duration tracking ────────────────────────────────
// tap < 300ms → Python gửi Space(nhảy)
// hold >= 300ms → Python giữ Shift(sneak)
unsigned long btn1PressTime   = 0;
bool          btn1WasPressed  = false;
bool          btn1SendSentinel = false;

// ── B2 hold-duration tracking ────────────────────────────────
// tap < 500ms → Python cuộn Hotbar
// hold >= 500ms → Python mở Inventory (UI mode)
unsigned long btn2PressTime   = 0;
bool          btn2WasPressed  = false;
bool          btn2SendSentinel = false;

// ── FSR402 (tay phải) grip hysteresis state ──────────────────
// ON  khi fsr_r_kg >= FSR_R_GRIP_ON_KG  (0.15 kg ≈ 1.5 N)
// OFF khi fsr_r_kg <  FSR_R_GRIP_OFF_KG (0.08 kg ≈ 0.8 N)
const float FSR_R_GRIP_ON_KG  = 0.15f;
const float FSR_R_GRIP_OFF_KG = 0.08f;
bool        fsrRGripState      = false;

// Calib mode
bool calibMode = false;
int  calibStep = 0;

// Timing
unsigned long lastTime = 0;
unsigned long lastSend = 0;

// ════════════════════════════════════════════════════════════
//  EEPROM HELPERS (giữ nguyên)
// ════════════════════════════════════════════════════════════
void eeprom_write_int(int addr, int val) {
    EEPROM.write(addr,   (uint8_t)(val >> 8));
    EEPROM.write(addr+1, (uint8_t)(val & 0xFF));
}
int eeprom_read_int(int addr) {
    return ((int)EEPROM.read(addr) << 8) | EEPROM.read(addr+1);
}
void eeprom_write_float(int addr, float val) {
    uint8_t* p = (uint8_t*)&val;
    for (int i=0;i<4;i++) EEPROM.write(addr+i, p[i]);
}
float eeprom_read_float(int addr) {
    float val; uint8_t* p = (uint8_t*)&val;
    for (int i=0;i<4;i++) p[i] = EEPROM.read(addr+i);
    return val;
}
void save_calib() {
    EEPROM.write(EEPROM_ADDR_MAGIC, EEPROM_MAGIC);
    eeprom_write_int  (EEPROM_ADDR_JOY_X_ZERO,  calib.joy_x_zero);
    eeprom_write_int  (EEPROM_ADDR_JOY_X_MIN,   calib.joy_x_min);
    eeprom_write_int  (EEPROM_ADDR_JOY_X_MAX,   calib.joy_x_max);
    eeprom_write_int  (EEPROM_ADDR_JOY_Y_ZERO,  calib.joy_y_zero);
    eeprom_write_int  (EEPROM_ADDR_JOY_Y_MIN,   calib.joy_y_min);
    eeprom_write_int  (EEPROM_ADDR_JOY_Y_MAX,   calib.joy_y_max);
    eeprom_write_int  (EEPROM_ADDR_FSR_L_ZERO,  calib.fsr_l_zero);
    eeprom_write_int  (EEPROM_ADDR_FSR_L_SPAN,  calib.fsr_l_span_adc);
    eeprom_write_float(EEPROM_ADDR_FSR_L_FSPAN, calib.fsr_l_span_n);
    eeprom_write_int  (EEPROM_ADDR_FSR_R_ZERO,  calib.fsr_r_zero);
    eeprom_write_int  (EEPROM_ADDR_FSR_R_SPAN,  calib.fsr_r_span_adc);
    eeprom_write_float(EEPROM_ADDR_FSR_R_FSPAN, calib.fsr_r_span_n);
    eeprom_write_float(EEPROM_ADDR_MPU_AX_OFF,  calib.mpu_ax_off);
    eeprom_write_float(EEPROM_ADDR_MPU_AY_OFF,  calib.mpu_ay_off);
    eeprom_write_float(EEPROM_ADDR_MPU_AZ_OFF,  calib.mpu_az_off);
    eeprom_write_float(EEPROM_ADDR_MPU_GX_OFF,  calib.mpu_gx_off);
    eeprom_write_float(EEPROM_ADDR_MPU_GY_OFF,  calib.mpu_gy_off);
    eeprom_write_float(EEPROM_ADDR_MPU_GZ_OFF,  calib.mpu_gz_off);
    Serial.println("CALIB_OK:SAVED_TO_EEPROM");
}
bool load_calib() {
    if (EEPROM.read(EEPROM_ADDR_MAGIC) != EEPROM_MAGIC) return false;
    calib.joy_x_zero     = eeprom_read_int  (EEPROM_ADDR_JOY_X_ZERO);
    calib.joy_x_min      = eeprom_read_int  (EEPROM_ADDR_JOY_X_MIN);
    calib.joy_x_max      = eeprom_read_int  (EEPROM_ADDR_JOY_X_MAX);
    calib.joy_y_zero     = eeprom_read_int  (EEPROM_ADDR_JOY_Y_ZERO);
    calib.joy_y_min      = eeprom_read_int  (EEPROM_ADDR_JOY_Y_MIN);
    calib.joy_y_max      = eeprom_read_int  (EEPROM_ADDR_JOY_Y_MAX);
    calib.fsr_l_zero     = eeprom_read_int  (EEPROM_ADDR_FSR_L_ZERO);
    calib.fsr_l_span_adc = eeprom_read_int  (EEPROM_ADDR_FSR_L_SPAN);
    calib.fsr_l_span_n   = eeprom_read_float(EEPROM_ADDR_FSR_L_FSPAN);
    calib.fsr_r_zero     = eeprom_read_int  (EEPROM_ADDR_FSR_R_ZERO);
    calib.fsr_r_span_adc = eeprom_read_int  (EEPROM_ADDR_FSR_R_SPAN);
    calib.fsr_r_span_n   = eeprom_read_float(EEPROM_ADDR_FSR_R_FSPAN);
    calib.mpu_ax_off     = eeprom_read_float(EEPROM_ADDR_MPU_AX_OFF);
    calib.mpu_ay_off     = eeprom_read_float(EEPROM_ADDR_MPU_AY_OFF);
    calib.mpu_az_off     = eeprom_read_float(EEPROM_ADDR_MPU_AZ_OFF);
    calib.mpu_gx_off     = eeprom_read_float(EEPROM_ADDR_MPU_GX_OFF);
    calib.mpu_gy_off     = eeprom_read_float(EEPROM_ADDR_MPU_GY_OFF);
    calib.mpu_gz_off     = eeprom_read_float(EEPROM_ADDR_MPU_GZ_OFF);
    return true;
}
void reset_calib() {
    EEPROM.write(EEPROM_ADDR_MAGIC, 0x00);
    calib = {512,0,1023, 512,0,1023,
             0,800,10.0f, 0,800,10.0f,
             0.0f,0.0f,0.0f, 0.0f,0.0f,0.0f};
    Serial.println("CALIB_OK:RESET_TO_DEFAULT");
}
void print_calib_status() {
    Serial.println("=== CALIBRATION STATUS ===");
    Serial.print("JOY_X: zero=");Serial.print(calib.joy_x_zero);
    Serial.print(" min=");Serial.print(calib.joy_x_min);
    Serial.print(" max=");Serial.println(calib.joy_x_max);
    Serial.print("JOY_Y: zero=");Serial.print(calib.joy_y_zero);
    Serial.print(" min=");Serial.print(calib.joy_y_min);
    Serial.print(" max=");Serial.println(calib.joy_y_max);
    Serial.print("FSR_L: zero=");Serial.print(calib.fsr_l_zero);
    Serial.print(" span_adc=");Serial.print(calib.fsr_l_span_adc);
    Serial.print(" span_N=");Serial.println(calib.fsr_l_span_n,2);
    Serial.print("FSR_R: zero=");Serial.print(calib.fsr_r_zero);
    Serial.print(" span_adc=");Serial.print(calib.fsr_r_span_adc);
    Serial.print(" span_N=");Serial.println(calib.fsr_r_span_n,2);
    Serial.print("MPU_ACCEL_OFF: ax=");Serial.print(calib.mpu_ax_off,4);
    Serial.print(" ay=");Serial.print(calib.mpu_ay_off,4);
    Serial.print(" az=");Serial.println(calib.mpu_az_off,4);
    Serial.print("MPU_GYRO_OFF : gx=");Serial.print(calib.mpu_gx_off,4);
    Serial.print(" gy=");Serial.print(calib.mpu_gy_off,4);
    Serial.print(" gz=");Serial.println(calib.mpu_gz_off,4);
    Serial.println("==========================");
}

// ════════════════════════════════════════════════════════════
//  MPU6050 INIT & READ
// ════════════════════════════════════════════════════════════
// ════════════════════════════════════════════════════════════
//  STRUCTURES & EXPLICIT PROTOTYPES (Fixes Arduino IDE Bug)
// ════════════════════════════════════════════════════════════
struct ImuRaw { 
    float ax, ay, az, gx, gy, gz; 
};

// Explicitly declare the prototype so Arduino doesn't mess it up
ImuRaw read_mpu_raw();
void mpu_sample_offsets(int n);

// ════════════════════════════════════════════════════════════
//  MPU6050 INIT & READ
// ════════════════════════════════════════════════════════════
void mpu_init() {
    Wire.setClock(400000);
    // Hardware I2C Mega 2560 Pro: SDA=pin20, SCL=pin21

    // ── I2C SCAN: kiểm tra MPU có phản hồi không ────────────────
    Wire.beginTransmission(MPU_ADDR);
    uint8_t scanResult = Wire.endTransmission(true);
    if (scanResult != 0) {
        Serial.print("MPU_ERR:I2C_SCAN_FAIL addr=0x");
        Serial.print(MPU_ADDR, HEX);
        Serial.print(" result=");
        Serial.println(scanResult);
        Serial.println("MPU_ERR:CHECK_SDA=pin20_SCL=pin21_HARDWARE_I2C");
        Wire.beginTransmission(0x68);
        uint8_t alt = Wire.endTransmission(true);
        if (alt == 0) {
            Serial.println("MPU_ERR:FOUND_AT_0x68_AD0_IS_LOW_CHECK_WIRING");
        }
    } else {
        Serial.println("MPU_OK:FOUND_AT_0x69_HARDWARE_I2C_SDA=20_SCL=21");
    }

    // Wake up MPU (thoát sleep mode)
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_PWR_REG); Wire.write(0x00);
    uint8_t r = Wire.endTransmission(true);
    if (r != 0) { Serial.print("MPU_ERR:WAKE_FAIL r="); Serial.println(r); }
    
    // DLPF = 3: Accel 44Hz, Gyro 42Hz — giảm noise phần cứng
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_DLPF_CFG); Wire.write(0x03);
    Wire.endTransmission(true);
    
    // Gyro ±250°/s
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_GYRO_CFG); Wire.write(0x00);
    Wire.endTransmission(true);
    
    // Accel ±2g
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_ACCEL_CFG); Wire.write(0x00);
    Wire.endTransmission(true);

    // Đọc WHO_AM_I register (0x75) — phải trả về 0x68 nếu MPU6050 thật
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x75);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)1, (uint8_t)true);
    if (Wire.available()) {
        uint8_t whoami = Wire.read();
        if (whoami == 0x68) {
            Serial.println("MPU_OK:WHO_AM_I=0x68_CONFIRMED");
        } else {
            Serial.print("MPU_ERR:WHO_AM_I=0x");
            Serial.print(whoami, HEX);
            Serial.println("_EXPECTED_0x68");
        }
    } else {
        Serial.println("MPU_ERR:WHO_AM_I_NO_RESPONSE");
    }
}

ImuRaw read_mpu_raw() {
    ImuRaw d = {0,0,0,0,0,0};  // default 0 nếu đọc thất bại
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(MPU_ACCEL_REG);
    Wire.endTransmission(false);
    uint8_t got = Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14, (uint8_t)true);
    if (got < 14) {
        // Không đủ bytes — MPU mất kết nối hoặc I2C bị treo
        // Gửi cảnh báo 1 lần / 500 packet để không spam Serial
        static uint16_t _errCnt = 0;
        if (++_errCnt >= 500) {
            Serial.print("MPU_ERR:READ_ONLY_");
            Serial.print(got);
            Serial.println("_BYTES_EXPECTED_14");
            _errCnt = 0;
        }
        return d;
    }
    int16_t rax = Wire.read() << 8 | Wire.read();
    int16_t ray = Wire.read() << 8 | Wire.read();
    int16_t raz = Wire.read() << 8 | Wire.read();
    Wire.read(); Wire.read();  // temp skip
    int16_t rgx = Wire.read() << 8 | Wire.read();
    int16_t rgy = Wire.read() << 8 | Wire.read();
    int16_t rgz = Wire.read() << 8 | Wire.read();
    
    d.ax = rax / 16384.0f - calib.mpu_ax_off;
    d.ay = ray / 16384.0f - calib.mpu_ay_off;
    d.az = raz / 16384.0f - calib.mpu_az_off;
    d.gx = rgx / 131.0f   - calib.mpu_gx_off;
    d.gy = rgy / 131.0f   - calib.mpu_gy_off;
    d.gz = rgz / 131.0f   - calib.mpu_gz_off;
    return d;
}  // end read_mpu_raw

void mpu_sample_offsets(int n) {
    calib.mpu_ax_off = calib.mpu_ay_off = calib.mpu_az_off = 0;
    calib.mpu_gx_off = calib.mpu_gy_off = calib.mpu_gz_off = 0;
    long ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;
    
    for (int i = 0; i < n; i++) {
        ImuRaw d = read_mpu_raw();
        ax += (long)(d.ax * 16384); ay += (long)(d.ay * 16384); az += (long)(d.az * 16384);
        gx += (long)(d.gx * 131);   gy += (long)(d.gy * 131);   gz += (long)(d.gz * 131);
        delay(200);
    }
    
    calib.mpu_ax_off = (float)ax / n / 16384.0f;
    calib.mpu_ay_off = (float)ay / n / 16384.0f;
    calib.mpu_az_off = (float)az / n / 16384.0f - 1.0f;
    calib.mpu_gx_off = (float)gx / n / 131.0f;
    calib.mpu_gy_off = (float)gy / n / 131.0f;
    calib.mpu_gz_off = (float)gz / n / 131.0f;
}

// ════════════════════════════════════════════════════════════
//  PIPELINE XỬ LÝ IMU
//  Raw → Offset subtract → EMA pre-filter →
//  Gyro drift compensation → Madgwick AHRS → Pitch/Roll
// ════════════════════════════════════════════════════════════
float filtered_pitch = 0.0f;
float filtered_roll  = 0.0f;

// ════════════════════════════════════════════════════════════
//  BIẾN TOÀN CỤC GÓC — Python có thể đọc bất kỳ lúc nào
//  Dùng lệnh serial ANGLE_STATUS để lấy snapshot tức thì
//  filtered_pitch / filtered_roll cũng được gửi trong packet D,
//  nhưng biến toàn cục giúp handle_cmd() truy cập dễ dàng
// ════════════════════════════════════════════════════════════
// (filtered_pitch và filtered_roll đã là toàn cục ở trên)

void imu_pipeline(float dt) {
    ImuRaw raw = read_mpu_raw();

    // TẦNG 1: EMA pre-filter — làm mượt trước khi vào Madgwick
    float ax = ema_ax.update(raw.ax);
    float ay = ema_ay.update(raw.ay);
    float az = ema_az.update(raw.az);
    float gx = ema_gx.update(raw.gx);
    float gy = ema_gy.update(raw.gy);
    float gz = ema_gz.update(raw.gz);

    // TẦNG 2: Gyro drift compensation
    // Khi thiết bị gần như đứng yên → học dần offset gyro
    float gyroMag = sqrtf(gx*gx + gy*gy + gz*gz);
    if (gyroMag < GYRO_STILL_THRESHOLD) {
        gyroDriftX += GYRO_DRIFT_GAIN * gx;
        gyroDriftY += GYRO_DRIFT_GAIN * gy;
        gyroDriftZ += GYRO_DRIFT_GAIN * gz;
    }
    gx -= gyroDriftX;
    gy -= gyroDriftY;
    gz -= gyroDriftZ;

    // TẦNG 3: Madgwick AHRS
    madgwick.update(ax, ay, az, gx, gy, gz, dt, MADGWICK_BETA);

    // TẦNG 4: Nắn thẳng sai số hệ thống bằng phương trình Excel
    filtered_pitch = (MPU_A_SLOPE * madgwick.get_pitch()) + MPU_B_INTERCEPT;
    filtered_roll  = (MPU_A_SLOPE * madgwick.get_roll())  + MPU_B_INTERCEPT;
}

// ════════════════════════════════════════════════════════════
//  PIPELINE XỬ LÝ JOYSTICK
//  Raw ADC → Median-3 → EMA → Normalize (-100..+100) → Deadzone
// ════════════════════════════════════════════════════════════
int normalize_joy(int raw, int zero, int mn, int mx) {
    int rp = mx - zero; if (rp <= 0) rp = 1;
    int rn = zero - mn; if (rn <= 0) rn = 1;
    int val = raw - zero;
    int pct = (val > 0) ?  (int)((long) val*100/rp)
                         : -(int)((long)-val*100/rn);
    pct = constrain(pct, -100, 100);
    if (abs(pct) <= JOY_DEADZONE_PCT) return 0;
    return pct;
}

int joystick_pipeline(int pin, Median3<int>& med, EMAf& ema,
                      int zero, int mn, int mx) {
    int raw      = analogRead(pin);
    int denoised = med.update(raw);              // Tầng 1: loại spike
    int smoothed = (int)ema.update((float)denoised); // Tầng 2: EMA
    return normalize_joy(smoothed, zero, mn, mx);    // Tầng 3: normalize
}

// ════════════════════════════════════════════════════════════
//  PIPELINE XỬ LÝ FSR
//  Raw ADC → Median-5 → IIR low-pass → Ohm → uS → kg
//  Nhận hệ số riêng cho từng loại cảm biến (FSR 402 / FSR 406)
// ════════════════════════════════════════════════════════════
float fsr_pipeline(int pin, Median5& med, IIRLowPass& iir, float a_slope, float b_intercept) {
    int raw      = analogRead(pin);
    int denoised = med.update(raw);              // Tầng 1: Loại spike
    float smooth = iir.update((float)denoised);  // Tầng 2: IIR Low-pass

    if (smooth <= 15) return 0.0; // Ngưỡng bỏ qua nhiễu ADC cực thấp

    // BƯỚC 1: Tính điện trở (Ohm) và Độ dẫn điện (uS)
    float rFsr = R_PULLUP * ((1023.0 / smooth) - 1.0);
    float conductance = 1000000.0 / rFsr;

    // BƯỚC 2: Tính khối lượng (kg) theo phương trình tương ứng
    float mass_kg = (a_slope * conductance) + b_intercept;

    return (mass_kg < 0.01) ? 0.0 : mass_kg;
}

// Hysteresis: tránh flicker ở ngưỡng grip
bool hysteresis_grip(int pct, bool& state) {
    if (!state && pct >= FSR_GRIP_ON_PCT)  state = true;
    if ( state && pct <  FSR_GRIP_OFF_PCT) state = false;
    return state;
}

// ════════════════════════════════════════════════════════════
//  VIBRATION — NON-BLOCKING
// ════════════════════════════════════════════════════════════
void vib_pulse(int pwm, int ms) {
    analogWrite(PIN_VIBRATION, pwm);
    lastVibEnd = millis() + ms;
}
void vib_update() {
    if (lastVibEnd > 0 && millis() >= lastVibEnd) {
        analogWrite(PIN_VIBRATION, 0);
        lastVibEnd = 0;
    }
}

// ════════════════════════════════════════════════════════════
//  SERVO — RATE LIMITER + DEAD-BAND
// ════════════════════════════════════════════════════════════
void servo_update_from_fsr(float fsr_r_kg) {
    // Nhân kg với 1000 để chuyển thành Gram.
    long gram = fsr_r_kg * 1000.0;

    // Giả định lực bóp tối đa để Servo xoay hết cỡ là 2kg (2000 gram).
    // Có thể chỉnh số 2000 này lên/xuống tùy sức cơ tay của bệnh nhân.
    int target = map(gram, 0, 2000, SERVO_NEUTRAL, SERVO_MAX_ANGLE);
    servoTarget = constrain(target, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE);
}
void servo_tick() {
    int err = servoTarget - servoActual;
    if (abs(err) <= SERVO_DEADBAND) return;   // Dead-band: không rung nhỏ
    int step = constrain(err, -SERVO_MAX_RATE, SERVO_MAX_RATE);
    servoActual += step;
    servoMotor.write(servoActual);
}

// ════════════════════════════════════════════════════════════
//  CALIBRATION COMMAND HANDLER (giữ nguyên logic v3.0)
// ════════════════════════════════════════════════════════════
void handle_cmd(const String& cmd) {
    if (cmd == "CALIB_START") {
        Serial.println("CALIB:START - Wizard 3 buoc: CALIB_ZERO / CALIB_SPAN,L,R / CALIB_SAVE");
        calibMode = true; calibStep = 0; return;
    }
    if (cmd == "CALIB_ZERO") {
        Serial.println("CALIB:ZERO_START - De joystick nghi, khong ap FSR, MPU nam phang...");
        long sx=0,sy=0,sfl=0,sfr=0;
        for(int i=0;i<200;i++){
            sx+=analogRead(PIN_JOY_X); sy+=analogRead(PIN_JOY_Y);
            sfl+=analogRead(PIN_FSR_LEFT); sfr+=analogRead(PIN_FSR_RIGHT);
            delay(200);
        }
        calib.joy_x_zero=(int)(sx/200); calib.joy_y_zero=(int)(sy/200);
        calib.fsr_l_zero=(int)(sfl/200); calib.fsr_r_zero=(int)(sfr/200);
        Serial.println("CALIB:MPU offset (2s)...");
        mpu_sample_offsets(400);
        // Reset bộ lọc sau calib
        ema_ax=EMAf(IMU_EMA_ALPHA); ema_ay=EMAf(IMU_EMA_ALPHA); ema_az=EMAf(IMU_EMA_ALPHA);
        ema_gx=EMAf(IMU_EMA_ALPHA); ema_gy=EMAf(IMU_EMA_ALPHA); ema_gz=EMAf(IMU_EMA_ALPHA);
        ema_jx=EMAf(JOY_EMA_ALPHA); ema_jy=EMAf(JOY_EMA_ALPHA);
        iir_fsr_l=IIRLowPass(FSR_IIR_ALPHA); iir_fsr_r=IIRLowPass(FSR_IIR_ALPHA);
        gyroDriftX=gyroDriftY=gyroDriftZ=0.0f;
        madgwick.reset();
        Serial.print("CALIB:ZERO_DONE JX=");Serial.print(calib.joy_x_zero);
        Serial.print(" JY=");Serial.print(calib.joy_y_zero);
        Serial.print(" FL=");Serial.print(calib.fsr_l_zero);
        Serial.print(" FR=");Serial.println(calib.fsr_r_zero);
        calibStep=1; return;
    }
    if (cmd.startsWith("CALIB_SPAN")) {
        float sL=10.0f, sR=10.0f;
        int c1=cmd.indexOf(',');
        if(c1>0){ int c2=cmd.indexOf(',',c1+1);
            if(c2>0){ sL=cmd.substring(c1+1,c2).toFloat(); sR=cmd.substring(c2+1).toFloat(); }
        }
        calib.fsr_l_span_n=sL; calib.fsr_r_span_n=sR;
        Serial.print("CALIB:SPAN_START FSR_L=");Serial.print(sL,2);Serial.print("N FSR_R=");Serial.println(sR,2);
        Serial.println("CALIB:Ap luc chuan + full joystick range (5s)...");
        int jxMin=1023,jxMax=0,jyMin=1023,jyMax=0;
        unsigned long t_end=millis()+5000;
        while(millis()<t_end){
            int rx=analogRead(PIN_JOY_X); int ry=analogRead(PIN_JOY_Y);
            if(rx<jxMin)jxMin=rx; if(rx>jxMax)jxMax=rx;
            if(ry<jyMin)jyMin=ry; if(ry>jyMax)jyMax=ry;
            delay(200);
        }
        calib.joy_x_min=jxMin; calib.joy_x_max=jxMax;
        calib.joy_y_min=jyMin; calib.joy_y_max=jyMax;
        long sfl=0,sfr=0;
        for(int i=0;i<200;i++){sfl+=analogRead(PIN_FSR_LEFT);sfr+=analogRead(PIN_FSR_RIGHT);delay(5);}
        calib.fsr_l_span_adc=(int)(sfl/200); calib.fsr_r_span_adc=(int)(sfr/200);
        bool ok=true;
        if(calib.fsr_l_span_adc<=calib.fsr_l_zero+10){Serial.println("CALIB:WARN FSR_L span qua thap");ok=false;}
        if(calib.fsr_r_span_adc<=calib.fsr_r_zero+10){Serial.println("CALIB:WARN FSR_R span qua thap");ok=false;}
        Serial.print("CALIB:SPAN_DONE FL_ADC=");Serial.print(calib.fsr_l_span_adc);
        Serial.print(" FR_ADC=");Serial.print(calib.fsr_r_span_adc);
        Serial.print(" JX=");Serial.print(jxMin);Serial.print("..");Serial.print(jxMax);
        Serial.print(" JY=");Serial.print(jyMin);Serial.print("..");Serial.println(jyMax);
        if(ok) Serial.println("CALIB:Sai so <5%: OK");
        calibStep=2; return;
    }
    if (cmd=="CALIB_SAVE")   { save_calib(); calibMode=false; calibStep=0; madgwick.reset(); Serial.println("CALIB:COMPLETE"); return; }
    if (cmd=="CALIB_LOAD")   { if(load_calib()){Serial.println("CALIB_OK:LOADED");print_calib_status();}else Serial.println("CALIB_ERR:NO_DATA"); return; }
    if (cmd=="CALIB_RESET")  { reset_calib(); return; }
    if (cmd=="CALIB_STATUS") { print_calib_status(); return; }

    if (cmd=="FILTER_STATUS") {
        Serial.println("=== FILTER STATUS ===");
        Serial.print("Madgwick beta=");    Serial.println(MADGWICK_BETA,4);
        Serial.print("IMU EMA alpha=");    Serial.println(IMU_EMA_ALPHA,2);
        Serial.print("Gyro still thr=");   Serial.println(GYRO_STILL_THRESHOLD,2);
        Serial.print("Gyro drift=");       Serial.print(gyroDriftX,4);
        Serial.print(",");                 Serial.print(gyroDriftY,4);
        Serial.print(",");                 Serial.println(gyroDriftZ,4);
        Serial.print("Joy EMA alpha=");    Serial.println(JOY_EMA_ALPHA,2);
        Serial.print("FSR IIR alpha=");    Serial.println(FSR_IIR_ALPHA,2);
        Serial.print("FSR grip on/off=");  Serial.print(FSR_GRIP_ON_PCT);
        Serial.print("/");                 Serial.println(FSR_GRIP_OFF_PCT);
        Serial.print("Debounce ms=");      Serial.println(DEBOUNCE_MS);
        Serial.print("Servo deadband=");   Serial.print(SERVO_DEADBAND);
        Serial.print("° rate=");           Serial.println(SERVO_MAX_RATE);
        Serial.println("--- FLIGHT STICK PINS ---");
        Serial.print("FS_UP=D");    Serial.print(FS_UP_PIN);
        Serial.print(" FS_DOWN=D"); Serial.print(FS_DOWN_PIN);
        Serial.print(" FS_LEFT=D"); Serial.print(FS_LEFT_PIN);
        Serial.print(" FS_RIGHT=D");Serial.println(FS_RIGHT_PIN);
        Serial.print("TRIGGER=D");  Serial.print(FS_TRIGGER_PIN);
        Serial.print(" THUMB=D");   Serial.println(FS_THUMB_PIN);
        Serial.println("====================");
        return;
    }
    // Lệnh điều khiển phản hồi từ Python
    if (cmd.startsWith("VIB,"))   { vib_pulse(constrain(cmd.substring(4).toInt(),0,255),300); return; }
    if (cmd.startsWith("SERVO,")) { servoTarget=constrain(cmd.substring(6).toInt(),SERVO_MIN_ANGLE,SERVO_MAX_ANGLE); return; }
    if (cmd.startsWith("BETA,"))  { MADGWICK_BETA=constrain(cmd.substring(5).toFloat(),0.005f,0.2f); return; }

    // Lệnh mới: trả về góc tức thì (Python gọi để debug hoặc căn zero)
    if (cmd == "ANGLE_STATUS") {
        Serial.print("ANGLE:PITCH=");
        Serial.print(filtered_pitch, 2);
        Serial.print(",ROLL=");
        Serial.println(filtered_roll, 2);
        return;
    }
    // Căn ZERO góc — reset Madgwick quaternion về vị trí hiện tại làm tham chiếu
    if (cmd == "ANGLE_ZERO") {
        madgwick.reset();
        // Warm-up nhanh 20 vòng để ổn định
        for (int i = 0; i < 20; i++) {
            ImuRaw r = read_mpu_raw();
            madgwick.update(r.ax, r.ay, r.az, r.gx, r.gy, r.gz, 0.02f, MADGWICK_BETA);
        }
        Serial.println("ANGLE_ZERO:OK");
        return;
    }
}

// ════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);
    pinMode(PIN_BTN1,      INPUT_PULLUP);
    pinMode(PIN_BTN2,      INPUT_PULLUP);
    // PIN_BTN_GRIP đã XÓA — FSR402 tay phải thay thế

    // Flight stick — tất cả INPUT_PULLUP (LOW = bấm)
    pinMode(FS_UP_PIN,      INPUT_PULLUP);
    pinMode(FS_DOWN_PIN,    INPUT_PULLUP);
    pinMode(FS_LEFT_PIN,    INPUT_PULLUP);
    pinMode(FS_RIGHT_PIN,   INPUT_PULLUP);
    pinMode(FS_TRIGGER_PIN, INPUT_PULLUP);
    pinMode(FS_THUMB_PIN,   INPUT_PULLUP);
    pinMode(PIN_VIBRATION, OUTPUT);
    analogWrite(PIN_VIBRATION, 0);

    servoMotor.attach(PIN_SERVO);
    servoMotor.write(SERVO_NEUTRAL);

    // Chờ Timer ổn định sau Servo attach — tránh B1/B2 đọc sai lúc boot
    delay(100);
    // Khởi tạo pressTime = now để tránh b2_dur = (now-0) khi boot
    btn1PressTime  = millis();
    btn2PressTime  = millis();
    // Sync wasPressed với trạng thái thực tế
    btn1WasPressed = !digitalRead(PIN_BTN1);
    btn2WasPressed = !digitalRead(PIN_BTN2);

    Wire.begin();  // Hardware I2C: SDA=pin20, SCL=pin21 (Mega 2560 Pro)
    mpu_init();
    delay(200);

    // Warm-up Madgwick: chạy 100 vòng để quaternion ổn định
    for (int i = 0; i < 100; i++) {
        ImuRaw r = read_mpu_raw();
        madgwick.update(r.ax, r.ay, r.az, r.gx, r.gy, r.gz, 0.01f, MADGWICK_BETA);
        delay(200);
    }

    if (load_calib()) {
        Serial.println("CALIB:EEPROM_LOADED");
    } else {
        Serial.println("CALIB:DEFAULT_VALUES");
    }

    lastTime = millis();
    Serial.println("BME_READY");
}

// ════════════════════════════════════════════════════════════
//  MAIN LOOP
// ════════════════════════════════════════════════════════════
void loop() {
    unsigned long now = millis();
    float dt = (now - lastTime) / 1000.0f;
    if (dt < 0.001f) dt = 0.001f;
    if (dt > 0.1f)   dt = 0.1f;  // clamp: tránh jump khi debug
    lastTime = now;

    // ── Serial commands ─────────────────────────────────────
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd.length() > 0) handle_cmd(cmd);
    }

    // ── IMU pipeline (50Hz, chạy mỗi loop) ──────────────────
    imu_pipeline(dt);

    // ── Joystick pipeline ────────────────────────────────────
    int jx = joystick_pipeline(PIN_JOY_X, med_jx, ema_jx,
                               calib.joy_x_zero, calib.joy_x_min, calib.joy_x_max);
    int jy = joystick_pipeline(PIN_JOY_Y, med_jy, ema_jy,
                               calib.joy_y_zero, calib.joy_y_min, calib.joy_y_max);

    // ── FSR pipeline (Truyền đúng hệ số của FSR 406 và FSR 402) ─────────────
    float fsr_l_kg = fsr_pipeline(PIN_FSR_LEFT,  med_fsr_l, iir_fsr_l, FSR_L_A_SLOPE, FSR_L_B_INTERCEPT);
    float fsr_r_kg = fsr_pipeline(PIN_FSR_RIGHT, med_fsr_r, iir_fsr_r, FSR_R_A_SLOPE, FSR_R_B_INTERCEPT);

    // ── Debounce B1 và B2 ────────────────────────────────────────────────
    bool btn1 = deb_btn1.update(!digitalRead(PIN_BTN1), now);
    bool btn2 = deb_btn2.update(!digitalRead(PIN_BTN2), now);

    // ── B1 duration tracking ─────────────────────────────────────────────
    // tap < 300ms → Python: Space (nhảy)
    // hold >= 300ms → Python: giữ Shift (sneak)
    if (btn1 && !btn1WasPressed) {
        btn1PressTime    = now;
        btn1SendSentinel = false;
        vib_pulse(60, 20);   // haptic nhẹ xác nhận bấm
    }
    if (!btn1 && btn1WasPressed) {
        btn1SendSentinel = true;
    }
    btn1WasPressed = btn1;

    uint16_t b1_dur = 0;
    if (btn1SendSentinel) {
        b1_dur           = 65535;    // sentinel: vừa nhả
        btn1SendSentinel = false;
    } else if (btn1) {
        unsigned long held1 = now - btn1PressTime;
        b1_dur = (uint16_t)min(held1, (unsigned long)65534);
    }

    // ── B2 duration tracking ─────────────────────────────────────────────
    // tap < 500ms → Python: cuộn Hotbar (1,2,3...)
    // hold >= 500ms → Python: mở Inventory (UI mode)
    if (btn2 && !btn2WasPressed) {
        btn2PressTime    = now;
        btn2SendSentinel = false;
        vib_pulse(80, 30);
    }
    if (!btn2 && btn2WasPressed) {
        btn2SendSentinel = true;
    }
    btn2WasPressed = btn2;

    uint16_t b2_dur = 0;
    if (btn2SendSentinel) {
        b2_dur           = 65535;
        btn2SendSentinel = false;
    } else if (btn2 && btn2WasPressed) {
        // guard: chỉ tính nếu đã ghi nhận rising edge (tránh boot glitch)
        unsigned long held2 = now - btn2PressTime;
        b2_dur = (uint16_t)min(held2, (unsigned long)65534);
    }

    // ── FSR402 tay phải: hysteresis grip detect ───────────────────────────
    // Thay thế hoàn toàn PIN_BTN_GRIP.
    // Gửi bit grip (0/1) để Python biết trạng thái, đồng thời gửi kg.
    // Hysteresis tránh flicker khi lực ở ranh giới ngưỡng.
    if (!fsrRGripState && fsr_r_kg >= FSR_R_GRIP_ON_KG)  fsrRGripState = true;
    if ( fsrRGripState && fsr_r_kg <  FSR_R_GRIP_OFF_KG) fsrRGripState = false;
    bool grip = fsrRGripState;

    // Haptic rising edge (bắt đầu bóp)
    if (grip && !prevGrip) vib_pulse(VIB_GRIP_PWM, 80);

    // ── Servo phản hồi lực tay phải ──────────────────────────────────────
    servo_update_from_fsr(fsr_r_kg);
    servo_tick();
    vib_update();

    prevBtn1 = btn1; prevBtn2 = btn2; prevGrip = grip;

    // ── Flight stick: đọc & debounce 6 đầu vào digital ──────────────────
    // INPUT_PULLUP → digitalRead LOW khi bấm → đảo dấu để active=true
    bool fs_up      = deb_fs_up     .update(!digitalRead(FS_UP_PIN),      now);
    bool fs_down    = deb_fs_down   .update(!digitalRead(FS_DOWN_PIN),    now);
    bool fs_left    = deb_fs_left   .update(!digitalRead(FS_LEFT_PIN),    now);
    bool fs_right   = deb_fs_right  .update(!digitalRead(FS_RIGHT_PIN),   now);
    bool fs_trigger = deb_fs_trigger.update(!digitalRead(FS_TRIGGER_PIN), now);
    bool fs_thumb   = deb_fs_thumb  .update(!digitalRead(FS_THUMB_PIN),   now);

    // ── Gửi packet 50Hz ──────────────────────────────────────────────────
    // Format: D,JX,JY,B1_DUR,B2_DUR,FSR_R_GRIP,PITCH,ROLL,
    //         FSR_L_KG,FSR_R_KG,VIB,SERVO,
    //         FS_UP,FS_DOWN,FS_LEFT,FS_RIGHT,FS_TRIGGER,FS_THUMB
    if (now - lastSend >= SEND_INTERVAL_MS) {
        lastSend = now;
        Serial.print("D,");
        Serial.print(jx);                      Serial.print(",");
        Serial.print(jy);                      Serial.print(",");
        Serial.print(b1_dur);                  Serial.print(",");   // B1 duration
        Serial.print(b2_dur);                  Serial.print(",");   // B2 duration
        Serial.print(grip ? 1 : 0);            Serial.print(",");   // FSR_R grip bit

        Serial.print(filtered_pitch, 2);       Serial.print(",");   // Pitch (°)
        Serial.print(filtered_roll,  2);       Serial.print(",");   // Roll (°)

        Serial.print(fsr_l_kg, 3);             Serial.print(",");   // FSR406 tay trái (kg)
        Serial.print(fsr_r_kg, 3);             Serial.print(",");   // FSR402 tay phải (kg)

        Serial.print(lastVibEnd > 0 ? 1 : 0); Serial.print(",");
        Serial.print(servoActual);             Serial.print(",");

        // Flight stick (6 bit trạng thái, 0/1)
        Serial.print(fs_up      ? 1 : 0);     Serial.print(",");
        Serial.print(fs_down    ? 1 : 0);     Serial.print(",");
        Serial.print(fs_left    ? 1 : 0);     Serial.print(",");
        Serial.print(fs_right   ? 1 : 0);     Serial.print(",");
        Serial.print(fs_trigger ? 1 : 0);     Serial.print(",");
        Serial.println(fs_thumb ? 1 : 0);
    }
}

