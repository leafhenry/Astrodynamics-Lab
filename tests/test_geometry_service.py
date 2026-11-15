import numpy as np
import pytest
from orbit_demo.resources import Spacecraft,align_resources
from orbit_demo.propagators import SGP4Model,DEMO_TLE
from orbit_demo.batch import GeometryEngine
from orbit_demo.geometry_service import GeometryService


def test_process_geometry_matches_direct_and_retires():
    source = SGP4Model(DEMO_TLE)
    crafts = align_resources([Spacecraft(str(i),source) for i in range(129)])
    service = GeometryService(crafts)
    assert service.isolated
    mask = np.ones((129,3),bool)
    try:
        result = service.build(600,mask,0,'3d')
        reference = GeometryEngine(crafts).build(600,mask,0,'3d')
        np.testing.assert_allclose(result['orbit'][0],reference['orbit'][0])
        np.testing.assert_allclose(result['trail'][0],reference['trail'][0])
        mapped = service.build(600,mask,0,'2d')
        assert not mapped['image'].isNull() and mapped['image'].width()==1600
        styles = dict(colors=np.tile([1.,.2,.3],(129,1)),widths=np.full(129,3),custom=np.ones(129,bool))
        restyled = service.build(600,mask,0,'3d',styles)
        assert np.all(restyled['line_widths']['orbit']==3)
        np.testing.assert_allclose(restyled['orbit'][1][0],[1,.2,.3],atol=1e-7)
        service.retire()
        with pytest.raises(ValueError): service.build(600,mask,0,'3d')
    finally:
        service.close()
