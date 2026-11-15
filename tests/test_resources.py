from datetime import timedelta
import numpy as np
import pytest
from sgp4.io import fix_checksum
from orbit_demo.mechanics import Elements, EARTH_RADIUS
from orbit_demo.propagators import DEFAULT_EPOCH, DEMO_TLE, SGP4Model
from orbit_demo.resources import (create_single,create_walker,parse_tle_catalog,
                                  align_resources,is_sgp4,Spacecraft)


def second_tle():
    first,second = DEMO_TLE.splitlines()[1:]
    first = first[:2]+'00006'+first[7:20]+'180.78495062'+first[32:]
    second = second[:2]+'00006'+second[7:]
    return '\n'.join([fix_checksum(first),fix_checksum(second)])


def test_walker_geometry():
    crafts = create_walker('Demo',24,6,1,550,53)
    assert len(crafts)==24 and len({c.uid for c in crafts})==24
    for p in range(6):
        for s in range(4):
            m = crafts[p*4+s].model
            assert m.a == EARTH_RADIUS+550 and m.e == 0
            assert m.raan == p*60 and m.true_anomaly == (s*90+p*15)%360
    star = create_walker('Star',12,3,2,800,87,kind='Star')
    assert [star[j].model.raan for j in (0,4,8)] == [0,60,120]
    assert star[4].model.true_anomaly == 60


@pytest.mark.parametrize('total,planes,f',[(23,6,1),(24,6,6),(24,6,-1),(10001,1,0),(0,1,0),(3,0,0),(3,4,0)])
def test_invalid_walker(total,planes,f):
    with pytest.raises(ValueError):
        create_walker('W',total,planes,f,550,53)


def test_multi_tle_and_common_utc():
    crafts = parse_tle_catalog('\ufeff0 '+DEMO_TLE+'\n\n'+second_tle())
    assert len(crafts)==2 and crafts[1].name == 'NORAD 6'
    sources = [c.model for c in crafts]
    aligned = align_resources(crafts)
    for craft,source in zip(aligned,sources):
        assert is_sgp4(craft.model)
        assert craft.model.utc(123) == sources[1].epoch+timedelta(seconds=123)
        offset = (sources[1].epoch-source.epoch).total_seconds()
        np.testing.assert_allclose(craft.model.state(123),source.state(offset+123))
    assert aligned[0].model.source.epoch != aligned[1].model.source.epoch


@pytest.mark.parametrize('text',['',DEMO_TLE+'\n'+DEMO_TLE,DEMO_TLE.splitlines()[1],DEMO_TLE.splitlines()[2],DEMO_TLE[:-1]+'0'])
def test_invalid_catalog(text):
    with pytest.raises(ValueError):
        parse_tle_catalog(text)


def test_alignment_preserves_state_and_visibility():
    first = create_single('early',Elements(),DEFAULT_EPOCH-timedelta(hours=1))
    second = create_single('late',Elements(),DEFAULT_EPOCH)
    first.body = False
    aligned = align_resources([first,second])
    assert aligned[0].uid == first.uid and not aligned[0].body
    np.testing.assert_allclose(aligned[0].model.state(60),first.model.state(3660))
    again = align_resources(aligned)
    np.testing.assert_allclose(again[0].model.state(60),aligned[0].model.state(60))


def test_bad_single_and_resource_count():
    with pytest.raises(ValueError):
        create_single('below ground',Elements(a=7000,e=.3))
    with pytest.raises(ValueError):
        align_resources([])
    craft = create_single('S',Elements())
    with pytest.raises(ValueError):
        align_resources([craft]*10001)
