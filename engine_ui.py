import sys
import math
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
from PyQt6.QtWidgets import QApplication, QWidget


class V6EngineWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("V6 Engine Side View - 2 Pistons")
        self.resize(600, 400)

        # Engine parameters
        self.rpm = 1000  # Hardcoded RPM, modify this for speed
        self.crank_radius = 40  # Radius of crank throw
        self.rod_length = 120  # Connecting rod length
        self.stroke = self.crank_radius * 2
        self.bank_angle_deg = 60  # V6 typical bank angle
        self.bank_angle_rad = math.radians(self.bank_angle_deg)
        self.crank_angle_deg=0

        # Center point (crankshaft center)
        self.center_x = 300
        self.center_y = 300

        # Precompute piston phases (in degrees) for 2 pistons in V6 firing order simplification
        self.phases_deg = [0, 120]  # Simplified piston phase difference

        # Timer for animation
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)  # ~33 fps

        self.elapsed_ms = 0

    def update_animation(self):
        self.elapsed_ms += 30
        # Increase crank angle according to RPM and elapsed time
        # RPM to degrees per ms: rpm * 360 degrees / 60000 ms
        self.crank_angle_deg = (self.elapsed_ms * self.rpm * 360 / 60000) % 360
        self.update()

    def rotate_180(self, x, y):
        # Rotate point 180 degrees around center (flip upside down)
        return (2 * self.center_x - x, 2 * self.center_y - y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw crankshaft center
        pen = QPen(QColor(0, 0, 0), 4)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(50, 50, 50)))
        painter.drawEllipse(QPointF(self.center_x, self.center_y), 10, 10)

        # Draw each bank piston (2 pistons)
        # Bank 1 angle = +bank_angle/2, Bank 2 angle = -bank_angle/2 for symmetry
        bank_angles = [self.bank_angle_rad / 2, -self.bank_angle_rad / 2]

        for i in range(2):
            bank_angle = bank_angles[i]
            phase = (self.crank_angle_deg + self.phases_deg[i]) % 360
            self.draw_bank(painter, bank_angle, phase)

    def draw_bank(self, painter, bank_angle_rad, phase_deg):
        # Compute crank throw position for this piston
        crank_angle_rad = math.radians(phase_deg)

        # Crank throw position relative to crankshaft center
        crank_x = self.crank_radius * math.cos(crank_angle_rad)
        crank_y = self.crank_radius * math.sin(crank_angle_rad)

        # Rotate crank throw by bank angle around crank center (crank journal position)
        crank_pos_x = self.center_x + math.sin(bank_angle_rad) * crank_y + crank_x * math.cos(bank_angle_rad)
        crank_pos_y = self.center_y + math.cos(bank_angle_rad) * crank_y - crank_x * math.sin(bank_angle_rad)

        # Calculate piston position along cylinder axis
        # Use law of cosines for rod length and crank throw to find piston displacement along cylinder axis
        # Piston displacement s = crank_radius * cos(theta) + sqrt(rod_length^2 - crank_radius^2 * sin^2(theta))
        theta = crank_angle_rad
        r = self.crank_radius
        l = self.rod_length

        piston_disp = r * math.cos(theta) + math.sqrt(l ** 2 - (r * math.sin(theta)) ** 2)

        # Cylinder axis unit vector (along bank angle)
        axis_x = math.sin(bank_angle_rad)
        axis_y = math.cos(bank_angle_rad)

        # Cylinder base (bottom of stroke) location
        cylinder_base_x = self.center_x + axis_x * (self.stroke / 2 + 10)
        cylinder_base_y = self.center_y + axis_y * (self.stroke / 2 + 10)

        # Piston position along cylinder axis, moving UP towards crankshaft
        piston_x = cylinder_base_x - axis_x * piston_disp
        piston_y = cylinder_base_y - axis_y * piston_disp

        # Rotate all points 180 degrees to flip engine upright
        crank_pos_x, crank_pos_y = self.rotate_180(crank_pos_x, crank_pos_y)
        piston_x, piston_y = self.rotate_180(piston_x, piston_y)
        cylinder_base_x, cylinder_base_y = self.rotate_180(cylinder_base_x, cylinder_base_y)

        # Draw connecting rod
        pen_rod = QPen(QColor(200, 150, 50), 6)
        painter.setPen(pen_rod)
        painter.drawLine(crank_pos_x, crank_pos_y, piston_x, piston_y)

        # Draw crank throw (small circle)
        painter.setBrush(QBrush(QColor(100, 100, 100)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(crank_pos_x, crank_pos_y), 8, 8)

        # Draw piston (rectangle)
        piston_width = 40
        piston_height = 30
        painter.setBrush(QBrush(QColor(180, 180, 180)))
        painter.setPen(QPen(QColor(50, 50, 50), 2))

        rect_x = piston_x - piston_width / 2
        rect_y = piston_y - piston_height / 2
        painter.drawRect(rect_x, rect_y, piston_width, piston_height)

        # Draw cylinder (rectangle) along bank axis at base position
        cyl_width = piston_width + 10
        cyl_height = self.stroke + 20

        # Calculate rectangle corners of cylinder
        # Width vector (perpendicular to bank axis)
        width_dx = math.cos(bank_angle_rad + math.pi / 2) * cyl_width / 2
        width_dy = math.sin(bank_angle_rad + math.pi / 2) * cyl_width / 2

        # Length vector (along negative bank axis, up toward crank)
        length_dx = -axis_x * cyl_height
        length_dy = -axis_y * cyl_height

        # 4 corners of cylinder rectangle
        p1 = QPointF(cylinder_base_x - width_dx, cylinder_base_y - width_dy)
        p2 = QPointF(cylinder_base_x + width_dx, cylinder_base_y + width_dy)
        p3 = QPointF(cylinder_base_x + width_dx + length_dx, cylinder_base_y + width_dy + length_dy)
        p4 = QPointF(cylinder_base_x - width_dx + length_dx, cylinder_base_y - width_dy + length_dy)

        # Draw cylinder
        painter.setBrush(QBrush(QColor(90, 90, 90, 180)))
        painter.setPen(QPen(QColor(150, 150, 150), 3))
        painter.drawPolygon(p1, p2, p3, p4)


def main():
    app = QApplication(sys.argv)
    window = V6EngineWidget()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
