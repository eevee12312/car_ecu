import sys
import json
import numpy as np
import matplotlib.pyplot as plt
import math
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
RPM_POINTS = np.arange(1100, 9200, 400)  # RPM points (11 columns)
MAP_PSI_POINTS = np.array([5, 10, 15, 20, 25, 30])  # MAP (psi) rows







def psi_to_kpa(psi):
    return 101.3 + psi * 6.89476

# === VE Map class ===

class EngineTuneMap2D:
    def __init__(self, rpm_points, map_psi_points):
        self.rpm_points = np.array(rpm_points)
        self.map_psi_points = np.array(map_psi_points)

        self.ve_grid = np.ones((len(map_psi_points), len(rpm_points))) * 0.7
        self.afr_grid = np.ones((len(map_psi_points), len(rpm_points))) * 14.7
        self.boost_grid = np.zeros((len(map_psi_points), len(rpm_points)))
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
                self.boost_grid[i, j] = np.clip(boost_target, 0.0, 3.0)

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
        return self._bilinear_interpolate(self.boost_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def get_thermal_load(self, rpm, map_kpa):
        map_psi = map_kpa / 6.89476
        return self._bilinear_interpolate(self.thermal_grid, self.rpm_points, self.map_psi_points, rpm, map_psi)

    def to_json(self):
        return json.dumps({
            'rpm_points': self.rpm_points.tolist(),
            'map_psi_points': self.map_psi_points.tolist(),
            've_grid': self.ve_grid.tolist(),
            'afr_grid': self.afr_grid.tolist(),
            'boost_grid': self.boost_grid.tolist(),
            'thermal_grid': self.thermal_grid.tolist()
        }, indent=2)

    def from_json(self, json_str):
        data = json.loads(json_str)
        self.rpm_points = np.array(data['rpm_points'])
        self.map_psi_points = np.array(data['map_psi_points'])
        self.ve_grid = np.array(data['ve_grid'])
        self.afr_grid = np.array(data['afr_grid'])
        self.boost_grid = np.array(data['boost_grid'])
        self.thermal_grid = np.array(data['thermal_grid'])



# === Engine config tuned style using the VEMap2D instance ===
def create_engine_config_tuned(ve_map: EngineTuneMap2D):
    return {
        # Engine basics
        'displacement_l': 3.8,
        'cylinders': 6,

        # Airflow
        'volumetric_efficiency': lambda rpm, map_kpa: ve_map.get_ve(rpm, map_kpa),
        'afr': lambda rpm, map_kpa: ve_map.get_afr(rpm, map_kpa),

        # Boost target (optional, if used)
        'boost_target_psi': lambda rpm: np.interp(
            rpm, ve_map.rpm_points, [ve_map.map_psi_points[-1]] * len(ve_map.rpm_points)
        ),  # Or define your own boost curve

        # Other parameters
        'boost_pressure_kpa': lambda rpm: (
            101.3 + 100 * np.clip((rpm - 2500) / 4000, 0, 1)
        ),
        'air_density': 1.18,

        # Combustion
        'ignition_efficiency': lambda rpm: (
            1.00 - 0.10 * np.exp(-((rpm - 6000)/800)**2)
        ),
        'thermal_efficiency':lambda rpm, map_kpa: ve_map.get_thermal_load(rpm,map_kpa),
        'fuel_density': 0.760,  # kg/L
        'fuel_energy_mj': 45,   # MJ/kg

        # Turbo
        'max_boost_psi': 33.0,
        'spool_rpm': 2200,
        'full_boost_rpm': 6500,
        'turbo_efficiency': 0.93,

        # Efficiency
        'base_thermal_efficiency': 0.35,
        'knock_ve_threshold': 0.95,
        'knock_boost_threshold_kpa': 170.0,
    }

ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QMessageBox,
    QTabWidget
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt
import numpy as np
import matplotlib.pyplot as plt
import json


class MapEditor(QWidget):
    def __init__(self, ve_map):
        super().__init__()
        self.ve_map = ve_map
        self.setWindowTitle("Map Editor (VE / AFR / Boost / Thermal)")
        self.resize(2600, 650)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Map types and their corresponding data keys
        self.maps = {
            'VE': ('ve_grid', '%', self.color_ve, (30.0, 150.0)),
            'AFR': ('afr_grid', '', self.color_afr, (10.0, 18.0)),
            'Boost': ('boost_grid', 'psi', self.color_boost, (0.0, 35.0)),
            'Thermal': ('thermal_grid', '°C', self.color_thermal, (0.0, 1.0)),
        }

        self.tables = {}

        for name in self.maps:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            label = QLabel(f"Edit {name} Map ({self.maps[name][1]}) - RPM (cols) vs MAP psi (rows)")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tab_layout.addWidget(label)

            table = QTableWidget(len(ve_map.map_psi_points), len(ve_map.rpm_points))
            table.setHorizontalHeaderLabels([str(int(rpm)) for rpm in ve_map.rpm_points])
            table.setVerticalHeaderLabels([str(int(psi)) for psi in ve_map.map_psi_points])
            tab_layout.addWidget(table)
            self.tables[name] = table
            self.tabs.addTab(tab, name)

        self.load_all_maps_to_tables()

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_show_3d = QPushButton("Show 3D Map")
        self.btn_save = QPushButton("Save Maps")
        self.btn_load = QPushButton("Load Maps")
        self.btn_run = QPushButton("Run Dyno Simulation")
        btn_layout.addWidget(self.btn_show_3d)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_run)
        layout.addLayout(btn_layout)

        self.btn_show_3d.clicked.connect(self.show_3d_map)
        self.btn_save.clicked.connect(self.save_maps)
        self.btn_load.clicked.connect(self.load_maps)

    def color_ve(self, val):
        return self.gradient_color(val, 30.0, 150.0)

    def color_afr(self, val):
        return self.gradient_color(val, 10.0, 18.0, color_low=(255, 0, 0), color_high=(0, 255, 0))

    def color_boost(self, val):
        return self.gradient_color(val, 0.0, 35.0)

    def color_thermal(self, val):
        return self.gradient_color(val, 0.0, 1.0, color_low=(0, 0, 255), color_high=(255, 165, 0))

    def gradient_color(self, val, min_val, max_val, color_low=(0, 255, 0), color_high=(255, 0, 0)):
        val = np.clip(val, min_val, max_val)
        t = (val - min_val) / (max_val - min_val)
        r = int(color_low[0] + t * (color_high[0] - color_low[0]))
        g = int(color_low[1] + t * (color_high[1] - color_low[1]))
        b = int(color_low[2] + t * (color_high[2] - color_low[2]))
        return QColor(r, g, b)

    def load_all_maps_to_tables(self):
        for name, (grid_name, suffix, color_func, _) in self.maps.items():
            grid = getattr(self.ve_map, grid_name)
            table = self.tables[name]
            for i in range(grid.shape[0]):
                for j in range(grid.shape[1]):
                    val = grid[i, j] * 100 if name == 'VE' else grid[i, j]
                    item = QTableWidgetItem(f"{val:.2f}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(color_func(val))
                    table.setItem(i, j, item)

    def update_maps_from_tables(self):
        for name, (grid_name, _, _, (min_val, max_val)) in self.maps.items():
            grid = getattr(self.ve_map, grid_name)
            table = self.tables[name]
            for i in range(grid.shape[0]):
                for j in range(grid.shape[1]):
                    try:
                        val = float(table.item(i, j).text())
                        val = np.clip(val, min_val, max_val)
                        grid[i, j] = val / 100.0 if name == 'VE' else val
                    except:
                        pass

    def save_maps(self):
            self.update_maps_from_tables()
            filename, _ = QFileDialog.getSaveFileName(self, "Save Maps", filter="JSON Files (*.json)")
            if filename:
                try:
                    with open(filename, 'w') as f:
                        f.write(self.ve_map.to_json())
                    QMessageBox.information(self, "Saved", "Maps saved successfully.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save maps: {e}")

    def load_maps(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Maps", filter="JSON Files (*.json)")
        if filename:
            try:
                with open(filename, 'r') as f:
                    self.ve_map.from_json(f.read())
                self.load_all_maps_to_tables()
                QMessageBox.information(self, "Loaded", "Maps loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load maps: {e}")

    def show_3d_map(self):
        for item in self.maps.items():
            self.update_maps_from_tables()
            
            rpm = np.array(self.ve_map.rpm_points)
            psi = np.array(self.ve_map.map_psi_points)
            if item[1][0]=='ve_grid':
                ve = np.array(self.ve_map.ve_grid) * 100  # Convert to %
            elif item[1][0]=='afr_grid':
                ve = np.array(self.ve_map.afr_grid) * 100  # Convert to %
            elif item[1][0]=='boost_grid':
                ve = np.array(self.ve_map.boost_grid) * 100  # Convert to %
            elif item[1][0]=='thermal_grid':
                ve = np.array(self.ve_map.thermal_grid) * 100  # Convert to %

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

            ax.set_title(f"{item[1][0]}", color='white')
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





def get_car_profile():
    with open(r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\car_profile.json", "r") as f:
        car_profile = json.load(f)
    return car_profile


def start():
    filename=r"C:\Users\Owner\Desktop\ctf\car_ecu\dyno\drag_tune.json"


    try:
        with open(filename, "r") as f:
            json_str = f.read()
        ve_map.from_json(json_str)
        print("Loaded VE map from r35_tune.json")
    except FileNotFoundError:
        print("r35_tune.json not found, using default VE map.")

    app = QApplication(sys.argv)
    editor = MapEditor(ve_map)
    editor.show()
    sys.exit(app.exec())

# Run the CLI entry point
if __name__ == "__main__":
    car_profile=get_car_profile()
    ve_map = EngineTuneMap2D(RPM_POINTS, MAP_PSI_POINTS)
    config = create_engine_config_tuned(ve_map)
    start()
