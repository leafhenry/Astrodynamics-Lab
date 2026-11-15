"""Portable, versioned JSON scenes. No executable serialization or external assets."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import tempfile
from .resources import Spacecraft,GroundStation,GridSettings,create_single,align_resources,MAX_SPACECRAFT,is_sgp4
from .mechanics import Elements
from .propagators import SGP4Model

FORMAT = 'astrodynamics-lab-scene'
VERSION = 1
MAX_BYTES = 32*1024*1024
FLAGS = ('earth','graticule','night','shadow','sun','plane','velocity')


def atomic_json(path,data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as stream:
            temporary = stream.name
            json.dump(data,stream,ensure_ascii=False,allow_nan=False,indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)


def scene_document(name,crafts,stations,grid,flags,epoch,seconds,selected_id,camera,speed=120,tab=0,preview=''):
    groups = {}
    records = []
    for c in crafts:
        source = getattr(c.model,'source',c.model)
        model = {'type':'sgp4','tle':source.tle} if is_sgp4(source) else {'type':'two_body','elements':asdict(source.elements),'epoch':source.epoch.isoformat()}
        records.append(dict(uid=c.uid,name=c.name,model=model,color=c.color,line_color=c.line_color,
            line_width=c.line_width,body=c.body,orbit=c.orbit,trail=c.trail,constellation_id=c.constellation_id))
        if c.constellation_id and c.constellation_id not in groups:
            spec = list(c.walker_spec)
            spec[-1] = spec[-1].isoformat()
            groups[c.constellation_id] = dict(name=c.constellation_name,spec=spec)
    return dict(format=FORMAT,version=VERSION,name=name,saved_at=datetime.now(timezone.utc).isoformat(),
        spacecraft=records,constellations=groups,stations=[asdict(s) for s in stations],
        display=dict(grid=asdict(grid),flags=dict(flags)),
        simulation=dict(epoch=epoch.isoformat(),seconds=float(seconds),selected_id=selected_id,speed=speed,tab=tab),
        camera=dict(zip(('yaw','pitch','distance'),map(float,camera))),preview=preview)


def finite(value,low,high,label):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{label} 超出范围或不是有限数值。')
    return value


def boolean(value):
    if type(value) is not bool: raise ValueError('显隐 / 显示设置必须为布尔值。')
    return value


def name(value):
    if not isinstance(value,str) or not value.strip() or len(value)>512: raise ValueError('名称或标识无效。')
    return value


def color(value):
    if not isinstance(value,(list,tuple)) or len(value)!=3: raise ValueError('颜色必须为 RGB 三元组。')
    return tuple(finite(v,0,1,'RGB') for v in value)


def utc(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None: raise ValueError('场景历元必须包含时区。')
    return result.astimezone(timezone.utc)


def decode_scene(doc):
    """Build and validate an independent candidate; callers commit only on success."""
    try:
        if doc['format']!=FORMAT or doc['version']!=VERSION: raise ValueError('不支持的场景格式或版本。')
        title = name(doc['name'])
        records,sites,groups = doc['spacecraft'],doc['stations'],doc['constellations']
        if not isinstance(records,list) or len(records)>MAX_SPACECRAFT: raise ValueError('航天器数量超限。')
        if not isinstance(sites,list) or len(sites)>10000: raise ValueError('测控站数量超限。')
        if not isinstance(groups,dict) or len(groups)>MAX_SPACECRAFT: raise ValueError('星座分组无效。')
        specs = {}
        for uid,group in groups.items():
            name(uid)
            group_name = name(group['name'])
            spec = list(group['spec'])
            if len(spec)!=10 or spec[0]!=group_name: raise ValueError('Walker 参数无效。')
            total,planes,phase = spec[1:4]
            if any(type(x) is not int for x in (total,planes,phase)) or not 1<=total<=MAX_SPACECRAFT or not 1<=planes<=total or total%planes or not 0<=phase<planes:
                raise ValueError('Walker 的 T / P / F 无效。')
            finite(spec[4],100,90000,'Walker 高度')
            finite(spec[5],0,180,'Walker 倾角')
            for angle in spec[6:8]: finite(angle,0,360,'Walker 角度')
            if spec[8] not in ('Delta','Star'): raise ValueError('Walker 类型无效。')
            spec[9] = utc(spec[9])
            specs[uid] = tuple(spec)
        crafts,stations,ids = [],[],set()
        def identifier(value):
            value = name(value)
            if value in ids: raise ValueError('资源标识重复。')
            ids.add(value)
            return value
        for record in records:
            uid,title_c,model = identifier(record['uid']),name(record['name']),record['model']
            if model['type']=='two_body':
                values = model['elements']
                for key,low,high in [('a',6500,100000),('e',0,.95),('inclination',0,180),('raan',0,360),('arg_periapsis',0,360),('true_anomaly',0,360)]:
                    finite(values[key],low,high,key)
                source = create_single(title_c,Elements(**values),utc(model['epoch'])).model
            elif model['type']=='sgp4': source = SGP4Model(model['tle'])
            else: raise ValueError('未知动力学模型。')
            group = record['constellation_id']
            if group is not None and group not in specs: raise ValueError('航天器引用了不存在的星座。')
            crafts.append(Spacecraft(title_c,source,uid,color(record['color']),
                boolean(record['body']),boolean(record['orbit']),boolean(record['trail']),
                None if record['line_color'] is None else color(record['line_color']),finite(record['line_width'],.5,5,'轨道线宽'),
                group,groups[group]['name'] if group else None,specs.get(group)))
        group_styles = {}
        for c in crafts:
            if c.constellation_id:
                style = c.line_color or c.color
                if group_styles.setdefault(c.constellation_id,style)!=style: raise ValueError('同一星座的轨道颜色必须一致。')
        if set(group_styles)!=set(groups): raise ValueError('存在没有成员的星座分组。')
        for record in sites:
            stations.append(GroundStation(name(record['name']),finite(record['longitude'],-180,180,'经度'),
                finite(record['latitude'],-90,90,'纬度'),finite(record['altitude_km'],0,20,'站点高度'),
                boolean(record['visible']),identifier(record['uid'])))
        display,sim,cam = doc['display'],doc['simulation'],doc['camera']
        flags = {key:boolean(display['flags'][key]) for key in FLAGS}
        g = display['grid']
        if type(g['spacing']) is not int or g['spacing'] not in (5,10,15,30,45,90): raise ValueError('经纬间隔无效。')
        grid = GridSettings(boolean(g['visible']),g['spacing'],finite(g['width'],.5,3,'经纬线宽'),color(g['color']),boolean(g['equator']))
        if grid.visible!=flags['graticule'] or grid.equator!=flags['plane']: raise ValueError('共享显示设置不一致。')
        epoch = utc(sim['epoch'])
        seconds = finite(sim['seconds'],0,1e10,'仿真时间')
        selected = sim['selected_id']
        if (crafts and selected not in {c.uid for c in crafts}) or (not crafts and selected is not None): raise ValueError('选中航天器无效。')
        speed,tab = sim['speed'],sim['tab']
        if type(speed) is not int or speed not in (1,10,30,60,120,300,1000) or type(tab) is not int or tab not in (0,1,2): raise ValueError('播放 / 视图设置无效。')
        camera = (finite(cam['yaw'],-1e9,1e9,'相机角度'),finite(cam['pitch'],-89,89,'相机俯仰'),finite(cam['distance'],2.2,150,'相机距离'))
        crafts = align_resources(crafts,epoch) if crafts else []
        if crafts:
            from .batch import BatchEngine
            if not BatchEngine(crafts).state(seconds).valid.all(): raise ValueError('保存时刻存在不可传播的航天器。')
        return dict(name=title,crafts=crafts,stations=stations,grid=grid,flags=flags,epoch=epoch,
            seconds=seconds,selected_id=selected,camera=camera,speed=speed,tab=tab)
    except (KeyError,TypeError,AttributeError,OverflowError,IndexError) as exc:
        raise ValueError(f'场景文件结构无效：{exc}') from exc


def read_scene(path):
    path = Path(path)
    if path.stat().st_size>MAX_BYTES: raise ValueError('场景文件超过 32 MB。')
    with path.open(encoding='utf-8-sig') as stream:
        doc = json.load(stream)
    return doc,decode_scene(doc)


def recent_entry(path,doc):
    return dict(path=str(Path(path).resolve()),name=doc['name'],saved_at=doc['saved_at'],
        spacecraft=len(doc['spacecraft']),constellations=len(doc['constellations']),stations=len(doc['stations']),preview=doc.get('preview',''))


class RecentScenes:
    def __init__(self,path):
        self.path = Path(path)

    def entries(self):
        try:
            if self.path.stat().st_size>16*1024*1024: return []
            items = json.loads(self.path.read_text(encoding='utf-8'))
            return [i for i in items if isinstance(i,dict) and isinstance(i.get('path'),str)][:24]
        except (OSError,ValueError,TypeError): return []

    def remember(self,path,doc):
        entry = recent_entry(path,doc)
        entries = [entry]+[i for i in self.entries() if os.path.normcase(i['path'])!=os.path.normcase(entry['path'])]
        self.path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(self.path,entries[:24])
