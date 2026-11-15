"""Spacecraft resources, shared rendering options and common-epoch propagation."""
from dataclasses import dataclass, field
from datetime import timedelta
import uuid
import numpy as np
from .mechanics import Elements, EARTH_RADIUS
from .propagators import TwoBodyModel, SGP4Model, DEFAULT_EPOCH

MAX_SPACECRAFT = 10000
PALETTE = [(0.26,.82,.88),(.98,.64,.30),(.65,.53,.95),(.30,.85,.62),(.93,.49,.67),(.40,.65,.98)]


@dataclass
class GridSettings:
    visible: bool = True
    spacing: int = 15
    width: float = 1.0
    color: tuple = (.23,.62,.70)
    equator: bool = False


@dataclass
class Spacecraft:
    name: str
    model: object
    uid: str = field(default_factory=lambda:uuid.uuid4().hex)
    color: tuple = PALETTE[0]
    body: bool = True
    orbit: bool = True
    trail: bool = True
    line_color: tuple | None = None
    line_width: float = 1.0
    constellation_id: str | None = None
    constellation_name: str | None = None
    walker_spec: tuple | None = None


@dataclass
class GroundStation:
    name: str
    longitude: float
    latitude: float
    altitude_km: float = 0.0
    visible: bool = True
    uid: str = field(default_factory=lambda:uuid.uuid4().hex)

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("请输入测控站名称。")
        if not np.isfinite([self.longitude,self.latitude,self.altitude_km]).all():
            raise ValueError("测控站坐标必须为有限数值。")
        if not -180<=self.longitude<=180 or not -90<=self.latitude<=90 or not 0<=self.altitude_km<=20:
            raise ValueError("经度范围 ±180°，纬度范围 ±90°，高度范围 0–20 km。")

    def position(self,earth_angle):
        lon,lat = np.radians([self.longitude,self.latitude])
        lon += earth_angle
        return (EARTH_RADIUS+self.altitude_km)*np.array([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)])


class AlignedModel:
    """Model using scenario seconds while retaining the source's own TLE epoch."""
    def __init__(self,source,epoch):
        self.source = source.source if isinstance(source,AlignedModel) else source
        self.epoch = epoch
        self.offset = (epoch-self.source.epoch).total_seconds()

    def __getattr__(self,name):
        return getattr(self.source,name)

    def state(self,seconds):
        return self.source.state(seconds+self.offset)

    def utc(self,seconds):
        return self.epoch+timedelta(seconds=float(seconds))

    def path(self,count=721,start_seconds=0):
        return self.source.path(count=count,start_seconds=start_seconds+self.offset)


def is_sgp4(model):
    return isinstance(getattr(model,"source",model),SGP4Model)


def create_single(name,elements,epoch=DEFAULT_EPOCH):
    if not name.strip():
        raise ValueError("请输入航天器名称。")
    if elements.a*(1-elements.e) <= EARTH_RADIUS:
        raise ValueError("近地点进入地球内部，请增大半长轴或减小偏心率。")
    return Spacecraft(name.strip(),TwoBodyModel(elements,epoch))


def create_walker(name,total,planes,phasing,altitude,inclination,raan=0,phase=0,kind="Delta",epoch=DEFAULT_EPOCH):
    if not name.strip():
        raise ValueError("请输入星座名称。")
    if any(type(v) is not int for v in (total,planes,phasing)):
        raise ValueError("T、P、F 必须是整数。")
    if not 1 <= total <= MAX_SPACECRAFT or not 1 <= planes <= total or total % planes:
        raise ValueError(f"总星数 T 必须能被轨道面数 P 整除，且 T ≤ {MAX_SPACECRAFT}。")
    if not 0 <= phasing < planes:
        raise ValueError("Walker 相位因子必须满足 0 ≤ F < P。")
    if kind not in ("Delta","Star") or not np.isfinite([altitude,inclination,raan,phase]).all() or altitude <= 0:
        raise ValueError("Walker 类型或轨道参数无效。")
    result = []
    per_plane = total//planes
    constellation_id = uuid.uuid4().hex
    spec = (name.strip(),total,planes,phasing,altitude,inclination,raan,phase,kind,epoch)
    for p in range(planes):
        for s in range(per_plane):
            elements = Elements(a=EARTH_RADIUS+altitude,e=0,inclination=inclination,
                                raan=(raan+(360 if kind == "Delta" else 180)*p/planes)%360,
                                arg_periapsis=0,true_anomaly=(phase+360*s/per_plane+360*phasing*p/total)%360)
            craft = create_single(f"{name.strip()} / P{p+1:02d}-S{s+1:02d}",elements,epoch)
            craft.color = craft.line_color = PALETTE[0]
            craft.constellation_id = constellation_id
            craft.constellation_name = name.strip()
            craft.walker_spec = spec
            result.append(craft)
    return result


def parse_tle_catalog(text):
    """Read mixed 2LE/3LE records, preserving fixed-width TLE lines."""
    lines = [(i+1,line.rstrip()) for i,line in enumerate(text.lstrip('\ufeff').splitlines()) if line.strip()]
    records,seen = [],set()
    cursor = 0
    while cursor < len(lines):
        number,line = lines[cursor]
        name = None
        if not line.startswith("1 "):
            if line.startswith("2 "):
                raise ValueError(f"第 {number} 行缺少对应的 TLE 第一行。")
            name = line[2:] if line.startswith("0 ") else line
            cursor += 1
        if cursor+1 >= len(lines):
            raise ValueError(f"第 {number} 行附近的 TLE 记录不完整。")
        first,second = lines[cursor][1],lines[cursor+1][1]
        try:
            model = SGP4Model((name+'\n' if name else '')+first+'\n'+second)
        except ValueError as error:
            raise ValueError(f"第 {lines[cursor][0]} 行：{error}") from error
        if model.satellite.satnum in seen:
            raise ValueError(f"卫星编号 {model.satellite.satnum} 重复；请为每颗卫星保留一份 TLE。")
        seen.add(model.satellite.satnum)
        records.append(Spacecraft(name or f"NORAD {model.satellite.satnum}",model,color=PALETTE[len(records)%len(PALETTE)]))
        cursor += 2
        if len(records) > MAX_SPACECRAFT:
            raise ValueError(f"当前 Demo 最多显示 {MAX_SPACECRAFT} 颗航天器。")
    if not records:
        raise ValueError("TLE 文件中没有有效记录。")
    return records


def align_resources(crafts,epoch=None):
    if not 1 <= len(crafts) <= MAX_SPACECRAFT:
        raise ValueError(f"场景航天器数量需为 1–{MAX_SPACECRAFT}。")
    sources = [getattr(c.model,"source",c.model) for c in crafts]
    epoch = epoch or max(m.epoch for m in sources)
    result = []
    for craft,source in zip(crafts,sources):
        model = AlignedModel(source,epoch)
        result.append(Spacecraft(craft.name,model,craft.uid,craft.color,craft.body,craft.orbit,craft.trail,
                                 craft.line_color,craft.line_width,craft.constellation_id,craft.constellation_name,craft.walker_spec))
    from .batch import BatchEngine
    engine = BatchEngine(result)
    for t in (0,-max(engine.periods)*.1,max(engine.periods)):
        frame = engine.state(t)
        if not frame.valid.all():
            name = result[np.flatnonzero(~frame.valid)[0]].name
            raise ValueError(f"{name} 在共同历元附近无法传播，请检查 TLE 的适用日期。")
    return result
