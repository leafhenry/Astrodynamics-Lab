"""Scene launcher with real saved previews, recent files and starter scenes."""
import base64
import json
from pathlib import Path
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QGridLayout
from .scene_store import recent_entry


class SceneCard(QPushButton):
    def __init__(self,entry,parent=None):
        super().__init__(parent)
        self.path = entry['path']
        self.setObjectName('sceneCard')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(260)
        self.setFixedHeight(270)
        self.setToolTip(self.path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,14,14,14)
        layout.setSpacing(9)
        preview = QLabel()
        preview.setFixedHeight(145)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        try:
            encoded = entry.get('preview','')
            if isinstance(encoded,str) and len(encoded)<2_000_000:
                pixmap.loadFromData(base64.b64decode(encoded,validate=True),'PNG')
        except (ValueError,TypeError): pass
        if not pixmap.isNull():
            preview.setPixmap(pixmap.scaled(360,145,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:
            preview.setText('◎   ASTRODYNAMICS LAB')
            preview.setStyleSheet('background: #102c3c; color: #56d6dc; border-radius: 5px; font-size: 16px;')
        layout.addWidget(preview)
        title = QLabel(str(entry.get('name',Path(self.path).stem)))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName('section')
        title.setWordWrap(True)
        layout.addWidget(title)
        details = QLabel(f"{entry.get('spacecraft',0)} 航天器   ·   {entry.get('constellations',0)} 星座   ·   {entry.get('stations',0)} 测控站")
        details.setObjectName('muted')
        layout.addWidget(details)
        exists = Path(self.path).is_file()
        stamp = str(entry.get('saved_at','')).replace('T',' ')[:16]
        meta = QLabel(f'保存于 {stamp} UTC' if exists else '文件已移动或不存在，请重新打开')
        meta.setObjectName('muted')
        layout.addWidget(meta)
        self.setEnabled(exists)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class WelcomePage(QWidget):
    open_requested = Signal(str)
    browse_requested = Signal()
    new_requested = Signal()
    resume_requested = Signal()

    def __init__(self,recent,examples,parent=None):
        super().__init__(parent)
        self.recent,self.examples = recent,Path(examples)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48,36,48,30)
        layout.setSpacing(18)
        top = QHBoxLayout()
        brand = QLabel('ASTRODYNAMICS LAB')
        brand.setObjectName('title')
        top.addWidget(brand)
        top.addStretch()
        self.resume = QPushButton('返回当前场景')
        self.resume.clicked.connect(self.resume_requested)
        top.addWidget(self.resume)
        layout.addLayout(top)
        title = QLabel('从你的场景开始')
        title.setStyleSheet('font-size: 30px; font-weight: 600; padding-top: 12px;')
        layout.addWidget(title)
        subtitle = QLabel('继续上次的轨道实验，或创建一个全新的航天任务场景。')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.cards_layout = QVBoxLayout(self.content)
        self.cards_layout.setContentsMargins(0,0,12,0)
        self.cards_layout.setSpacing(16)
        scroll.setWidget(self.content)
        layout.addWidget(scroll,1)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setObjectName('error')
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.new_button = QPushButton('＋  新建场景')
        self.new_button.setObjectName('primary')
        self.new_button.setMinimumHeight(46)
        self.new_button.clicked.connect(self.new_requested)
        actions.addWidget(self.new_button)
        self.open_button = QPushButton('打开场景文件…')
        self.open_button.setMinimumHeight(46)
        self.open_button.clicked.connect(self.browse_requested)
        actions.addWidget(self.open_button)
        actions.addStretch()
        hint = QLabel('Ctrl+N  新建    Ctrl+O  打开    Ctrl+S  保存')
        hint.setObjectName('muted')
        actions.addWidget(hint)
        layout.addLayout(actions)
        self.reload()

    def reload(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = []
        recent = self.recent.entries()
        self.add_section('最近的场景',recent)
        if not recent:
            empty = QLabel('还没有最近记录。保存或打开场景后，这里会显示场景缩略图。')
            empty.setObjectName('muted')
            self.cards_layout.addWidget(empty)
        examples = []
        recent_paths = {str(Path(entry['path']).resolve()).casefold() for entry in recent}
        for path in sorted(self.examples.glob('*.astro.json')):
            if str(path.resolve()).casefold() in recent_paths: continue
            try:
                doc = json.loads(path.read_text(encoding='utf-8'))
                examples.append(recent_entry(path,doc))
            except (OSError,ValueError,KeyError,TypeError): continue
        if examples: self.add_section('示例场景',examples)
        self.cards_layout.addStretch()

    def add_section(self,title,entries):
        heading = QLabel(title)
        heading.setObjectName('section')
        self.cards_layout.addWidget(heading)
        if not entries: return
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0,0,0,0)
        grid.setSpacing(16)
        for i,entry in enumerate(entries):
            card = SceneCard(entry)
            card.clicked.connect(lambda checked=False,path=card.path:self.open_requested.emit(path))
            grid.addWidget(card,i//3,i%3)
            self.cards.append(card)
        for col in range(3): grid.setColumnStretch(col,1)
        self.cards_layout.addWidget(container)
