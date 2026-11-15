"""Spherical subsatellite coordinates, using the same GMST as the 3D globe.

TEME -> Earth-fixed neglects polar motion and uses UTC for UT1. The two-body
epoch frame is treated as mean-of-date over the short demo interval, as in 3D.
Latitude here is geocentric latitude, not WGS84 geodetic latitude.
"""
import math
from pathlib import Path
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QImage
from PySide6.QtWidgets import QWidget
from .environment import earth_rotation,night_alpha,terminator_points
from .batch import map_coordinates
from .map_raster import image_from_rgba,raster_points
from .resources import GridSettings


def subsatellite_point(position, utc):
    x,y,z = np.asarray(position,dtype=float)
    longitude = (math.degrees(math.atan2(y,x)-earth_rotation(utc))+180)%360-180
    latitude = math.degrees(math.atan2(z,math.hypot(x,y)))
    return longitude,latitude


def split_at_dateline(points):
    """Split polyline at +/-180 degrees, interpolating both map-edge endpoints."""
    if len(points) == 0:
        return []
    segments = [[tuple(points[0])]]
    for lon,lat in points[1:]:
        prev_lon,prev_lat = segments[-1][-1]
        delta = lon-prev_lon
        if abs(delta) > 180:
            adjusted = lon-360 if delta > 180 else lon+360
            edge = -180.0 if delta > 180 else 180.0
            weight = (edge-prev_lon)/(adjusted-prev_lon)
            edge_lat = prev_lat+weight*(lat-prev_lat)
            segments[-1].append((edge,edge_lat))
            segments.append([(-edge,edge_lat)])
        segments[-1].append((lon,lat))
    return segments


def sample_groundtrack(model, start, stop, count=361):
    return [subsatellite_point(model.state(t)[0],model.utc(t))
            for t in np.linspace(start,stop,count)]


class GroundTrackView(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(480,280)
        self.texture = QPixmap(str(Path(__file__).resolve().parent.parent/"assets"/"earth_day.png"))
        self.model = None
        self.seconds = 0.0
        self.current_point = (0.,0.)
        self.future = []
        self.past = []
        self._cache_key = None
        self.error = ""
        self.grid_settings = GridSettings()
        self.show_earth = True
        self.resources = []
        self.active_id = None
        self.track_image = QImage()
        self.point_image = QImage()
        self.stations = []
        self.show_night = True
        self.night_key = None
        self.night_image = QImage()
        self.terminator_segments = []

    def update_state(self,model,seconds,position):
        self.model,self.seconds = model,seconds
        self.current_point = subsatellite_point(position,model.utc(seconds))
        self.update()

    def update_resources(self,resources,active_id):
        self.resources,self.active_id = resources,active_id
        self.colors = np.asarray([c.color for c in resources],dtype=np.float32)
        self.selected_index = next((i for i,c in enumerate(resources) if c.uid==active_id),None)
        self.active = resources[self.selected_index] if self.selected_index is not None else None
        if not resources: self.clear_batches()
        self.update()

    def apply_frame(self,frame,visibility):
        if self.model is None:
            return
        mask = visibility[:,0]&frame.valid
        mask[self.selected_index] = False
        points = map_coordinates(frame.positions[mask],earth_rotation(self.model.utc(frame.seconds)))
        self.point_image = raster_points(points,self.colors[mask])
        self.update()

    def apply_geometry(self,result):
        self.track_image = result['image']
        self.update()

    def clear_batches(self):
        self.point_image = QImage()
        self.track_image = QImage()
        self.update()

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(),QColor("#0b1421"))
        available_width,available_height = self.width()-82,self.height()-100
        width = min(available_width,available_height*2)
        height = width/2
        area = QRectF((self.width()-width)/2,(self.height()-height)/2-8,width,height)
        def project(lon,lat):
            return QPointF(area.left()+(lon+180)/360*width,area.top()+(90-lat)/180*height)
        if self.show_earth and not self.texture.isNull():
            painter.drawPixmap(area,self.texture,QRectF(self.texture.rect()))
        painter.fillRect(area,QColor(3,12,24,35))
        if self.show_night and self.show_earth and self.model is not None:
            utc = self.model.utc(self.seconds)
            key = int(utc.timestamp()//30)
            if key != self.night_key:
                alpha = night_alpha(utc)
                rgba = np.zeros((*alpha.shape,4),dtype=np.uint8)
                rgba[:,:,:3] = [8,14,32]
                rgba[:,:,3] = alpha
                self.night_image = image_from_rgba(rgba)
                coordinates = map_coordinates(terminator_points(utc),earth_rotation(utc))
                self.terminator_segments = split_at_dateline(coordinates*np.array([360,-180])+np.array([-180,90]))
                self.night_key = key
            painter.drawImage(area,self.night_image)
        settings = self.grid_settings
        if settings.visible and self.show_earth:
            color = QColor.fromRgbF(*settings.color,.48)
            painter.setPen(QPen(color,settings.width))
            for lon in range(-180,181,settings.spacing):
                painter.drawLine(project(lon,-90),project(lon,90))
            for lat in range(-90,91,settings.spacing):
                painter.drawLine(project(-180,lat),project(180,lat))
            if settings.equator:
                painter.setPen(QPen(QColor.fromRgbF(.65,.85,.9,.65),settings.width*1.5))
                painter.drawLine(project(-180,0),project(180,0))
        if self.show_night and self.show_earth and self.model is not None:
            painter.save()
            painter.setClipRect(area)
            for segment in self.terminator_segments:
                path = QPainterPath(project(*segment[0]))
                for point in segment[1:]: path.lineTo(project(*point))
                painter.setPen(QPen(QColor(20,27,40,210),4.0))
                painter.drawPath(path)
                painter.setPen(QPen(QColor('#f3cf87'),1.6))
                painter.drawPath(path)
            painter.restore()
        for lon in range(-180,181,60):
            painter.setPen(QColor("#91a6bd"))
            painter.drawText(QRectF(project(lon,-90).x()-28,area.bottom()+7,56,20),Qt.AlignmentFlag.AlignCenter,f"{lon}°")
        for lat in range(-60,61,30):
            painter.setPen(QColor("#91a6bd"))
            painter.drawText(QRectF(area.left()-43,project(-180,lat).y()-10,38,20),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f"{lat}°")
        painter.save()
        painter.setClipRect(area)
        active = getattr(self,'active',None)
        if not self.track_image.isNull():
            painter.drawImage(area,self.track_image)
        if not self.point_image.isNull():
            painter.drawImage(area,self.point_image)
        for station in self.stations:
            if not station.visible:
                continue
            point = project(station.longitude,station.latitude)
            painter.setPen(QPen(QColor('#ffe19b'),1.5))
            painter.setBrush(QColor('#d5a64b'))
            painter.drawRect(QRectF(point.x()-4,point.y()-4,8,8))
            painter.drawText(point+QPointF(7,-6),station.name)
        if self.model and active is not None and active.body:
            point = project(*self.current_point)
            painter.setPen(QPen(QColor("#fff0d5"),1.5))
            painter.setBrush(QColor("#ffad55"))
            painter.drawEllipse(point,5,5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255,173,85,130),1))
            painter.drawEllipse(point,10,10)
        painter.restore()
        painter.setPen(QPen(QColor("#30445d"),1))
        painter.drawRect(area)
        painter.setPen(QColor("#b4dce4"))
        lon,lat = self.current_point
        text = self.error or (f"当前星下点    经度 {lon:+.3f}°    /    纬度 {lat:+.3f}°" if active is not None else '未选中航天器')
        painter.drawText(QRectF(20,10,self.width()-40,25),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
        painter.setPen(QColor("#8497b0"))
        painter.drawText(QRectF(20,self.height()-30,self.width()-40,24),Qt.AlignmentFlag.AlignCenter,
                         "等距经纬投影 · 球面星下点 · 东经 / 北纬为正")
