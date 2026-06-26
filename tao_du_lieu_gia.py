import os
import time
import random
import csv
import math
from datetime import datetime

OUTPUT_DIR = "Patient_Records/Raw_CSV"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HZ = 50
DT = 1.0 / HZ
DURATION_MINUTES = 3
TOTAL_SAMPLES = int(DURATION_MINUTES * 60 * HZ)

def generate_session(profile_name):
    time.sleep(1) 
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if profile_name == "Baseline":
        prefix = "Session_NguoiBinhThuong"
        # Người bình thường chơi Luanti 20-30 phút
        local_duration_minutes = random.uniform(20.0, 30.0)
        local_total_samples = int(local_duration_minutes * 60 * HZ)
        
        # CĂN CHỈNH LẠI DỰA TRÊN TIÊU CHUẨN Y KHOA & THỰC TẾ CHƠI GAME:
        # - aROM Pitch mục tiêu: ~120°-135° (=> p max = 65°)
        # - aROM Roll mục tiêu (đã gộp lật cẳng tay): ~90°-110° (=> r max = 50°)
        # - Grip Rate (clk): Đưa về trung bình ~12 - 15 lần/phút. (0.005 ở 50Hz = 15 lần/phút)
        states = {
            # EXPLORE: Góc vừa phải, thư giãn, ngắm cảnh. (Pitch ROM ~90°, Roll ROM ~60°)
            "EXPLORE": {"p": 45.0, "r": 30.0, "spd": 0.05, "grip": 15, "act": 0.8, "clk": 0.004, "dur": (30, 90)},
            
            # MINE: Góc nhỏ (đào block trước mặt), nhưng tốc độ nhanh, click giữ liên tục
            "MINE":    {"p": 25.0, "r": 20.0, "spd": 0.15, "grip": 45, "act": 0.3, "clk": 0.020, "dur": (15, 60)},
            
            # COMBAT: Cử động gắt, hết cỡ ROM chức năng để quay người đánh quái.
            "COMBAT":  {"p": 65.0, "r": 50.0, "spd": 0.25, "grip": 70, "act": 0.9, "clk": 0.040, "dur": (10, 25)},
            
            # IDLE: Đứng im xem kho đồ, check map.
            "IDLE":    {"p": 5.0,  "r": 5.0,  "spd": 0.02, "grip": 0,  "act": 0.0, "clk": 0.000, "dur": (5, 15)}
        }
    else:
        # Cấu hình 3 phút gốc của bệnh nhân
        local_total_samples = TOTAL_SAMPLES
        if profile_name == "Patient_Pre":
            prefix = "Session_BenhNhan_TruocTap"
            rom_pitch_max = random.uniform(20.0, 30.0)    
            rom_roll_max = random.uniform(15.0, 25.0)
            speed_factor = random.uniform(0.005, 0.02)
            pause_chance = 0.7
            left_active_prob = 0.15                       
            grip_max = random.uniform(20, 35)
            tremor_amp = random.uniform(6.0, 10.0)
            fatigue_target = random.uniform(0.3, 0.5)     
            
        elif profile_name == "Patient_Post":
            prefix = "Session_BenhNhan_SauTap"
            rom_pitch_max = random.uniform(40.0, 55.0)
            rom_roll_max = random.uniform(35.0, 50.0)
            speed_factor = random.uniform(0.02, 0.06)
            pause_chance = 0.5
            left_active_prob = 0.5
            grip_max = random.uniform(50, 70)
            tremor_amp = random.uniform(2.5, 4.5)
            fatigue_target = random.uniform(0.7, 0.85)

    filename = os.path.join(OUTPUT_DIR, f"{prefix}_{timestamp_str}.csv")
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "JX", "JY", "B1", "B2", "Grip", "Pitch", "Roll"])
        
        current_time = time.time()
        pitch_real, roll_real, grip_real = 0.0, 0.0, 0.0
        jx_real, jy_real = 0, 0
        
        target_pitch, target_roll, target_grip = 0.0, 0.0, 0.0
        target_jx, target_jy = 0, 0
        state_timer = 0.0
        move_timer = 0.0
        current_state = "EXPLORE"
        total_grip_sum = 0.0
        click_count = 0 
        
        print(f"Đang nội suy chuyển động thực tế: {profile_name}...")

        for i in range(local_total_samples):
            t = i * DT
            progress = i / local_total_samples
            b1_real, b2_real = 0, 0

            # --- LOGIC NGƯỜI BÌNH THƯỜNG ---
            if profile_name == "Baseline":
                # Fatigue Index duy trì ở mức > 95% theo thực tế (giảm nhẹ 5% vì người bình thường ít mỏi)
                fatigue = 1.0 - (0.05 * progress) 
                
                state_timer -= DT
                if state_timer <= 0:
                    keys = list(states.keys())
                    # Luanti: Explore nhiều nhất, đào mỏ nhì, thỉnh thoảng combat
                    weights = [60, 25, 10, 5] 
                    current_state = random.choices(keys, weights=weights, k=1)[0]
                    params = states[current_state]
                    state_timer = random.uniform(params["dur"][0], params["dur"][1])
                    
                params = states[current_state]
                
                move_timer -= DT
                if move_timer <= 0:
                    move_timer = random.uniform(0.3, 1.5)
                    # Tính toán góc thực tế
                    target_pitch = random.uniform(-params["p"], params["p"])
                    target_roll = random.uniform(-params["r"], params["r"])
                    
                    if random.random() < params["act"]:
                        target_jx = random.choice([-100, 100]) if random.random() > 0.3 else 0
                        target_jy = random.choice([-100, 100]) if target_jx == 0 else 0
                    else:
                        target_jx, target_jy = 0, 0
                        
                b1_real = 1 if random.random() < params["clk"] else 0
                b2_real = 1 if (random.random() < params["clk"] * 0.1) else 0
                
                if b1_real or b2_real:
                    click_count += 1
                
                target_grip = params["grip"] * fatigue
                if b1_real or b2_real:
                    target_grip += random.uniform(15, 25) 
                target_grip = max(0, min(100, target_grip))
                
                speed = params["spd"] * fatigue
                pitch_real += (target_pitch - pitch_real) * speed
                roll_real += (target_roll - roll_real) * speed
                grip_real += (target_grip - grip_real) * 0.3
                
                jx_real = target_jx if random.random() > 0.05 else jx_real
                jy_real = target_jy if random.random() > 0.05 else jy_real
                
                tremor_wave = math.sin(t * math.pi * 8) * 0.5
                tremor_amp_val = 1.0 + (grip_real / 100.0) 
                noise_p = tremor_wave * tremor_amp_val + random.uniform(-0.5, 0.5)
                noise_r = tremor_wave * tremor_amp_val + random.uniform(-0.5, 0.5)
                final_grip = int(max(0, min(100, grip_real + random.choice([-1, 0, 1]))))

            # --- LOGIC BỆNH NHÂN (GIỮ NGUYÊN) ---
            else:
                current_fatigue = 1.0
                if progress > 0.3:
                    current_fatigue = 1.0 - ((progress - 0.3) * (1.0 / 0.7) * (1.0 - fatigue_target))

                state_timer -= DT
                if state_timer <= 0:
                    if random.random() < pause_chance:
                        state_timer = random.uniform(0.5, 3.0)
                        target_pitch = pitch_real + random.uniform(-3, 3) 
                        target_roll = roll_real + random.uniform(-3, 3)
                        target_grip = 0
                        target_jx, target_jy = 0, 0
                    else:
                        state_timer = random.uniform(1.0, 4.0)
                        target_pitch = random.uniform(-rom_pitch_max, rom_pitch_max) * current_fatigue
                        target_roll = random.uniform(-rom_roll_max, rom_roll_max) * current_fatigue
                        if random.random() < left_active_prob:
                            target_grip = grip_max * current_fatigue
                            target_jx = random.choice([-100, 100]) if random.random() > 0.5 else 0
                            target_jy = random.choice([-100, 100]) if target_jx == 0 else 0

                pitch_real += (target_pitch - pitch_real) * speed_factor
                roll_real += (target_roll - roll_real) * speed_factor
                grip_real += (target_grip - grip_real) * 0.15
                jx_real = target_jx if random.random() > 0.05 else jx_real
                jy_real = target_jy if random.random() > 0.05 else jy_real

                current_tremor = tremor_amp
                if grip_real > 20: 
                    current_tremor *= random.uniform(1.2, 2.0)
                
                noise_p = random.uniform(-current_tremor, current_tremor)
                noise_r = random.uniform(-current_tremor, current_tremor)
                final_grip = int(max(0, min(100, grip_real + random.uniform(-2, 2))))

            total_grip_sum += final_grip
            
            writer.writerow([
                current_time + t, 
                int(jx_real), int(jy_real), b1_real, b2_real, 
                final_grip, 
                round(pitch_real + noise_p, 2), 
                round(roll_real + noise_r, 2)
            ])
            
    print(f"✅ Đã kết xuất: {filename.split('/')[-1]}")
    if profile_name == "Baseline":
        grip_rate = click_count / local_duration_minutes
        print(f"   📊 Cường độ nắm (Avg Grip): {total_grip_sum / local_total_samples:.2f} / 100")
        print(f"   🖱️ Grip Rate: {grip_rate:.1f} lần/phút (Chuẩn ~12.3/ph)")

if __name__ == "__main__":
    while True:
        print("\n" + "="*60)
        print("🏭 TRẠM TẠO DỮ LIỆU ĐỒ ÁN (V4.1 - ĐÃ HIỆU CHUẨN CLINICAL ROM)")
        print("="*60)
        print("1. [Người Thường] Baseline (aROM Pitch ~130°, Roll ~100°)")
        print("2. [Đột Quỵ] Trước tập (Khựng nhiều, run tay, yếu trái)")
        print("3. [Đột Quỵ] Sau tập (Cải thiện rõ rệt)")
        print("4. 🚀 TẠO COMBO 9 FILE")
        print("0. Thoát")
        
        choice = input("\n👉 Nhập lựa chọn: ")
        if choice == '1': generate_session("Baseline")
        elif choice == '2': generate_session("Patient_Pre")
        elif choice == '3': generate_session("Patient_Post")
        elif choice == '4':
            print("\n⏳ Đang render 9 file dữ liệu mô phỏng tay người thật...")
            for _ in range(3): generate_session("Baseline")
            for _ in range(3): generate_session("Patient_Pre")
            for _ in range(3): generate_session("Patient_Post")
            print("🎉 Hoàn tất!")
        elif choice == '0': break