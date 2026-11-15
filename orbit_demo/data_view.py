"""Linked orbital charts with an optional external chart-host interface."""
from dataclasses import dataclass
from datetime import datetime
import math
import numpy as np
from PySide6.QtCore import Qt, Signal,QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QComboBox, QScrollArea, QGridLayout
from .telemetry import state_values, sample_telemetry
from .charts import TimeSeriesPlot
from .workers import LatestWorker
from .resources import is_sgp4,AlignedModel
from .propagators import SGP4Model


def chart_samples(model,start,stop,count):
    if is_sgp4(model):
        model = AlignedModel(SGP4Model(model.tle),model.epoch)
    return sample_telemetry(model,start,stop,count)


@dataclass(frozen=True)
class SimulationSnapshot:
    model_name: str
    frame: str
    epoch_utc: datetime
    utc: datetime
    seconds: float
    position_km: tuple[float,float,float]
    velocity_km_s: tuple[float,float,float]
    spacecraft_name: str = ""


class DataView(QFrame):
    # Charts can subscribe to this signal; snapshots are immutable and in km/s.
    state_updated = Signal(object)
    time_requested = Signal(float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.latest_state = None
        self.model = None
        self.cache_key = None
        self.sample_count = 0
        self.requested_key = None
        self.worker = LatestWorker('telemetry-analysis',self)
        self.poller = QTimer(self)
        self.poller.timeout.connect(self.poll_result)
        self.poller.start(30)
        self.chart_widget = None
        self.host_layout = QVBoxLayout(self)
        self.host_layout.setContentsMargins(15,12,15,12)
        self.dashboard = QWidget()
        layout = QVBoxLayout(self.dashboard)
        layout.setContentsMargins(0,0,0,0)
        header = QHBoxLayout()
        self.caption = QLabel("轨道数据")
        self.caption.setObjectName("eyebrow")
        header.addWidget(self.caption,1)
        header.addWidget(QLabel("显示区间"))
        self.span_combo = QComboBox()
        self.span_combo.addItem("1 个周期",1)
        self.span_combo.addItem("3 个周期",3)
        header.addWidget(self.span_combo)
        layout.addLayout(header)
        self.time_label = QLabel("")
        self.time_label.setObjectName("muted")
        layout.addWidget(self.time_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.plots_layout = QGridLayout(container)
        self.plots_layout.setContentsMargins(0,0,8,0)
        self.plots_layout.setSpacing(10)
        self.plots = {}
        specs = [("altitude","轨道高度 · km","#4dd5df",False),
                 ("speed","惯性速度 |v| · km/s","#ffb65c",False),
                 ("a","半长轴 a · km","#5ba5f5",False),("e","偏心率 e","#b493f4",False),
                 ("inclination","倾角 i · °","#55d0ac",False),("raan","升交点赤经 Ω · °","#6db9ed",True),
                 ("arg_periapsis","近地点幅角 ω · °","#e69cc8",True),("true_anomaly","真近点角 ν · °","#eed081",True)]
        for index,(key,title,color,wrapped) in enumerate(specs):
            plot = TimeSeriesPlot(title,color,wrapped)
            plot.time_requested.connect(self.time_requested.emit)
            self.plots[key] = plot
            self.plots_layout.addWidget(plot,index//2,index%2)
        scroll.setWidget(container)
        layout.addWidget(scroll,1)
        self.note = QLabel("横轴：历元后时间 / min · 点击曲线定位时间 · 六根数为瞬时密切根数\n圆/赤道轨道的退化角显示未定义；角度在 0°/360° 处断线。")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ffb478")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.host_layout.addWidget(self.dashboard)
        self.span_combo.currentIndexChanged.connect(self.refresh_charts)

    def set_model(self,model):
        if self.model is not model:
            self.model = model
            self.cache_key = None
            for plot in self.plots.values():
                plot.set_series(np.array([0.,model.period]),np.array([np.nan,np.nan]))

    def clear_state(self):
        self.model = self.latest_state = self.cache_key = self.requested_key = None
        self.caption.setText('暂无航天器数据')
        self.time_label.clear()
        self.error_label.hide()
        for plot in self.plots.values():
            plot.set_series(np.array([0.,1.]),np.array([np.nan,np.nan]))
            plot.set_cursor(0.,math.nan)
        self.state_updated.emit(None)

    def update_state(self,snapshot):
        self.latest_state = snapshot
        self.state_updated.emit(snapshot)
        if self.isVisible() and self.chart_widget is None:
            self.refresh_charts()

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh_charts()

    def refresh_charts(self,*unused):
        if self.model is None or self.latest_state is None:
            return
        snapshot = self.latest_state
        span = self.model.period*self.span_combo.currentData()
        block = max(0,math.ceil(snapshot.seconds/span)-1)
        key = (id(self.model),self.span_combo.currentData(),block)
        if self.cache_key != key and self.requested_key != key:
            self.requested_key = key
            self.worker.submit(key,chart_samples,self.model,block*span,(block+1)*span,480*self.span_combo.currentData()+1)
        current = state_values(self.model,snapshot.position_km,snapshot.velocity_km_s)
        for name,plot in self.plots.items():
            plot.set_cursor(snapshot.seconds,current[name])
        self.caption.setText(f"{snapshot.spacecraft_name}  /  {snapshot.model_name}  /  {snapshot.frame}")
        self.time_label.setText(f"UTC {snapshot.utc:%Y-%m-%d %H:%M:%S}    ·    T + {snapshot.seconds:,.1f} s    ·    橙色虚线：当前时刻")

    def poll_result(self):
        result = self.worker.take()
        if result is None: return
        key,value,error = result
        if key!=self.requested_key or key[0]!=id(self.model): return
        if error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        times,values,errors = value
        for name,plot in self.plots.items():
            plot.set_series(times,values[name])
        self.cache_key = key
        self.sample_count += 1
        self.error_label.setText(f'{len(errors)} 个采样点传播失败：{errors[0]}' if errors else '')
        self.error_label.setVisible(bool(errors))

    def shutdown(self):
        self.poller.stop()
        self.worker.stop()

    def set_chart_widget(self,widget):
        """Host an external Qt chart widget; pass None to restore built-in plots.

        Ownership transfers to this page. The previous chart is deleted later;
        use latest_state for initial population and state_updated for updates.
        """
        if widget is self.chart_widget:
            return
        if self.chart_widget is not None:
            self.host_layout.removeWidget(self.chart_widget)
            self.chart_widget.deleteLater()
        self.chart_widget = widget
        self.dashboard.setVisible(widget is None)
        if widget is not None:
            self.host_layout.addWidget(widget)
        else:
            self.refresh_charts()
