import sys
import json
import numpy as np
import matplotlib.pyplot as plt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QHBoxLayout, QPushButton, QFileDialog, QLabel, QMessageBox,QHeaderView
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
RPM_POINTS = np.arange(800, 7600, 700)  # RPM points (11 columns)
MAP_PSI_POINTS = np.array([5, 10, 15, 20, 25, 30])  # MAP (psi) rows







def psi_to_kpa(psi):
    return psi * 6.89476

# === VE Map class ===
class VEMap2D:
    def __init__(self, rpm_points, map_psi_points):
        self.rpm_points = rpm_points
        self.map_psi_points = map_psi_points
        self.ve_grid = np.ones((len(map_psi_points), len(rpm_points))) * 0.7
        for i, psi in enumerate(map_psi_points):
            for j, rpm in enumerate(rpm_points):
                base_ve = 0.5 + 0.5 * np.exp(-((rpm - 4500)/2000)**2)
                boost_factor = 1 - 0.015 * (psi - 5)
                self.ve_grid[i, j] = np.clip(base_ve * boost_factor, 0.4, 1.0)

    def get_ve(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        rpm = np.clip(rpm, self.rpm_points[0], self.rpm_points[-1])
        map_psi = np.clip(map_psi, self.map_psi_points[0], self.map_psi_points[-1])
        rpm_idx = np.searchsorted(self.rpm_points, rpm) - 1
        rpm_idx = np.clip(rpm_idx, 0, len(self.rpm_points) - 2)
        rpm_frac = (rpm - self.rpm_points[rpm_idx]) / (self.rpm_points[rpm_idx+1] - self.rpm_points[rpm_idx])
        map_idx = np.searchsorted(self.map_psi_points, map_psi) - 1
        map_idx = np.clip(map_idx, 0, len(self.map_psi_points) - 2)
        map_frac = (map_psi - self.map_psi_points[map_idx]) / (self.map_psi_points[map_idx+1] - self.map_psi_points[map_idx])

        ve00 = self.ve_grid[map_idx, rpm_idx]
        ve01 = self.ve_grid[map_idx, rpm_idx+1]
        ve10 = self.ve_grid[map_idx+1, rpm_idx]
        ve11 = self.ve_grid[map_idx+1, rpm_idx+1]

        ve_r0 = ve00 + rpm_frac * (ve01 - ve00)
        ve_r1 = ve10 + rpm_frac * (ve11 - ve10)
        return ve_r0 + map_frac * (ve_r1 - ve_r0)

    def to_json(self):
        return json.dumps({
            'rpm_points': self.rpm_points.tolist(),
            'map_psi_points': self.map_psi_points.tolist(),
            've_grid': self.ve_grid.tolist()
        }, indent=2)

    def from_json(self, json_str):
        data = json.loads(json_str)
        self.rpm_points = np.array(data['rpm_points'])
        self.map_psi_points = np.array(data['map_psi_points'])
        self.ve_grid = np.array(data['ve_grid'])

# === Engine config tuned style using the VEMap2D instance ===
def create_engine_config_tuned(ve_map: VEMap2D):
    return {
        'displacement_l': 3.8,
        'volumetric_efficiency': ve_map,
        'boost_pressure_kpa': lambda rpm: (
            101.3 + 100 * np.clip((rpm - 2500) / 4000, 0, 1)
        ),
        'ignition_efficiency': lambda rpm: (
            1.00 - 0.10 * np.exp(-((rpm - 6000)/800)**2)
        ),
        'afr': 14.0,
        'air_density': 1.18,
        'rpm_step': 50,
        "max_boost_psi": 22.0,
        "spool_rpm": 2200,
        "full_boost_rpm": 3200,
        "turbo_efficiency": 0.93,
        "base_thermal_efficiency": 0.35,
        "knock_ve_threshold": 0.95,
        "knock_boost_threshold_kpa": 170.0,
    }

# === Dyno simulation function uses engine_config_tuned ===

def simulate_dyno(car, engine, shift_rpms):
    """
    Simulate dyno run with gear shifting at specified RPMs.

    Args:
      car: dict with car parameters including 'gear_ratios', 'final_drive_ratio', 'idle_rpm', 'redline_rpm'
      engine: dict with engine parameters and functions
      shift_rpms: list of RPM values at which to shift for each gear (length = number of gears - 1)
                 e.g. [6500, 7000, 7000, 7000, 7000] for a 6-speed

    Returns:
      concatenated arrays for rpm, torque, horsepower, speed_kph, ve, boost_psi, ignition_efficiency, thermal_efficiency, gears
      across the full run with gear shifts
    """

    # Prepare empty lists to accumulate data across gears
    all_rpm = []
    all_torque = []
    all_hp = []
    all_speed_kph = []
    all_ve = []
    all_boost_psi = []
    all_ign_eff = []
    all_therm_eff = []
    all_gears = []

    num_gears = len(car['gear_ratios'])

    for gear_idx in range(num_gears):
        gear = gear_idx + 1
        gear_ratio = car['gear_ratios'][gear_idx]
        final_drive = car['final_drive_ratio']

        # Determine RPM range for this gear: from idle or previous shift RPM up to shift RPM or redline
        if gear_idx == 0:
            rpm_start = car['idle_rpm']
        else:
            rpm_start = shift_rpms[gear_idx - 1]  # start at last shift RPM

        if gear_idx < len(shift_rpms):
            rpm_end = min(shift_rpms[gear_idx], car['redline_rpm'])
        else:
            rpm_end = car['redline_rpm']

        if rpm_end <= rpm_start:
            rpm_end = car['redline_rpm']

        rpm_values = np.arange(rpm_start, rpm_end + engine['rpm_step'], engine['rpm_step'], dtype=np.float64)

        # Boost spool function
        def twin_turbo_spool(rpm_val):
            max_boost = engine.get('max_boost_psi', 22.0)
            spool_rpm = engine.get('spool_rpm', 2200)
            full_boost_rpm = engine.get('full_boost_rpm', 3200)
            if rpm_val < spool_rpm:
                return 0.0
            elif rpm_val >= full_boost_rpm:
                return max_boost
            else:
                return max_boost * (rpm_val - spool_rpm) / (full_boost_rpm - spool_rpm)

        boost_psi = np.array([twin_turbo_spool(r) for r in rpm_values])
        boost_kpa = boost_psi * 6.89476
        boost_ratio = (boost_kpa + 101.325) / 101.325

        wheel_rpm = rpm_values / (gear_ratio * final_drive)
        tire_circumference_m = car.get('tire_circumference_m', 2.05)
        speed_mps = wheel_rpm * tire_circumference_m / 60.0
        speed_kph = speed_mps * 3.6

        ve_map = engine['volumetric_efficiency']
        ve = np.array([ve_map.get_ve(r, boost_psi[i]) for i, r in enumerate(rpm_values)])

        turbo_efficiency = engine.get('turbo_efficiency', 0.93)
        effective_boost = boost_ratio * turbo_efficiency

        torque_base = 200 + 100 * np.sin(np.pi * (rpm_values - car['idle_rpm']) / (car['redline_rpm'] - car['idle_rpm']))
        torque = torque_base * ve * effective_boost

        torque_ftlbs = torque * 0.73756
        hp = torque_ftlbs * rpm_values / 5252

        ign_eff = engine['ignition_efficiency'](rpm_values)

        therm_eff = np.ones_like(rpm_values) * engine.get('base_thermal_efficiency', 0.35)
        knock_ve_thresh = engine.get('knock_ve_threshold', 0.95)
        knock_boost_thresh_kpa = engine.get('knock_boost_threshold_kpa', 170.0)
        knock_cond = (ve > knock_ve_thresh) & (boost_kpa > knock_boost_thresh_kpa)
        therm_eff[knock_cond] *= 0.8

        # Append this gear's data
        all_rpm.append(rpm_values)
        all_torque.append(torque)
        all_hp.append(hp)
        all_speed_kph.append(speed_kph)
        all_ve.append(ve)
        all_boost_psi.append(boost_psi)
        all_ign_eff.append(ign_eff)
        all_therm_eff.append(therm_eff)

        # Append gear array for this gear run segment
        all_gears.append(np.full_like(rpm_values, gear, dtype=int))

    # Concatenate all gear data into single arrays
    all_rpm = np.concatenate(all_rpm)
    all_torque = np.concatenate(all_torque)
    all_hp = np.concatenate(all_hp)
    all_speed_kph = np.concatenate(all_speed_kph)
    all_ve = np.concatenate(all_ve)
    all_boost_psi = np.concatenate(all_boost_psi)
    all_ign_eff = np.concatenate(all_ign_eff)
    all_therm_eff = np.concatenate(all_therm_eff)
    all_gears = np.concatenate(all_gears)

    # Print peak torque and horsepower overall
    peak_torque_idx = np.argmax(all_torque)
    peak_hp_idx = np.argmax(all_hp)
    print(f"Peak Torque: {all_torque[peak_torque_idx]:.2f} Nm at {all_rpm[peak_torque_idx]:.0f} RPM")
    print(f"Peak Horsepower: {all_hp[peak_hp_idx]:.2f} HP at {all_rpm[peak_hp_idx]:.0f} RPM")
    print(all_gears)

    return all_rpm, all_torque, all_hp, all_speed_kph, all_ve, all_boost_psi, all_ign_eff, all_therm_eff, all_gears



# === Plot function ===
def plot_dyno(rpm, tq, hp, speed, ve, boost, ign_eff, therm_eff, gears):
    step = 0.0054347826
    throttle = np.arange(0, 1 + step, step)
    min_len = min(len(rpm), len(throttle))
    rpm = rpm[:min_len]
    throttle = throttle[:min_len]

    plt.style.use('dark_background')
    fig, axs = plt.subplots(4, 1, figsize=(16, 14), sharex=True)
    fig.suptitle("Rolling Road Dyno – VR38DETT Engine Simulation", fontsize=18, y=0.95)

    # Torque and HP
    axs[0].plot(rpm, tq, label='Torque (Nm)', color='orange', linewidth=3)
    axs[0].plot(rpm, hp, label='Horsepower (HP)', color='deepskyblue', linewidth=3)
    axs[0].fill_between(rpm, tq, color='orange', alpha=0.15)
    axs[0].fill_between(rpm, hp, color='deepskyblue', alpha=0.15)
    axs[0].set_ylabel("Torque / HP", fontsize=12)
    axs[0].legend(loc='upper left')
    axs[0].grid(True, linestyle='--', alpha=0.3)

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

    # Speed and Throttle
    axs[3].plot(rpm, speed, label='Speed (km/h)', color='dodgerblue', linewidth=2.5)
    axs[3].plot(rpm, throttle * 100, label='Throttle (%)', color='white', linestyle='--', linewidth=2)
    axs[3].set_xlabel("Engine RPM", fontsize=12)
    axs[3].set_ylabel("Speed / Throttle", fontsize=12)
    axs[3].legend(loc='upper left')
    axs[3].grid(True, linestyle='--', alpha=0.3)

    # Add gear text labels on the speed plot
    # Find distinct gear change points and annotate
    prev_gear = None
    gears=gears[:min_len]
    for i, g in enumerate(gears):
        if g != prev_gear or i == 0:
            axs[3].text(
                rpm[i], speed[i] + 5,  # slightly above speed curve
                f"Gear {g}",
                color='white',
                fontsize=10,
                fontweight='bold',
                ha='center',
                va='bottom',
                bbox=dict(facecolor='black', alpha=0.6, boxstyle='round,pad=0.3')
            )
        prev_gear = g

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()
    plt.savefig("dyno.png")







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
        self.table.setVerticalHeaderLabels([str(int(psi)) for psi in ve_map.map_psi_points])
        layout.addWidget(self.table)

        self.load_ve_map_to_table()

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save VE Map")
        self.btn_load = QPushButton("Load VE Map")
        self.btn_run = QPushButton("Run Dyno Simulation")
        self.btn_show_3d = QPushButton("Show 3D VE Map")
        btn_layout.addWidget(self.btn_show_3d)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_run)
        layout.addLayout(btn_layout)

        self.btn_show_3d.clicked.connect(self.show_3d_ve_map)
        self.btn_save.clicked.connect(self.save_ve_map)
        self.btn_load.clicked.connect(self.load_ve_map)
        self.btn_run.clicked.connect(self.run_dyno)

    def load_ve_map_to_table(self):
        for i in range(len(self.ve_map.map_psi_points)):
            for j in range(len(self.ve_map.rpm_points)):
                ve_val = self.ve_map.ve_grid[i, j] * 100
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
        for i in range(len(self.ve_map.map_psi_points)):
            for j in range(len(self.ve_map.rpm_points)):
                item = self.table.item(i, j)
                try:
                    val = float(item.text())
                    val = np.clip(val, 30.0, 150.0) / 100.0
                    self.ve_map.ve_grid[i, j] = val
                except Exception:
                    pass

    def save_ve_map(self):
        self.update_ve_map_from_table()
        filename, _ = QFileDialog.getSaveFileName(self, "Save VE Map", "", "JSON Files (*.json)")
        if filename:
            with open(filename, 'w') as f:
                f.write(self.ve_map.to_json())
            QMessageBox.information(self, "Saved", "VE Map saved successfully.")

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
        car_profile = {
            'idle_rpm': 850,
            'redline_rpm': 8500,
            'rpm_step': 50,
            'gear_ratios': [4.06, 2.3, 1.59, 1.25, 1.0, 0.80],
            'final_drive_ratio': 3.7,
            'current_gear': 1
        }
        engine_config = create_engine_config_tuned(self.ve_map)
        shifts=[8229,8229,8229,8229,8229]
        rpm, torque, hp, speed, ve, boost, ign_eff, therm_eff,gears = simulate_dyno(car_profile, engine_config,shifts)
        plot_dyno(rpm, torque, hp, speed, ve, boost, ign_eff, therm_eff,gears)
        tuning_assistant(car_profile, engine_config)


    def show_3d_ve_map(self):
        self.update_ve_map_from_table()
        
        rpm = np.array(self.ve_map.rpm_points)
        psi = np.array(self.ve_map.map_psi_points)
        ve = np.array(self.ve_map.ve_grid) * 100  # Convert to %

        RPM, PSI = np.meshgrid(rpm, psi)

        fig = plt.figure(figsize=(10, 6), facecolor='black')
        ax = fig.add_subplot(111, projection='3d', facecolor='black')

        surf = ax.plot_surface(
            RPM, PSI, ve,
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
        ax.xaxis._axinfo['grid'].update(color = 'gray', linestyle='--')
        ax.yaxis._axinfo['grid'].update(color = 'gray', linestyle='--')
        ax.zaxis._axinfo['grid'].update(color = 'gray', linestyle='--')

        # Add color bar
        cbar = fig.colorbar(surf, shrink=0.5, aspect=10)
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

        plt.tight_layout()
        plt.show()



# === Tuning assistant ===
def tuning_assistant(car_profile, engine_config):
    shifts = [7500, 7800, 8100, 8300, 8400]
    rpm, torque, hp, speed, ve, boost, ign_eff, therm_eff,gears = simulate_dyno(car_profile, engine_config, shifts)

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
def start():
    filename=r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\race_tune.json"



    ve_map = VEMap2D(RPM_POINTS, MAP_PSI_POINTS)
    try:
        with open(filename, "r") as f:
            json_str = f.read()
        ve_map.from_json(json_str)
        print("Loaded VE map from r35_tune.json")
    except FileNotFoundError:
        print("r35_tune.json not found, using default VE map.")


    app = QApplication(sys.argv)
    editor = VEMapEditor(ve_map)
    editor.show()
    sys.exit(app.exec())

# Run the CLI entry point
if __name__ == "__main__":
    start()
