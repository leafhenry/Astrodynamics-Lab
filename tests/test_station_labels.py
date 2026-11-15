import numpy as np
from orbit_demo.station_labels import project_station


def test_front_station_projects_to_camera_center_and_back_is_occluded():
    eye = [4.,0.,0.]
    np.testing.assert_allclose(project_station([1.002,0,0],eye,800,600),[400,300])
    assert project_station([-1.002,0,0],eye,800,600) is None
    assert project_station([-1.002,0,0],eye,800,600,False) is not None


def test_projection_tracks_camera_and_clips_points_behind_camera():
    p = [1.002,0.,0.]
    assert project_station(p,[4,0,0],800,600) is not None
    assert project_station(p,[-4,0,0],800,600) is None
    assert project_station([5,0,0],[4,0,0],800,600,False) is None
    above = project_station([1,.1,.1],[4,0,0],800,600)
    assert above[0]>400 and above[1]<300
