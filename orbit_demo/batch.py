"""Vectorized dynamics and packed geometry for large constellations."""
from dataclasses import dataclass
from datetime import timedelta
import time
import numpy as np
from sgp4.api import Satrec,SatrecArray,WGS72
from sgp4.conveniences import jday_datetime
from .mechanics import EARTH_RADIUS
from .environment import earth_rotation
from .resources import is_sgp4


@dataclass
class Frame:
    seconds: float
    positions: np.ndarray
    velocities: np.ndarray
    valid: np.ndarray
    elapsed_ms: float


class BatchEngine:
    def __init__(self,crafts):
        self.count = len(crafts)
        self.epoch = crafts[0].model.epoch
        self.models = [c.model for c in crafts]
        self.periods = np.array([m.period for m in self.models])
        self.two = np.array([i for i,m in enumerate(self.models) if not is_sgp4(m)],dtype=int)
        self.sgp = np.array([i for i,m in enumerate(self.models) if is_sgp4(m)],dtype=int)
        elements = [self.models[i] for i in self.two]
        self.a = np.array([m.a for m in elements])
        self.e = np.array([m.e for m in elements])
        self.n = 2*np.pi/self.periods[self.two]
        self.m0 = np.array([m.mean_anomaly_epoch for m in elements])
        self.offset = np.array([getattr(m,'offset',0) for m in elements])
        self.rotation = np.array([m.rotation for m in elements]).reshape(-1,3,3)
        # Each worker owns its own mutable SGP4 objects (including deep-space state).
        self.sats = [Satrec.twoline2rv(*self.models[i].tle.splitlines(),WGS72) for i in self.sgp]
        self.sat_array = SatrecArray(self.sats) if self.sats else None
        self.jd,self.fr = jday_datetime(self.epoch)

    def two_state(self,seconds):
        t = np.asarray(seconds)
        mean = np.remainder(self.m0+self.n*(t+self.offset),2*np.pi)
        eccentric = np.where(self.e<.8,mean,np.pi)
        low,high = np.zeros_like(mean),np.full_like(mean,2*np.pi)
        for _ in range(50):
            residual = eccentric-self.e*np.sin(eccentric)-mean
            if np.max(np.abs(residual),initial=0) < 1e-13:
                break
            high = np.where(residual>0,eccentric,high)
            low = np.where(residual<=0,eccentric,low)
            trial = eccentric-residual/(1-self.e*np.cos(eccentric))
            new = np.where((trial>low)&(trial<high),trial,(low+high)/2)
            eccentric = np.where(np.abs(residual)<1e-13,eccentric,new)
        x = self.a*(np.cos(eccentric)-self.e)
        y = self.a*np.sqrt(1-self.e*self.e)*np.sin(eccentric)
        rate = self.n/(1-self.e*np.cos(eccentric))
        vx = -self.a*np.sin(eccentric)*rate
        vy = self.a*np.sqrt(1-self.e*self.e)*np.cos(eccentric)*rate
        r = x[...,None]*self.rotation[:, :,0]+y[...,None]*self.rotation[:,:,1]
        v = vx[...,None]*self.rotation[:,:,0]+vy[...,None]*self.rotation[:,:,1]
        return r,v

    def state(self,seconds):
        start = time.perf_counter()
        positions,velocities = np.zeros((self.count,3)),np.zeros((self.count,3))
        valid = np.ones(self.count,dtype=bool)
        if self.two.size:
            positions[self.two],velocities[self.two] = self.two_state(seconds)
        if self.sgp.size:
            errors,r,v = self.sat_array.sgp4(np.array([self.jd]),np.array([self.fr+seconds/86400]))
            positions[self.sgp],velocities[self.sgp] = r[:,0],v[:,0]
            valid[self.sgp] = errors[:,0]==0
        valid &= np.isfinite(positions).all(axis=1)&np.isfinite(velocities).all(axis=1)
        return Frame(seconds,positions,velocities,valid,(time.perf_counter()-start)*1000)

    def paths(self,seconds,fractions):
        """N x K positions; fractions refer to each spacecraft's own period."""
        fractions = np.asarray(fractions)
        times = seconds+self.periods[:,None]*fractions
        result = np.full((self.count,len(fractions),3),np.nan)
        if self.two.size:
            for k in range(len(fractions)):
                result[self.two,k] = self.two_state(times[self.two,k])[0]
        for row,sat in zip(self.sgp,self.sats):
            errors,r,_ = sat.sgp4_array(np.full(len(fractions),self.jd),self.fr+times[row]/86400)
            r[errors!=0] = np.nan
            result[row] = r
            if row%128==0:
                time.sleep(0)  # Let the UI/propagation thread run between native batches.
        return result,times


def map_coordinates(positions,angles):
    lon = (np.arctan2(positions[...,1],positions[...,0])-angles+np.pi)%(2*np.pi)-np.pi
    lat = np.arctan2(positions[...,2],np.hypot(positions[...,0],positions[...,1]))
    return np.stack(((lon+np.pi)/(2*np.pi),(.5-lat/np.pi)),axis=-1)


def line_segments(points):
    return np.stack((points[:,:-1],points[:,1:]),axis=2)


class GeometryEngine:
    def __init__(self,crafts):
        self.engine = BatchEngine(crafts)
        self.colors = np.array([c.color for c in crafts],dtype=np.float32)
        self.orbit_keys = []
        for i,c in enumerate(crafts):
            m = c.model
            self.orbit_keys.append(('sgp4',i) if is_sgp4(m) else (m.a,m.e,m.inclination,m.raan,m.arg_periapsis,*c.color))

    def build(self,seconds,visibility,selected,mode,styles=None):
        start = time.perf_counter()
        # All checked spacecraft are included. Only curve tessellation changes with load.
        samples = 129 if self.engine.count<=128 else 65
        results = {'line_widths':{}}
        palette = self.colors if styles is None else styles['colors']
        widths = np.ones(self.engine.count) if styles is None else styles['widths']
        for layer,fractions in [('orbit',np.linspace(0,1,samples)),('trail',np.linspace(-.1,0,13))]:
            mask = visibility[:,1 if layer=='orbit' else 2].copy()
            if mode=='3d':
                mask[selected] = False
                if layer=='orbit':
                    # Identical Kepler ellipses share one curve; every body/trail remains.
                    seen = set()
                    for i in np.flatnonzero(mask):
                        key = (self.orbit_keys[i],tuple(palette[i]),float(widths[i]))
                        if key in seen: mask[i] = False
                        else: seen.add(key)
            if not mask.any():
                results[layer] = (np.empty((0,3),np.float32),np.empty((0,3),np.float32))
                results['line_widths'][layer] = np.empty(0,np.float32)
                continue
            positions,times = self.engine.paths(seconds,fractions)
            if mode=='2d':
                # GMST is linear over these short windows; include the date's sidereal rate.
                angle = earth_rotation(self.engine.epoch+timedelta(seconds=seconds))+(times-seconds)*7.2921158553e-5
                points = map_coordinates(positions,angle)
            else:
                points = positions/EARTH_RADIUS
            segments = line_segments(points[mask])
            valid = np.isfinite(segments).all(axis=(-1,-2))
            if mode=='2d':
                valid &= np.abs(segments[:,:,0,0]-segments[:,:,1,0])<.5
            layer_palette = palette.copy()
            if mode=='2d' and (styles is None or not styles['custom'][selected]):
                layer_palette[selected] = [.26,.82,.88] if layer=='orbit' else [1,.67,.33]
            colors = np.broadcast_to(layer_palette[mask,None,:],(*valid.shape,3))[valid]
            line_widths = np.broadcast_to(widths[mask,None],valid.shape)[valid]
            results['line_widths'][layer] = np.repeat(line_widths,2).astype(np.float32)
            results[layer] = (np.ascontiguousarray(segments[valid].reshape(-1,points.shape[-1]),dtype=np.float32),
                              np.repeat(colors,2,axis=0))
        results['mode'],results['seconds'] = mode,seconds
        if mode=='2d':
            from .map_raster import raster_lines
            results['image'] = raster_lines([(*results[key],results['line_widths'][key]) for key in ('orbit','trail')])
        results['elapsed_ms'] = (time.perf_counter()-start)*1000
        return results
