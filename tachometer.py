import sys
import math
from throttle import MAX_RPM,max_boost,estp,red_line
from PyQt6.QtWidgets import QApplication, QWidget , QHBoxLayout
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPainter, QColor, QPen, QFont


class CircularGauge(QWidget):
    def __init__(self, min_value=0, max_value=int(MAX_RPM), parent=None):
        super().__init__(parent)
        self.min_value = min_value
        self.max_value = max_value
        self.value = min_value

        self.start_angle=225
        self.sweep_angle=270

    def set_value(self, value):
        self.value = max(self.min_value, min(self.max_value, value))
        self.update()

    def paintEvent(self, event):
        
        width = self.width()
        height = self.height()
        radius = min(width, height) // 2 - 30

        center = width // 2, height // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw outer circle
        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawEllipse(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)

        # Ticks and labels
        num_ticks = int(MAX_RPM/1000)
        font = QFont("Arial", 10)
        painter.setFont(font)
        painter.setPen(QPen(Qt.GlobalColor.white, 4))

        for i in range(num_ticks + 1):
            tick_val = self.min_value + i * (self.max_value - self.min_value) // num_ticks
            angle_deg = self.start_angle - (i * self.sweep_angle / num_ticks)
            angle_rad = math.radians(angle_deg)

            # Tick lines
            x1 = center[0] + (radius - 10) * math.cos(angle_rad)
            y1 = center[1] - (radius - 10) * math.sin(angle_rad)
            x2 = center[0] + radius * math.cos(angle_rad)
            y2 = center[1] - radius * math.sin(angle_rad)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            # Labels
            label_radius = radius - 25
            lx = center[0] + label_radius * math.cos(angle_rad)
            ly = center[1] - label_radius * math.sin(angle_rad)
            label_text = str(int(tick_val/1000))
            text_width = painter.fontMetrics().horizontalAdvance(label_text)
            text_height = painter.fontMetrics().height()
            painter.drawText(int(lx - text_width / 2), int(ly + text_height / 4), label_text)

        # Needle
        angle = self.start_angle - ((self.value - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        angle_rad = math.radians(angle)
        needle_length = radius - 30
        x = center[0] + needle_length * math.cos(angle_rad)
        y = center[1] - needle_length * math.sin(angle_rad)
        painter.setPen(QPen(QColor("red"), 4))
        painter.drawLine(center[0], center[1], int(x), int(y))

        # RedLine
        redline_start = int(red_line)
        redline_end = int(MAX_RPM)
        start_angle_deg = self.start_angle - ((redline_start - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        end_angle_deg = self.start_angle - ((redline_end - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle


        rect_size = radius * 2
        arc_rect = center[0] - radius, center[1] - radius, rect_size, rect_size

        painter.setPen(QPen(QColor("red"), 5))
        painter.drawArc(*arc_rect,
                int(end_angle_deg * 16),
                int((start_angle_deg - end_angle_deg) * 16))


        # Center cap
        painter.setBrush(QColor("black"))
        painter.drawEllipse(center[0] - 5, center[1] - 5, 10, 10)


class SpeedGauge(QWidget):
    def __init__(self, min_value=0, max_value=int(estp), parent=None):
        super().__init__(parent)
        self.min_value = min_value
        self.max_value = max_value
        self.value = min_value

        self.start_angle=225
        self.sweep_angle=290
        self.setMinimumSize(300, 300)

    def set_value(self, value):
        self.value = max(self.min_value, min(self.max_value, value))
        self.update()

    def paintEvent(self, event):
        width = self.width()
        height = self.height()
        radius = min(width, height) // 2 - 30

        center = width // 2, height // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)


        # Ticks and labels
        num_ticks = int(estp/10)
        font = QFont("Arial", 10)
        painter.setFont(font)
        painter.setPen(QPen(Qt.GlobalColor.white, 4))

        for i in range(num_ticks + 1):
            tick_val = self.min_value + (i * (self.max_value - self.min_value) // num_ticks)
            angle_deg = self.start_angle - (i * self.sweep_angle / num_ticks)
            angle_rad = math.radians(angle_deg)

            # Tick lines
            x1 = center[0] + (radius - 10) * math.cos(angle_rad)
            y1 = center[1] - (radius - 10) * math.sin(angle_rad)
            x2 = center[0] + radius * math.cos(angle_rad)
            y2 = center[1] - radius * math.sin(angle_rad)
            if int(tick_val/10)%2==1:
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
            else:
                painter.setPen(QPen(Qt.GlobalColor.white, 4))
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            # Labels
            label_radius = radius - 25
            lx = center[0] + label_radius * math.cos(angle_rad)
            ly = center[1] - label_radius * math.sin(angle_rad)
            if int(tick_val/10)%4==0:
                font=QFont("Arial",10)
                painter.setFont(font)
            else:
                font=QFont("Arial",8)
                painter.setFont(font)

            if int(tick_val/10)%2==0:
                label_text = str(int(tick_val))
                text_width = painter.fontMetrics().horizontalAdvance(label_text)
                text_height = painter.fontMetrics().height()
                painter.drawText(int(lx - text_width / 2), int(ly + text_height / 4), label_text)

        # Draw outer circle
        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawEllipse(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)

        # Needle
        angle = self.start_angle - ((self.value - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        angle_rad = math.radians(angle)
        needle_length = radius - 30
        x = center[0] + needle_length * math.cos(angle_rad)
        y = center[1] - needle_length * math.sin(angle_rad)
        painter.setPen(QPen(QColor("red"), 4))
        painter.drawLine(center[0], center[1], int(x), int(y))


        # Center cap
        painter.setBrush(QColor("black"))
        painter.drawEllipse(center[0] - 5, center[1] - 5, 10, 10)


from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGridLayout
from PyQt6.QtCore import Qt, QTimer

class RevLight(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)

        self.num_lights = int(MAX_RPM/1000)
        self.max_rpm = int(MAX_RPM)
        self.step = self.max_rpm // self.num_lights

        self.rev_labels = [QLabel(self) for _ in range(self.num_lights)]
        layout = QHBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for label in self.rev_labels:
            label.setFixedSize(40, 40)
            # Make circles with border and default gray background
            label.setStyleSheet("""
                border-radius: 20px;
                border: 2px solid white;
                background-color: gray;
            """)
            layout.addWidget(label)

        self.setLayout(layout)

        # Blinking state for red zone
        self.blinking = False
        self.blink_on = True
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.toggle_blink)

    def toggle_blink(self):
        self.blink_on = not self.blink_on
        for i in range(self.num_lights-1,self.num_lights):  # Last two lights blink
            if self.blink_on:
                color = "red"
            else:
                color = "gray"
            self.rev_labels[i].setStyleSheet(f"""
                border-radius: 20px;
                border: 2px solid white;
                background-color: {color};
            """)

    def set_rpm(self, rpm):
        active_lights = min(self.num_lights, rpm // self.step)

        for i in range(self.num_lights):
            if i < active_lights:
                if i >= 6:
                    color = "red"
                elif i >= 4:
                    color = "yellow"
                else:
                    color = "green"
            else:
                color = "gray"

            self.rev_labels[i].setStyleSheet(f"""
                border-radius: 20px;
                border: 2px solid white;
                background-color: {color};
            """)

        # Start blinking if RPM exceeds 7000
        if rpm >= 7000:
            if not self.blinking:
                self.blinking = True
                self.blink_timer.start(250)
        else:
            if self.blinking:
                self.blinking = False
                self.blink_timer.stop()
                # Reset last two lights color after blinking stops
                for i in range(self.num_lights-2,self.num_lights):
                    color = "red" if rpm >= (i + 1) * self.step else "gray"
                    self.rev_labels[i].setStyleSheet(f"""
                        border-radius: 20px;
                        border: 2px solid white;
                        background-color: {color};
                    """)


class TurboGauge(QWidget):
    def __init__(self, min_value=0, max_value=max_boost, parent=None):
        super().__init__(parent)
        self.min_value = min_value
        self.max_value = max_value
        self.value = min_value

        self.start_angle=225
        self.sweep_angle=290
        self.setMinimumSize(300, 300)

    def set_psi(self, value):
        self.value = max(self.min_value, min(self.max_value, value))
        self.update()
    def paintEvent(self, event):
        width = self.width()
        height = self.height()
        radius = min(width, height) // 2 - 30

        center = width // 2, height // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw outer circle
        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawEllipse(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)

        # Ticks and labels
        num_ticks = int(max_boost)
        font = QFont("Arial", 10)
        painter.setFont(font)
        painter.setPen(QPen(Qt.GlobalColor.white, 4))

        for i in range(num_ticks + 1):
            tick_val = self.min_value + i * (self.max_value - self.min_value) // num_ticks
            angle_deg = self.start_angle - (i * self.sweep_angle / num_ticks)
            angle_rad = math.radians(angle_deg)

            # Tick lines
            x1 = center[0] + (radius - 10) * math.cos(angle_rad)
            y1 = center[1] - (radius - 10) * math.sin(angle_rad)
            x2 = center[0] + radius * math.cos(angle_rad)
            y2 = center[1] - radius * math.sin(angle_rad)
            if int(tick_val)%3==0:
                painter.setPen(QPen(Qt.GlobalColor.white, 4))
            else:
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))


            # Labels
            label_radius = radius - 25
            lx = center[0] + label_radius * math.cos(angle_rad)
            ly = center[1] - label_radius * math.sin(angle_rad)
            if int(tick_val)%3==0:
                label_text = str(int(tick_val))
                text_width = painter.fontMetrics().horizontalAdvance(label_text)
                text_height = painter.fontMetrics().height()
                painter.drawText(int(lx - text_width / 2), int(ly + text_height / 4), label_text)

        # Needle
        angle = self.start_angle - ((self.value - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        angle_rad = math.radians(angle)
        needle_length = radius - 30
        x = center[0] + needle_length * math.cos(angle_rad)
        y = center[1] - needle_length * math.sin(angle_rad)
        painter.setPen(QPen(QColor("red"), 4))
        painter.drawLine(center[0], center[1], int(x), int(y))


        # Center cap
        painter.setBrush(QColor("black"))
        painter.drawEllipse(center[0] - 5, center[1] - 5, 10, 10)





from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QPainter, QPen, QFont
from PyQt6.QtCore import Qt, QRectF
import sys
import math



class GearDisplay(QWidget):
    def __init__(self, min_value=0, max_value=6, parent=None):
        super().__init__(parent)
        self.min_value = min_value
        self.max_value = max_value
        self.gear = 0

        self.setWindowTitle("Gear Display")
        self.setMinimumSize(300, 300)

        # Remove QLabel, we will paint text ourselves for perfect alignment

        self.setStyleSheet("background-color: transparent;")

    def set_gear(self, gear):
        self.gear = max(self.min_value, min(self.max_value, gear))
        self.update()  # Trigger repaint

    def paintEvent(self, event):
        width = self.width()
        height = self.height()

        # Outer circle radius (biggest)
        outer_radius = min(width, height) // 2 - 2  

        # Inner circle radius (a bit smaller to fit inside outer circle)
        inner_radius = outer_radius - 8  # 8 px smaller radius for the blue circle

        center_x, center_y = width // 2, height // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw outer black circle (solid fill)
        painter.setBrush(QColor("#000000"))  # Black color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center_x - outer_radius, center_y - outer_radius, 2 * outer_radius, 2 * outer_radius)

        # Draw inner blue circle (on top)
        painter.setBrush(QColor("#FF0000"))  # Blue color
        painter.drawEllipse(center_x - inner_radius, center_y - inner_radius, 2 * inner_radius, 2 * inner_radius)

        # Draw black border around the inner circle (optional)
        pen = QPen(Qt.GlobalColor.black, 4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center_x - inner_radius, center_y - inner_radius, 2 * inner_radius, 2 * inner_radius)

        # Draw gear number centered in white with LCD font
        painter.setPen(QColor("#C7C6C6"))
        font_size = inner_radius  # font size relative to inner radius
        font = QFont("DS-Digital", font_size, QFont.Weight.Bold)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        painter.setFont(font)

        gear_text = "N" if self.gear == 0 else str(self.gear)
        rect = QRectF(center_x - inner_radius, center_y - inner_radius, 2 * inner_radius, 2 * inner_radius)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, gear_text)


class TempGauge(QWidget):
    def __init__(self, min_value=0, max_value=120, parent=None):
        super().__init__(parent)
        self.min_value = min_value
        self.max_value = max_value
        self.value = min_value

        self.start_angle=225
        self.sweep_angle=120
        self.setMinimumSize(300, 300)

    def set_temp(self, value):
        self.value = max(self.min_value, min(self.max_value, value))
        self.update()

    def paintEvent(self, event):
        width = self.width()
        height = self.height()
        radius = min(width, height) // 2 - 30

        center = width // 2, height // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw outer circle
        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawEllipse(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)

        # Ticks and labels
        num_ticks = 6
        font = QFont("Arial", 10)
        painter.setFont(font)
        painter.setPen(QPen(Qt.GlobalColor.white, 4))

        for i in range(num_ticks + 1):
            tick_val = self.min_value + i * (self.max_value - self.min_value) // num_ticks
            angle_deg = self.start_angle - (i * self.sweep_angle / num_ticks)
            angle_rad = math.radians(angle_deg)

            # Tick lines
            x1 = center[0] + (radius - 10) * math.cos(angle_rad)
            y1 = center[1] - (radius - 10) * math.sin(angle_rad)
            x2 = center[0] + radius * math.cos(angle_rad)
            y2 = center[1] - radius * math.sin(angle_rad)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            # Labels
            label_radius = radius - 25
            lx = center[0] + label_radius * math.cos(angle_rad)
            ly = center[1] - label_radius * math.sin(angle_rad)
            if int(tick_val%20==0):
                label_text = str(int(tick_val))
                text_width = painter.fontMetrics().horizontalAdvance(label_text)
                text_height = painter.fontMetrics().height()
                painter.drawText(int(lx - text_width / 2), int(ly + text_height / 4), label_text)

        # Needle
        angle = self.start_angle - ((self.value - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        angle_rad = math.radians(angle)
        needle_length = radius - 30
        x = center[0] + needle_length * math.cos(angle_rad)
        y = center[1] - needle_length * math.sin(angle_rad)
        painter.setPen(QPen(QColor("red"), 4))
        painter.drawLine(center[0], center[1], int(x), int(y))

        # RedLine
        redline_start = 100
        redline_end = 120
        start_angle_deg = self.start_angle - ((redline_start - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle
        end_angle_deg = self.start_angle - ((redline_end - self.min_value) / (self.max_value - self.min_value)) * self.sweep_angle


        rect_size = radius * 2
        arc_rect = center[0] - radius, center[1] - radius, rect_size, rect_size

        painter.setPen(QPen(QColor("red"), 5))
        painter.drawArc(*arc_rect,
                int(end_angle_deg * 16),
                int((start_angle_deg - end_angle_deg) * 16))


        # Center cap
        painter.setBrush(QColor("black"))
        painter.drawEllipse(center[0] - 5, center[1] - 5, 10, 10)



if __name__ == "__main__":
    app = QApplication(sys.argv)
    display = CircularGauge()
    display.set_value(7200)  # Set initial gear
    display.show()
    sys.exit(app.exec())