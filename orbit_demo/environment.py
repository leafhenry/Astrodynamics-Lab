"""Approximate solar ephemeris and finite-disc Earth eclipse geometry.

Sun: USNO low-precision equatorial coordinates of date (about one arcminute).
For this visual demo the small MOD/TEME difference is neglected, as are UT1-UTC,
polar motion and atmospheric refraction. This is not a precision eclipse service.
"""
import math
import numpy as np
from sgp4.conveniences import jday_datetime
from sgp4.propagation import gstime
from .mechanics import EARTH_RADIUS

AU_KM = 149597870.7
SUN_RADIUS = 695700.0


def night_alpha(utc,width=720,height=360):
    """Readable night overlay: maximum opacity 58%, with a twilight transition."""
    lon = np.linspace(-np.pi,np.pi,width)
    lat = np.linspace(np.pi/2,-np.pi/2,height)
    sun = solar_position(utc)
    sun /= np.linalg.norm(sun)
    angle = earth_rotation(utc)
    incidence = np.cos(lat)[:,None]*(sun[0]*np.cos(lon+angle)+sun[1]*np.sin(lon+angle))+sun[2]*np.sin(lat)[:,None]
    blend = np.clip((.018-incidence)/.036,0,1)
    blend = blend*blend*(3-2*blend)
    return np.rint(148*blend).astype(np.uint8)


def terminator_points(utc,count=721):
    """Unit-sphere day/night boundary in the same solar frame as the globe."""
    axis = solar_position(utc)
    axis /= np.linalg.norm(axis)
    helper = np.array([0.,0.,1.]) if abs(axis[2])<.9 else np.array([0.,1.,0.])
    u = np.cross(axis,helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis,u)
    angles = np.linspace(0,2*np.pi,count)
    return np.cos(angles)[:,None]*u+np.sin(angles)[:,None]*v


def solar_position(utc):
    jd, fraction = jday_datetime(utc)
    days = (jd-2451545.0)+fraction
    mean = math.radians((357.529+.98560028*days) % 360)
    longitude = math.radians((280.459+.98564736*days+1.915*math.sin(mean)+.020*math.sin(2*mean)) % 360)
    obliquity = math.radians(23.439-.00000036*days)
    distance = AU_KM*(1.00014-.01671*math.cos(mean)-.00014*math.cos(2*mean))
    return distance*np.array([math.cos(longitude),math.cos(obliquity)*math.sin(longitude),math.sin(obliquity)*math.sin(longitude)])


def earth_rotation(utc):
    jd, fraction = jday_datetime(utc)
    return gstime(jd+fraction)


def eclipse(position, sun_position):
    """Return (sunlit/penumbra/umbra, visible solar-disc fraction).

Disc overlap uses apparent angular radii, a small-angle circle-overlap model.
The sphere and finite solar disc correctly distinguish umbra and penumbra.
"""
    position = np.asarray(position,dtype=float)
    to_sun = np.asarray(sun_position,dtype=float)-position
    radius = np.linalg.norm(position)
    if radius <= EARTH_RADIUS:
        return "umbra", 0.0
    earth_angle = math.asin(EARTH_RADIUS/radius)
    sun_angle = math.asin(SUN_RADIUS/np.linalg.norm(to_sun))
    separation = math.acos(float(np.clip(np.dot(-position,to_sun)/(radius*np.linalg.norm(to_sun)),-1,1)))
    if separation >= earth_angle+sun_angle:
        return "sunlit",1.0
    if earth_angle >= separation+sun_angle:
        return "umbra",0.0
    if sun_angle >= separation+earth_angle:
        return "penumbra",1-(earth_angle/sun_angle)**2
    r, R, d = sun_angle,earth_angle,separation
    overlap = r*r*math.acos(float(np.clip((d*d+r*r-R*R)/(2*d*r),-1,1)))
    overlap += R*R*math.acos(float(np.clip((d*d+R*R-r*r)/(2*d*R),-1,1)))
    overlap -= .5*math.sqrt(max(0,(-d+r+R)*(d+r-R)*(d-r+R)*(d+r+R)))
    return "penumbra",float(np.clip(1-overlap/(math.pi*r*r),0,1))


def shadow_outline(sun_position, length=6.0, penumbra=False):
    """Truncated tangent-cone wireframe in Earth-radius render units."""
    distance = np.linalg.norm(sun_position)/EARTH_RADIUS
    axis = -np.asarray(sun_position)/np.linalg.norm(sun_position)
    helper = np.array([0,0,1.]) if abs(axis[2]) < .9 else np.array([0,1.,0])
    u = np.cross(axis,helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis,u)
    solar_radius = SUN_RADIUS/EARTH_RADIUS
    alpha = math.asin((solar_radius+1 if penumbra else solar_radius-1)/distance)
    # Sphere-cone tangency ring; the cross-section radius at x=0 is sec(alpha).
    slope = math.tan(alpha)*(1 if penumbra else -1)
    start = -math.sin(alpha) if penumbra else math.sin(alpha)
    def point(x,angle):
        return axis*x+(1/math.cos(alpha)+slope*x)*(math.cos(angle)*u+math.sin(angle)*v)
    points = []
    for x in (start,length/2,length):
        for a,b in zip(np.linspace(0,2*math.pi,97)[:-1],np.linspace(0,2*math.pi,97)[1:]):
            points.extend((point(x,a),point(x,b)))
    for a in np.linspace(0,2*math.pi,9)[:-1]:
        points.extend((point(start,a),point(length,a)))
    return np.asarray(points)
