import sys
import json
import numpy as np
import matplotlib.pyplot as plt
import math
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QHBoxLayout, QPushButton, QFileDialog, QLabel, QMessageBox,QHeaderView,QGridLayout
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import (needed for 3D)
from matplotlib import cm


# === Constants for RPM and MAP axis points ===
RPM_POINTS = np.arange(800, 11201, 400)  # RPM points (28 columns)
MAP_PSI_POINTS = np.array([ 90, 150, 210, 270, 330, 390, 450, 510, 570, 630, 690, 750, 800]) # MAP kpa points (13 rows)







def psi_to_kpa(psi):
    return 101.3 + psi * 6.89476

# === VE Map class ===

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
        return self._bilinear_interpolate(self.ve_grid, self.rpm_points, self.map_psi_points, rpm, map_kpa)

    def get_afr(self, rpm, map_kpa):
        return self._bilinear_interpolate(self.afr_grid, self.rpm_points, self.map_psi_points, rpm, map_kpa)

    def get_target_boost_psi(self, rpm, map_kpa):
        return self._bilinear_interpolate(self.boost_target_grid, self.rpm_points, self.map_psi_points, rpm, map_kpa)

    def get_thermal_load(self, rpm, map_kpa):
        return self._bilinear_interpolate(self.thermal_grid, self.rpm_points, self.map_psi_points, rpm, map_kpa)

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
        self.map_psi_points = np.array(data['map_kpa_points'])
        self.ve_grid = np.array(data['ve_grid'])
        self.afr_grid = np.array(data['afr_grid'])
        self.boost_target_grid = np.array(data['boost_grid'])
        self.thermal_grid = np.array(data['thermal_grid'])





# === Engine config tuned style using the VEMap2D instance ===
function_map = {
    "ve_map.get_ve": lambda rpm, map_kpa, ve_map: ve_map.get_ve(rpm, map_kpa),
    "ve_map.get_afr": lambda rpm, map_kpa, ve_map: ve_map.get_afr(rpm, map_kpa),
    "ve_map.get_thermal_load": lambda rpm, map_kpa, ve_map: ve_map.get_thermal_load(rpm, map_kpa),
    "custom_boost_curve": lambda rpm, ve_map: custom_boost_curve(rpm, ve_map),
    "ve_map.get_target_boost_psi": lambda rpm, map_kpa, ve_map: ve_map.get_target_boost_psi(rpm, map_kpa),
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


ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
# === Dyno simulation function uses engine_config_tuned ===
def calculate_airflow(rpm, boost_psi, ve_map=ve_map):
    map_kpa = boost_psi
    ve = config['volumetric_efficiency'](rpm, map_kpa)
    displacement_m3 = config['displacement_l'] / 1000
    air_density = config['air_density']
    airflow = (ve * displacement_m3 * rpm * air_density) / (2 * 60) 
    return airflow 

def calculate_thermal_efficiency(rpm, afr,boost):
    # Engine parameters
    redline_rpm = 7000
    peak_eff_rpm = 0.4 * redline_rpm  # Most efficient at ~2800 RPM
    max_efficiency = 0.40  # Realistic max for performance gasoline engine
    
    # RPM efficiency curve (Gaussian falloff)
    rpm_eff = max_efficiency * np.exp(-((rpm - peak_eff_rpm) / 1800) ** 2)
    
    # AFR penalty
    afr_optimal = ve_map.get_afr(rpm,boost)
    afr_penalty_factor = 0.12  # Higher penalty for off-stoich
    afr_penalty = afr_penalty_factor * abs(afr - afr_optimal) / afr_optimal
    
    # Final efficiency calculation
    efficiency = rpm_eff - afr_penalty
    return np.clip(efficiency, 0.20, max_efficiency)  # Clamp to realistic rang
# === Engine Temp ===
def calculate_engine_temp(rpm, throttle, boost_psi, speed, dt, engine_temp=70.0):
    ambient_temp = 24.0
    heating_rate = (rpm / car_profile['MAX_RPM']) * throttle * (1 + boost_psi / 14.7) * 20
    cooling_rate = (speed / 200) * 10 + 5

    temp_change = heating_rate - cooling_rate
    engine_temp += temp_change * dt
    engine_temp = max(ambient_temp, min(engine_temp, 120.0))

    return engine_temp

# === Boost Calculation ===
def calculate_boost_psi_interactive(rpm, throttle):
    if rpm < config['spool_rpm']:
        return 0
    ramp_factor = np.clip((rpm - config['spool_rpm']) / (config['full_boost_rpm'] - config['spool_rpm']), 0, 1)
    max_boost_kpa = psi_to_kpa(config['max_boost_psi'])
    target_boost = max_boost_kpa * throttle 
    return target_boost * ramp_factor

def calculate_engine_torque_hp(rpm, throttle, boost_psi_input=None, ve_map=ve_map):
    if boost_psi_input is None:
        boost_psi = calculate_boost_psi_interactive(rpm, throttle)
    else:
        boost_psi = boost_psi_input
        
    map_kpa = boost_psi
    
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








def simulate_dyno(car, engine, shift_rpms, ve_map):
    """
    Simulate dyno run with gear shifting using realistic VE, boost, torque, thermal, and airflow models.

    Args:
        car: dict with car parameters including 'GEARS', 'final_drive', 'IDLE_RPM', 'red_line', 'tire_diameter_m'
        engine: dict with engine parameters and functions
        shift_rpms: list of shift RPMs for each gear (length = num_gears - 1)
        ve_map: VE map object with get_ve(rpm, boost_psi)

    Returns:
        Arrays: rpm, torque, horsepower, speed_kph, ve, boost_psi, ignition_efficiency, thermal_efficiency, gear, engine_temp
    """

    # Setup
    engine['rpm_step'] = 50
    dt = 0.1
    throttle = 1.0  # Wide open throttle
    engine_temp = 70.0  # Initial engine temp

    # Accumulators
    all_rpm = []
    all_torque = []
    all_hp = []
    all_speed_kph = []
    all_ve = []
    all_boost_psi = []
    all_ign_eff = []
    all_therm_eff = []
    all_gears = []
    all_engine_temp = []

    num_gears = len(car['GEARS']) - 1

    for gear_idx in range(num_gears):
        gear = gear_idx + 1
        gear_ratio = car['GEARS'][str(gear)]
        final_drive = car['final_drive']

        # RPM Range
        rpm_start = car['IDLE_RPM'] if gear_idx == 0 else shift_rpms[gear_idx - 1]
        rpm_end = min(shift_rpms[gear_idx], car['red_line']) if gear_idx < len(shift_rpms) else car['red_line']
        if rpm_end <= rpm_start:
            rpm_end = car['red_line']
        rpm_values = np.arange(rpm_start, rpm_end + engine['rpm_step'], engine['rpm_step'], dtype=np.float64)


        wheel_rpm = rpm_values / (gear_ratio * final_drive)
        tire_circumference_m = 2 * math.pi * (car['tire_diameter_m'] / 2)
        speed_mps = wheel_rpm * tire_circumference_m / 60.0
        speed_kph = speed_mps * 3.6

        # Per-RPM calculations
        torque = []
        hp = []
        ve = []
        ign_eff = []
        therm_eff = []
        temp_log = []
        boost=[]

        for i, rpm in enumerate(rpm_values):
            tq, hp_val, psi,_ = calculate_engine_torque_hp(rpm, throttle)
            v = ve_map.get_ve(rpm, psi)
            afr = config['afr'](rpm, psi)
            therm = calculate_thermal_efficiency(rpm, afr,psi)
            ign = engine['ignition_efficiency'](rpm)
            speed = speed_kph[i]
            engine_temp = calculate_engine_temp(rpm, throttle, psi, speed, dt, engine_temp)

            torque.append(tq)
            hp.append(hp_val)
            ve.append(v)
            boost.append(psi)
            ign_eff.append(ign)
            therm_eff.append(therm)
            temp_log.append(engine_temp)

        # Append gear segment data
        all_rpm.append(rpm_values)
        all_torque.append(torque)
        all_hp.append(hp)
        all_speed_kph.append(speed_kph)
        all_ve.append(ve)
        all_boost_psi.append(boost)
        all_ign_eff.append(ign_eff)
        all_therm_eff.append(therm_eff)
        all_engine_temp.append(temp_log)
        all_gears.append(np.full_like(rpm_values, gear, dtype=int))

    # Concatenate all gear data
    return (
        np.concatenate(all_rpm),
        np.concatenate(all_torque),
        np.concatenate(all_hp),
        np.concatenate(all_speed_kph),
        np.concatenate(all_ve),
        np.concatenate(all_boost_psi),
        np.concatenate(all_ign_eff),
        np.concatenate(all_therm_eff),
        np.concatenate(all_gears),
        np.concatenate(all_engine_temp)
    )


# === Plot function ===
def plot_dyno(rpm, tq, hp, speed, ve, boost, ign_eff, therm_eff, gears, afr=None):
    arrays = [rpm, tq, hp, speed, ve, boost, ign_eff, therm_eff, gears]
    if afr is not None:
        arrays.append(afr)

    min_len = min(map(len, arrays))

    rpm = rpm[:min_len]
    tq = tq[:min_len]
    hp = hp[:min_len]
    speed = speed[:min_len]
    ve = ve[:min_len]
    boost = boost[:min_len]
    ign_eff = ign_eff[:min_len]
    therm_eff = therm_eff[:min_len]
    gears = gears[:min_len]
    if afr is not None:
        afr = afr[:min_len]
    throttle = np.linspace(0, 1, min_len)

    plt.style.use('dark_background')
    fig, axs = plt.subplots(5, 1, figsize=(16, 18), sharex=True)
    fig.suptitle("Rolling Road Dyno – VR38DETT Engine Simulation", fontsize=18, y=0.95)

    # Torque and HP
    axs[0].plot(rpm, tq, label='Torque (Nm)', color='orange', linewidth=3)
    axs[0].plot(rpm, hp, label='Horsepower (HP)', color='deepskyblue', linewidth=3)
    axs[0].fill_between(rpm, tq, color='orange', alpha=0.15)
    axs[0].fill_between(rpm, hp, color='deepskyblue', alpha=0.15)
    axs[0].set_ylabel("Torque / HP", fontsize=12)
    axs[0].legend(loc='upper left')
    axs[0].grid(True, linestyle='--', alpha=0.3)

    # Mark peak torque and HP on this subplot
    peak_torque_idx = np.argmax(tq)
    peak_hp_idx = np.argmax(hp)
    axs[0].annotate(f'Peak Torque\n{tq[peak_torque_idx]:.1f} Nm @ {rpm[peak_torque_idx]:.0f} RPM',
                    xy=(rpm[peak_torque_idx], tq[peak_torque_idx]),
                    xytext=(rpm[peak_torque_idx] + 500, tq[peak_torque_idx] + 20),
                    arrowprops=dict(facecolor='orange', shrink=0.05),
                    color='orange', fontsize=10)
    axs[0].annotate(f'Peak HP\n{hp[peak_hp_idx]:.1f} HP @ {rpm[peak_hp_idx]:.0f} RPM',
                    xy=(rpm[peak_hp_idx], hp[peak_hp_idx]),
                    xytext=(rpm[peak_hp_idx] + 500, hp[peak_hp_idx] + 20),
                    arrowprops=dict(facecolor='deepskyblue', shrink=0.05),
                    color='deepskyblue', fontsize=10)

    # Boost and VE
    axs[1].plot(rpm, boost, label='Boost (kPa)', color='red', linestyle='-.', linewidth=2.5)
    axs[1].plot(rpm, ve * 100, label='VE (%)', color='magenta', linestyle=':', linewidth=2.5)
    axs[1].fill_between(rpm, 0, boost, color='red', alpha=0.07)
    axs[1].set_ylabel("Boost / VE (%)", fontsize=12)
    axs[1].legend(loc='upper left')
    axs[1].grid(True, linestyle='--', alpha=0.3)

    # Efficiency
    axs[2].plot(rpm, ign_eff * 100, label='Ign. Eff. (%)', color='yellow', linestyle='--', linewidth=2.5)
    axs[2].plot(rpm, therm_eff * 100, label='Thermal Eff. (%)', color='lime', linestyle='-', linewidth=2.5)
    axs[2].set_ylabel("Efficiency (%)", fontsize=12)
    axs[2].legend(loc='upper left')
    axs[2].grid(True, linestyle='--', alpha=0.3)

    # AFR if available
    if afr is not None:
        axs[3].plot(rpm, afr, label='AFR', color='cyan', linewidth=2)
        axs[3].axhline(14.7, color='white', linestyle='--', alpha=0.5, label='Stoich AFR')
        axs[3].set_ylabel("Air Fuel Ratio", fontsize=12)
        axs[3].set_ylim(9, 16)
        axs[3].legend(loc='upper right')
        axs[3].grid(True, linestyle='--', alpha=0.3)
    else:
        axs[3].axis('off')  # Hide if no AFR data

    # Speed and Throttle
    axs[4].plot(rpm, speed, label='Speed (km/h)', color='dodgerblue', linewidth=2.5)
    axs[4].plot(rpm, throttle * 100, label='Throttle (%)', color='white', linestyle='--', linewidth=2)
    axs[4].set_xlabel("Engine RPM", fontsize=12)
    axs[4].set_ylabel("Speed / Throttle", fontsize=12)
    axs[4].legend(loc='upper left')
    axs[4].grid(True, linestyle='--', alpha=0.3)

    # Annotate gear changes on speed plot
    prev_gear = None
    for idx, gear in enumerate(gears):
        if gear != prev_gear:
            rpm_val = rpm[idx]
            speed_val = speed[idx]
            axs[4].annotate(f'Gear {gear}', xy=(rpm_val, speed_val), xycoords='data',
                            xytext=(rpm_val + 200, speed_val + 5),
                            textcoords='data', arrowprops=dict(arrowstyle='-|>'),
                            fontsize=10, color='yellow', fontweight='bold')
            prev_gear = gear

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show()
    plt.savefig(r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\dyno.png")
    print(f"Horsepower: {hp.max():.2f} HP at {rpm[np.argmax(hp)]:.0f} RPM")
    print(f"Peak Torque: {tq.max():.2f} Nm at {rpm[np.argmax(tq)]:.0f} RPM")







# === VEMapEditor GUI ===
class VEMapEditor(QWidget):
    def __init__(self, ve_map):
        super().__init__()
        self.ve_map = ve_map
        self.setWindowTitle("VE Map Editor (RPM x MAP psi)")
        self.resize(2400, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel("Edit Volumetric Efficiency (VE) values (%) - RPM (cols) vs MAP (psi) (rows)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self.table = QTableWidget(len(ve_map.map_psi_points), len(ve_map.rpm_points))
        self.table.setHorizontalHeaderLabels([str(int(rpm)) for rpm in ve_map.rpm_points])
        # Invert psi points for vertical header so lower psi is at the bottom
        self.table.setVerticalHeaderLabels([str(int(psi)) for psi in ve_map.map_psi_points[::-1]])
        layout.addWidget(self.table)

        self.load_ve_map_to_table()

        btn_layout = QGridLayout()
        self.btn_save = QPushButton("Save VE Map")
        self.btn_load = QPushButton("Load VE Map")
        self.btn_show_afr_3d = QPushButton("Show 3D AFR Map")
        self.btn_show_3d = QPushButton("Show 3D VE Map")
        self.btn_show_afr = QPushButton("Show AFR Map")
        self.btn_show_ve_map = QPushButton("Show VE Map")
        btn_layout.addWidget(self.btn_show_3d,0, 0)
        btn_layout.addWidget(self.btn_save, 0, 1)
        btn_layout.addWidget(self.btn_load, 0, 2)
        btn_layout.addWidget(self.btn_show_afr_3d, 1,0)
        btn_layout.addWidget(self.btn_show_afr, 1, 1)
        btn_layout.addWidget(self.btn_show_ve_map, 1, 2)
        layout.addLayout(btn_layout)

        self.btn_show_3d.clicked.connect(self.show_3d_ve_map)
        self.btn_save.clicked.connect(self.save_ve_map)
        self.btn_load.clicked.connect(self.load_ve_map)
        self.btn_show_afr_3d.clicked.connect(self.show_3d_afr_map)
        self.btn_show_ve_map.clicked.connect(self.load_ve_map_to_table)
        self.btn_show_afr.clicked.connect(self.show_afr)

    def load_ve_map_to_table(self):
        rows = len(self.ve_map.map_psi_points)
        cols = len(self.ve_map.rpm_points)
        # Invert psi rows so lower psi is at the bottom
        for i in range(rows):
            for j in range(cols):
                ve_val = self.ve_map.ve_grid[rows - 1 - i, j] * 100
                item = QTableWidgetItem(f"{ve_val:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color coding: green = low, red = high
                color = self.ve_color(ve_val)
                item.setBackground(color)

                self.table.setItem(i, j, item)

    def ve_color(self, ve_val):
        """Return a QColor from green (30%) to red (120%)"""
        min_val = 30.0
        max_val = 150.0
        ve_val = np.clip(ve_val, min_val, max_val)
        t = (ve_val - min_val) / (max_val - min_val)

        r = int(0 + t * (255 - 0))       # Red increases
        g = int(255 - t * (255 - 0))     # Green decreases
        b = 0

        return QColor(r, g, b)

    def update_ve_map_from_table(self):
        rows = len(self.ve_map.map_psi_points)
        for i in range(rows):
            for j in range(len(self.ve_map.rpm_points)):
                item = self.table.item(i, j)
                try:
                    val = float(item.text())
                    val = np.clip(val, 30.0, 150.0) / 100
                    # Invert psi rows so lower psi is at the bottom
                    self.ve_map.ve_grid[rows - 1 - i, j] = val
                except Exception:
                    pass

    def save_ve_map(self):
        self.update_ve_map_from_table()
        filename, _ = QFileDialog.getSaveFileName(self, "Save VE Map", "", "JSON Files (*.json)")
        if filename:
            # Save with compact arrays (no pretty indent, separators to minimize whitespace)
            json_str = json.dumps({
                'rpm_points': self.ve_map.rpm_points.tolist(),
                'map_kpa_points': self.ve_map.map_psi_points.tolist(),
                've_grid': self.ve_map.ve_grid.tolist(),
                'afr_grid': self.ve_map.afr_grid.tolist(),
                'boost_grid': self.ve_map.boost_target_grid.tolist(),
                'thermal_grid': self.ve_map.thermal_grid.tolist()
            },separators=(',', ':'))
            
            with open(filename, 'w') as f:
                f.write(json_str)
            QMessageBox.information(self, "Saved", "VE Map saved successfully.")
    
    def show_afr(self):
        rows = len(self.ve_map.map_psi_points)
        cols = len(self.ve_map.rpm_points)
        # Invert psi rows so lower psi is at the bottom
        for i in range(rows):
            for j in range(cols):
                ve_val = self.ve_map.afr_grid[rows - 1 - i, j]
                item = QTableWidgetItem(f"{ve_val:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color coding: green = low, red = high
                color = self.afr_color(ve_val)
                item.setBackground(color)

                self.table.setItem(i, j, item)

    def afr_color(self, afr_val):
        """Return a QColor: blue (low AFR), green (middle), yellow (between), red (high AFR)"""
        min_val = 9.0
        max_val = 16.5
        afr_val = np.clip(afr_val, min_val, max_val)
        t = (afr_val - min_val) / (max_val - min_val)

        # Blue (low) -> Green (middle) -> Yellow (between) -> Red (high)
        if t < 0.33:
            # Blue to Green
            ratio = t / 0.33
            r = 0
            g = int(255 * ratio)
            b = int(255 * (1 - ratio))
        elif t < 0.66:
            # Green to Yellow
            ratio = (t - 0.33) / (0.33)
            r = int(255 * ratio)
            g = 255
            b = 0
        else:
            # Yellow to Red
            ratio = (t - 0.66) / (0.34)
            r = 255
            g = int(255 * (1 - ratio))
            b = 0

        return QColor(r, g, b)


    def load_ve_map(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load VE Map", "", "JSON Files (*.json)")
        if filename:
            with open(filename, 'r') as f:
                json_str = f.read()
            self.ve_map.from_json(json_str)
            self.load_ve_map_to_table()
            QMessageBox.information(self, "Loaded", "VE Map loaded successfully.")

    def run_dyno(self):
        self.update_ve_map_from_table()
        car_profile = get_car_profile()
        car_profile['current_gear'] = 1
        engine_config = load_engine_config(engine_name, self.ve_map)
        shifts = [8600, 8000, 7800, 7700, 7900]
        rpm, torque, hp, speed_kph, ve, boost_psi, ign_eff, therm_eff, gears, engine_temp = simulate_dyno(car_profile, engine_config, shifts, ve_map)
        # Get AFR from VE map for rpm and boost psi:
        afr = np.array([engine_config['afr'](r, b) for r, b in zip(rpm, boost_psi)])

        plot_dyno(rpm, torque, hp, speed_kph, ve, boost_psi, ign_eff, therm_eff, gears, afr)
        tuning_assistant(car_profile, engine_config)

    def show_3d_ve_map(self):
        #self.update_ve_map_from_table()

        rpm = np.array(self.ve_map.rpm_points)
        psi = np.array(self.ve_map.map_psi_points)
        ve = np.array(self.ve_map.ve_grid) * 100  # Convert to %

        # Invert psi axis so lower psi is more down
        RPM, PSI = np.meshgrid(rpm, psi[::-1])
        ve_plot = ve[::-1, :]

        fig = plt.figure(figsize=(10, 6), facecolor='black')
        ax = fig.add_subplot(111, projection='3d', facecolor='black')
        ax.invert_xaxis()

        surf = ax.plot_surface(
            RPM, PSI, ve_plot,
            cmap='jet',       # Similar to the image
            edgecolor='k',    # Black wireframe
            linewidth=0.3,
            antialiased=True
        )

        ax.set_title("VE Map 3D Surface (RPM vs MAP vs VE%)", color='white')
        ax.set_xlabel("RPM", color='white')
        ax.set_ylabel("MAP (psi)", color='white')
        ax.set_zlabel("VE (%)", color='white')

        # Set axis color
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.zaxis.label.set_color('white')

        # Grid & background
        ax.xaxis._axinfo['grid'].update(color='gray', linestyle='--')
        ax.yaxis._axinfo['grid'].update(color='gray', linestyle='--')
        ax.zaxis._axinfo['grid'].update(color='gray', linestyle='--')

        # Add color bar
        cbar = fig.colorbar(surf, shrink=0.5, aspect=10)
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

        plt.tight_layout()
        plt.show()


    def show_3d_afr_map(self):
        #self.update_ve_map_from_table()

        rpm = np.array(self.ve_map.rpm_points)
        psi = np.array(self.ve_map.map_psi_points)
        ve = np.array(self.ve_map.afr_grid)

        # Invert psi axis so lower psi is more down
        RPM, PSI = np.meshgrid(rpm, psi[::-1])
        ve_plot = ve[::-1, :]

        fig = plt.figure(figsize=(10, 6), facecolor='black')
        ax = fig.add_subplot(111, projection='3d', facecolor='black')
        ax.invert_xaxis()

        surf = ax.plot_surface(
            RPM, PSI, ve_plot,
            cmap='jet',       # Similar to the image
            edgecolor='k',    # Black wireframe
            linewidth=0.3,
            antialiased=True
        )

        ax.set_title("AFR Map 3D Surface (RPM vs MAP vs AFR)", color='white')
        ax.set_xlabel("RPM", color='white')
        ax.set_ylabel("MAP (Kpa)", color='white')
        ax.set_zlabel("AFR (1:AFR)", color='white')

        # Set axis color
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.zaxis.label.set_color('white')

        # Grid & background
        ax.xaxis._axinfo['grid'].update(color='gray', linestyle='--')
        ax.yaxis._axinfo['grid'].update(color='gray', linestyle='--')
        ax.zaxis._axinfo['grid'].update(color='gray', linestyle='--')

        # Add color bar
        cbar = fig.colorbar(surf, shrink=0.5, aspect=10)
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

        plt.tight_layout()
        plt.show()



# === Tuning assistant ===
def tuning_assistant(car_profile, engine_config):
    shifts = [8600,8000, 7800, 7700, 7900]  # Example shift points
    rpm, torque, hp, speed, ve, boost, ign_eff, therm_eff,gears,temp = simulate_dyno(car_profile, engine_config, shifts,ve_map)

    print("=== Tuning Assistant ===")

    for i in range(len(rpm)):
        suggestions = []

        # Knock warning: high VE + high boost
        if ve[i] > engine_config['knock_ve_threshold'] and boost[i] > engine_config['knock_boost_threshold_kpa']:
            suggestions.append(
                f"Reduce boost below {engine_config['knock_boost_threshold_kpa']/6.89:.1f} psi or "
                f"lower VE below {engine_config['knock_ve_threshold']*100:.1f}% around {int(rpm[i])} RPM to avoid knock."
            )
            print(f"[KNOCK WARNING] RPM: {int(rpm[i])}, VE: {ve[i]*100:.1f}%, Boost: {boost[i]/6.89:.1f} psi")
        
        # Low VE warning
        if ve[i] < 0.65:
            suggestions.append(
                f"Increase VE to at least 65% near {int(rpm[i])} RPM for better combustion efficiency."
            )
            print(f"[LOW VE] RPM: {int(rpm[i])}, VE: {ve[i]*100:.1f}% - Consider raising VE in this range.")
        
        # High boost warning
        if boost[i] > 220:  # 220 kPa ~ 31.9 psi
            suggestions.append(
                f"Reduce boost pressure below 32 psi around {int(rpm[i])} RPM to protect engine components."
            )
            print(f"[HIGH BOOST] RPM: {int(rpm[i])}, Boost: {boost[i]/6.89:.1f} psi - Check your boost curve.")
        
        # Print suggestions if any
        for s in suggestions:
            print("  -> Suggestion: " + s)

    print("\nTuning Tips:")
    print(" - Keep VE under 95% at high boost to avoid knock.")
    print(" - Peak VE usually occurs near torque peak (4000–5000 RPM).")
    print(" - Avoid sharp transitions in VE.")
    print(" - Use GUI editor for fine-grained control.")

    #plot_dyno(rpm, torque, hp, speed, ve, boost, ign_eff, therm_eff)

# === Main CLI entry point ===



def get_car_profile():
    with open(r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\car_profile.json", "r") as f:
        car_profile = json.load(f)
    return car_profile


def start():
    filename=car_profile['tune']


    try:
        with open(filename, "r") as f:
            json_str = f.read()
        ve_map.from_json(json_str)
        print(f"Loaded VE map from {filename.split("\\")[-1]}")
    except FileNotFoundError:
        print("r35_tune.json not found, using default VE map.")

    app = QApplication(sys.argv)
    editor = VEMapEditor(ve_map)
    editor.show()
    sys.exit(app.exec())

# Run the CLI entry point
if __name__ == "__main__":
    car_profile=get_car_profile()
    engine_name=car_profile['engine_name']
    ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
    config= load_engine_config(engine_name, ve_map)
    start()
