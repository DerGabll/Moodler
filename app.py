from PyQt6.QtWidgets import QPushButton, QMainWindow, QLabel, QVBoxLayout, QWidget, QApplication
from PyQt6.QtCore import Qt
import sys

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setFixedSize(100, 100)
        
        # position top left and change size
        self.setGeometry(0, 0, 700, 700)
        # No title bar
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint )
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Creating Widgets
        self.button_lst = [
            QPushButton("A"),
            QPushButton("B"),
            QPushButton("C"),
            QPushButton("D")
        ]
        self.label = QLabel("Test Text")

        layout = QVBoxLayout()

        #Adding Widgets to layout
        layout.addWidget(self.label)

        for button in self.button_lst:
            button.setStyleSheet("background-color: rgb(32, 32, 32); color: rgb(100, 100, 100)")
            layout.addWidget(button)
        
        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.show()

app = QApplication(sys.argv)
window = MainWindow()
app.exec()
