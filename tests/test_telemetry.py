import math
import numpy as np
import pytest
from orbit_demo.mechanics import Elements,EARTH_MU,EARTH_RADIUS
from orbit_demo.propagators import TwoBodyModel,SGP4Model,DEMO_TLE
from orbit_demo.telemetry import osculating_elements,sample_telemetry,state_values


@pytest.mark.parametrize("inclination",[20,90,155])
@pytest.mark.parametrize("nu",[0,73,180,315])
def test_elements_round_trip(inclination,nu):
    orbit = Elements(a=15000,e=.32,inclination=inclination,raan=215,arg_periapsis=73,true_anomaly=nu)
    position,velocity = orbit.state(0)
    recovered = osculating_elements(position,velocity,orbit.mu)
    for name in ("a","e","inclination","raan","arg_periapsis","true_anomaly"):
        assert recovered[name] == pytest.approx(getattr(orbit,name),abs=1e-8)


def test_two_body_curve_invariants_and_speed():
    model = TwoBodyModel()
    times,values,errors = sample_telemetry(model,0,model.period)
    assert not errors
    for name in ("a","e","inclination","raan","arg_periapsis"):
        np.testing.assert_allclose(values[name],getattr(model,name),atol=1e-8)
    np.testing.assert_allclose(values["speed"]**2,model.mu*(2/(values["altitude"]+EARTH_RADIUS)-1/model.a),atol=1e-10)
    assert values["true_anomaly"][240] == pytest.approx(180)


def test_singular_angles_are_undefined():
    for inclination in (0,180):
        r,v = Elements(e=0,inclination=inclination).state(0)
        result = osculating_elements(r,v,EARTH_MU)
        assert result["e"] == 0
        assert all(math.isnan(result[key]) for key in ("raan","arg_periapsis","true_anomaly"))
    r,v = Elements(e=.2,inclination=0,true_anomaly=30).state(0)
    assert osculating_elements(r,v,EARTH_MU)["true_anomaly"] == pytest.approx(30)


def test_sgp4_curves_are_osculating_not_tle_mean_elements():
    model = SGP4Model(DEMO_TLE)
    times,values,errors = sample_telemetry(model,0,model.period,81)
    assert not errors
    assert np.ptp(values["a"]) > .1
    assert np.ptp(values["e"]) > 1e-5
    pos,vel = model.state(times[20])
    current = state_values(model,pos,vel)
    assert values["speed"][20] == pytest.approx(np.linalg.norm(vel))
    assert values["a"][20] == pytest.approx(1/(2/np.linalg.norm(pos)-np.dot(vel,vel)/model.satellite.mu))
    assert current["a"] == values["a"][20]


def test_sampling_failure_is_gap_not_stale_curve():
    class BrokenModel(TwoBodyModel):
        def state(self,seconds):
            if seconds >= 5:
                raise ValueError("sample failed")
            return self.elements.state(seconds)
    times,values,errors = sample_telemetry(BrokenModel(),0,10,11)
    assert len(errors) == 6
    assert np.isfinite(values["altitude"][:5]).all()
    assert np.isnan(values["altitude"][5:]).all()
