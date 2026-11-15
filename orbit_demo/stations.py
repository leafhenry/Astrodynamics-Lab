"""Ground-station configuration (spherical Earth, geographic coordinates)."""
from PySide6.QtWidgets import QDialog,QFormLayout,QLineEdit,QDialogButtonBox,QLabel
from .configuration import number
from .resources import GroundStation


class StationDialog(QDialog):
    def __init__(self,parent=None,station=None):
        super().__init__(parent)
        self.setWindowTitle('测控站配置 · ASTRODYNAMICS LAB')
        self.resize(440,320)
        self.original = station
        self.station = None
        form = QFormLayout(self)
        self.name = QLineEdit(station.name if station else 'Station-1')
        self.longitude = number(-180,180,station.longitude if station else 116.4,5)
        self.latitude = number(-90,90,station.latitude if station else 39.9,5)
        self.altitude = number(0,20,station.altitude_km if station else 0,3)
        for title,field in [('名称',self.name),('经度 / °（东经为正）',self.longitude),('纬度 / °（北纬为正）',self.latitude),('高度 / km',self.altitude)]:
            form.addRow(title,field)
        note = QLabel('球面地球坐标；测控站随地球自转。\n本次提供位置管理与显示，不计算通信覆盖或可见弧段。')
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QLabel('')
        self.error.setStyleSheet('color: #ffb478')
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            self.station = GroundStation(self.name.text().strip(),self.longitude.value(),self.latitude.value(),self.altitude.value())
            if self.original:
                self.station.uid,self.station.visible = self.original.uid,self.original.visible
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()
