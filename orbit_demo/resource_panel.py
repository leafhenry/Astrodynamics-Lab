"""Resource tree and one set of geographic grid controls for both views."""
from PySide6.QtCore import Qt,Signal,QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTreeView,
    QPushButton,QComboBox,QDoubleSpinBox,QMenu)
from .resources import GridSettings
from .resource_tree import ResourceTreeModel
from .line_style import LineStyleDialog


class ResourcePanel(QWidget):
    changed = Signal()
    selected = Signal(str)
    configure_requested = Signal()
    remove_requested = Signal()
    station_requested = Signal()
    edit_requested = Signal()
    style_changed = Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.settings = GridSettings()
        self.crafts = []
        self.active_id = None
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,4,10,4)
        layout.setSpacing(9)
        title = QLabel("01   场景配置")
        title.setObjectName("section")
        layout.addWidget(title)
        configure = QPushButton("＋ 航天器")
        configure.setObjectName("primary")
        configure.clicked.connect(self.configure_requested)
        add_row = QHBoxLayout()
        add_row.addWidget(configure)
        station = QPushButton("＋ 测控站")
        station.clicked.connect(self.station_requested)
        add_row.addWidget(station)
        layout.addLayout(add_row)
        title = QLabel('02   场景管理')
        title.setObjectName('section')
        layout.addWidget(title)
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(170)
        self.tree.setIndentation(17)
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree,1)
        self.model = ResourceTreeModel(self)
        self.tree.setModel(self.model)
        self.model.changed.connect(self.item_changed)
        self.tree.selectionModel().currentChanged.connect(self.item_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.selection_label = QLabel("")
        self.selection_label.setWordWrap(False)
        self.selection_label.setObjectName("eyebrow")
        layout.addWidget(self.selection_label)
        edit_row = QHBoxLayout()
        edit = QPushButton("配置选中资源…")
        self.edit_button = edit
        edit.clicked.connect(self.edit_requested)
        edit_row.addWidget(edit)
        remove = QPushButton("移除选中资源")
        self.remove_button = remove
        remove.clicked.connect(self.remove_requested)
        edit_row.addWidget(remove)
        layout.addLayout(edit_row)
        title = QLabel("03   共享显示配置")
        title.setObjectName("section")
        layout.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(QLabel("经纬间隔"))
        self.spacing = QComboBox()
        for step in (5,10,15,30,45,90):
            self.spacing.addItem(f"{step}°",step)
        self.spacing.setCurrentIndex(2)
        row.addWidget(self.spacing)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("线宽"))
        self.width = QDoubleSpinBox()
        self.width.setRange(.5,3)
        self.width.setSingleStep(.25)
        self.width.setValue(1)
        self.width.setSuffix(" px")
        row.addWidget(self.width)
        layout.addLayout(row)
        self.buttons = {}
        row = QHBoxLayout()
        for key,title in [('sun','太阳方向'),('shadow','本影 / 半影')]:
            button = self.toggle_button(key,title)
            row.addWidget(button)
        layout.addLayout(row)
        self.equator = self.toggle_button('plane','赤道参考平面 / 强调赤道')
        layout.addWidget(self.equator)
        layout.addWidget(self.toggle_button('velocity','选中航天器速度方向'))
        for signal in (self.spacing.currentIndexChanged,self.width.valueChanged):
            signal.connect(self.grid_changed)

    def toggle_button(self,key,title):
        button = QPushButton(title)
        button.setCheckable(True)
        button.setChecked(self.model.flags_state[key])
        button.toggled.connect(lambda value:self.toggle_feature(key,value))
        self.buttons[key] = button
        return button

    def toggle_feature(self,key,value):
        self.model.flags_state[key] = value
        if key=='plane': self.settings.equator = value
        self.changed.emit()

    def enabled(self,key):
        return self.model.flags_state[key]

    def apply_display(self,settings,flags):
        self.settings = settings
        self.model.flags_state = dict(flags)
        widgets = [self.spacing,self.width,*self.buttons.values()]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        self.spacing.setCurrentIndex(self.spacing.findData(settings.spacing))
        self.width.setValue(settings.width)
        for key,button in self.buttons.items(): button.setChecked(flags[key])
        del blockers
        self.tree.viewport().update()

    def set_resources(self,crafts,active_id,stations=None):
        self.crafts,self.active_id = crafts,active_id
        self.tree.blockSignals(True)
        self.model.set_resources(crafts,stations if stations is not None else self.model.stations)
        self.tree.expandToDepth(0)
        self.select_active(active_id)
        self.tree.blockSignals(False)
        if not crafts:
            self.selection_label.setText('未选中航天器')
            self.selection_label.setToolTip('')
            self.edit_button.setEnabled(False)
            self.remove_button.setEnabled(False)

    def select_active(self,uid):
        self.active_id = uid
        for i,c in enumerate(self.crafts):
            if c.uid==uid:
                current = self.tree.currentIndex()
                node = current.internalPointer() if current.isValid() else None
                current_i = node.key if node and node.kind=='sat' else node.key[0] if node and node.kind=='layer' else None
                if current_i!=i: self.tree.setCurrentIndex(self.model.spacecraft_index(i))
                self.selection_label.setText(f"分析对象：{c.name}")
                self.selection_label.setToolTip(f'{c.model.model_name} / {c.model.frame}')
                break

    def item_changed(self):
        self.settings.visible = self.enabled("graticule")
        self.tree.viewport().update()
        self.changed.emit()

    def item_selected(self,index,previous):
        if not index.isValid(): return
        node = index.internalPointer()
        self.edit_button.setEnabled(node.kind in ('sat','layer','station','constellation'))
        self.remove_button.setEnabled(node.kind in ('sat','layer','station','constellation'))
        if node.kind in ('sat','layer'):
            i = node.key if node.kind=='sat' else node.key[0]
            if self.crafts[i].uid!=self.active_id:
                self.selected.emit(self.crafts[i].uid)

    def current_station(self):
        index = self.tree.currentIndex()
        if index.isValid() and index.internalPointer().kind=='station':
            return self.model.stations[index.internalPointer().key]
        return None

    def current_constellation(self):
        index = self.tree.currentIndex()
        if index.isValid() and index.internalPointer().kind=='constellation':
            return index.internalPointer().key
        return None

    def style_targets(self,node):
        if node.kind=='satgroup': return self.crafts
        if node.kind=='constellation':
            return [c for c in self.crafts if c.constellation_id==node.key]
        craft = self.crafts[node.key if node.kind=='sat' else node.key[0]]
        if craft.constellation_id:
            return [c for c in self.crafts if c.constellation_id==craft.constellation_id]
        return [craft]

    def grid_changed(self,*args):
        self.settings.spacing = self.spacing.currentData()
        self.settings.width = self.width.value()
        self.settings.equator = self.equator.isChecked()
        self.changed.emit()

    def context_menu(self,point):
        index = self.tree.indexAt(point)
        if not index.isValid(): return
        self.tree.setCurrentIndex(index)
        node = index.internalPointer()
        menu = QMenu(self)
        if node.kind in ('sat','layer','satgroup','constellation'):
            action = menu.addAction('轨道颜色与线宽…')
            action.triggered.connect(lambda:self.edit_line_style(node))
        if node.kind=='global' and node.key=='graticule':
            action = menu.addAction('经纬网颜色与线宽…')
            action.triggered.connect(lambda:self.edit_grid_style())
        if node.kind in ('sat','layer','station','constellation'):
            menu.addSeparator()
            menu.addAction('配置资源…',self.edit_requested.emit)
            menu.addAction('移除资源',self.remove_requested.emit)
        if menu.isEmpty():
            action = menu.addAction('此节点没有轨道样式')
            action.setEnabled(False)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def edit_line_style(self,node):
        targets = self.style_targets(node)
        if not targets: return
        ids = {c.uid for c in targets}
        first = targets[0]
        title = '星座轨道 / 尾迹样式（全部成员）' if first.constellation_id and node.kind!='satgroup' else '轨道 / 尾迹样式'
        dialog = LineStyleDialog(title,first.line_color or first.color,first.line_width,self)
        if dialog.exec()==dialog.DialogCode.Accepted:
            color,width = dialog.values()
            for c in self.crafts:
                if c.uid in ids: c.line_color,c.line_width = color,width
            self.style_changed.emit()
        dialog.deleteLater()

    def edit_grid_style(self):
        dialog = LineStyleDialog('经纬网样式',self.settings.color,self.settings.width,self)
        dialog.width.setMaximum(3)
        if dialog.exec()==dialog.DialogCode.Accepted:
            self.settings.color,self.settings.width = dialog.values()
            self.width.setValue(self.settings.width)
            self.changed.emit()
        dialog.deleteLater()
