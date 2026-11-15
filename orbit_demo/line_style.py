"""Small transactional line-style editor used by resource-tree context menus."""
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QPushButton,QDoubleSpinBox,QLabel,QDialogButtonBox,QColorDialog,QWidget


class LinePreview(QWidget):
    def __init__(self,dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setFixedHeight(45)

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.dialog.color,self.dialog.width.value(),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        painter.drawLine(15,self.height()//2,self.width()-15,self.height()//2)


class LineStyleDialog(QDialog):
    def __init__(self,title,color,width,parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(350,230)
        self.color = QColor.fromRgbF(*color)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.pick_color)
        form.addRow('线条颜色',self.color_button)
        self.width = QDoubleSpinBox()
        self.width.setRange(.5,5)
        self.width.setSingleStep(.5)
        self.width.setValue(width)
        self.width.setSuffix(' px')
        form.addRow('线宽',self.width)
        layout.addLayout(form)
        self.preview = LinePreview(self)
        layout.addWidget(self.preview)
        self.width.valueChanged.connect(lambda value:self.preview.update())
        self.update_color()
        note = QLabel('同步应用于二维和三维；保存后生效。')
        note.setObjectName('muted')
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_color(self):
        self.color_button.setText(self.color.name().upper())
        self.color_button.setStyleSheet(f'background: {self.color.name()}; color: {"#071920" if self.color.lightnessF()>.5 else "white"};')
        self.preview.update()

    def pick_color(self):
        value = QColorDialog.getColor(self.color,self,'轨道颜色')
        if value.isValid():
            self.color = value
            self.update_color()

    def values(self):
        return (self.color.redF(),self.color.greenF(),self.color.blueF()),self.width.value()
