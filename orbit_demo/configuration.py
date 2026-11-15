"""Transactional spacecraft/model configuration, outside the resource sidebar."""
from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import Qt,QDateTime,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,
    QLabel,QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QDateTimeEdit,QPlainTextEdit,
    QPushButton,QFileDialog,QDialogButtonBox)
from .mechanics import Elements,PRESETS
from .propagators import DEFAULT_EPOCH,DEMO_TLE
from .resources import create_single,create_walker,parse_tle_catalog,is_sgp4,MAX_SPACECRAFT
from .workers import LatestWorker


def build_spec(spec):
    kind,args = spec
    if kind=='single': return [create_single(*args)]
    if kind=='walker': return create_walker(*args)
    if kind=='file':
        path = Path(args[0])
        if path.stat().st_size>8_000_000: raise ValueError('TLE 文件不得超过 8 MB。')
        text = path.read_text(encoding='utf-8-sig')
        return text,parse_tle_catalog(text)
    return parse_tle_catalog(args[0])


def number(low,high,value,decimals=2):
    spin = QDoubleSpinBox()
    spin.setRange(low,high)
    spin.setDecimals(decimals)
    spin.setValue(value)
    return spin


class ConfigurationDialog(QDialog):
    def __init__(self,parent=None,selected=None,constellation=None):
        super().__init__(parent)
        self.setWindowTitle("模型与航天器配置")
        self.resize(720,740)
        self.result_resources = None
        self.constellation_id = constellation[0].constellation_id if constellation else None
        self.worker = LatestWorker('configuration-import',self)
        self.poller = QTimer(self)
        self.poller.timeout.connect(self.poll_result)
        self.poller.start(30)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("单星 / Walker 使用二体模型；TLE 使用 SGP4。保存前统一校验，取消不会修改场景。"))
        self.operation = QComboBox()
        self.operation.addItem("替换全部航天器","replace")
        self.operation.addItem("追加到当前场景","append")
        if selected is not None:
            self.operation.addItem("替换当前选中的航天器","selected")
        layout.addWidget(self.operation)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs,1)
        single = QWidget()
        form = QFormLayout(single)
        self.name = QLineEdit(selected.name if selected else "Satellite-1")
        form.addRow("名称",self.name)
        self.presets = QComboBox()
        self.presets.addItems(PRESETS)
        form.addRow("轨道预设",self.presets)
        source = getattr(selected.model,"source",selected.model) if selected else None
        elements = source.elements if source is not None and hasattr(source,"elements") else Elements()
        self.fields = {}
        for key,title,low,high,digits in [("a","半长轴 a / km",6500,100000,2),("e","偏心率 e",0,.95,5),
                ("inclination","倾角 i / °",0,180,2),("raan","升交点赤经 Ω / °",0,360,2),
                ("arg_periapsis","近地点幅角 ω / °",0,360,2),("true_anomaly","初始真近点角 ν / °",0,360,2)]:
            self.fields[key] = number(low,high,getattr(elements,key),digits)
            form.addRow(title,self.fields[key])
        self.epoch = QDateTimeEdit()
        self.epoch.setTimeSpec(Qt.TimeSpec.UTC)
        self.epoch.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.epoch.setDateTime(QDateTime.fromString((source.epoch if source else DEFAULT_EPOCH).isoformat(),Qt.DateFormat.ISODate))
        self.epoch.setCalendarPopup(True)
        epoch_row = QHBoxLayout()
        epoch_row.addWidget(QLabel("单星 / Walker 历元 UTC"))
        epoch_row.addWidget(self.epoch,1)
        layout.insertLayout(2,epoch_row)
        self.tabs.addTab(single,"单星 · 二体")
        self.presets.currentTextChanged.connect(self.load_preset)

        walker = QWidget()
        wf = QFormLayout(walker)
        self.walker_name = QLineEdit("Walker")
        self.walker_kind = QComboBox()
        self.walker_kind.addItems(["Delta","Star"])
        self.total,self.planes,self.phasing = QSpinBox(),QSpinBox(),QSpinBox()
        for widget,low,high,value in [(self.total,1,MAX_SPACECRAFT,24),(self.planes,1,MAX_SPACECRAFT,6),(self.phasing,0,MAX_SPACECRAFT-1,1)]:
            widget.setRange(low,high)
            widget.setValue(value)
        self.altitude = number(100,90000,550)
        self.inclination = number(0,180,53)
        self.raan = number(0,360,0)
        self.phase = number(0,360,0)
        for title,widget in [("星座名称",self.walker_name),("类型",self.walker_kind),("总星数 T",self.total),
                 ("轨道面数 P",self.planes),("相位因子 F",self.phasing),("圆轨道高度 / km",self.altitude),
                 ("倾角 / °",self.inclination),("首轨道面 Ω / °",self.raan),("首星相位 / °",self.phase)]:
            wf.addRow(title,widget)
        note = QLabel("T 必须能被 P 整除；0 ≤ F < P。\nDelta 的轨道面分布范围为 360°，Star 为 180°。\n圆轨道、二体传播；历元使用上方 UTC 设置。\n以星座名称建立分组；全部成员共用轨道颜色，可在树中右键设置。")
        note.setWordWrap(True)
        wf.addRow(note)
        self.tabs.addTab(walker,"Walker 星座")

        tle_page = QWidget()
        tl = QVBoxLayout(tle_page)
        row = QHBoxLayout()
        load = QPushButton("读取 TLE 文件…")
        row.addWidget(load)
        self.file_label = QLabel("支持两行 / 三行格式、多颗卫星、UTF-8 文本")
        row.addWidget(self.file_label,1)
        tl.addLayout(row)
        self.tle = QPlainTextEdit(DEMO_TLE)
        self.tle.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        tl.addWidget(self.tle,1)
        tl.addWidget(QLabel("使用文件中的 TLE 历元，不把六根数转换成 TLE；内置示例为 2000 年历史数据。"))
        self.tabs.addTab(tle_page,"TLE 文件 · SGP4")
        if constellation:
            spec = constellation[0].walker_spec
            name,total,planes,phasing,altitude,inclination,raan,phase,kind,epoch = spec
            self.walker_name.setText(name)
            for widget,value in [(self.total,total),(self.planes,planes),(self.phasing,phasing),
                    (self.altitude,altitude),(self.inclination,inclination),(self.raan,raan),(self.phase,phase)]:
                widget.setValue(value)
            self.walker_kind.setCurrentText(kind)
            self.epoch.setDateTime(QDateTime.fromString(epoch.isoformat(),Qt.DateFormat.ISODate))
            self.operation.clear()
            self.operation.addItem('更新选中的 Walker 星座','constellation')
            self.tabs.setCurrentIndex(1)
            self.tabs.setTabEnabled(0,False)
            self.tabs.setTabEnabled(2,False)
            self.setWindowTitle('配置 Walker 星座')
            note.setText(note.text()+'\n保存后按上述参数重新生成本星座全部成员，保留星座配色。')
        if not constellation and source is not None and is_sgp4(source):
            self.tle.setPlainText(selected.name+'\n'+source.tle)
            self.tabs.setCurrentIndex(2)
        load.clicked.connect(self.load_file)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #ffb478")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.buttons = buttons

    def load_preset(self,name):
        for key,widget in self.fields.items():
            widget.setValue(getattr(PRESETS[name],key))

    def read_tle_file(self,path):
        if Path(path).stat().st_size > 8_000_000:
            raise ValueError("TLE 文件过大，请使用不超过 8 MB 的文本文件。")
        text = Path(path).read_text(encoding="utf-8-sig")
        records = parse_tle_catalog(text)
        self.tle.setPlainText(text)
        self.file_label.setText(f"{Path(path).name} · {len(records)} 颗")
        return records

    def load_file(self):
        path,_ = QFileDialog.getOpenFileName(self,"读取 TLE 文件","","TLE 文本 (*.tle *.txt);;所有文件 (*)")
        if path:
            self.error.setText('正在后台读取和校验 TLE…')
            self.worker.submit(('file',path),build_spec,('file',(path,)))

    def build_resources(self):
        return build_spec(self.spec())

    def spec(self):
        epoch = datetime.fromtimestamp(self.epoch.dateTime().toSecsSinceEpoch(),timezone.utc)
        if self.tabs.currentIndex() == 0:
            return 'single',(self.name.text(),Elements(**{key:w.value() for key,w in self.fields.items()}),epoch)
        if self.tabs.currentIndex() == 1:
            return 'walker',(self.walker_name.text(),self.total.value(),self.planes.value(),self.phasing.value(),
                self.altitude.value(),self.inclination.value(),self.raan.value(),self.phase.value(),self.walker_kind.currentText(),epoch)
        return 'tle',(self.tle.toPlainText(),)

    def validate_and_accept(self):
        try:
            spec = self.spec()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.error.setText('正在后台生成 / 校验资源…')
        self.worker.submit(('build',self.operation.currentData()),build_spec,spec)

    def poll_result(self):
        result = self.worker.take()
        if result is None: return
        key,value,error = result
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        if error:
            self.error.setText(str(error))
            return
        if key[0]=='file':
            text,records = value
            self.tle.setPlainText(text)
            self.file_label.setText(f'{Path(key[1]).name} · {len(records)} 颗')
            self.error.clear()
        else:
            if key[1]=='selected' and len(value)!=1:
                self.error.setText('替换选中航天器时只能提交一颗卫星。')
                return
            self.result_resources = value
            self.accept()

    def done(self,result):
        self.poller.stop()
        self.worker.stop()
        super().done(result)
