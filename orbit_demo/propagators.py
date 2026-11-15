"""Interchangeable two-body and genuine Vallado SGP4 propagators."""
from datetime import datetime, timedelta, timezone
import math
import numpy as np
from sgp4.api import Satrec, WGS72, SGP4_ERRORS
from sgp4.io import twoline2rv, verify_checksum
from sgp4.earth_gravity import wgs72
from sgp4.conveniences import sat_epoch_datetime
from .mechanics import Elements

DEFAULT_EPOCH = datetime(2026,11,15,4,0,tzinfo=timezone.utc)
# Vallado verification satellite; deliberately historical, never a live TLE.
DEMO_TLE = """VANGUARD 1 / historical verification sample
1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753
2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"""


class PropagationError(ValueError):
    pass


class TwoBodyModel:
    model_name = "二体"
    frame = "ECI (epoch MOD)"
    def __init__(self, elements=None, epoch=DEFAULT_EPOCH):
        self.elements = elements or Elements()
        if epoch.tzinfo is None:
            raise ValueError("历元必须带 UTC 时区。")
        self.epoch = epoch.astimezone(timezone.utc)

    def __getattr__(self,name):
        return getattr(self.elements,name)

    def utc(self, seconds):
        return self.epoch+timedelta(seconds=float(seconds))

    def path(self,count=721,start_seconds=0):
        return self.elements.path(count)


class SGP4Model:
    model_name = "SGP4"
    frame = "TEME"
    def __init__(self, text):
        lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
        if len(lines) == 3 and not lines[0].startswith("1 "):
            self.name,lines = lines[0],lines[1:]
        else:
            self.name = "TLE satellite"
        if len(lines) != 2 or any(len(line) != 69 or not line.isascii() for line in lines):
            raise ValueError("请输入两行完整 TLE（每行 69 个 ASCII 字符），可在前面加一行名称。")
        if not lines[0].startswith("1 ") or not lines[1].startswith("2 ") or lines[0][2:7] != lines[1][2:7]:
            raise ValueError("TLE 行号或卫星编号不匹配。")
        if any(not line[68].isdigit() for line in lines):
            raise ValueError("TLE 缺少校验位。")
        try:
            verify_checksum(*lines)
            twoline2rv(*lines,wgs72)  # Strict column/ASCII validation, unlike the C++ fast parser.
            self.satellite = Satrec.twoline2rv(*lines,WGS72)
            self.epoch = sat_epoch_datetime(self.satellite).astimezone(timezone.utc)
        except (ValueError,IndexError,OverflowError) as exc:
            raise ValueError(f"TLE 解析失败：{exc}") from exc
        self.tle = "\n".join(lines)
        self.e = self.satellite.ecco
        self.inclination = math.degrees(self.satellite.inclo)
        if not (0 <= self.e < 1 and self.satellite.no_kozai > 0):
            raise ValueError("TLE 偏心率或平均运动无效。")
        self.period = 2*math.pi/self.satellite.no_kozai*60
        self.a = self.satellite.a*self.satellite.radiusearthkm
        self.state(0)

    def utc(self,seconds):
        return self.epoch+timedelta(seconds=float(seconds))

    def state(self,seconds):
        if not math.isfinite(seconds):
            raise PropagationError("传播时间必须为有限值。")
        # Keep the split Julian date: do not lose sub-ms precision or wrap at period.
        error,position,velocity = self.satellite.sgp4(self.satellite.jdsatepoch,
                                                    self.satellite.jdsatepochF+seconds/86400)
        if error:
            raise PropagationError(f"SGP4 错误 {error}：{SGP4_ERRORS.get(error,'未知传播错误')}")
        if not np.isfinite([*position,*velocity]).all():
            raise PropagationError("SGP4 返回了无效状态。")
        return np.asarray(position),np.asarray(velocity)

    def path(self,count=721,start_seconds=0):
        # This is a time-sampled trajectory, not a closed Kepler ellipse.
        return np.array([self.state(t)[0] for t in np.linspace(start_seconds,start_seconds+self.period,count)])
