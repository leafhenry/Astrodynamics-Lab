"""Osculating elements from native states; undefined singular angles are NaN."""
import math
import numpy as np
from .mechanics import EARTH_RADIUS

KEYS = ("altitude","speed","a","e","inclination","raan","arg_periapsis","true_anomaly")


def osculating_elements(position,velocity,mu):
    r,v = np.asarray(position,dtype=float),np.asarray(velocity,dtype=float)
    if r.shape != (3,) or v.shape != (3,) or not np.isfinite([*r,*v,mu]).all() or mu <= 0:
        raise ValueError("位置、速度和引力参数无效。")
    radius = np.linalg.norm(r)
    h = np.cross(r,v)
    hn = np.linalg.norm(h)
    if radius <= 0 or hn < 1e-12:
        raise ValueError("无法从径向或零位置状态计算六根数。")
    hhat = h/hn
    node = np.array([-h[1],h[0],0.])
    eccentricity = np.cross(v,h)/mu-r/radius
    e = float(np.linalg.norm(eccentricity))
    inverse_a = 2/radius-np.dot(v,v)/mu
    a = float(1/inverse_a) if abs(inverse_a) > 1e-15 else math.nan
    inclination = math.degrees(math.atan2(math.hypot(h[0],h[1]),h[2]))
    equatorial,circular = np.linalg.norm(node)/hn < 1e-8,e < 1e-8
    def angle(first,second):
        result = math.degrees(math.atan2(np.dot(np.cross(first,second),hhat),np.dot(first,second))) % 360
        return 0.0 if result > 360-1e-10 else result
    return {"a":a,"e":0.0 if e < 1e-12 else e,"inclination":inclination,
            "raan":math.nan if equatorial else math.degrees(math.atan2(node[1],node[0])) % 360,
            "arg_periapsis":math.nan if equatorial or circular else angle(node,eccentricity),
            "true_anomaly":math.nan if circular else angle(eccentricity,r)}


def state_values(model,position,velocity):
    mu = model.satellite.mu if hasattr(model,"satellite") else model.mu
    values = osculating_elements(position,velocity,mu)
    values["altitude"] = float(np.linalg.norm(position)-EARTH_RADIUS)
    values["speed"] = float(np.linalg.norm(velocity))
    return values


def sample_telemetry(model,start,stop,count=481):
    times = np.linspace(start,stop,count)
    values = {key:np.full(count,np.nan) for key in KEYS}
    errors = []
    for index,t in enumerate(times):
        try:
            position,velocity = model.state(float(t))
            sample = state_values(model,position,velocity)
            for key in KEYS:
                values[key][index] = sample[key]
        except (ValueError,OverflowError) as error:
            errors.append(str(error))
    return times,values,errors
