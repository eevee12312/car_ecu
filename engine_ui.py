import pygame
import time
import threading
import socket
import os
import platform
from engine_sound_mine import play_turbo,EngineSoundSimulator
# === Choose Tune Mode ===
# Options: "stock", "upgraded"
TUNE_MODE = "upgraded"

# === Engine Tune Profiles ===
TUNES = {
    "stock": { #top speed 270
        "MAX_RPM": 8000,               # Stock rev limit for R35 VR38DETT engine
        "IDLE_RPM": 800,               # Typical stock idle RPM
        "final_drive": 4.111,           # Stock final drive ratio (close to actual ~3.91)
        "tire_diameter_m": 0.62,       # Approximate stock tire diameter in meters (~25 inches)
        "driveline_efficiency": 0.75,  # Driveline loss ~25%
        "engine_inertia": 0.3,         # Estimated engine inertia
        "car_mass": 1740,              # Approximate curb weight (kg)
        "GEARS": {
            0: 0,
            1: 4.06,
            2: 2.30,
            3: 1.59,
            4: 1.25,
            5: 1.0,
            6: 0.85     
        },
        "peak_rpm": 4800,              # Peak power RPM
        "max_boost": 22.0,             # Stock max boost (around 21-23 PSI)
        "max_torque": 430,             # Stock torque (Nm) - ~430Nm (~317 lb-ft)
    },
    "upgraded": { #top speed 301
        "MAX_RPM": 9000,      
        "IDLE_RPM": 900,        
        "final_drive": 4.11,     
        "tire_diameter_m": 0.62,    
        "driveline_efficiency": 0.82,
        "engine_inertia": 0.25, 
        "car_mass": 1500,            
        "GEARS": {
            0: 0,
            1: 4.06,
            2: 2.30,
            3: 1.59,
            4: 1.25,
            5: 1.0,
            6: 0.85     
        },
        "peak_rpm": 6800,
        "max_boost": 32.0,  
        "max_torque": 550, 
    },
    "qm": { # 0-60 & 1/4mi optimized
        "MAX_RPM": 9500,               # Still sporty, but not excessive to reduce unnecessary rev time
        "IDLE_RPM": 1100,              # Higher idle helps quicker launches
        "final_drive": 4.55,           # Shorter for more wheel torque
        "tire_diameter_m": 0.60,       # Slightly smaller tire increases effective torque
        "driveline_efficiency": 0.88, # Better tuned power delivery
        "engine_inertia": 0.18,        # Faster RPM climb
        "car_mass": 1450,              # Lightweight build
        "GEARS": {
            0: 0,
            1: 4.35,                   # Shorter 1st gear for strong launch
            2: 2.60,                   # Closer ratios
            3: 1.85,
            4: 1.35,
            5: 1.0,
            6: 0.80     
        },
        "peak_rpm": 7500,              # Torque stays high near redline
        "max_boost": 35.0,             # Maxed turbo pressure
        "max_torque": 720,             # High output engine tune
    }
}


# === Load selected tune ===
tune = TUNES[TUNE_MODE]

MAX_RPM = tune["MAX_RPM"]
IDLE_RPM = tune["IDLE_RPM"]
final_drive = tune["final_drive"]
tire_diameter_m = tune["tire_diameter_m"]
driveline_efficiency = tune["driveline_efficiency"]
engine_inertia = tune["engine_inertia"]
car_mass = tune["car_mass"]
GEARS = tune["GEARS"]
peak_rpm = tune["peak_rpm"]
max_boost = tune["max_boost"]
max_torque = tune["max_torque"]
LAUNCH_CONTROL_RPM = 4500  # Launch RPM setpoint
LAUNCH_BUTTON_INDEX = 0    # Button 0 for launch control

global peak_hp, peak_rpm_recorded, top_speed
peak_rpm_recorded = 0
top_speed = 0
peak_hp = 0
sim = EngineSoundSimulator("sounds/engine_idle.wav")


# === Engine State ===
rpm = IDLE_RPM
gear = 0
engine_on = False

# === Log ===
def log():
    msg = f"========\nTune:{TUNE_MODE}\nPeak RPM: {peak_rpm_recorded}\nTop Speed:{top_speed}\nPeak HorsePower: {peak_hp}\n0-60 mph: {time_0_60:.2f} s\n1/4 Mile: {time_qm:.2f} s, Speed: {speed_kph_at_qm:.1f}\n========\n"
    with open("log.txt", 'a') as file:
        file.write(msg)





# === Engine Temp ===
def calculate_engine_temp(rpm, throttle, boost_psi, speed, dt, engine_temp=70.0):
    ambient_temp = 24.0
    heating_rate = (rpm / MAX_RPM) * throttle * (1 + boost_psi / 14.7) * 20
    cooling_rate = (speed / 200) * 10 + 5

    temp_change = heating_rate - cooling_rate
    engine_temp += temp_change * dt
    engine_temp = max(ambient_temp, min(engine_temp, 120.0))

    return engine_temp

# === Boost Calculation ===
def calculate_boost_psi(rpm, throttle):
    if rpm < 2000:
        return 0
    ramp = min(1, (rpm - 2000) / (MAX_RPM - 2000))
    return throttle * max_boost * ramp

# === HP Calculation ===
def calculate_engine_hp(rpm, torque_na, boost_psi):
    map_pressure = 14.7 + boost_psi
    boost_factor = map_pressure / 14.7
    torque_boosted = torque_na * boost_factor
    horsepower = (torque_boosted * rpm) / 5252
    return horsepower

# === Torque + HP Calculation with Boost ===
def calculate_engine_torque_hp(rpm, throttle):
    norm_rpm = max(min(rpm, MAX_RPM), IDLE_RPM)

    if norm_rpm < peak_rpm:
        torque_factor = norm_rpm / peak_rpm
    else:
        torque_factor = max(0, 1 - (norm_rpm - peak_rpm) / (MAX_RPM - peak_rpm))

    base_torque = throttle * torque_factor * max_torque

    boost_psi = calculate_boost_psi(norm_rpm, throttle)
    horsepower = calculate_engine_hp(norm_rpm, base_torque, boost_psi)
    torque_with_boost = base_torque * (1 + boost_psi / 14.7)

    return torque_with_boost, horsepower, boost_psi

# === Speed Calculation ===
def calculate_speed_kph(rpm, gear):
    gear_ratio = GEARS.get(gear, 3.214)
    if gear_ratio == 0:
        return 0
    wheel_rpm = rpm / (gear_ratio * final_drive)
    wheel_circ = tire_diameter_m * 3.1416
    speed_mps = (wheel_rpm * wheel_circ) / 60
    return speed_mps * 3.6


# == Estimate top speed ==
def estimate_top_speed():
    return round(calculate_speed_kph(MAX_RPM,6),-1)
estp=estimate_top_speed()


# === Acceleration Model ===
def calculate_acceleration(torque_nm, gear):
    gear_ratio = GEARS.get(gear, 3.214)
    if gear_ratio == 0:
        return 0
    wheel_torque = torque_nm * gear_ratio * final_drive * driveline_efficiency
    force = wheel_torque / (tire_diameter_m / 2)
    return force / car_mass

# === Speed Update ===
def update_speed(current_speed, acceleration, dt):
    return current_speed + acceleration * dt

# === Gear Shifting Logic ===
def shift_gear(new_gear, rpm, prev_gear):
    prev_ratio = GEARS.get(prev_gear, 1)
    new_ratio = GEARS.get(new_gear, 1)
    if prev_ratio == 0:
        return IDLE_RPM
    return max(IDLE_RPM, min(rpm * (new_ratio / prev_ratio), MAX_RPM))

# === Data Sender ===
def send_data_to_server(rpm: int, speed: float, temp: float, gear: int, boost: float, hp: float, torque: float, host='127.0.0.1', port=9999):
    try:
        data_str = f"{rpm},{speed:.2f},{temp},{gear},{boost:.1f},{hp:.1f},{torque:.1f}"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall(data_str.encode())
    except ConnectionRefusedError:
        print("[ERROR] Server not found")
    except Exception as e:
        print(f"[ERROR] {e}")

# === Main Loop ===
def get_throttle_and_buttons():
    turbo_release_cooldown=time.time()-1
    engine_temp = 70.0
    global gear, rpm, engine_on, peak_hp, peak_rpm_recorded, top_speed

    pygame.init()
    pygame.joystick.init()
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    sim.start()

    speed = 0
    last_time = time.time()
    prev_thr = 0
    start_timer = None
    distance = 0
    recorded_0_60 = False
    recorded_qm = False
    result_logged = False

    try:
        while True:
            now = time.time()
            dt = now - last_time
            last_time = now

            pygame.event.pump()

            if not engine_on:
                gear = 0
                rpm = 0
                speed = 0
                boost = 0
                hp = 0.0
                torque = 0.0
                send_data_to_server(rpm, speed, 0, gear, boost, hp, torque)
                os.system("cls")
                print("ENGINE OFF\nThrottle: 0%\nGear: N\nRPM: 0\nSpeed: 0.00 km/h")
                time.sleep(0.1)
                continue

            # === Throttle ===
            throttle = (-joystick.get_axis(2) + 1) / 2
            axis1=(-joystick.get_axis(1))
            if axis1 > 0.0:
                clutch=axis1
                brake=0.0
            else:
                brake=axis1
                clutch=0.0

            # === Gear Input ===
            shifted = False
            prev_gear = gear

            # === Launch Control ===
            launch_mode_active = False
            if gear == 0 and clutch > 0.95 and joystick.get_button(LAUNCH_BUTTON_INDEX):
                launch_mode_active = True
                rpm = LAUNCH_CONTROL_RPM
                throttle=0.7

            turbo_release_pressed = joystick.get_button(3)
            turbo_now=time.time()
            if turbo_release_pressed and turbo_now > turbo_release_cooldown:
                turbo_release_active = True
                boost = 0
                play_turbo_async("sounds/turbo_flutter.wav")
                turbo_release_cooldown = turbo_now + 1.0  # 1 sec cooldown
            else:
                turbo_release_active = False
                # calculate boost normally
                _, _, boost = calculate_engine_torque_hp(rpm, throttle)

            # If turbo release active, force boost=0
            if turbo_release_active:
                boost = 0

            torque, hp, _ = calculate_engine_torque_hp(rpm, throttle)
            # If turbo release active, torque is based on 0 boost
            if turbo_release_active:
                torque = throttle * max_torque * (rpm / peak_rpm) if rpm < peak_rpm else 0




            if joystick.get_button(8) and clutch > 0.7:
                if gear < 6:
                    gear += 1
                    rpm = shift_gear(gear, rpm, prev_gear)
                    shifted = True
                    time.sleep(0.2)

            if joystick.get_button(9) and clutch > 0.7:
                if gear > 0:
                    gear -= 1
                    rpm = shift_gear(gear, rpm, prev_gear)
                    shifted = True
                    time.sleep(0.2)

            # === Engine Physics ===
            torque, hp, boost = calculate_engine_torque_hp(rpm, throttle)
            acceleration = calculate_acceleration(torque, gear)

            if launch_mode_active:
                rpm = LAUNCH_CONTROL_RPM  # Maintain set RPM for launch
            elif throttle < 0.8 and not shifted:
                rpm -= (rpm - IDLE_RPM) * ((1 - throttle) * 0.2)
            else:
                rpm += torque * engine_inertia

            if clutch < 0.1:
                torque = torque
                speed = update_speed(speed, acceleration, dt)
            elif clutch < 0.7:
                torque *= (1 - clutch * 1.2)
                speed = update_speed(speed, acceleration * (1 - clutch * 1.2), dt)
            else:
                torque = 0
                speed = speed

            rpm = max(IDLE_RPM, min(rpm, MAX_RPM))
            speed = update_speed(speed, acceleration, dt)
            speed_kph = calculate_speed_kph(rpm, gear)
            distance+=(speed/3.6)*dt
            engine_temp = calculate_engine_temp(rpm, throttle, boost, speed, dt, engine_temp)
            sim.update_rpm(rpm)
            #send_data_to_server(int(rpm), speed_kph, engine_temp, gear, boost, hp, torque)



            global speed_kph_at_qm,time_0_60
            if speed_kph > 3 and start_timer is None:
                start_timer = time.time()
                recorded_0_60 = False
                recorded_qm = False
                result_logged = False
                distance = 0

            if start_timer and not recorded_0_60 and speed_kph >= 96.5:
                time_0_60 = time.time() - start_timer
                recorded_0_60 = True

            if start_timer and not recorded_qm and distance >= 402.0:
                global time_qm
                time_qm = time.time() - start_timer
                recorded_qm = True
                speed_kph_at_qm=speed_kph

            if recorded_0_60 and recorded_qm and not result_logged:
                result_logged = True

            # Reset when stopped
            if speed_kph < 2 and start_timer:
                start_timer = None
                recorded_0_60 = False
                recorded_qm = False
                result_logged = False
                distance = 0


            os.system("cls")
            print(f"TUNE MODE: {TUNE_MODE.upper()}")
            print(f"Throttle: {int(throttle * 100)}%")
            print(f"RPM: {int(rpm)}")
            print(f"Speed: {speed_kph:.2f} km/h")
            print(f"Gear: {gear}")
            print(f"Horsepower: {hp:.2f} HP")
            print(f"Torque: {torque:.2f} Nm")
            print(f"Boost: {boost:.1f} PSI")
            print(f"Clutch: {clutch} | {clutch*100}%")
            print(f"Brake: {brake} | {brake*100}%")
            

            if rpm > peak_rpm_recorded:
                peak_rpm_recorded = rpm
            if speed_kph > top_speed:
                top_speed = speed_kph
            if hp > peak_hp:
                peak_hp = hp

            prev_thr = throttle
            time.sleep(0.05)

    except KeyboardInterrupt:
        pygame.quit()
    finally:
        pygame.quit()
        sim.stop()
        log()

# === Entry Point ===
if __name__ == "__main__":
    engine_on = True
    get_throttle_and_buttons()
def play_turbo_async(sound_file):
    threading.Thread(target=play_turbo, args=(sound_file,), daemon=True).start()