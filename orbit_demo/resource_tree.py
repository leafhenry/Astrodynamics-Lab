"""Virtual tree: 10,000 resources without 40,000 eagerly created Qt items."""
from PySide6.QtCore import Qt,QAbstractItemModel,QModelIndex,Signal


class Node:
    def __init__(self,title,kind,key=None,parent=None,row=0):
        self.title,self.kind,self.key,self.parent,self.row = title,kind,key,parent,row
        self.children = []

    def add(self,title,kind,key=None):
        child = Node(title,kind,key,self,len(self.children))
        self.children.append(child)
        return child


class ResourceTreeModel(QAbstractItemModel):
    changed = Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.crafts,self.stations = [],[]
        self.flags_state = dict(earth=True,graticule=True,night=True,shadow=False,sun=False,plane=False,velocity=False)
        self.root = Node('', 'root')
        self.common = self.root.add('二维 / 三维共享资源','group')
        for key,title in [('earth','地球 / 地图底图'),('graticule','地理经纬网'),('night','二维昼夜阴影')]:
            self.common.add(title,'global',key)
        self.sats = self.root.add('航天器','satgroup')
        self.sites = self.root.add('测控站','stationgroup')

    def set_resources(self,crafts,stations):
        self.beginResetModel()
        self.crafts,self.stations = crafts,stations
        self.sats.children = []
        self.craft_nodes = []
        groups = {}
        for i,c in enumerate(crafts):
            parent = self.sats
            if c.constellation_id:
                if c.constellation_id not in groups:
                    groups[c.constellation_id] = self.sats.add(c.constellation_name,'constellation',c.constellation_id)
                parent = groups[c.constellation_id]
            self.craft_nodes.append(parent.add(c.name,'sat',i))
        for group in groups.values():
            group.title += f'（{len(group.children):,} 颗）'
        self.sats.title = f'航天器（{len(crafts):,}）'
        self.sites.children = []
        for i,s in enumerate(stations):
            self.sites.add(s.name,'station',i)
        self.sites.title = f'测控站（{len(stations)}）'
        self.endResetModel()

    def children(self,node):
        if node.kind=='sat' and not node.children:
            for key,title in [('body','星体 / 星下点'),('orbit','轨道 / 地面轨迹'),('trail','尾迹')]:
                node.add(title,'layer',(node.key,key))
        return node.children

    def index(self,row,column,parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self.root
        children = self.children(node)
        if column!=0 or not 0<=row<len(children):
            return QModelIndex()
        return self.createIndex(row,0,children[row])

    def parent(self,index):
        if not index.isValid():
            return QModelIndex()
        p = index.internalPointer().parent
        return QModelIndex() if p is self.root else self.createIndex(p.row,0,p)

    def rowCount(self,parent=QModelIndex()):
        if parent.isValid() and parent.column()!=0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return 3 if node.kind=='sat' else len(node.children)

    def columnCount(self,parent=QModelIndex()):
        return 1

    def flags(self,index):
        return Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable

    def state(self,node):
        if node.kind=='global': return self.flags_state[node.key]
        if node.kind=='layer': return getattr(self.crafts[node.key[0]],node.key[1])
        if node.kind=='station': return self.stations[node.key].visible
        if node.kind=='sat':
            c = self.crafts[node.key]
            values = [c.body,c.orbit,c.trail]
        elif node.kind=='satgroup':
            values = [c.body and c.orbit and c.trail for c in self.crafts]
            if not any(values) and any(c.body or c.orbit or c.trail for c in self.crafts): return None
        elif node.kind=='stationgroup': values = [s.visible for s in self.stations]
        else: values = [self.state(n) for n in node.children]
        return True if values and all(v is True for v in values) else False if all(v is False for v in values) else None

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        node = index.internalPointer()
        if role==Qt.ItemDataRole.DisplayRole: return node.title
        if role==Qt.ItemDataRole.CheckStateRole:
            value = self.state(node)
            return Qt.CheckState.PartiallyChecked if value is None else Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        if role==Qt.ItemDataRole.ToolTipRole and node.kind=='sat':
            c = self.crafts[node.key]
            return f'{c.model.model_name} / {c.model.frame}\n原始历元：{c.model.source.epoch.isoformat()}'

    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if role!=Qt.ItemDataRole.CheckStateRole or not index.isValid(): return False
        checked = value in (Qt.CheckState.Checked,Qt.CheckState.Checked.value)
        node = index.internalPointer()
        def change(n):
            if n.kind=='global': self.flags_state[n.key] = checked
            elif n.kind=='station': self.stations[n.key].visible = checked
            elif n.kind=='layer': setattr(self.crafts[n.key[0]],n.key[1],checked)
            elif n.kind=='sat':
                c = self.crafts[n.key]
                c.body=c.orbit=c.trail=checked
            elif n.kind=='satgroup':
                for c in self.crafts: c.body=c.orbit=c.trail=checked
            else:
                for child in n.children: change(child)
        change(node)
        # Only invalidate visible rows, without a Qt signal per spacecraft.
        self.dataChanged.emit(index,index,[Qt.ItemDataRole.CheckStateRole])
        self.changed.emit()
        return True

    def spacecraft_index(self,i):
        node = self.craft_nodes[i]
        return self.createIndex(node.row,0,node)
