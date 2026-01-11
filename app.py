from PyQt6.QtWidgets import QPushButton, QMainWindow, QLabel, QVBoxLayout, QWidget, QApplication
import sys

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setFixedSize(100, 100)

        #Create the buttons for the window layout
        self.btn_mult = QPushButton("A")
        self.btn_screenshot = QPushButton("B")
        self.btn_send = QPushButton("C")
        self.btn_exit = QPushButton("D")

        self.label = QLabel("Test Text")
        self.setGeometry(100,1000, 700,700)

        layout = QVBoxLayout()
        layout.addWidget(self.btn_mult)
        layout.addWidget(self.btn_screenshot)
        layout.addWidget(self.btn_send)
        layout.addWidget(self.btn_exit)
        layout.addWidget(self.label)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.show()

app = QApplication(sys.argv)
window = MainWindow()
app.exec()
