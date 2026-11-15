from copy import deepcopy
import json
import numpy as np
import pytest
from orbit_demo.scene_store import scene_document,decode_scene,read_scene,atomic_json,RecentScenes,MAX_BYTES
from orbit_demo.resources import create_single,create_walker,parse_tle_catalog,align_resources,GroundStation,GridSettings
from orbit_demo.mechanics import Elements
from orbit_demo.propagators import DEMO_TLE,DEFAULT_EPOCH


def document(empty=False):
    tle = parse_tle_catalog(DEMO_TLE)
    epoch = tle[0].model.epoch
    crafts = [] if empty else align_resources(tle+[create_single('独立单星',Elements(),epoch)]+create_walker('测试星座',6,2,1,700,60,epoch=epoch))
    if crafts:
        crafts[1].line_color = (.8,.2,.5)
        crafts[1].line_width = 3.5
        crafts[1].body = False
        crafts[3].orbit = False
    flags = dict(earth=True,graticule=True,night=False,shadow=True,sun=False,plane=True,velocity=False)
    grid = GridSettings(True,30,2.,(.3,.5,.8),True)
    stations = [GroundStation('北京',116.4,39.9,.05,False)]
    return scene_document('中文场景',crafts,stations,grid,flags,epoch,321.5,crafts[-1].uid if crafts else None,(-25.,40.,7.),60,1),crafts


def test_scene_round_trip_models_styles_groups_and_epochs(tmp_path):
    doc,original = document()
    path = tmp_path/'场景.astro.json'
    atomic_json(path,doc)
    saved,state = read_scene(path)
    assert saved['name']=='中文场景' and state['seconds']==321.5
    assert state['camera']==(-25.,40.,7.) and state['speed']==60 and state['tab']==1
    assert state['selected_id']==original[-1].uid
    assert not state['stations'][0].visible and state['stations'][0].name=='北京'
    assert state['grid'].equator and state['flags']['shadow'] and not state['flags']['night']
    for actual,expected in zip(state['crafts'],original):
        for field in ('uid','name','color','line_color','line_width','body','orbit','trail','constellation_id','constellation_name','walker_spec'):
            assert getattr(actual,field)==getattr(expected,field)
        assert actual.model.source.epoch==expected.model.source.epoch
        np.testing.assert_allclose(actual.model.state(321.5),expected.model.state(321.5),atol=1e-9)
    assert state['crafts'][0].model.tle==original[0].model.tle


def test_empty_scene_keeps_sites_and_environment():
    doc,_ = document(empty=True)
    state = decode_scene(doc)
    assert state['crafts']==[] and state['selected_id'] is None
    assert len(state['stations'])==1 and state['grid'].spacing==30


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(version=99),
    lambda d:d['spacecraft'][0].update(line_width=-1),
    lambda d:d['spacecraft'][0].update(color=[float('nan'),0,0]),
    lambda d:d['spacecraft'][0].update(body='false'),
    lambda d:d['spacecraft'][1].update(uid=d['spacecraft'][0]['uid']),
    lambda d:d['spacecraft'][2].update(constellation_id='missing'),
    lambda d:d['spacecraft'][3].update(line_color=[1,0,0]),
    lambda d:d['simulation'].update(selected_id='missing'),
    lambda d:d['simulation'].update(seconds=float('inf')),
    lambda d:d['display']['flags'].update(plane=False),
    lambda d:d['spacecraft'][0]['model'].update(tle='bad tle'),
    lambda d:d['stations'][0].update(latitude=100),
])
def test_invalid_scene_rejected(mutation):
    doc,_ = document()
    mutation(doc)
    with pytest.raises(ValueError): decode_scene(doc)


def test_atomic_save_failure_preserves_original_and_recent_paths(tmp_path):
    path = tmp_path/'scene.astro.json'
    doc,_ = document()
    atomic_json(path,doc)
    original = path.read_bytes()
    bad = deepcopy(doc)
    bad['simulation']['seconds'] = float('nan')
    with pytest.raises(ValueError): atomic_json(path,bad)
    assert path.read_bytes()==original
    assert list(tmp_path.iterdir())==[path]
    recent = RecentScenes(tmp_path/'profile'/'recent.json')
    recent.remember(path,doc)
    recent.remember(path,doc)
    assert len(recent.entries())==1
    assert recent.entries()[0]['spacecraft']==8
    path.unlink()
    assert len(recent.entries())==1  # Welcome page can explain a moved file.


def test_ten_thousand_scene_fits_file_limit_and_restores_group(tmp_path):
    crafts = align_resources(create_walker('10000 星',10000,100,1,550,53))
    flags = dict(earth=True,graticule=True,night=True,shadow=False,sun=False,plane=False,velocity=False)
    doc = scene_document('大型场景',crafts,[],GridSettings(),flags,DEFAULT_EPOCH,0,crafts[0].uid,(0,35,6))
    path = tmp_path/'large.astro.json'
    atomic_json(path,doc)
    assert path.stat().st_size<MAX_BYTES
    _,state = read_scene(path)
    assert len(state['crafts'])==10000
    assert len({c.constellation_id for c in state['crafts']})==1
