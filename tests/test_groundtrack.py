import math
import numpy as np
import pytest
from orbit_demo.environment import earth_rotation
from orbit_demo.groundtrack import subsatellite_point, split_at_dateline, sample_groundtrack
from orbit_demo.propagators import DEFAULT_EPOCH, TwoBodyModel, SGP4Model, DEMO_TLE
from orbit_demo.mechanics import PRESETS


def test_greenwich_equator_and_north_pole():
    angle = earth_rotation(DEFAULT_EPOCH)
    position = 7000*np.array([math.cos(angle),math.sin(angle),0])
    np.testing.assert_allclose(subsatellite_point(position,DEFAULT_EPOCH),(0,0),atol=1e-10)
    assert subsatellite_point([0,0,7000],DEFAULT_EPOCH)[1] == 90


@pytest.mark.parametrize("points,edges",[
    ([(170,10),(-170,30)],[180,-180]),
    ([(-170,10),(170,30)],[-180,180]),
])
def test_dateline_interpolation(points,edges):
    segments = split_at_dateline(points)
    assert len(segments) == 2
    assert segments[0][-1] == (edges[0],20)
    assert segments[1][0] == (edges[1],20)
    assert segments[0][0] == points[0]
    assert segments[1][-1] == points[-1]


def test_geosynchronous_groundtrack_is_nearly_stationary():
    model = TwoBodyModel(PRESETS["地球同步轨道 · GEO"])
    points = np.asarray(sample_groundtrack(model,0,model.period))
    longitude = np.degrees(np.unwrap(np.radians(points[:,0])))
    assert np.ptp(longitude) < .01
    np.testing.assert_allclose(points[:,1],0,atol=1e-10)


def test_sgp4_groundtrack_bounds_and_time():
    model = SGP4Model(DEMO_TLE)
    points = sample_groundtrack(model,100,100+model.period)
    assert points[0] == subsatellite_point(model.state(100)[0],model.utc(100))
    assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon,lat in points)
    for segment in split_at_dateline(points):
        assert all(abs(b[0]-a[0]) <= 180 for a,b in zip(segment,segment[1:]))
