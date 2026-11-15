from datetime import timedelta
import numpy as np
import pytest
from orbit_demo.batch import BatchEngine,GeometryEngine,map_coordinates
from orbit_demo.resources import create_single,create_walker,align_resources,parse_tle_catalog,GroundStation
from orbit_demo.mechanics import Elements,EARTH_RADIUS
from orbit_demo.propagators import DEFAULT_EPOCH,DEMO_TLE
from orbit_demo.environment import night_alpha,solar_position,earth_rotation


@pytest.mark.parametrize('seconds',[-10000,0,123.456,90000])
def test_vector_kepler_matches_scalar(seconds):
    crafts = [create_single(str(i),Elements(a=70000 if e>.8 else 17000,e=e,inclination=130,raan=71,true_anomaly=nu),DEFAULT_EPOCH-timedelta(hours=i))
              for i,(e,nu) in enumerate([(0,0),(.35,90),(.9,179),(.9,359.99)])]
    crafts = align_resources(crafts)
    frame = BatchEngine(crafts).state(seconds)
    assert frame.valid.all()
    for i,c in enumerate(crafts):
        r,v = c.model.state(seconds)
        np.testing.assert_allclose(frame.positions[i],r,atol=1e-7)
        np.testing.assert_allclose(frame.velocities[i],v,atol=1e-10)


def test_batch_mixed_tle_offsets_and_paths():
    crafts = parse_tle_catalog(DEMO_TLE)
    crafts += [create_single('other',Elements(),crafts[0].model.epoch+timedelta(hours=1))]
    crafts = align_resources(crafts)
    engine = BatchEngine(crafts)
    frame = engine.state(234)
    positions,times = engine.paths(234,[-.1,0,.5,1])
    for i,c in enumerate(crafts):
        np.testing.assert_allclose(frame.positions[i],c.model.state(234)[0],atol=1e-7)
        for k,t in enumerate(times[i]):
            np.testing.assert_allclose(positions[i,k],c.model.state(t)[0],atol=1e-7)


def test_ten_thousand_states_and_visibility():
    crafts = align_resources(create_walker('W',10000,100,1,550,53))
    frame = BatchEngine(crafts).state(700)
    assert frame.positions.shape==(10000,3) and frame.valid.all()
    np.testing.assert_allclose(np.linalg.norm(frame.positions,axis=1),EARTH_RADIUS+550,atol=1e-8)
    mask = np.zeros((10000,3),bool)
    mask[4,1] = True
    result = GeometryEngine(crafts).build(700,mask,0,'3d')
    assert len(result['orbit'][0])==128 and len(result['trail'][0])==0


def test_night_map_remains_readable_and_rotates():
    alpha = night_alpha(DEFAULT_EPOCH)
    assert alpha.shape==(360,720)
    assert alpha.min()==0 and alpha.max()==148
    assert .4<np.mean(alpha>74)<.6
    assert not np.array_equal(alpha,night_alpha(DEFAULT_EPOCH+timedelta(hours=12)))
    sun = solar_position(DEFAULT_EPOCH)
    xy = map_coordinates(sun,earth_rotation(DEFAULT_EPOCH))
    x,y = np.rint(xy*[719,359]).astype(int)
    assert alpha[y,x]==0


@pytest.mark.parametrize('days',[0,90,180,270])
def test_terminator_matches_solar_boundary_and_narrow_twilight(days):
    from orbit_demo.environment import terminator_points
    utc = DEFAULT_EPOCH+timedelta(days=days)
    boundary = terminator_points(utc)
    sun = solar_position(utc)
    sun /= np.linalg.norm(sun)
    np.testing.assert_allclose(boundary@sun,0,atol=1e-15)
    np.testing.assert_allclose(np.linalg.norm(boundary,axis=1),1,atol=1e-15)
    np.testing.assert_allclose(boundary[0],boundary[-1],atol=1e-15)
    alpha = night_alpha(utc)
    assert np.mean((alpha>0)&(alpha<148))<.035


def test_station_earth_fixed_rotation():
    station = GroundStation('S',0,0)
    np.testing.assert_allclose(station.position(0),[EARTH_RADIUS,0,0],atol=1e-9)
    np.testing.assert_allclose(station.position(np.pi/2),[0,EARTH_RADIUS,0],atol=1e-9)
    with pytest.raises(ValueError): GroundStation('bad',181,0)
    with pytest.raises(ValueError): GroundStation('bad',0,-91)


def test_resource_line_style_survives_alignment_and_batching():
    crafts = create_walker('W',3,1,0,550,53)
    crafts[1].line_color = (1.,0.,.2)
    crafts[1].line_width = 4
    crafts = align_resources(crafts)
    assert crafts[1].line_color==(1.,0.,.2) and crafts[1].line_width==4
    styles = dict(colors=np.array([c.line_color or c.color for c in crafts]),
                  widths=np.array([c.line_width for c in crafts]),custom=np.array([False,True,False]))
    result = GeometryEngine(crafts).build(100,np.ones((3,3),bool),0,'3d',styles)
    widths = result['line_widths']['orbit']
    assert set(widths)=={1,4}  # Coincident orbits with distinct styles must not be merged.
    np.testing.assert_allclose(result['orbit'][1][widths==4],np.tile([1,0,.2],(np.count_nonzero(widths==4),1)),atol=1e-7)
