import math
import numpy as np
import pytest
from orbit_demo.mechanics import Elements, PRESETS, EARTH_MU


@pytest.mark.parametrize("elements",list(PRESETS.values()))
def test_energy_angular_momentum_and_period(elements):
    initial_pos, initial_vel = elements.state(0)
    angular = np.cross(initial_pos,initial_vel)
    for t in np.linspace(-elements.period,2*elements.period,101):
        pos, vel = elements.state(t)
        energy = np.dot(vel,vel)/2-elements.mu/np.linalg.norm(pos)
        assert energy == pytest.approx(-elements.mu/(2*elements.a),rel=1e-11)
        np.testing.assert_allclose(np.cross(pos,vel),angular,rtol=1e-11,atol=1e-9)
    final_pos,final_vel = elements.state(elements.period)
    np.testing.assert_allclose(final_pos,initial_pos,atol=1e-8)
    np.testing.assert_allclose(final_vel,initial_vel,atol=1e-11)


def test_circular_quarter_period():
    orbit = Elements(a=7000,e=0,inclination=0,raan=0,arg_periapsis=0)
    pos,vel = orbit.state(orbit.period/4)
    np.testing.assert_allclose(pos,[0,7000,0],atol=1e-9)
    np.testing.assert_allclose(vel,[-math.sqrt(EARTH_MU/7000),0,0],atol=1e-12)


@pytest.mark.parametrize("eccentricity",[0,.35,.95,.9999])
def test_apsides_and_high_eccentricity(eccentricity):
    orbit = Elements(e=eccentricity)
    assert np.linalg.norm(orbit.state(0)[0]) == pytest.approx(orbit.a*(1-orbit.e))
    assert np.linalg.norm(orbit.state(orbit.period/2)[0]) == pytest.approx(orbit.a*(1+orbit.e))
    for t in [1e-5,.5,100]:
        pos,vel = orbit.state(t)
        assert np.linalg.norm(vel)**2 == pytest.approx(orbit.mu*(2/np.linalg.norm(pos)-1/orbit.a),rel=1e-9)


def test_initial_true_anomaly_and_orientation():
    orbit = Elements(a=10000,e=.2,inclination=90,raan=0,arg_periapsis=0,true_anomaly=90)
    pos,_ = orbit.state(0)
    np.testing.assert_allclose(pos,[0,0,9600],atol=1e-9)


@pytest.mark.parametrize("kwargs",[{"e":1},{"a":0},{"mu":-1},{"inclination":181},{"a":float("nan")}])
def test_reject_invalid_elements(kwargs):
    with pytest.raises(ValueError):
        Elements(**kwargs)
