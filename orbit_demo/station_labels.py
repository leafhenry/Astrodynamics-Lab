"""Qt labels projected with the OSG camera; Earth occludes back-side stations."""
import math
import numpy as np
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QWidget
from .environment import earth_rotation
from .mechanics import EARTH_RADIUS


def project_station(position,eye,width,height,earth_visible=True):
    position,eye = np.asarray(position,float),np.asarray(eye,float)
    offset = position-eye
    distance = np.linalg.norm(offset)
    direction = offset/distance
    if earth_visible:
        along = np.dot(eye,direction)
        discriminant = along*along-np.dot(eye,eye)+1
        if discriminant>=0 and 0 < -along-math.sqrt(discriminant) < distance-1e-6:
            return None
    forward = -eye/np.linalg.norm(eye)
    right = np.cross(forward,[0.,0.,1.])
    right /= np.linalg.norm(right)
    up = np.cross(right,forward)
    depth = np.dot(offset,forward)
    if depth<=.05: return None
    scale = height/(2*math.tan(math.radians(19)))
    x = width/2+np.dot(offset,right)*scale/depth
    y = height/2-np.dot(offset,up)*scale/depth
    return (float(x),float(y)) if 0<=x<=width and 0<=y<=height else None


class StationLabels(QWidget):
    def __init__(self,view):
        super().__init__(view)
        self.view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet('background: transparent;')
        self.visible_names = []

    def paintEvent(self,event):
        view = self.view
        self.visible_names = []
        if not view.ready or view.elements is None: return
        angle = earth_rotation(view.elements.utc(view.seconds))
        eye = view.camera_eye()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = painter.fontMetrics()
        for station in view.stations:
            if not station.visible: continue
            position = station.position(angle)/EARTH_RADIUS*1.002
            point = project_station(position,eye,self.width(),self.height(),view.earth.nodeMask!=0)
            if point is None: continue
            x,y = point
            x = max(3,min(x+8,self.width()-metrics.horizontalAdvance(station.name)-3))
            y = max(metrics.ascent()+3,min(y-6,self.height()-3))
            path = QPainterPath()
            path.addText(QPointF(x,y),painter.font(),station.name)
            painter.setPen(QPen(QColor('#101722'),2.5))
            painter.setBrush(QColor('#ffe19b'))
            painter.drawPath(path)
            painter.fillPath(path,QColor('#ffe19b'))
            self.visible_names.append(station.name)
