import argparse
import csv
import sys
import time
import os
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSlider, QVBoxLayout, QWidget, QTabWidget,QStackedWidget,
)
from .mechanics import EARTH_RADIUS
from .scene import OrbitView
from .propagators import TwoBodyModel, PropagationError
from .environment import solar_position, eclipse
from .groundtrack import GroundTrackView
from .data_view import DataView, SimulationSnapshot
from .resources import Spacecraft,align_resources,is_sgp4
from .resource_panel import ResourcePanel
from .configuration import ConfigurationDialog
from .stations import StationDialog
from .batch import BatchEngine,GeometryEngine
from .geometry_service import GeometryService
from .workers import LatestWorker
from .scene_actions import SceneActions

STYLE = """
QWidget { background: #0b1220; color: #dce7f5; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QMainWindow { background: #0b1220; }
QFrame#panel { background: #111d2d; border: 1px solid #223148; border-radius: 10px; }
QFrame#panel QLabel, QFrame#panel QCheckBox { background: transparent; }
QLabel#eyebrow { color: #56d6dc; font-size: 11px; font-weight: 600; }
QLabel#title { font-size: 25px; font-weight: 700; color: #f0f5fc; }
QLabel#muted { color: #8497b0; font-size: 11px; }
QLabel#section { color: #e5edf8; font-size: 14px; font-weight: 600; }
QLabel#error { color: #ffb478; }
QPushButton { background: #192a40; border: 1px solid #31445f; border-radius: 6px; padding: 8px 13px; }
QPushButton:hover { background: #263d58; border-color: #51bac9; }
QPushButton:disabled { background: #111c2a; border-color: #233246; color: #586b80; }
QPushButton#primary { background: #38bcc5; color: #071920; border: 0; font-weight: bold; }
QPushButton#primary:hover { background: #71d6dc; }
QPushButton:checked { background: #214653; border-color: #45bdc6; color: #9be9ec; }
QTreeView::item:selected { background: #214653; color: #f0fbff; }
QMenu { background: #142235; border: 1px solid #31445f; padding: 5px; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #284a61; }
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit { background: #0b1625; border: 1px solid #30445d; border-radius: 5px; padding: 6px; min-height: 19px; }
QComboBox QAbstractItemView { background: #122034; selection-background-color: #284a61; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; }
QPlainTextEdit, QDateTimeEdit { background: #0b1625; border: 1px solid #30445d; border-radius: 5px; padding: 5px; }
QScrollArea { border: 0; background: transparent; }
QStackedWidget, QWidget#configPanel { background: transparent; }
QScrollBar:vertical { background: #0b1625; width: 9px; margin: 0; }
QScrollBar:horizontal { background: #0b1625; height: 9px; margin: 0; }
QScrollBar::handle { background: #30445d; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 5px; background: #26374d; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #44c5cf; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #b4f5f7; border-radius: 6px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #4a627e; border-radius: 3px; }
QCheckBox::indicator:checked { background: #40bec8; }
QTabWidget::pane { border: 1px solid #223148; border-radius: 8px; background: #111d2d; top: -1px; }
QTabBar::tab { background: #101b2b; color: #8497b0; padding: 13px 28px; margin-right: 5px; border: 1px solid #223148; border-bottom: 3px solid transparent; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #16283b; color: #72e1e7; border-bottom: 3px solid #42c4ce; }
QTabBar::tab:hover { color: #dce7f5; background: #1a2d43; }
QPushButton#sceneCard { background: #111d2d; border: 1px solid #263c53; border-radius: 10px; padding: 0; text-align: left; }
QPushButton#sceneCard:hover { background: #172d40; border-color: #48c3ce; }
QPushButton#sceneCard QLabel { background: transparent; border: none; }
"""


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def panel():
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18,16,18,16)
    layout.setSpacing(12)
    return widget, layout


def prepare_scene(candidates,selected_id):
    if not candidates: return [],None,None,None
    resources = align_resources(candidates)
    return resources,BatchEngine(resources),GeometryService(resources),selected_id


class MainWindow(SceneActions,QMainWindow):
    def __init__(self,start_welcome=True,recent_path=None):
        super().__init__()
        self.setWindowTitle("ASTRODYNAMICS LAB")
        self.resize(1460,960)
        self.setMinimumSize(1120,800)
        self.resources = align_resources([Spacecraft("Satellite-1",TwoBodyModel())])
        self.stations = []
        self.selected_id = self.resources[0].uid
        self.elements = self.resources[0].model
        self.seconds = 0.0
        self.playing = True
        self._last_tick = time.perf_counter()
        root = QWidget()
        self.workspace = root
        self.pages = QStackedWidget()
        self.pages.addWidget(root)
        self.setCentralWidget(self.pages)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24,20,24,18)
        outer.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("ASTRODYNAMICS LAB", "title"))
        header.addLayout(titles)
        header.addStretch()
        self.scene_buttons = []
        for title,callback in [('欢迎页',self.show_welcome),('打开场景',self.open_scene),('保存',self.save_scene),('另存为',lambda:self.save_scene(save_as=True))]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False,fn=callback:fn())
            header.addWidget(button)
            self.scene_buttons.append(button)
        outer.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body,1)

        controls, left = panel()
        controls.setFixedWidth(350)
        left.setContentsMargins(8,12,8,12)
        self.resource_panel = ResourcePanel()
        self.resource_panel.set_resources(self.resources,self.selected_id)
        left.addWidget(self.resource_panel,1)
        actions = QWidget()
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(10,0,10,0)
        actions_layout.setSpacing(9)
        actions_layout.addWidget(label('04   视角和数据','section'))
        views = QHBoxLayout()
        home,top = QPushButton("复位视角"),QPushButton("俯视")
        views.addWidget(home)
        views.addWidget(top)
        actions_layout.addLayout(views)
        export = QPushButton("导出选中航天器 CSV")
        self.export_button = export
        actions_layout.addWidget(export)
        left.addWidget(actions)
        self.message = label("通过配置按钮创建单星、Walker 星座或导入 TLE。", "muted")
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        body.addWidget(controls)

        right = QVBoxLayout()
        right.setSpacing(12)
        body.addLayout(right,1)
        self.view_tabs = QTabWidget()
        self.view_tabs.setDocumentMode(True)
        self.view_tabs.setMovable(False)
        view_panel, view_layout = panel()
        view_layout.setContentsMargins(1,1,1,1)
        self.view = OrbitView()
        self.view.render_failed.connect(self.render_failure)
        self.view.set_resources(self.resources,self.selected_id)
        view_layout.addWidget(self.view,1)
        self.view.setToolTip('拖动旋转 / 滚轮缩放')
        self.view_tabs.addTab(view_panel,"轨道视图")
        ground_panel,ground_layout = panel()
        ground_layout.setContentsMargins(1,1,1,1)
        self.ground_view = GroundTrackView()
        ground_layout.addWidget(self.ground_view,1)
        self.view_tabs.addTab(ground_panel,"星下点视图")
        self.data_view = DataView()
        self.data_view.time_requested.connect(self.seek_chart)
        self.view_tabs.addTab(self.data_view,"数据视图")
        self.view_tabs.setCurrentIndex(0)
        right.addWidget(self.view_tabs,1)

        playback, playback_layout = panel()
        row = QHBoxLayout()
        self.play_button = QPushButton("Ⅱ  暂停")
        self.play_button.setObjectName("primary")
        self.reset_button = QPushButton("↺  重置")
        row.addWidget(self.play_button)
        row.addWidget(self.reset_button)
        row.addSpacing(12)
        row.addWidget(label("时间倍率", "muted"))
        self.speed = QComboBox()
        for value in (1,10,30,60,120,300,1000):
            self.speed.addItem(f"{value} ×",value)
        self.speed.setCurrentIndex(4)
        row.addWidget(self.speed)
        row.addStretch()
        playback_layout.addLayout(row)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0,10000)
        playback_layout.addWidget(self.timeline)
        self.utc_label = label("", "muted")
        playback_layout.addWidget(self.utc_label)
        right.addWidget(playback)

        self.resource_panel.configure_requested.connect(self.open_configuration)
        self.resource_panel.station_requested.connect(self.open_station)
        self.resource_panel.edit_requested.connect(self.edit_resource)
        self.view_tabs.currentChanged.connect(self.change_view)
        self.resource_panel.selected.connect(self.select_resource)
        self.resource_panel.remove_requested.connect(self.remove_resource)
        self.visibility_timer = QTimer(self)
        self.visibility_timer.setSingleShot(True)
        self.visibility_timer.timeout.connect(self.sync_resources)
        self.resource_panel.changed.connect(lambda:self.visibility_timer.start(0))
        self.resource_panel.style_changed.connect(lambda:self.visibility_timer.start(0))
        self.resource_panel.changed.connect(self.mark_scene_dirty)
        self.resource_panel.style_changed.connect(self.mark_scene_dirty)
        self.play_button.clicked.connect(self.toggle_play)
        self.reset_button.clicked.connect(self.reset)
        self.timeline.sliderMoved.connect(self.seek)
        self.timeline.sliderReleased.connect(self.release_seek)
        home.clicked.connect(self.view.home)
        top.clicked.connect(self.view.top)
        export.clicked.connect(self.export_csv)
        self.scenario_revision = self.visibility_revision = self.seek_revision = 0
        self.requested_seconds = self.seconds
        self.last_frame = None
        self.sim_worker = LatestWorker('constellation-dynamics',self)
        self.geometry_worker = LatestWorker('trajectory-geometry',self)
        self.load_worker = LatestWorker('scene-loading',self)
        self.load_revision = 0
        self.sim_engine = BatchEngine(self.resources)
        self.geometry_engine = GeometryService(self.resources)
        self.geometry_due = 0
        self.geometry_last_request = None
        self.timings = {}
        self.resource_map = {c.uid:c for c in self.resources}
        self.visibility = np.array([[c.body,c.orbit,c.trail] for c in self.resources],dtype=bool)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.sync_resources()
        self.refresh()
        self.init_scene_files(start_welcome,recent_path)
        self.view.initialized.connect(lambda:QTimer.singleShot(0,self.sync_resources))

    def open_configuration(self,edit=False,group=None):
        selected = self.resource_map.get(self.selected_id) if edit else None
        members = [c for c in self.resources if c.constellation_id==group] if group else None
        if members: selected = members[0]
        dialog = ConfigurationDialog(self,selected,members)
        if not group: dialog.operation.setCurrentIndex(2 if selected else 1)
        if dialog.exec() == dialog.DialogCode.Accepted:
            try:
                candidates = self.candidates(dialog.result_resources,dialog.operation.currentData(),group)
            except ValueError as error:
                self.message.setText(str(error))
                return
            self.load_revision += 1
            self.load_worker.submit(self.load_revision,prepare_scene,candidates,dialog.result_resources[0].uid)
            self.message.setText('正在后台载入场景，现有视图仍可操作…')
        dialog.deleteLater()

    def open_station(self,station=None):
        dialog = StationDialog(self,station)
        if dialog.exec()==dialog.DialogCode.Accepted:
            self.install_station(dialog.station)
        dialog.deleteLater()

    def install_station(self,station):
        for i,old in enumerate(self.stations):
            if old.uid==station.uid:
                self.stations[i] = station
                break
        else:
            self.stations.append(station)
        self.resource_panel.set_resources(self.resources,self.selected_id,self.stations)
        self.sync_resources()
        self.message.setText(f'已保存测控站：{station.name}')
        self.mark_scene_dirty()

    def edit_resource(self):
        group = self.resource_panel.current_constellation()
        if group:
            self.open_configuration(edit=True,group=group)
            return
        station = self.resource_panel.current_station()
        self.open_station(station) if station else self.open_configuration(edit=True)

    def candidates(self,crafts,operation,group=None):
        if operation=='append': return self.resources+crafts
        if operation=='constellation':
            members = [c for c in self.resources if c.constellation_id==group]
            if not members: raise ValueError('选中的星座已不存在。')
            old = members[0]
            for c in crafts:
                c.constellation_id = group
                c.color,c.line_color,c.line_width = old.color,old.line_color,old.line_width
                c.body,c.orbit,c.trail = old.body,old.orbit,old.trail
            result = []
            for c in self.resources:
                if c is old: result.extend(crafts)
                if c.constellation_id!=group: result.append(c)
            return result
        if operation=='selected':
            if len(crafts)!=1: raise ValueError('只能用一颗航天器替换当前选择。')
            old = self.resource_map[self.selected_id]
            crafts[0].uid = old.uid
            crafts[0].color,crafts[0].line_color,crafts[0].line_width = old.color,old.line_color,old.line_width
            crafts[0].body,crafts[0].orbit,crafts[0].trail = old.body,old.orbit,old.trail
            if old.constellation_id:
                crafts[0].constellation_id,crafts[0].constellation_name = old.constellation_id,old.constellation_name
                crafts[0].line_color,crafts[0].line_width = old.line_color,old.line_width
                crafts[0].walker_spec = old.walker_spec
            return [crafts[0] if c.uid==self.selected_id else c for c in self.resources]
        if operation=='replace': return crafts
        raise ValueError('未知资源操作。')

    def install_resources(self,crafts,operation='replace'):
        # Synchronous API for tests/scripts. User configuration uses load_worker.
        self.commit_scene(prepare_scene(self.candidates(crafts,operation),crafts[0].uid if crafts else None))

    def commit_scene(self,prepared):
        if self.geometry_engine is not None: self.geometry_engine.retire()
        self.resources,self.sim_engine,self.geometry_engine,self.selected_id = prepared
        self.resource_map = {c.uid:c for c in self.resources}
        self.elements = self.resource_map[self.selected_id].model if self.resources else TwoBodyModel(epoch=self.elements.epoch)
        self.scenario_revision += 1
        self.seek_revision += 1
        self.last_frame = None
        self.seconds = self.requested_seconds = 0
        self._last_tick = time.perf_counter()
        self.view.set_resources(self.resources,self.selected_id)
        if not self.resources: self.view.elements = self.elements
        self.resource_panel.set_resources(self.resources,self.selected_id,self.stations)
        self.ground_view.update_resources(self.resources,self.selected_id)
        self.export_button.setEnabled(bool(self.resources))
        self.timeline.setEnabled(bool(self.resources))
        if not self.resources: self.data_view.clear_state()
        self.sync_resources()
        self.refresh()
        self.message.setText(f'已载入 {len(self.resources):,} 颗；批量计算与轨迹采样在后台运行。' if self.resources else '场景中没有航天器，可添加单星、Walker 星座或导入 TLE。')
        self.message.setStyleSheet('color: #65d4bc')
        self.mark_scene_dirty()

    def select_resource(self,uid):
        craft = self.resource_map.get(uid)
        if craft is None or uid==self.selected_id: return
        camera = (self.view.yaw,self.view.pitch,self.view.distance)
        self.selected_id,self.elements = uid,craft.model
        self.view.set_resources(self.resources,uid,self.seconds)
        self.view.yaw,self.view.pitch,self.view.distance = camera
        self.resource_panel.select_active(uid)
        self.ground_view.update_resources(self.resources,uid)
        self.sync_resources()
        self.refresh()

    def remove_resource(self):
        station = self.resource_panel.current_station()
        if station:
            self.stations = [s for s in self.stations if s.uid!=station.uid]
            self.resource_panel.set_resources(self.resources,self.selected_id,self.stations)
            self.sync_resources()
            self.mark_scene_dirty()
            return
        group = self.resource_panel.current_constellation()
        candidates = [c for c in self.resources if c.constellation_id!=group] if group else [c for c in self.resources if c.uid!=self.selected_id]
        self.load_revision += 1
        self.load_worker.submit(self.load_revision,prepare_scene,candidates,candidates[0].uid if candidates else None)

    def sync_resources(self):
        panel = self.resource_panel
        self.view.set_grid_settings(panel.settings)
        self.view.show_grid = panel.enabled('plane')
        self.view.show_stars = True
        self.view.show_shadow = panel.enabled('shadow')
        self.view.show_sun = panel.enabled('sun')
        self.view.show_velocity = panel.enabled('velocity')
        self.view.stations = self.stations
        self.ground_view.stations = self.stations
        self.ground_view.grid_settings = panel.settings
        self.ground_view.show_earth = panel.enabled('earth')
        self.ground_view.show_night = panel.enabled('night')
        self.visibility = np.array([[c.body,c.orbit,c.trail] for c in self.resources],dtype=bool)
        self.line_styles = dict(colors=np.asarray([c.line_color or c.color for c in self.resources],dtype=np.float32),
            widths=np.asarray([c.line_width for c in self.resources],dtype=np.float32),
            custom=np.asarray([c.line_color is not None for c in self.resources],dtype=bool))
        self.view.apply_line_style()
        self.visibility_revision += 1
        self.view.clear_batches()
        self.ground_view.clear_batches()
        if self.view.ready:
            self.view.earth.nodeMask = 0xffffffff if panel.enabled('earth') else 0
            self.view.grid.nodeMask = 0xffffffff if self.view.show_grid else 0
            self.view.set_time(self.seconds)
        self.ground_view.update_resources(self.resources,self.selected_id)
        self.request_frame()
        self.queue_geometry(force=True)

    def change_view(self,*unused):
        if not hasattr(self,'sim_worker'): return
        self.request_frame()
        self.queue_geometry(force=True)

    def request_frame(self):
        if self.sim_engine is None: return
        self.sim_worker.submit((self.scenario_revision,self.seek_revision),self.sim_engine.state,self.requested_seconds)

    def geometry_key(self):
        return (self.scenario_revision,self.visibility_revision,self.seek_revision,self.selected_id,self.view_tabs.currentIndex())

    def queue_geometry(self,force=False):
        if not self.resources: return
        mode = self.view_tabs.currentIndex()
        if mode==2: return
        now = time.perf_counter()
        request = (self.geometry_key(),self.seconds)
        if not force and request==self.geometry_last_request: return
        if not force and (now<self.geometry_due or self.geometry_worker.busy): return
        self.geometry_due = now+(3 if len(self.resources)>1000 else 1)
        self.geometry_last_request = request
        index = self.view.selected_index
        self.geometry_worker.submit(self.geometry_key(),self.geometry_engine.build,self.seconds,self.visibility.copy(),index,'3d' if mode==0 else '2d',self.line_styles)

    def poll_workers(self):
        self.poll_scene_files()
        result = self.load_worker.take()
        if result is not None:
            key,value,error = result
            if key==self.load_revision:
                if error: self.message.setText(f'载入失败，保留原场景：{error}')
                else: self.commit_scene(value)
        result = self.sim_worker.take()
        if result is not None:
            key,frame,error = result
            if key==(self.scenario_revision,self.seek_revision):
                if error:
                    self.message.setText(f'传播失败：{error}')
                elif frame.valid[self.view.selected_index]:
                    self.last_frame = frame
                    self.seconds = frame.seconds
                    started = time.perf_counter()
                    self.refresh(frame)
                    self.record_timing('selected_refresh',started)
                    started = time.perf_counter()
                    if self.view_tabs.currentIndex()==0: self.view.apply_frame(frame,self.visibility)
                    elif self.view_tabs.currentIndex()==1: self.ground_view.apply_frame(frame,self.visibility)
                    self.record_timing('batch_frame',started)
                    if not frame.valid.all(): self.message.setText(f'{np.count_nonzero(~frame.valid)} 颗卫星传播失败，已隐藏；请检查 TLE 日期。')
                else:
                    self.playing = False
                    self.play_button.setText('▶  播放')
                    self.message.setText('选中航天器传播失败，已暂停；请检查 TLE 日期。')
        result = self.geometry_worker.take()
        if result is not None:
            key,value,error = result
            if key==self.geometry_key():
                started = time.perf_counter()
                if error: self.message.setText(f'轨迹采样失败：{error}')
                elif value['mode']=='3d': self.view.apply_geometry(value)
                else: self.ground_view.apply_geometry(value)
                self.record_timing('geometry_upload',started)

    def record_timing(self,key,started):
        self.timings[key] = max(self.timings.get(key,0),(time.perf_counter()-started)*1000)

    def toggle_play(self):
        self.playing = not self.playing
        self._last_tick = time.perf_counter()
        self.play_button.setText("Ⅱ  暂停" if self.playing else "▶  播放")

    def reset(self):
        self._last_tick = time.perf_counter()
        self.advance_to(0)

    def render_failure(self,message):
        self.playing = False
        self.play_button.setText("▶  播放")
        self.message.setText(f"三维渲染初始化失败：{message}")
        self.message.setStyleSheet("color: #ffb478")

    def seek(self, value):
        self.advance_to(self.elements.period*value/10000)

    def seek_chart(self,seconds):
        self._last_tick = time.perf_counter()
        self.advance_to(seconds)

    def release_seek(self):
        self.seek(self.timeline.value())
        self._last_tick = time.perf_counter()

    def advance_to(self,seconds):
        self.requested_seconds = float(seconds)
        self.seek_revision += 1
        self.request_frame()
        self.geometry_due = 0
        if not self.resources:
            self.seconds = self.requested_seconds
            self.refresh()

    def tick(self):
        now = time.perf_counter()
        elapsed,self._last_tick = now-self._last_tick,now
        self.poll_workers()
        if self.pages.currentWidget() is not self.workspace: return
        if self.playing and not self.timeline.isSliderDown():
            self.requested_seconds += elapsed*self.speed.currentData()
            self.request_frame()
            if not self.resources:
                self.seconds = self.requested_seconds
                self.refresh()
        self.queue_geometry()
        self.record_timing('gui_tick',now)

    def refresh(self,frame=None):
        if not self.resources:
            self.view.set_time(self.seconds)
            self.ground_view.model,self.ground_view.seconds = self.elements,self.seconds
            self.ground_view.update()
            self.timeline.setValue(0)
            utc = self.elements.utc(self.seconds)
            self.utc_label.setText(f"UTC  {utc:%Y-%m-%d %H:%M:%S}")
            return
        if frame is None:
            pos,vel = self.elements.state(self.seconds)
        else:
            pos,vel = frame.positions[self.view.selected_index],frame.velocities[self.view.selected_index]
        if self.view_tabs.currentIndex()==0:
            self.view.set_time(self.seconds)
        self.ground_view.update_state(self.elements,self.seconds,pos)
        self.data_view.set_model(self.elements)
        self.data_view.update_state(SimulationSnapshot(
            spacecraft_name=self.resource_map[self.selected_id].name,
            model_name=self.elements.model_name,frame=self.elements.frame,
            epoch_utc=self.elements.epoch,utc=self.elements.utc(self.seconds),seconds=self.seconds,
            position_km=tuple(float(v) for v in pos),velocity_km_s=tuple(float(v) for v in vel)))
        phase = (self.seconds/self.elements.period) % 1
        if not self.timeline.isSliderDown():
            self.timeline.setValue(round(phase*10000))
        utc = self.elements.utc(self.seconds)
        self.utc_label.setText(f"UTC  {utc:%Y-%m-%d %H:%M:%S}")

    def write_csv(self, path):
        if not self.resources: raise ValueError('请先添加并选中航天器。')
        rows = []
        name = next(c.name for c in self.resources if c.uid == self.selected_id)
        for t in np.linspace(self.seconds,self.seconds+self.elements.period,721):
            pos,vel = self.elements.state(t)
            utc = self.elements.utc(t)
            status,fraction = eclipse(pos,solar_position(utc))
            rows.append([name,self.elements.model_name,self.elements.frame,self.elements.source.epoch.isoformat(),self.elements.epoch.isoformat(),utc.isoformat(),
                         *[f"{v:.9f}" for v in (t,*pos,*vel)],status,f"{fraction:.6f}"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w",newline="",encoding="utf-8-sig",dir=Path(path).resolve().parent,delete=False) as handle:
                temporary = handle.name
                writer = csv.writer(handle)
                writer.writerow(["spacecraft","model","frame","source_epoch_utc","epoch_utc","utc","time_s","x_km","y_km","z_km","vx_km_s","vy_km_s","vz_km_s","illumination","sun_visible_fraction"])
                writer.writerows(rows)
            os.replace(temporary,path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def export_csv(self):
        if not self.resources: return
        path,_ = QFileDialog.getSaveFileName(self,"导出一周期轨道","orbit.csv","CSV (*.csv)")
        if path:
            try:
                self.write_csv(path)
            except (OSError,ValueError) as error:
                self.message.setText(f"导出失败：{error}")
                self.message.setStyleSheet("color: #ffb478")
            else:
                self.message.setText(f"已导出 721 个采样点：{Path(path).name}")
                self.message.setStyleSheet("color: #65d4bc")

    def closeEvent(self,event):
        if getattr(self,'io_busy',False):
            event.ignore()
            return
        if getattr(self,'scene_dirty',False) and self.confirm_unsaved:
            event.ignore()
            self.guard_scene_change(self.close_without_save)
            return
        self.timer.stop()
        for worker in (self.sim_worker,self.geometry_worker,self.load_worker): worker.stop()
        if self.geometry_engine is not None: self.geometry_engine.close()
        self.data_view.shutdown()
        self.file_worker.stop()
        self.view.cleanup()
        super().closeEvent(event)


def run_smoke_test(window,app):
    from .smoke import run
    run(window,app)


def main():
    parser = argparse.ArgumentParser(description="Python + OSG + Qt 二体轨道演示")
    parser.add_argument("--smoke-test",action="store_true")
    parser.add_argument("--benchmark",action="store_true",help="真实窗口一万星压力测试")
    parser.add_argument("--gallery",action="store_true",help="生成示例场景与说明文档截图")
    args = parser.parse_args()
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    # Qt owns the composition FBO. Pace via the precise UI timer rather than
    # blocking its event loop on an additional swap/vsync wait.
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setFont(QFont("Microsoft YaHei UI",10))
    app.setStyleSheet(STYLE)
    test_mode = args.smoke_test or args.benchmark or args.gallery
    recent_path = Path(__file__).resolve().parent.parent/'artifacts'/('gallery_profile' if args.gallery else 'test_profile')/'recent.json' if test_mode else None
    window = MainWindow(start_welcome=not test_mode,recent_path=recent_path)
    window.confirm_unsaved = not test_mode
    window.show()
    if args.smoke_test:
        QTimer.singleShot(1800,lambda:run_smoke_test(window,app))
    elif args.benchmark:
        from .benchmark import run
        QTimer.singleShot(1800,lambda:run(window,app))
    elif args.gallery:
        from .gallery import run
        QTimer.singleShot(1800,lambda:run(window,app))
    return app.exec()
