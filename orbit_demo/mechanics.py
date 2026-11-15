"""Elliptic two-body motion in an Earth-centred inertial reference frame.

Distances: km. Time: s. Angles in the public element interface: degrees.
The propagator solves Kepler's equation, rather than numerically integrating.
"""
from dataclasses import dataclass
import math
import numpy as np

EARTH_MU = 398600.4418
EARTH_RADIUS = 6378.137


@dataclass(frozen=True)
class Elements:
    a: float = 12000.0
    e: float = 0.35
    inclination: float = 40.0
    raan: float = 25.0
    arg_periapsis: float = 35.0
    true_anomaly: float = 0.0
    mu: float = EARTH_MU

    def __post_init__(self):
        if not all(math.isfinite(v) for v in self.__dict__.values()):
            raise ValueError("轨道参数必须是有限数值。")
        if self.a <= 0 or self.mu <= 0 or not 0 <= self.e < 1:
            raise ValueError("椭圆轨道要求 a > 0、μ > 0 且 0 ≤ e < 1。")
        if not 0 <= self.inclination <= 180:
            raise ValueError("轨道倾角必须在 0° 到 180° 之间。")

    @property
    def period(self):
        return 2 * math.pi * math.sqrt(self.a**3 / self.mu)

    @property
    def rotation(self):
        o, i, w = np.radians([self.raan, self.inclination, self.arg_periapsis])
        co, so, ci, si, cw, sw = math.cos(o), math.sin(o), math.cos(i), math.sin(i), math.cos(w), math.sin(w)
        return np.array([[co*cw-so*sw*ci, -co*sw-so*cw*ci, so*si],
                         [so*cw+co*sw*ci, -so*sw+co*cw*ci, -co*si],
                         [sw*si, cw*si, ci]])

    @property
    def mean_anomaly_epoch(self):
        nu = math.radians(self.true_anomaly)
        eccentric = math.atan2(math.sqrt(1-self.e**2)*math.sin(nu), self.e+math.cos(nu))
        return eccentric-self.e*math.sin(eccentric)

    def state(self, seconds):
        if not math.isfinite(seconds):
            raise ValueError("时间必须是有限数值。")
        mean = (self.mean_anomaly_epoch + 2*math.pi*((seconds % self.period)/self.period)) % (2*math.pi)
        # Monotonic bracketed Newton method remains stable even near e -> 1.
        low, high = 0.0, 2*math.pi
        eccentric = mean if self.e < 0.8 else math.pi
        for _ in range(100):
            residual = eccentric-self.e*math.sin(eccentric)-mean
            if abs(residual) < 1e-14:
                break
            if residual > 0:
                high = eccentric
            else:
                low = eccentric
            trial = eccentric-residual/(1-self.e*math.cos(eccentric))
            eccentric = trial if low < trial < high else (low+high)/2
        c, s = math.cos(eccentric), math.sin(eccentric)
        root = math.sqrt(1-self.e*self.e)
        pos = self.a*np.array([c-self.e, root*s, 0.0])
        vel = math.sqrt(self.mu/self.a)/(1-self.e*c)*np.array([-s, root*c, 0.0])
        rotation = self.rotation
        return rotation @ pos, rotation @ vel

    def path(self, count=721):
        eccentric = np.linspace(0, 2*math.pi, count)
        points = self.a*np.column_stack((np.cos(eccentric)-self.e,
                                        math.sqrt(1-self.e**2)*np.sin(eccentric),
                                        np.zeros(count)))
        return points @ self.rotation.T


PRESETS = {
    "倾斜椭圆轨道": Elements(),
    "近地轨道 · LEO": Elements(a=7200, e=0.03, inclination=51.6, raan=20, arg_periapsis=0),
    "地球同步轨道 · GEO": Elements(a=42164, e=0, inclination=0, raan=0, arg_periapsis=0),
    "高偏心轨道 · HEO": Elements(a=26560, e=0.72, inclination=63.4, raan=25, arg_periapsis=270),
}
