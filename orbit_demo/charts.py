"""Small native Qt time-series plots with a shared simulation cursor."""
import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class TimeSeriesPlot(QWidget):
    time_requested = Signal(float)

    def __init__(self,title,color,wrapped=False,parent=None):
        super().__init__(parent)
        self.title,self.color,self.wrapped = title,QColor(color),wrapped
        self.times = np.array([0.,1.])
        self.values = np.array([np.nan,np.nan])
        self.cursor = 0.
        self.current_value = math.nan
        self.ymin,self.ymax = 0.,1.
        self.setMinimumSize(280,180)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("点击或拖动图表定位仿真时间；橙色虚线与播放时间同步。")

    def set_series(self,times,values):
        self.times,self.values = times,values
        finite = values[np.isfinite(values)]
        if finite.size:
            low,high = float(finite.min()),float(finite.max())
            span = max(high-low,max(abs(low),abs(high),.01)*.002)
            self.ymin,self.ymax = (low+high)/2-span*.6,(low+high)/2+span*.6
            if self.wrapped and high-low > 180:
                self.ymin,self.ymax = 0.,360.
        else:
            self.ymin,self.ymax = 0.,1.
        self.update()

    def set_cursor(self,seconds,value):
        self.cursor,self.current_value = seconds,value
        self.update()

    def plot_rect(self):
        return QRectF(73,44,max(1,self.width()-90),max(1,self.height()-79))

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#27394f"),1))
        painter.setBrush(QColor("#0e1929"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),7,7)
        painter.setPen(QColor("#dce7f5"))
        painter.drawText(QRectF(12,8,self.width()-24,22),Qt.AlignmentFlag.AlignLeft,self.title)
        value_text = f"{self.current_value:.7g}" if math.isfinite(self.current_value) else "未定义"
        painter.setPen(self.color)
        painter.drawText(QRectF(12,8,self.width()-24,22),Qt.AlignmentFlag.AlignRight,value_text)
        area = self.plot_rect()
        start,stop = self.times[0],self.times[-1]
        def project(t,y):
            return QPointF(area.left()+(t-start)/(stop-start)*area.width(),area.bottom()-(y-self.ymin)/(self.ymax-self.ymin)*area.height())
        font = painter.font()
        font.setPointSizeF(8)
        painter.setFont(font)
        for ratio in (0,.5,1):
            y = area.bottom()-ratio*area.height()
            painter.setPen(QPen(QColor("#24354a"),1))
            painter.drawLine(QPointF(area.left(),y),QPointF(area.right(),y))
            painter.setPen(QColor("#8497b0"))
            tick = self.ymin+ratio*(self.ymax-self.ymin)
            painter.drawText(QRectF(4,y-9,63,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f"{tick:.7g}")
            x = area.left()+ratio*area.width()
            left = min(max(x-32,area.left()),area.right()-64)
            align = Qt.AlignmentFlag.AlignLeft if ratio == 0 else Qt.AlignmentFlag.AlignRight if ratio == 1 else Qt.AlignmentFlag.AlignHCenter
            painter.drawText(QRectF(left,area.bottom()+6,64,20),align|Qt.AlignmentFlag.AlignVCenter,f"{(start+ratio*(stop-start))/60:.2f}")
        painter.save()
        painter.setClipRect(area.adjusted(-1,-1,1,1))
        path = QPainterPath()
        previous = None
        for t,value in zip(self.times,self.values):
            if not math.isfinite(value):
                previous = None
                continue
            point = project(t,value)
            if previous is None or (self.wrapped and abs(value-previous) > 180):
                path.moveTo(point)
            else:
                path.lineTo(point)
            previous = value
        painter.setPen(QPen(self.color,1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        x = project(self.cursor,self.ymin).x()
        painter.setPen(QPen(QColor("#ffb65c"),1,Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x,area.top()),QPointF(x,area.bottom()))
        if math.isfinite(self.current_value):
            painter.setBrush(QColor("#ffb65c"))
            painter.drawEllipse(project(self.cursor,self.current_value),3.2,3.2)
        painter.restore()
        if not np.isfinite(self.values).any():
            painter.setPen(QColor("#8497b0"))
            painter.drawText(area,Qt.AlignmentFlag.AlignCenter,"此区间无定义或无有效数据")

    def _seek(self,event):
        area = self.plot_rect()
        ratio = float(np.clip((event.position().x()-area.left())/area.width(),0,1))
        self.time_requested.emit(float(self.times[0]+ratio*(self.times[-1]-self.times[0])))

    def mousePressEvent(self,event):
        if event.button() == Qt.MouseButton.LeftButton and self.plot_rect().contains(event.position()):
            self._seek(event)

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek(event)
