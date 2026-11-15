from datetime import datetime,timezone,timedelta
import math
import numpy as np
import pytest
from orbit_demo.mechanics import EARTH_RADIUS,Elements
from orbit_demo.propagators import SGP4Model,TwoBodyModel,DEMO_TLE,PropagationError
from orbit_demo.environment import AU_KM,solar_position,earth_rotation,eclipse,shadow_outline


@pytest.mark.parametrize("minutes,position,velocity",[
    (0,[7022.46529266,-1400.08296755,.03995155],[1.893841015,6.405893759,4.534807250]),
    (360,[-7154.03120202,-3783.17682504,-3536.19412294],[4.741887409,-4.151817765,-2.093935425]),
    (1440,[-938.55923943,-6268.18748831,-4294.02924751],[7.536105209,-.427127707,.989878080]),
])
def test_vallado_reference_vectors(minutes,position,velocity):
    # Published Vallado verification set, sgp4/tcppver.out satellite 00005.
    model = SGP4Model(DEMO_TLE)
    r,v = model.state(minutes*60)
    np.testing.assert_allclose(r,position,atol=2e-8,rtol=0)
    np.testing.assert_allclose(v,velocity,atol=2e-9,rtol=0)


def test_sgp4_epoch_and_no_period_wrap():
    model = SGP4Model(DEMO_TLE)
    assert model.epoch.year == 2000
    assert model.utc(86400)-model.epoch == timedelta(days=1)
    assert np.linalg.norm(model.state(0)[0]-model.state(model.period)[0]) > 1
    np.testing.assert_allclose(model.path(count=5,start_seconds=100)[0],model.state(100)[0])
    assert model.frame == "TEME"


@pytest.mark.parametrize("text",["",DEMO_TLE[:-1],DEMO_TLE[:-1]+"0",DEMO_TLE.replace("2 00005","2 00006"),DEMO_TLE.replace("348.7242","错误.7242")])
def test_invalid_tle(text):
    with pytest.raises(ValueError):
        SGP4Model(text)


def test_bad_or_decayed_sgp4_state():
    model = SGP4Model(DEMO_TLE)
    with pytest.raises(PropagationError):
        model.state(float("nan"))
    class FailedSatellite:
        jdsatepoch,jdsatepochF = 2451545.,0.
        def sgp4(self,jd,fraction):
            return 6,[0,0,0],[0,0,0]
    model.satellite = FailedSatellite()
    with pytest.raises(PropagationError,match="6"):
        model.state(0)


def test_deep_space_branch():
    model = SGP4Model("""1 04632U 70093B   04031.91070959 -.00000084  00000-0  10000-3 0  9955
2 04632  11.4628 273.1101 1450506 207.6000 143.9350  1.20231981 44145""")
    assert model.satellite.method == "d"
    assert np.isfinite(model.state(86400)[0]).all()


def test_two_body_adapter_preserves_physics():
    elements = Elements()
    model = TwoBodyModel(elements)
    np.testing.assert_allclose(model.state(100)[0],elements.state(100)[0])
    assert model.utc(100)-model.epoch == timedelta(seconds=100)


@pytest.mark.parametrize("month,declination",[(6,23.44),(12,-23.44)])
def test_solar_solstices(month,declination):
    sun = solar_position(datetime(2026,month,21,12,tzinfo=timezone.utc))
    assert math.degrees(math.asin(sun[2]/np.linalg.norm(sun))) == pytest.approx(declination,abs=.08)
    assert .98*AU_KM < np.linalg.norm(sun) < 1.02*AU_KM


def test_earth_sidereal_rotation():
    utc = datetime(2026,11,15,tzinfo=timezone.utc)
    delta = (earth_rotation(utc+timedelta(hours=6))-earth_rotation(utc)) % (2*math.pi)
    assert math.degrees(delta) == pytest.approx(90.2464,abs=.001)


def test_eclipse_geometries_and_continuity():
    sun = np.array([AU_KM,0,0])
    assert eclipse([7000,0,0],sun) == ("sunlit",1.)
    assert eclipse([-7000,0,0],sun) == ("umbra",0.)
    assert eclipse([0,7000,0],sun) == ("sunlit",1.)
    status,fraction = eclipse([-7000,EARTH_RADIUS,0],sun)
    assert status == "penumbra" and .45 < fraction < .55
    values = [eclipse([-7000,y,0],sun)[1] for y in np.linspace(6300,6450,301)]
    assert all(a <= b+1e-10 for a,b in zip(values,values[1:]))
    assert max(np.diff(values)) < .02
    # Shadow boundaries coincide with the independent angular eclipse test.
    for penumbra in (False,True):
        outline = shadow_outline(sun,penumbra=penumbra)
        assert outline.shape == (592,3)
        end_ring = outline[384:576]*EARTH_RADIUS
        fractions = [eclipse(p,sun)[1] for p in end_ring[::24]]
        np.testing.assert_allclose(fractions,1. if penumbra else 0.,atol=1e-6)
