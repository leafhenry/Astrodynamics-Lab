"""Scene-file UI workflow; disk I/O and scene validation run outside the GUI."""
import base64
from pathlib import Path
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog,QMessageBox
from .scene_store import scene_document,read_scene,atomic_json,RecentScenes
from .welcome import WelcomePage
from .workers import LatestWorker
from .resources import GridSettings
from .propagators import TwoBodyModel
from .batch import BatchEngine
from .geometry_service import GeometryService


def scene_file_job(operation,path,document,recent_path):
    if operation=='save':
        atomic_json(path,document)
        state = prepared = None
    else:
        document,state = read_scene(path)
        crafts = state['crafts']
        prepared = (crafts,BatchEngine(crafts) if crafts else None,GeometryService(crafts) if crafts else None,state['selected_id'])
    warning = ''
    try: RecentScenes(recent_path).remember(path,document)
    except OSError as error: warning = f'（最近记录未更新：{error}）'
    return document,state,prepared,warning


class SceneActions:
    def init_scene_files(self,start_welcome,recent_path=None):
        project = Path(__file__).resolve().parent.parent
        self.recent_scenes = RecentScenes(recent_path or project/'.astro_lab'/'recent.json')
        self.file_worker = LatestWorker('scene-files',self)
        self.io_busy = False
        self.io_completion = None
        self.edit_revision = 0
        self.scene_dirty = False
        self.current_path = None
        self.current_name = '未命名场景'
        self.has_scene = not start_welcome
        self.confirm_unsaved = True
        self._restoring = False
        self.welcome = WelcomePage(self.recent_scenes,project/'examples')
        self.pages.addWidget(self.welcome)
        self.welcome.new_requested.connect(self.new_scene)
        self.welcome.browse_requested.connect(self.open_scene)
        self.welcome.open_requested.connect(self.open_scene)
        self.welcome.resume_requested.connect(self.show_workspace)
        for title,shortcut,callback in [('新建场景','Ctrl+N',self.new_scene),('打开场景','Ctrl+O',self.open_scene),
                ('保存场景','Ctrl+S',self.save_scene),('另存为','Ctrl+Shift+S',lambda:self.save_scene(save_as=True))]:
            action = QAction(title,self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False,fn=callback:fn())
            self.addAction(action)
        if start_welcome:
            self.playing = False
            self.play_button.setText('▶  播放')
            self.show_welcome()

    def mark_scene_dirty(self):
        if not hasattr(self,'scene_dirty') or self._restoring: return
        self.scene_dirty = True
        self.edit_revision += 1
        self.update_scene_title()

    def update_scene_title(self):
        self.setWindowTitle(f"ASTRODYNAMICS LAB — {self.current_name}{' *' if self.scene_dirty else ''}")

    def show_welcome(self):
        if not hasattr(self,'welcome') or self.io_busy: return
        self.playing = False
        self.play_button.setText('▶  播放')
        self.welcome.reload()
        self.welcome.resume.setVisible(self.has_scene)
        self.welcome.status.clear()
        self.pages.setCurrentWidget(self.welcome)

    def show_workspace(self):
        self.pages.setCurrentWidget(self.workspace)
        self.has_scene = True
        self.request_frame()
        self.queue_geometry(force=True)

    def guard_scene_change(self,action):
        if self.io_busy: return
        if not self.scene_dirty or not self.confirm_unsaved:
            action()
            return
        box = QMessageBox(self)
        box.setWindowTitle('保存当前场景？')
        box.setText(f'“{self.current_name}”有尚未保存的配置修改。')
        box.setStandardButtons(QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Save).setText('保存后继续')
        box.button(QMessageBox.StandardButton.Discard).setText('不保存')
        box.button(QMessageBox.StandardButton.Cancel).setText('取消')
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        result = box.exec()
        if result==QMessageBox.StandardButton.Save: self.save_scene(after=action)
        elif result==QMessageBox.StandardButton.Discard:
            action()

    def close_without_save(self):
        self.scene_dirty = False
        self.close()

    def new_scene(self):
        self.guard_scene_change(self.create_empty_scene)

    def create_empty_scene(self):
        self.load_revision += 1
        self._restoring = True
        self.playing = False
        self.play_button.setText('▶  播放')
        self.stations = []
        self.resource_panel.apply_display(GridSettings(),dict(earth=True,graticule=True,night=True,shadow=False,sun=False,plane=False,velocity=False))
        self.commit_scene(([],None,None,None))
        self.elements = TwoBodyModel()
        self.view.elements = self.elements
        self.view.home()
        self.view_tabs.setCurrentIndex(0)
        self.speed.setCurrentIndex(self.speed.findData(120))
        self.current_path,self.current_name = None,'未命名场景'
        self._restoring = False
        self.scene_dirty = False
        self.update_scene_title()
        self.refresh()
        self.show_workspace()

    def capture_preview(self):
        page = self.view_tabs.currentWidget()
        pixmap = page.grab()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.scaled(480,270,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation).save(buffer,'PNG')
        return base64.b64encode(bytes(data)).decode('ascii')

    def document_snapshot(self,name=None):
        panel = self.resource_panel
        return scene_document(name or self.current_name,self.resources,self.stations,panel.settings,panel.model.flags_state,
            self.elements.epoch,self.seconds,self.selected_id,(self.view.yaw,self.view.pitch,self.view.distance),
            self.speed.currentData(),self.view_tabs.currentIndex(),self.capture_preview())

    def save_scene(self,save_as=False,after=None,path=None):
        if self.io_busy or not self.has_scene: return
        target = path or (None if save_as else self.current_path)
        if target is None:
            default = str(self.current_path) if self.current_path else str(Path.home()/'Documents'/'未命名场景.astro.json')
            target,_ = QFileDialog.getSaveFileName(self,'保存场景',default,'ASTRODYNAMICS 场景 (*.astro.json)')
            if not target: return
        target = Path(target)
        if not str(target).lower().endswith('.astro.json'): target = target.with_name(target.name+'.astro.json')
        title = target.name[:-len('.astro.json')]
        document = self.document_snapshot(title)
        self.io_completion = after
        self.start_scene_io('save',target,document)

    def open_scene(self,path=None):
        if self.io_busy: return
        if not path:
            path,_ = QFileDialog.getOpenFileName(self,'打开场景','','ASTRODYNAMICS 场景 (*.astro.json);;JSON (*.json)')
            if not path: return
        target = Path(path)
        self.guard_scene_change(lambda:self.start_scene_io('load',target,None))

    def start_scene_io(self,operation,path,document):
        self.io_busy = True
        self.io_key = (operation,str(path.resolve()),self.edit_revision)
        for button in self.scene_buttons: button.setEnabled(False)
        self.welcome.setEnabled(False)
        if operation=='load' or self.io_completion is not None:
            self.workspace.setEnabled(False)
        if operation=='load':
            self.playing = False
            self.play_button.setText('▶  播放')
        message = '正在后台保存场景…' if operation=='save' else '正在后台校验并加载场景…'
        self.message.setText(message)
        self.welcome.status.setText(message)
        self.file_worker.submit(self.io_key,scene_file_job,operation,path,document,self.recent_scenes.path)

    def poll_scene_files(self):
        if not hasattr(self,'file_worker'): return
        result = self.file_worker.take()
        if result is None: return
        key,value,error = result
        self.io_busy = False
        self.workspace.setEnabled(True)
        self.welcome.setEnabled(True)
        for button in self.scene_buttons: button.setEnabled(True)
        after,self.io_completion = self.io_completion,None
        if error:
            message = f"{'保存' if key[0]=='save' else '加载'}失败：{error}"
            self.message.setText(message)
            self.welcome.status.setText(message)
            return
        document,state,prepared,warning = value
        self.current_path = Path(key[1])
        self.current_name = document['name']
        if key[0]=='load':
            self.load_revision += 1
            self._restoring = True
            self.stations = state['stations']
            self.resource_panel.apply_display(state['grid'],state['flags'])
            self.commit_scene(prepared)
            if not self.resources:
                self.elements = TwoBodyModel(epoch=state['epoch'])
                self.view.elements = self.elements
            self.seconds = self.requested_seconds = state['seconds']
            self.seek_revision += 1
            self.view.yaw,self.view.pitch,self.view.distance = state['camera']
            self.speed.setCurrentIndex(self.speed.findData(state['speed']))
            self.view_tabs.setCurrentIndex(state['tab'])
            self.refresh()
            self.show_workspace()
            self._restoring = False
            self.scene_dirty = False
        elif self.edit_revision==key[2]: self.scene_dirty = False
        self.update_scene_title()
        message = f"已{'保存' if key[0]=='save' else '加载'}：{self.current_name}{warning}"
        self.message.setText(message)
        self.welcome.status.setText(message)
        self.welcome.reload()
        if after: self.guard_scene_change(after)
