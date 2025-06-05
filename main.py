import sys
import time
import socket
import threading
import pygame

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QDial, QPushButton, QGridLayout, QFrame, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QPalette, QLinearGradient, QBrush, QColor


import throttle
from engine_sound_mine import EngineSoundSimulator, play_turbo
from throttle import MAX_RPM, max_boost,estp
from tachometer import CircularGauge, SpeedGauge, RevLight, TurboGauge, GearDisplay, TempGauge


class DataSignal(QObject):
    data_received = pyqtSignal(int, float, float, int, float, float, float)  
    # rpm, speed, temp, gear, boost, hp, torque
def play_turbo_async(sound_file):
    threading.Thread(target=play_turbo, args=(sound_file,), daemon=True).start()

class ECUGUI(QMainWindow):
    secret_combo_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.secret_window = None
        self.setWindowTitle("Car ECU Interface")
        self.setMinimumSize(800, 600)
        self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #FF3C38;
            }
            QLabel {
                font-size: 16px;
                padding: 5px;
            }
        """)

        self.signal = DataSignal()
        self.signal.data_received.connect(self.update_display)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        info_layout = QHBoxLayout()
        self.temp_label = QLabel("Temp: --- °C")
        info_layout.addWidget(self.temp_label)
        main_layout.addLayout(info_layout)

        self.rev_light = RevLight()
        self.rev_light.setStyleSheet("margin: 10px;")
        main_layout.addWidget(self.rev_light)
        
        self.speed_gauge = SpeedGauge(0, estp)
        self.rpm_gauge = CircularGauge(0, MAX_RPM)
        self.turbo_gauge = TurboGauge(0, max_boost)
        self.gear_display = GearDisplay(0, 6)
        self.temp_gauge = TempGauge(0,120)
        gauges_layout = QGridLayout()

        # Increase gauge sizes
        self.rpm_gauge.setFixedSize(450, 450)
        self.speed_gauge.setFixedSize(350, 350)
        self.gear_display.setFixedSize(160, 160)
        self.turbo_gauge.setFixedSize(200, 200)
        self.temp_gauge.setFixedSize(200, 200)

        # Gear + Turbo stacked, pushed up and right
        gear_turbo_widget = QWidget()
        gear_turbo_layout = QVBoxLayout()
        gear_turbo_layout.setContentsMargins(0, 20, 0, 0)  # Less margin to pull it higher
        gear_turbo_layout.setSpacing(15)
        gear_turbo_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        gear_turbo_layout.addWidget(self.gear_display)
        gear_turbo_layout.addWidget(self.turbo_gauge)
        gear_turbo_widget.setLayout(gear_turbo_layout)

        # Temp aligned with RPM center and pushed right
        temp_container = QWidget()
        temp_layout = QVBoxLayout()
        temp_layout.setContentsMargins(0, 150, 0, 0)
        temp_layout.addWidget(self.temp_gauge, alignment=Qt.AlignmentFlag.AlignTop)
        temp_container.setLayout(temp_layout)

        # Add empty column to push everything to the right
        # Grid: column 0 (spacer), 1 = speed, 2 = RPM, 3 = gear/turbo, 4 = temp
        gauges_layout.addItem(QSpacerItem(50, 10, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum), 1, 0)

        gauges_layout.addWidget(self.speed_gauge, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        gauges_layout.addWidget(self.rpm_gauge, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        gauges_layout.addWidget(gear_turbo_widget, 1, 3)
        gauges_layout.addWidget(temp_container, 1, 4)

        main_layout.addLayout(gauges_layout)


        self.secret_combo_signal.connect(self.show_secret_window)

        threading.Thread(target=self.start_server, daemon=True).start()
        threading.Thread(target=self.monitor_ignition_button, daemon=True).start()

    def monitor_ignition_button(self):
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            print("No joystick found!")
            return
        joystick = pygame.joystick.Joystick(0)
        joystick.init()

        print("-----------------------\n\tcar ECU\nWaiting for Ignition button press (Joystick button 1)...\n-----------------------")

        while True:
            pygame.event.pump()
            if joystick.get_button(1):  # Ignition button
                print("Ignition button pressed! Starting engine...")
                self.start_engine()
                while joystick.get_button(1):
                    pygame.event.pump()
                    time.sleep(0.1)
            if joystick.get_hat(0) == (0,1) and joystick.get_button(0):
                throttle.open_ve_map()
                self.secret_combo_signal.emit()
                while joystick.get_hat(0) == (0,1) and joystick.get_button(0):
                    pygame.event.pump()
                    time.sleep(0.1)
            time.sleep(0.1)

    def start_engine(self):
        if getattr(throttle, "engine_on", False):
            throttle.engine_on = False
            print("Engine shutdown initiated.")
            self.update_display(0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
            if not throttle.logged:
                throttle.log()
                throttle.logged=True
        else:
            #play_turbo("sounds/engine_startup.wav")
            throttle.engine_on = True
            play_turbo_async("sounds/engine_startup.wav")
            threading.Thread(target=throttle.get_throttle_and_buttons, daemon=True).start()
            print("Engine started!")

    def update_display(self, rpm: int, speed: float, temp: float, gear: int, boost: float, hp: float, torque: float):
        self.temp_label.setText(f"Temp: {temp:.1f} °C")

        self.rpm_gauge.set_value(rpm)
        self.speed_gauge.set_value(speed)
        self.rev_light.set_rpm(rpm)
        self.turbo_gauge.set_psi(boost)
        self.gear_display.set_gear(gear)
        self.temp_gauge.set_temp(temp)

        if self.secret_window and self.secret_window.isVisible():
            self.secret_window.update_values(torque, hp, rpm, speed, boost,gear)

    def start_server(self, host="127.0.0.1", port=9999):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            s.listen()
            print(f"[ECU GUI] Listening on {host}:{port}...")

            while True:
                conn, addr = s.accept()
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
                        rpm = int(parts[0])
                        speed = float(parts[1])
                        temp = float(parts[2])
                        gear = int(parts[3])
                        boost = float(parts[4])
                        hp = float(parts[5])
                        torque = float(parts[6])
                        self.signal.data_received.emit(rpm, speed, temp, gear, boost, hp, torque)
                except Exception as e:
                    print(f"[ECU GUI] Error: {e}")
                    break

    def show_secret_window(self):
        if self.secret_window is None or not self.secret_window.isVisible():
            self.secret_window = SecretWindow()
            self.secret_window.show()

class SecretWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nissan GT-R Secret Screen")
        self.setFixedSize(480, 320)

        # Gradient dark background
        palette = QPalette()
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor("#0d0d0d"))
        gradient.setColorAt(1.0, QColor("#1a1a1a"))
        palette.setBrush(QPalette.ColorRole.Window, QBrush(gradient))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""
            QLabel#title {
                color: #ff0000;
                font-weight: bold;
                font-size: 36px;
                font-family: 'Arial Black', Arial, sans-serif;
                qproperty-alignment: 'AlignCenter';
            }
            QLabel#label {
                color: #FF3C38;
                font-size: 16px;
                font-weight: 600;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                qproperty-alignment: 'AlignCenter';
            }
            QLabel#value {
                color: #FFFFFF;
                font-size: 26px;
                font-family: 'Courier New', monospace;
                font-weight: bold;
                qproperty-alignment: 'AlignCenter';
            }
            QFrame#box {
                border: 2px solid #FF3C38;
                border-radius: 10px;
                background-color: #1e1e1e;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Title at top
        self.title = QLabel("NISSAN GT-R", self)
        self.title.setObjectName("title")
        main_layout.addWidget(self.title)

        # Grid layout 2 columns, 3 rows
        grid = QGridLayout()
        grid.setSpacing(15)
        main_layout.addLayout(grid)

        # Stats to display (6 total for 2x3)
        stats = ["Torque (Nm)", "Horsepower (HP)", "RPM", "Speed (km/h)", "Boost (PSI)", "Gear"]

        self.value_labels = {}

        for i, stat in enumerate(stats):
            box = QFrame(self)
            box.setObjectName("box")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(10, 10, 10, 10)
            box_layout.setSpacing(5)

            label = QLabel(stat, box)
            label.setObjectName("label")

            value = QLabel("---", box)
            value.setObjectName("value")

            box_layout.addWidget(label)
            box_layout.addWidget(value)

            row = i % 2
            col = i // 2
            grid.addWidget(box, row, col)

            self.value_labels[stat] = value

        # Blink effect for the title
        self._blink = True
        self.timer = QTimer()
        self.timer.timeout.connect(self.blink_title)
        self.timer.start(600)

    def blink_title(self):
        self._blink = not self._blink
        color = "#ff0000" if self._blink else "#990000"
        self.title.setStyleSheet(f"""
            color: {color};
            font-weight: bold;
            font-size: 36px;
            font-family: 'Arial Black', Arial, sans-serif;
        """)

    def update_values(self, torque, hp, rpm, speed, boost, gear):
        self.value_labels["Torque (Nm)"].setText(f"{torque:.1f}")
        self.value_labels["Horsepower (HP)"].setText(f"{hp:.1f}")
        self.value_labels["RPM"].setText(f"{rpm}")
        self.value_labels["Speed (km/h)"].setText(f"{speed:.1f}")
        self.value_labels["Boost (PSI)"].setText(f"{boost:.1f}")
        self.value_labels["Gear"].setText(str(gear))


def start():
    app = QApplication(sys.argv)
    window = ECUGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    start()
