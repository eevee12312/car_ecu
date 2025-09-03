import sys
import socket
import threading
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout, QGridLayout
from PyQt6.QtGui import QFont
import pyqtgraph as pg
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox
)




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

# ---------------- SIGNAL CLASS ----------------
class DataSignal(QObject):
    data_received = pyqtSignal(int, float, int, float, float, float, float,float, float, int)  



class VEMapEditor(QWidget):
    def __init__(self, ve_map,signal: DataSignal):
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
        self.table.setVerticalHeaderLabels([str(int(psi)) for psi in ve_map.map_psi_points[::-1]])
        layout.addWidget(self.table)

        self.load_ve_map_to_table()

    def load_ve_map_to_table(self):
        rows = len(self.ve_map.map_psi_points)
        cols = len(self.ve_map.rpm_points)
        # Get current RPM and MAP psi from car_profile if available
        current_rpm = None
        current_map_psi = None
        try:
            # Try to get current values from car_profile (if available)
            boost_kpa=boost  # Convert boost psi to kPa
            current_rpm = rpm
            current_map_psi = boost_kpa
        except Exception:
            pass

        # Find closest indices for current RPM and MAP psi
        rpm_idx = None
        map_idx = None
        if current_rpm is not None and current_map_psi is not None:
            rpm_idx = (np.abs(self.ve_map.rpm_points - current_rpm)).argmin()
            map_idx = (np.abs(self.ve_map.map_psi_points - current_map_psi)).argmin()
            # Table rows are reversed for MAP psi
            map_idx = rows - 1 - map_idx

        for i in range(rows):
            for j in range(cols):
                ve_val = self.ve_map.ve_grid[rows - 1 - i, j] * 100
                item = QTableWidgetItem(f"{ve_val:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color coding: green = low, red = high
                color = self.ve_color(ve_val)
                item.setBackground(color)

                # Mark current cell in purple
                if rpm_idx is not None and map_idx is not None and i == map_idx and j == rpm_idx:
                    item.setBackground(QColor(128, 0, 128))  # Purple

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
        rows= len(self.ve_map.map_psi_points)
        for i in range(rows):
            for j in range(len(self.ve_map.rpm_points)):
                item = self.table.item(i, j)
                try:
                    val = float(item.text())
                    val = np.clip(val, 30.0, 150.0) / 100
                    self.ve_map.ve_grid[rows - 1 - i, j] = val
                except Exception:
                    pass

class AFRMapEditor(QWidget):
    def __init__(self, ve_map,signal: DataSignal):
        super().__init__()
        self.ve_map = ve_map
        self.setWindowTitle("AFR Map Editor (RPM x MAP Kpa)")
        self.resize(2400, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel("Edit Air Fuel Ratio (AFR) values (AFR) - RPM (cols) vs MAP (KPA) (rows)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self.table = QTableWidget(len(ve_map.map_psi_points), len(ve_map.rpm_points))
        self.table.setHorizontalHeaderLabels([str(int(rpm)) for rpm in ve_map.rpm_points])
        self.table.setVerticalHeaderLabels([str(int(psi)) for psi in ve_map.map_psi_points[::-1]])
        layout.addWidget(self.table)

        self.load_afr_map_to_table()

    def load_afr_map_to_table(self):
        rows = len(self.ve_map.map_psi_points)
        cols = len(self.ve_map.rpm_points)
        # Get current RPM and MAP psi from car_profile if available
        current_rpm = None
        current_map_psi = None
        try:
            # Try to get current values from car_profile (if available)
            boost_kpa=boost  # Convert boost psi to kPa
            current_rpm = rpm
            current_map_psi = boost_kpa
        except Exception:
            pass

        # Find closest indices for current RPM and MAP psi
        rpm_idx = None
        map_idx = None
        if current_rpm is not None and current_map_psi is not None:
            rpm_idx = (np.abs(self.ve_map.rpm_points - current_rpm)).argmin()
            map_idx = (np.abs(self.ve_map.map_psi_points - current_map_psi)).argmin()
            # Table rows are reversed for MAP psi
            map_idx = rows - 1 - map_idx

        for i in range(rows):
            for j in range(cols):
                ve_val = self.ve_map.afr_grid[rows - 1 - i, j]
                item = QTableWidgetItem(f"{ve_val:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color coding: green = low, red = high
                color = self.afr_color(ve_val)
                item.setBackground(color)

                # Mark current cell in purple
                if rpm_idx is not None and map_idx is not None and i == map_idx and j == rpm_idx:
                    item.setBackground(QColor(128, 0, 128))  # Purple

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

    def update_afr_map_from_table(self):
        rows= len(self.ve_map.map_psi_points)
        for i in range(rows):
            for j in range(len(self.ve_map.rpm_points)):
                item = self.table.item(i, j)
                try:
                    val = float(item.text())
                    val = np.clip(val, 30.0, 150.0) / 100
                    self.ve_map.afr_grid[rows - 1 - i, j] = val
                except Exception:
                    pass


# ---------------- SOCKET RECEIVER ----------------
class TelemetryReceiver:
    def __init__(self, signal: DataSignal, host='127.0.0.1', port=9000):
        self.signal = signal
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.host, self.port))
        self.sock.listen(1)

        threading.Thread(target=self.accept_loop, daemon=True).start()

    def accept_loop(self):
        while True:
            conn, addr = self.sock.accept()
            threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()

    def handle_client(self, conn):
        with conn:
            while True:
                try:
                    data = conn.recv(1024)
                    if not data:
                        break
                    decoded = data.decode().strip()
                    parts = decoded.split(",")
                    if len(parts) >= 7:
                        global rpm,boost,ve
                        rpm = int(parts[0])
                        speed = float(parts[1])
                        gear = int(parts[2])
                        boost = float(parts[3])
                        hp = float(parts[4])
                        torque = float(parts[5])
                        acceleration = float(parts[6])
                        ve = float(parts[7])
                        afr = float(parts[8])
                        tps = int(parts[9])

                        self.signal.data_received.emit(rpm, speed, gear, boost, hp, torque, acceleration, ve, afr, tps)
                        ve_editor.load_ve_map_to_table()  # Update VE map display
                        afr_editor.load_afr_map_to_table()  # Update AFR map display
                except Exception as e:
                    print(f"[ECU GUI] Error: {e}")
                    break

# ---------------- DASHBOARD WIDGET ----------------
class DynoDashboard(QWidget):
    def __init__(self, signal: DataSignal):
        super().__init__()
        self.setWindowTitle("Live Dyno Display")
        self.resize(900, 600)

        # Fonts
        big_font = QFont("Arial", 18, QFont.Weight.Bold)
        label_font = QFont("Arial", 14)

        # Labels
        self.rpm_label = QLabel("RPM: 0")
        self.speed_label = QLabel("Speed: 0 km/h")
        self.gear_label = QLabel("Gear: N")
        self.boost_label = QLabel("Boost: 0 Kpa")
        self.hp_label = QLabel("HP: 0")
        self.torque_label = QLabel("Torque: 0 Nm")
        self.accel_label = QLabel("Accel: 0 m/s²")
        self.ve_label = QLabel("VE: 0.00")
        self.afr_label = QLabel("AFR: 0.00")
        self.tps_label = QLabel("TPS: 0%")

        for lbl in [self.rpm_label, self.speed_label, self.gear_label,
                    self.boost_label, self.hp_label, self.torque_label, self.accel_label,self.ve_label, self.afr_label, self.tps_label]:
            lbl.setFont(big_font)

        # Grid for text data
        grid = QGridLayout()
        grid.addWidget(self.rpm_label, 0, 0)
        grid.addWidget(self.speed_label, 0, 1)
        grid.addWidget(self.gear_label, 1, 0)
        grid.addWidget(self.boost_label, 1, 1)
        grid.addWidget(self.hp_label, 2, 0)
        grid.addWidget(self.torque_label, 2, 1)
        grid.addWidget(self.accel_label, 3, 0)
        grid.addWidget(self.ve_label, 3, 1)
        grid.addWidget(self.afr_label, 4, 0)
        grid.addWidget(self.tps_label, 4, 1)
        # Combined HP & Torque Graph
        self.hp_torque_plot = pg.PlotWidget(title="Horsepower & Torque")
        self.hp_torque_plot.setYRange(0, 500)  # adjustable
        self.hp_torque_plot.showGrid(x=True, y=True)
        self.hp_curve = self.hp_torque_plot.plot(pen=pg.mkPen(color='r', width=2), name="HP")
        self.torque_curve = self.hp_torque_plot.plot(pen=pg.mkPen(color='y', width=2), name="Torque")

        # Boost Graph
        self.boost_plot = pg.PlotWidget(title="Boost Pressure")
        self.boost_plot.setYRange(0, 200)  # adjustable
        self.boost_plot.showGrid(x=True, y=True)
        self.boost_curve = self.boost_plot.plot(pen=pg.mkPen(color='g', width=2))

        self.hp_data = []
        self.boost_data = []
        self.torque_data = []
        self.x_data = []

        # Layout
        layout = QVBoxLayout()
        layout.addLayout(grid)

        graph_layout = QHBoxLayout()
        graph_layout.addWidget(self.hp_torque_plot)
        graph_layout.addWidget(self.boost_plot)
        layout.addLayout(graph_layout)

        self.setLayout(layout)

        # Connect signal
        signal.data_received.connect(self.update_display)
    def abs_kpa_to_psi(self, kpa):
        return max((kpa - 101.3) / 6.89476,0)

    def update_display(self, rpm, speed, gear, boost, hp, torque, accel, ve, afr, tps):
        self.rpm_label.setText(f"RPM: {rpm}")
        self.speed_label.setText(f"Speed: {speed:.1f} km/h")
        self.gear_label.setText(f"Gear: {gear}")
        self.boost_label.setText(f"Boost: {self.abs_kpa_to_psi(boost):.1f} psi")
        self.hp_label.setText(f"HP: {hp:.1f}")
        self.torque_label.setText(f"Torque: {torque:.1f} Nm")
        self.accel_label.setText(f"Accel: {accel:.2f} m/s²")
        self.ve_label.setText(f"VE: {ve:.2f}")
        self.afr_label.setText(f"AFR: {afr:.2f}")
        self.tps_label.setText(f"TPS: {tps}%")

        # Append new data for graphs
        if len(self.x_data) > 200:
            self.x_data.pop(0)
            self.hp_data.pop(0)
            self.torque_data.pop(0)
            self.boost_data.pop(0)
        if rpm < 10000:
            self.x_data.append(rpm)
            self.hp_data.append(hp)
            self.boost_data.append(boost)
            self.torque_data.append(torque)

            self.hp_curve.setData(self.x_data, self.hp_data)
            self.torque_curve.setData(self.x_data, self.torque_data)
            self.boost_curve.setData(self.x_data, self.boost_data)

# ---------------- MAIN APP ----------------

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

if __name__ == "__main__":
    try:
        car_profile=get_car_profile()
        engine_name = car_profile['engine_name']
        ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
        config= load_engine_config(engine_name, ve_map)
        start()
        signal = DataSignal()
        app = QApplication(sys.argv)
        

        TelemetryReceiver(signal)  # Starts listening for socket data

        dash = DynoDashboard(signal)
        dash.show()
        ve_editor = VEMapEditor(ve_map,signal)
        ve_editor.show()
        afr_editor = AFRMapEditor(ve_map,signal)
        afr_editor.show()

        sys.exit(app.exec())
    except Exception as e:
        with open(r"C:\Users\Owner\Desktop\ctf\car_ecu\errors.txt", 'a') as error_log:
            error_log.write(f"Error: {e}\n")
        print(f"An error occurred: {e}")

#display in the ve map what the current ve is for the current rpm and boost