from PySide6.QtCore import Qt
from orbit_demo.resource_tree import ResourceTreeModel
from orbit_demo.resources import create_single,create_walker,align_resources
from orbit_demo.mechanics import Elements


def test_single_and_named_constellations_are_peers_with_stable_identity():
    single = create_single('单星',Elements())
    first = create_walker('同名星座',6,2,1,550,53)
    second = create_walker('同名星座',4,2,0,600,50)
    crafts = align_resources([single]+first+second)
    model = ResourceTreeModel()
    model.set_resources(crafts,[])
    root = model.index(1,0)
    assert model.rowCount(root)==3
    assert model.index(0,0,root).internalPointer().kind=='sat'
    group = model.index(1,0,root)
    other = model.index(2,0,root)
    assert group.internalPointer().key!=other.internalPointer().key
    assert model.rowCount(group)==6 and model.rowCount(other)==4
    for i in range(1,7):
        assert model.parent(model.spacecraft_index(i))==group
    assert crafts[1].constellation_id==first[0].constellation_id
    assert crafts[1].constellation_name=='同名星座'
    assert crafts[1].walker_spec==first[0].walker_spec
    assert crafts[1].walker_spec[1:4]==(6,2,1)
    assert len({c.line_color for c in crafts[1:7]})==1
    model.setData(group,Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)
    assert all(not (c.body or c.orbit or c.trail) for c in crafts[1:7])
    assert crafts[0].body and all(c.body for c in crafts[7:])
    model.setData(model.spacecraft_index(2),Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    assert model.data(group,Qt.ItemDataRole.CheckStateRole)==Qt.CheckState.PartiallyChecked
    model.setData(group,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    assert all(c.body and c.orbit and c.trail for c in crafts)
