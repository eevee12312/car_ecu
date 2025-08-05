import pygame
import time
import threading
import socket
import os
from datetime import datetime
from engine_sound_mine import play_turbo, EngineSoundSimulator, OtherEngineSoundSimulator

import json
import sys
import numpy as np
import matplotlib.pyplot as plt
import subprocess










class EngineTuneMap2D:
    def __init__(self, rpm_points, map_psi_points):
        self.rpm_points = np.array(rpm_points)
        self.map_psi_points = np.array(map_psi_points)

        self.ve_grid = np.ones((len(map_psi_points), len(rpm_points))) * 0.7
        self.afr_grid = np.ones((len(map_psi_points), len(rpm_points))) * 14.7
        self.boost_target_grid = np.zeros((len(map_psi_points), len(rpm_points)))
        self.thermal_grid = np.zeros((len(map_psi_points), len(rpm_points)))

        for i, psi in enumerate(map_psi_points):
            for j, rpm in enumerate(rpm_points):
                # VE Map
                base_ve = 0.5 + 0.5 * np.exp(-((rpm - 4500) / 2000) ** 2)
                boost_factor = 1 - 0.015 * (psi - 5)
                self.ve_grid[i, j] = np.clip(base_ve * boost_factor, 0.4, 1.0)

                # AFR Map
                base_afr = 14.7
                boost_enrichment = max(0, psi - 0) * 0.25
                afr = base_afr - boost_enrichment
                if rpm > 6000:
                    afr -= (rpm - 6000) / 3000 * 0.5
                self.afr_grid[i, j] = np.clip(afr, 10.0, 14.7)

                # Boost Target Map
                rpm_factor = np.exp(-((rpm - 4500) / 2500) ** 2)
                psi_factor = np.clip((psi - 5) / 25.0, 0, 1.0)
                boost_target = 1.0 + 2.0 * psi_factor * rpm_factor
                self.boost_target_grid[i, j] = np.clip(boost_target, 0.0, 3.0)

                # Thermal Load Map (scaled VE * boost^2 approximation)
                boost_abs = max(psi, 0)  # treat vacuum as zero
                thermal_load = base_ve * (1 + 0.1 * boost_abs ** 2) * (rpm / max(rpm_points))
                self.thermal_grid[i, j] = np.clip(thermal_load, 0.0, 2.0)

    def _bilinear_interpolate(self, grid, x_points, y_points, x, y):
        x = np.clip(x, x_points[0], x_points[-1])
        y = np.clip(y, y_points[0], y_points[-1])

        x_idx = np.searchsorted(x_points, x) - 1
        y_idx = np.searchsorted(y_points, y) - 1

        x_idx = np.clip(x_idx, 0, len(x_points) - 2)
        y_idx = np.clip(y_idx, 0, len(y_points) - 2)

        x_frac = (x - x_points[x_idx]) / (x_points[x_idx + 1] - x_points[x_idx])
        y_frac = (y - y_points[y_idx]) / (y_points[y_idx + 1] - y_points[y_idx])

        v00 = grid[y_idx, x_idx]
        v10 = grid[y_idx, x_idx + 1]
        v01 = grid[y_idx + 1, x_idx]
        v11 = grid[y_idx + 1, x_idx + 1]

        v0 = v00 + x_frac * (v10 - v00)
        v1 = v01 + x_frac * (v11 - v01)

        return v0 + y_frac * (v1 - v0)

    def get_ve(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        return self._bilinear_interpolate(self.ve_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def get_afr(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        return self._bilinear_interpolate(self.afr_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def get_target_boost_psi(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        return self._bilinear_interpolate(self.boost_target_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def get_thermal_load(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        return self._bilinear_interpolate(self.thermal_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def to_json(self):
        return json.dumps({
            'rpm_points': self.rpm_points.tolist(),
            'map_psi_points': self.map_psi_points.tolist(),
            've_grid': self.ve_grid.tolist(),
            'afr_grid': self.afr_grid.tolist(),
            'boost_grid': self.boost_target_grid.tolist(),
            'thermal_grid': self.thermal_grid.tolist()
        }, indent=2)

    def from_json(self, json_str):
        data = json.loads(json_str)
        self.rpm_points = np.array(data['rpm_points'])
        self.map_psi_points = np.array(data['map_psi_points'])
        self.ve_grid = np.array(data['ve_grid'])
        self.afr_grid = np.array(data['afr_grid'])
        self.boost_target_grid = np.array(data['boost_grid'])
        self.thermal_grid = np.array(data['thermal_grid'])




def psi_to_kpa(psi):
    return 101.3 + psi * 6.89476

# === Example: Load VE map from file or use default ===



# Options: "stock", "upgraded"
TUNE_MODE = "race"  # Change this to select different tunes

TUNES = {
    "stock": {  # Top speed ~276 km/h
        "MAX_RPM": 7000,
        "IDLE_RPM": 800,
        "final_drive": 3.7,
        "tire_diameter_m": 0.62,  # ~245/40R20
        "driveline_efficiency": 0.78,
        "engine_inertia": 0.35,
        "car_mass": 1740,
        "GEARS": {
            0: 0,
            1: 4.06,
            2: 2.30,
            3: 1.59,
            4: 1.25,
            5: 1.00,
            6: 0.80
        },
        "peak_rpm": 4800,
        "red_line": 5800,
        "max_boost": 17.0,  # psi
        "max_torque": 652,  # Nm (Stock VR38DETT in Nismo trim)
        "tune":r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\factory_tune.json",
        "engine_name": "VR38DETT",
        "frontal_area": 2.2,  # m^2, typical for a sports car
        
    },

    "stage2": {  # ECU + turbo back exhaust tune top speed 315
        "MAX_RPM": 8000,
        "IDLE_RPM": 850,
        "final_drive": 3.7,
        "tire_diameter_m": 0.62,
        "driveline_efficiency": 0.8,
        "engine_inertia": 0.32,
        "car_mass": 1720,
        "GEARS": {
            0: 0,
            1: 4.06,
            2: 2.30,
            3: 1.59,
            4: 1.25,
            5: 1.00,
            6: 0.80
        },
        "peak_rpm": 5200,
        "red_line": 6500,
        "max_boost": 22.0,
        "max_torque": 720,
        "tune":r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\stage2_tune.json",
        "engine_name": "VR38DETT",
        "frontal_area": 2.2,  # m^2, typical for a sports car
    },

    "race": {  #top speed 381
        "MAX_RPM": 9200,
        "IDLE_RPM": 1100,
        "final_drive": 3.9,
        "tire_diameter_m": 0.60,  # semi-slicks or drag radials
        "driveline_efficiency": 0.85,
        "engine_inertia": 0.28,
        "car_mass": 1680,
        "GEARS": {
            0: 0,
            1: 3.90,
            2: 2.20,
            3: 1.55,
            4: 1.20,
            5: 0.95,
            6: 0.70
        },
        "peak_rpm": 6000,
        "red_line": 7500,
        "max_boost": 33.0,
        "max_torque": 850,
        "tune":r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\race_tune.json",
        "engine_name": "VR38DETT",
        "frontal_area": 2.2,  # m^2, typical for a sports car
    },
    "lfa": {
        "MAX_RPM": 9500,
        "IDLE_RPM": 900,
        "final_drive": 3.42,
        "tire_diameter_m": 0.5,  # wider tires for drag
        "driveline_efficiency": 0.9,
        "engine_inertia": 0.55,
        "car_mass": 1480,
        "GEARS": {
            0: 0,
            1: 3.23,
            2: 2.19,
            3: 1.61,
            4: 1.23,
            5: 0.97,
            6: 0.80
        },
        "peak_rpm": 5800,
        "red_line": 8500,
        "max_boost": 33.0,
        "max_torque": 480,
        "tune":r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\lfa_tune.json",
        "engine_name": "lfa",
        "frontal_area": 2.0,  # m^2, typical for a sports car
    },
    "hayabusa": {
        "MAX_RPM": 11750,
        "IDLE_RPM": 900,
        "final_drive": 2.389,
        "tire_diameter_m": 0.5,
        "driveline_efficiency": 0.99,
        "engine_inertia": 0.65,
        "car_mass": 220,
        "GEARS": {
            0: 0,
            1: 2.615,
            2: 1.938,
            3: 1.526,
            4: 1.286,
            5: 1.136,
            6: 1.043
        },
        "red_line": 9000,
        "peak_rpm": 7000,
        "max_boost": 33.0,  # No boost for NA engine
        "max_torque": 500,
        "tune":r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\lfa_tune.json",
        "engine_name": "hayabusa",
        "frontal_area": 0.8,  # m^2, typical for a motorcycle
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
red_line = tune["red_line"]
tune_path=tune['tune']
frontal_area=tune["frontal_area"]
engine_name = tune["engine_name"]
LAUNCH_CONTROL_RPM = 4500  # Launch RPM setpoint
LAUNCH_BUTTON_INDEX = 0    # Button 0 for launch control
logged = False
air_density = 1.225  # kg/m^3 at sea level, 15°C
gravity = 9.81  # m/s^2

global peak_hp, peak_rpm_recorded, top_speed
peak_rpm_recorded = 0
top_speed = 0
peak_hp = 0
sim = EngineSoundSimulator("sounds/engine_idle.wav")
engine = OtherEngineSoundSimulator()
car_profile=tune
# === Engine State ===
rpm = IDLE_RPM
gear = 0
engine_on = False

def generate_rpm_points(idle_rpm, max_rpm, step=700):
    return np.arange(idle_rpm, max_rpm + 1, step)
# === Constants for RPM and MAP axis points (for VE map) ===
RPM_POINTS = generate_rpm_points(IDLE_RPM, MAX_RPM)
MAP_PSI_POINTS = np.array([0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 32.5, 35]) 




VE_MAP_FILE = tune_path
ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
try:
    with open(VE_MAP_FILE, "r") as f:
        json_str = f.read()
    ve_map.from_json(json_str)
except FileNotFoundError:
    pass


function_map = {
    "ve_map.get_ve": lambda rpm, map_kpa, ve_map: ve_map.get_ve(rpm, map_kpa),
    "ve_map.get_afr": lambda rpm, map_kpa, ve_map: ve_map.get_afr(rpm, map_kpa),
    "ve_map.get_thermal_load": lambda rpm, map_kpa, ve_map: ve_map.get_thermal_load(rpm, map_kpa),
    "custom_boost_curve": lambda rpm, ve_map: custom_boost_curve(rpm, ve_map),
    "custom_boost_pressure": lambda rpm: custom_boost_pressure(rpm),
    "custom_ignition_efficiency": lambda rpm: custom_ignition_efficiency(rpm),
}



def load_engine_config(engine_name, ve_map: EngineTuneMap2D):
    with open(r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\engine_profiles.json", "r") as f:
        raw_config=json.load(f)[engine_name]
    config = {}
    for key, value in raw_config.items():
        if isinstance(value, str) and value.startswith("function:"):
            func_name=value[len("function:"):]
            if func_name not in function_map:
                raise ValueError(f"Function '{func_name}' not found in function_map")
            
            if "ve_map" in func_name:
                # If the function also needs map_kpa as input
                if "map_kpa" in function_map[func_name].__code__.co_varnames:
                    config[key] = lambda rpm, map_kpa, fn=function_map[func_name]: fn(rpm, map_kpa, ve_map)
                else:
                    # Only rpm and ve_map
                    config[key] = lambda rpm, fn=function_map[func_name]: fn(rpm, ve_map)
            else:
                # Just use the function as-is (no ve_map needed)
                config[key] = function_map[func_name]
        else:
            # Regular value, store directly
            config[key] = value

    return config


def custom_boost_curve(rpm, ve_map):
    return np.interp(rpm, ve_map.rpm_points, [ve_map.map_psi_points[-1]] * len(ve_map.rpm_points))

def custom_boost_pressure(rpm):
    return 101.3 + 100 * np.clip((rpm - 2500) / 4000, 0, 1)

def custom_ignition_efficiency(rpm):
    return 1.00 - 0.10 * np.exp(-((rpm - 6000)/800)**2)

config= load_engine_config(engine_name, ve_map)

def log():
    msg = f"========\nTune:{TUNE_MODE}\nPeak RPM: {peak_rpm_recorded}\nTop Speed:{top_speed}\nPeak HorsePower: {peak_hp}\n0-60 mph: {time_0_60:.2f} s\n1/4 Mile: {time_qm:.2f} s, Speed: {speed_kph_at_qm:.1f}\n========\n"
    #with open("log.txt", 'a') as file:
    #    file.write(msg)
def calculate_airflow(rpm, boost_psi, ve_map=ve_map):
    map_kpa = psi_to_kpa(boost_psi) 
    ve = config['volumetric_efficiency'](rpm, map_kpa)
    displacement_m3 = config['displacement_l'] / 1000
    air_density = config['air_density']
    airflow = (ve * displacement_m3 * rpm * air_density) / (2 * 60) 
    return airflow  

# === Engine Temp Calculation ===
def calculate_engine_temp(rpm, throttle, boost_psi, speed, dt, engine_temp=70.0):
    ambient_temp = 24.0
    heating_rate = (rpm / MAX_RPM) * throttle * (1 + boost_psi / 14.7) * 20
    cooling_rate = (speed / 200) * 10 + 5

    temp_change = heating_rate - cooling_rate
    engine_temp += temp_change * dt
    engine_temp = max(ambient_temp, min(engine_temp, 120.0))
    return engine_temp

# --- Boost Calculation (Simplified for real-time simulation) ---
def calculate_boost_psi_interactive(rpm, throttle):
    if rpm < config['spool_rpm']:
        return 0
    ramp_factor = np.clip((rpm - config['spool_rpm']) / (config['full_boost_rpm'] - config['spool_rpm']), 0, 1)
    target_boost = config['max_boost_psi'] * throttle 
    return target_boost * ramp_factor

# --- Torque + HP Calculation with Boost and VE Map ---
def calculate_engine_torque_hp(rpm, throttle, boost_psi_input=None, ve_map=ve_map):
    if boost_psi_input is None:
        boost_psi = calculate_boost_psi_interactive(rpm, throttle)
    else:
        boost_psi = boost_psi_input
        
    map_kpa = psi_to_kpa(boost_psi)
    
    ve = config['volumetric_efficiency'](rpm, map_kpa)
    afr = config['afr'](rpm, map_kpa)
    thermal_eff = config['thermal_efficiency'](rpm, map_kpa)

    airflow = calculate_airflow(rpm, boost_psi, ve_map)
    
    if afr == 0:
        fuel_air_ratio = 0
    else:
        fuel_air_ratio = 1 / afr
    fuel_flow_kg_s = airflow * fuel_air_ratio

    fuel_energy_j = config['fuel_energy_mj'] * 1_000_000  
    power_watts = fuel_flow_kg_s * fuel_energy_j * thermal_eff

    # === ADDED: FRICTION AND PARASITIC LOSSES ===
    c0 = 1000 
    c1 = 0.5  
    c2 = 0.00005 
    c3 = 0.00000000005 
    
    friction_power_watts = c0 + (c1 * rpm) + (c2 * rpm**2) + (c3 * rpm**3)
    
    power_watts -= friction_power_watts
    power_watts = max(0, power_watts)



    if rpm > 0:
        torque=((power_watts/1000)/rpm)*9550
    else:
        torque = 0

    horsepower = (torque * rpm) / 7127
    torque *= throttle

    return torque, horsepower, boost_psi,power_watts

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
    return round(calculate_speed_kph(MAX_RPM, 6), -1)
estp = estimate_top_speed()

# === Acceleration Model ===
def calculate_acceleration(torque_nm, gear,rpm,speed):
    gear_ratio = GEARS.get(gear, 3.214)
    if gear_ratio == 0:
        return 0
    wheel_torque = torque_nm * gear_ratio * final_drive * driveline_efficiency
    force = wheel_torque / (tire_diameter_m / 2)
    drag_force=0.5*air_density*0.32*frontal_area* speed**2
    rolling_resistance = 0.015 * car_mass * gravity
    total_resistance = drag_force + rolling_resistance

    net_force = force - total_resistance
    net_force = max(0, net_force)  # No negative force

    acceleration=net_force/car_mass
    return acceleration

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

def play_turbo_async(sound_file):
    threading.Thread(target=play_turbo, args=(sound_file,), daemon=True).start()

def save_car_profile(car_profile):
    with open(r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\car_profile.json", "w") as f:
        json.dump(car_profile, f, indent=2)
    
def open_ve_map():
    save_car_profile(car_profile)
    subprocess.Popen(["python", r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\dyno.py"])






def get_throttle_and_buttons():
    turbo_release_cooldown = time.time() - 1
    engine_temp = 70.0
    global gear, rpm, engine_on, peak_hp, peak_rpm_recorded, top_speed

    pygame.init()
    pygame.joystick.init()
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    sim.start()
    engine.start()
    peak_torque=0
    peak_hp_recorded=0
    peak_hp_rpm=0
    peak_torque_rpm=0

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
                print(f"Tune: {TUNE_MODE} |Throttle: {throttle:.2f} | Clutch: {clutch:.2f}")
                print(f"Gear: {gear if gear > 0 else 'N'} | RPM: {int(rpm):>4} | Boost: {boost:>4.1f} PSI | m/s: {speed:.2f}")
                print(f"Speed: {speed_kph:.1f} km/h | Temp: {engine_temp:>5.1f} °C | Estimated Top Speed: {estp:.1f} km/h")
                print(f"Torque: {torque:>6.1f} Nm  | HP: {hp:>6.1f} | Top Speed: {top_speed:>6.2f} km/h")
                print(f"Peak RPM: {peak_rpm_recorded} | Peak HP: {peak_hp:.1f} | Distance: {distance:.2f} m")
                print(f"Peak Speed: {top_speed:.1f} km/h | Peak Torque: {max_torque:.1f} Nm")
                print(f"VE: {ve_map.get_ve(rpm, psi_to_kpa(boost)):.2f} | Boost: {boost:.1f} PSI")
                sim.stop()
                time.sleep(0.1)
                continue

            # === Throttle ===
            throttle = (-joystick.get_axis(2) + 1) / 2
            clutch = (-joystick.get_axis(1))

            # === Gear Input ===
            shifted = False
            prev_gear = gear

            # === Launch Control ===
            launch_mode_active = False
            if gear == 0 and clutch > 0.95 and joystick.get_button(LAUNCH_BUTTON_INDEX):
                launch_mode_active = True
                rpm = LAUNCH_CONTROL_RPM
                throttle = 0.7

            turbo_release_pressed = joystick.get_button(3)
            turbo_now = time.time()
            if turbo_release_pressed and turbo_now > turbo_release_cooldown:
                turbo_release_active = True
                boost = 0
                play_turbo_async("sounds/turbo_flutter.wav")
                turbo_release_cooldown = turbo_now + 1.0  # 1 sec cooldown
            else:
                turbo_release_active = False
                # calculate boost normally
                _, _, boost,_ = calculate_engine_torque_hp(rpm, throttle)

            # If turbo release active, force boost=0
            if turbo_release_active:
                boost = 0

            torque, hp, _,power = calculate_engine_torque_hp(rpm, throttle)
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
            torque, hp, boost,power = calculate_engine_torque_hp(rpm, throttle)
            acceleration = calculate_acceleration(torque, gear,rpm,speed)

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
            speed_kph=calculate_speed_kph(rpm, gear)
            distance += (speed_kph / 3.6) * dt
            engine_temp = calculate_engine_temp(rpm, throttle, boost, speed, dt, engine_temp)
            sim.update_rpm(rpm)
            engine.set_rpm(rpm)

            global speed_kph_at_qm, time_0_60
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
                speed_kph_at_qm = speed_kph

            if recorded_0_60 and recorded_qm and not result_logged:
                result_logged = True

            # Reset when stopped
            if speed_kph < 2 and start_timer:
                start_timer = None
                recorded_0_60 = False
                recorded_qm = False
                result_logged = False
                distance = 0

            if peak_torque < torque:
                peak_torque=torque
                peak_torque_rpm=rpm
            if peak_hp_recorded < hp:
                peak_hp_recorded=hp
                peak_hp_rpm=rpm

            os.system("cls")
            print(f"Tune: {TUNE_MODE} |Throttle: {throttle:.2f} | Clutch: {clutch:.2f}")
            print(f"Gear: {gear if gear > 0 else 'N'} | RPM: {int(rpm):>4} | Boost: {boost:>4.1f} PSI | m/s: {(speed):.2f}")
            print(f"Speed: {speed_kph:.1f} km/h | Temp: {engine_temp:>5.1f} °C | Estimated Top Speed: {estp:.1f} km/h | Power: {power:.1f} W")
            print(f"Torque: {torque:>6.1f} Nm  | HP: {hp:>6.1f} | Peak Torque: {peak_torque:.2f} at {peak_torque_rpm:.1f} RPM | Peak Hp: {peak_hp_recorded:.2f} at {peak_hp_rpm:.1f} RPM")
            print(f"VE: {ve_map.get_ve(rpm, psi_to_kpa(boost)):.2f} | Boost: {ve_map.get_target_boost_psi(rpm,psi_to_kpa(boost)):.1f} : {boost} PSI | AFR: {ve_map.get_afr(rpm, psi_to_kpa(boost)):.2f}")
            print(f"Airflow: {calculate_airflow(rpm,boost):.2f} | Thermal efficiency: {ve_map.get_thermal_load(rpm,psi_to_kpa(boost)):.2f} | acceleration: {acceleration:.2f} m/s²")
            send_data_to_server(int(rpm), speed_kph, engine_temp, gear, boost, hp, torque)

            if result_logged:
                print(f"0-60 mph: {time_0_60:.2f} s | 1/4 mi: {time_qm:.2f} s @ {speed_kph_at_qm:.1f} km/h")

            if rpm > peak_rpm_recorded:
                peak_rpm_recorded = rpm
            if speed_kph > top_speed:
                top_speed = speed_kph
            if hp > peak_hp:
                peak_hp = hp

            prev_thr = throttle
            time.sleep(0.05)

    except Exception as e:
        timestamp = time.time()
        date = datetime.fromtimestamp(timestamp)
        with open("errors.txt", 'a') as error_log:
            error_log.write(f"{date.strftime('%H:%M:%S %d/%m/%y')} : {e}")
    finally:
        pygame.quit()
        sim.stop()
        engine.stop()
        log()






# === Entry Point ===
if __name__ == "__main__":
    engine_on = True
    get_throttle_and_buttons()
