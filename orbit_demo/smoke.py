"""Desktop integration checks; needs a working OpenGL context."""
import csv
import traceback
import time
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt,QEventLoop,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu,QLabel
from PySide6.QtGui import QColor
from .line_style import LineStyleDialog
from .configuration import ConfigurationDialog
from .stations import StationDialog
from .resources import create_walker,parse_tle_catalog,create_single,GroundStation,MAX_SPACECRAFT
from .mechanics import Elements
from .propagators import DEMO_TLE


def run(window,app):
    try:
        check(window,app)
    except Exception:
        traceback.print_exc()
        window.close()
        app.exit(1)
    else:
        print('SMOKE PASS: async propagation, resource tree, stations, night map, charts, playback, CSV',flush=True)
        window.close()
        app.exit(0)


def pump(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds,loop.quit)
    loop.exec()


def wait_for(predicate,timeout=10000):
    deadline = time.perf_counter()+timeout/1000
    while not predicate():
        if time.perf_counter()>deadline: raise AssertionError('Timed out waiting for background result')
        pump(30)


def check(w,app):
    out = Path(__file__).resolve().parent.parent/'artifacts'
    out.mkdir(exist_ok=True)
    if w.playing: w.toggle_play()
    w.reset()
    wait_for(lambda:w.last_frame is not None and w.seconds==0)
    assert w.view.ready,w.view.render_error
    assert w.windowTitle()=='ASTRODYNAMICS LAB'
    panel = w.resource_panel
    labels = [label.text() for label in w.findChildren(QLabel)]
    assert all(title in labels for title in ['01   场景配置','02   场景管理','03   共享显示配置','04   视角和数据'])
    assert not hasattr(w,'frame_label') and not hasattr(w,'clock') and not hasattr(w,'apsides')
    assert panel.model.rowCount()==3 and 'stars' not in panel.model.flags_state
    assert w.view_tabs.tabText(0)=='轨道视图' and '轨道视图' not in labels
    assert not any('轨迹：跟随资源' in text for text in labels)
    # The initial (last) spacecraft can be removed; late worker results stay out.
    original = w.resources
    w.remove_resource()
    wait_for(lambda:not w.resources)
    pump(150)
    assert w.selected_id is None and w.sim_engine is None
    assert not w.export_button.isEnabled() and not w.timeline.isEnabled()
    assert w.view.satellite.nodeMask==w.view.orbits.nodeMask==w.view.trail.nodeMask==0
    assert w.ground_view.active is None and w.ground_view.track_image.isNull()
    w.view_tabs.setCurrentIndex(2)
    pump(100)
    assert w.data_view.latest_state is None and w.data_view.model is None
    assert all(np.isnan(plot.values).all() for plot in w.data_view.plots.values())
    w.view_tabs.setCurrentIndex(0)
    assert w.grab().save(str(out/'lab_empty.png'))
    w.install_resources(original)
    wait_for(lambda:w.last_frame is not None)
    assert w.export_button.isEnabled() and w.timeline.isEnabled()
    # Editing a single spacecraft changes orbital parameters, not only its name.
    uid = w.selected_id
    def edit_single():
        dialog = app.activeModalWidget()
        if isinstance(dialog,ConfigurationDialog):
            dialog.name.setText('单星编辑回归')
            dialog.fields['a'].setValue(8000)
            dialog.fields['e'].setValue(.05)
            dialog.validate_and_accept()
    QTimer.singleShot(80,edit_single)
    w.edit_resource()
    wait_for(lambda:w.resources[0].name=='单星编辑回归')
    assert w.selected_id==uid and w.elements.a==8000 and w.elements.e==.05
    assert not any(panel.buttons[key].isChecked() for key in ('plane','sun','shadow','velocity'))
    assert not panel.settings.equator
    assert not any('Python  +  OpenSceneGraph' in text for text in labels)
    panel.buttons['plane'].click()
    pump(60)
    assert w.view.show_grid and panel.settings.equator
    panel.buttons['plane'].click()
    panel.buttons['sun'].click()
    pump(60)
    assert w.view.sun_arrow.nodeMask!=0 and w.view.umbra.nodeMask==0 and w.view.show_stars
    panel.buttons['sun'].click()
    for key,node in [('shadow',w.view.umbra),('velocity',w.view.velocity)]:
        panel.buttons[key].click()
        pump(60)
        assert node.nodeMask!=0
        panel.buttons[key].click()
    pump(60)
    def global_flag(key,enabled):
        panel.model.flags_state[key] = enabled
        panel.item_changed()
        QTest.qWait(100)
    def picture(name):
        QTest.qWait(150)
        assert w.grab().save(str(out/name))
    before = w.view.grabFramebuffer()
    global_flag('graticule',False)
    assert before!=w.view.grabFramebuffer()
    global_flag('graticule',True)
    panel.spacing.setCurrentIndex(3)
    panel.width.setValue(1.5)
    QTest.qWait(80)
    assert w.view.grid_settings is w.ground_view.grid_settings
    assert w.view.grid_settings.spacing==30
    w.install_resources(create_walker('Walker',24,6,1,550,53))
    w.advance_to(600)
    wait_for(lambda:w.seconds==600)
    wait_for(lambda:w.view.batch_nodes['orbit'].drawables[0].primitiveSets[0].count>0)
    assert len(w.view.batch_nodes)==4
    satroot = panel.model.index(1,0)
    group = panel.model.index(0,0,satroot)
    assert group.internalPointer().kind=='constellation'
    assert panel.model.rowCount(group)==24
    panel.tree.expand(group)
    panel.model.setData(satroot,Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)
    QTest.qWait(100)
    assert not any(c.body or c.orbit or c.trail for c in w.resources)
    assert w.view.satellite.nodeMask==0
    panel.model.setData(satroot,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    QTest.qWait(100)
    target = w.resources[5]
    camera = (w.view.yaw,w.view.pitch,w.view.distance)
    panel.tree.setCurrentIndex(panel.model.spacecraft_index(5))
    QTest.qWait(100)
    assert w.selected_id==target.uid and w.seconds==600
    assert (w.view.yaw,w.view.pitch,w.view.distance)==camera
    # Exercise the actual context menu and transactional style dialog.
    index = panel.model.spacecraft_index(5)
    panel.tree.scrollTo(index)
    pump(50)
    style_checks = []
    def save_style():
        dialog = app.activeModalWidget()
        if isinstance(dialog,LineStyleDialog):
            dialog.color = QColor('#f34488')
            dialog.width.setValue(4)
            dialog.update_color()
            dialog.grab().save(str(out/'layout_line_style.png'))
            dialog.accept()
            style_checks.append('saved')
    def choose_style():
        menu = app.activePopupWidget()
        if isinstance(menu,QMenu):
            action = menu.actions()[0]
            menu.close()
            QTimer.singleShot(80,save_style)
            action.trigger()
    QTimer.singleShot(80,choose_style)
    panel.context_menu(panel.tree.visualRect(index).center())
    wait_for(lambda:bool(style_checks))
    pump(80)
    assert target.line_width==4 and target.line_color is not None
    assert all(c.line_color==target.line_color and c.line_width==4 for c in w.resources)
    assert w.view.orbit_node.drawables[0].vertexAttrib[2][0].x==4
    # Selecting another resource retains the custom line in the batched renderer.
    panel.tree.setCurrentIndex(panel.model.spacecraft_index(0))
    wait_for(lambda:'orbit_styled' in w.view.batch_nodes and w.view.batch_nodes['orbit_styled'].drawables[0].primitiveSets[0].count>0)
    panel.tree.setCurrentIndex(panel.model.spacecraft_index(5))
    assert w.utc_label.text().startswith('UTC  ') and '|' not in w.utc_label.text()
    station = GroundStation('Beijing',116.4,39.9,.05)
    w.install_station(station)
    assert w.view.stations[0] is station
    assert w.view.batch_nodes['stations'].drawables[0].primitiveSets[0].count==1
    pump(100)
    assert 'Beijing' in w.view.station_labels.visible_names
    wait_for(lambda:w.view.batch_nodes['orbit_styled'].drawables[0].primitiveSets[0].count>0)
    from OpenSceneGraph import osg
    assert w.view.batch_nodes['body'].drawables[0].vertexAttrib[1].binding==osg.Array.BIND_PER_VERTEX
    picture('lab_3d.png')
    w.view_tabs.setCurrentIndex(1)
    wait_for(lambda:not w.ground_view.track_image.isNull())
    before = w.ground_view.grab().toImage()
    global_flag('night',False)
    assert before!=w.ground_view.grab().toImage()
    global_flag('night',True)
    wait_for(lambda:not w.ground_view.track_image.isNull())
    picture('lab_2d.png')
    sites = panel.model.index(2,0)
    site = panel.model.index(0,0,sites)
    panel.model.setData(site,Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)
    pump(80)
    assert not station.visible
    assert w.view.batch_nodes['stations'].drawables[0].primitiveSets[0].count==0
    panel.model.setData(site,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    w.advance_to(600+43200)
    wait_for(lambda:w.seconds==43800)
    assert before!=w.ground_view.grab().toImage()
    for seconds in range(100,2000,100): w.advance_to(seconds)
    wait_for(lambda:w.seconds==1900)
    pump(100)
    assert w.seconds==1900
    w.view_tabs.setCurrentIndex(2)
    wait_for(lambda:w.data_view.cache_key is not None)
    w.advance_to(700)
    wait_for(lambda:w.seconds==700)
    wait_for(lambda:w.data_view.cache_key==w.data_view.requested_key)
    assert all(p.cursor==700 for p in w.data_view.plots.values())
    assert w.data_view.latest_state.spacecraft_name==target.name
    plot = w.data_view.plots['altitude']
    QTest.mouseClick(plot,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,plot.plot_rect().center().toPoint())
    wait_for(lambda:abs(w.seconds-w.elements.period*.5)<30)
    w.timeline.setValue(2500)
    w.release_seek()
    wait_for(lambda:abs(w.seconds-w.elements.period*.25)<1e-6)
    picture('lab_data.png')
    dialog = ConfigurationDialog(w,target)
    dialog.tabs.setCurrentIndex(1)
    dialog.total.setValue(23)
    dialog.validate_and_accept()
    wait_for(lambda:'整除' in dialog.error.text())
    dialog.total.setValue(10000)
    dialog.planes.setValue(100)
    dialog.show()
    QTest.qWait(100)
    dialog.grab().save(str(out/'lab_configuration.png'))
    dialog.reject()
    sd = StationDialog(w,station)
    sd.show()
    QTest.qWait(100)
    sd.grab().save(str(out/'lab_station.png'))
    sd.longitude.setValue(80)
    sd.save()
    assert sd.station.uid==station.uid and sd.station.longitude==80
    w.install_resources(parse_tle_catalog(DEMO_TLE))
    w.advance_to(700)
    wait_for(lambda:w.seconds==700)
    wait_for(lambda:w.data_view.cache_key==w.data_view.requested_key)
    assert np.ptp(w.data_view.plots['a'].values)>1
    w.write_csv(out/'lab.csv')
    with (out/'lab.csv').open(encoding='utf-8-sig') as f: rows = list(csv.DictReader(f))
    assert len(rows)==721 and rows[0]['frame']=='TEME'
    before = w.seconds
    w.toggle_play()
    wait_for(lambda:w.seconds>before)
    w.toggle_play()
    w.install_resources([create_single('Custom',Elements(),w.elements.epoch)],'append')
    assert len(w.resources)==2
    original = w.resources
    try: w.install_resources([w.resources[0]]*MAX_SPACECRAFT,'append')
    except ValueError: pass
    else: raise AssertionError('Resource count not validated')
    assert w.resources is original
    w.remove_resource()
    wait_for(lambda:len(w.resources)==1)
    assert w.elements.model_name=='SGP4'
    # Named constellation added beside a single resource, removed as a group.
    w.install_resources(create_walker('分组回归',6,2,1,550,53),'append')
    root = panel.model.index(1,0)
    assert panel.model.rowCount(root)==2
    group = panel.model.index(1,0,root)
    w.select_resource(w.resources[0].uid)
    panel.tree.setCurrentIndex(group)
    assert panel.current_constellation()==w.resources[-1].constellation_id
    group_id = w.resources[-1].constellation_id
    other_id = w.resources[0].uid
    def edit_group():
        dialog = app.activeModalWidget()
        if isinstance(dialog,ConfigurationDialog):
            assert dialog.total.value()==6 and dialog.planes.value()==2
            assert dialog.tabs.currentIndex()==1
            dialog.walker_name.setText('参数编辑星座')
            dialog.total.setValue(8)
            dialog.planes.setValue(4)
            dialog.phasing.setValue(2)
            dialog.altitude.setValue(850)
            dialog.inclination.setValue(63.4)
            dialog.walker_kind.setCurrentText('Star')
            dialog.grab().save(str(out/'lab_walker_edit.png'))
            dialog.validate_and_accept()
    QTimer.singleShot(80,edit_group)
    w.edit_resource()
    wait_for(lambda:len(w.resources)==9)
    assert w.resources[0].uid==other_id
    assert all(c.constellation_name=='参数编辑星座' and c.constellation_id==group_id for c in w.resources[1:])
    assert all(c.model.a==6378.137+850 and c.model.inclination==63.4 for c in w.resources[1:])
    assert w.resources[1].walker_spec[8]=='Star'
    root = panel.model.index(1,0)
    panel.tree.setCurrentIndex(panel.model.index(1,0,root))
    def cancel_group():
        dialog = app.activeModalWidget()
        if isinstance(dialog,ConfigurationDialog):
            assert dialog.total.value()==8 and dialog.altitude.value()==850
            dialog.altitude.setValue(900)
            dialog.reject()
    QTimer.singleShot(80,cancel_group)
    w.edit_resource()
    assert all(c.model.a==6378.137+850 for c in w.resources[1:])
    w.remove_resource()
    wait_for(lambda:len(w.resources)==1)
    assert w.elements.model_name=='SGP4'
    w.view_tabs.setCurrentIndex(0)
    # Last-resource deletion also preserves ground stations and their labels.
    w.remove_resource()
    wait_for(lambda:not w.resources)
    assert w.stations and w.view.batch_nodes['stations'].drawables[0].primitiveSets[0].count==1
    w.advance_to(100)
    assert w.seconds==100
    assert w.grab().save(str(out/'lab_empty_stations.png'))
    w.install_resources([create_single('重新添加',Elements())],'append')
    wait_for(lambda:w.last_frame is not None)
    QTest.qWait(100)
    assert w.view.ready
    check_scene_files(w,app,out)


def check_scene_files(w,app,out):
    from .app import MainWindow
    from .scene_store import atomic_json
    from PySide6.QtWidgets import QMessageBox
    panel = w.resource_panel
    crafts = create_walker('保存恢复星座',12,3,1,700,60)
    for c in crafts: c.line_color,c.line_width = (.2,.8,.55),2.5
    crafts[2].body = False
    crafts[3].orbit = False
    w.install_resources(crafts+[create_single('独立星',Elements())])
    panel.spacing.setCurrentIndex(panel.spacing.findData(45))
    panel.width.setValue(2.)
    panel.buttons['sun'].setChecked(True)
    panel.buttons['plane'].setChecked(True)
    panel.model.flags_state['night'] = False
    panel.item_changed()
    w.stations[0].visible = False
    w.select_resource(w.resources[5].uid)
    w.view.yaw,w.view.pitch,w.view.distance = 23.,42.,6.
    w.speed.setCurrentIndex(w.speed.findData(60))
    w.advance_to(345.5)
    wait_for(lambda:w.seconds==345.5)
    w.view_tabs.setCurrentIndex(1)
    pump(100)
    path = out/'保存恢复回归.astro.json'
    w.save_scene(path=path)
    wait_for(lambda:not w.io_busy)
    assert path.exists() and not w.scene_dirty
    assert w.current_path==path.resolve()
    uid = w.selected_id
    w.create_empty_scene()
    assert not w.resources
    w.open_scene(path)
    wait_for(lambda:not w.io_busy)
    assert len(w.resources)==13 and w.selected_id==uid and w.seconds==345.5
    assert w.view.yaw==23 and w.view.pitch==42 and w.view.distance==6
    assert w.speed.currentData()==60 and w.view_tabs.currentIndex()==1 and not w.playing
    assert panel.settings.spacing==45 and panel.settings.width==2
    assert panel.buttons['sun'].isChecked() and panel.buttons['plane'].isChecked()
    assert not panel.enabled('night') and not w.stations[0].visible
    assert not w.resources[2].body and not w.resources[3].orbit
    assert all(c.line_width==2.5 and c.line_color==(.2,.8,.55) for c in w.resources[:12])
    # Invalid files leave every current resource and the dirty state intact.
    invalid = out/'invalid_scene.json'
    atomic_json(invalid,{'format':'broken'})
    previous = w.resources
    w.mark_scene_dirty()
    w.open_scene(invalid)
    wait_for(lambda:not w.io_busy)
    assert w.resources is previous and w.scene_dirty and '失败' in w.message.text()
    # Canceling the unsaved-change prompt must keep the current scene.
    w.confirm_unsaved = True
    def cancel_change():
        box = app.activeModalWidget()
        if isinstance(box,QMessageBox): box.button(QMessageBox.StandardButton.Cancel).click()
    QTimer.singleShot(60,cancel_change)
    w.new_scene()
    assert w.resources is previous
    # Save-and-continue waits for disk success before creating the new scene.
    def save_change():
        box = app.activeModalWidget()
        if isinstance(box,QMessageBox): box.button(QMessageBox.StandardButton.Save).click()
    QTimer.singleShot(60,save_change)
    w.new_scene()
    wait_for(lambda:not w.io_busy and not w.resources)
    assert not w.scene_dirty
    w.confirm_unsaved = False
    w.open_scene(path)
    wait_for(lambda:not w.io_busy)
    w.show_welcome()
    pump(100)
    assert w.pages.currentWidget() is w.welcome and w.welcome.cards
    assert all(card.height()>=250 for card in w.welcome.cards)
    assert w.welcome.grab().save(str(out/'lab_welcome_recent.png'))
    w.show_workspace()
    # A fresh application window loads a recent card without an initialized GL view.
    fresh = MainWindow(start_welcome=True,recent_path=w.recent_scenes.path)
    fresh.confirm_unsaved = False
    fresh.show()
    pump(100)
    assert fresh.pages.currentWidget() is fresh.welcome
    card = next(c for c in fresh.welcome.cards if Path(c.path)==path.resolve())
    card.click()
    wait_for(lambda:not fresh.io_busy)
    assert len(fresh.resources)==13 and fresh.selected_id==uid
    fresh.view_tabs.setCurrentIndex(0)
    wait_for(lambda:fresh.view.ready)
    pump(100)
    assert fresh.view.show_sun and fresh.view.show_grid
    assert fresh.view.grid_settings.spacing==45
    fresh.close()
    blank = MainWindow(start_welcome=True,recent_path=w.recent_scenes.path)
    blank.confirm_unsaved = False
    blank.show()
    pump(80)
    blank.welcome.new_button.click()
    wait_for(lambda:blank.view.ready)
    assert not blank.resources and blank.pages.currentWidget() is blank.workspace
    assert blank.view.satellite.nodeMask==0
    blank.close()
    # Empty scenes with ground stations can also be saved and restored.
    w.install_resources([])
    empty = out/'empty_scene.astro.json'
    w.save_scene(path=empty)
    wait_for(lambda:not w.io_busy)
    w.create_empty_scene()
    w.open_scene(empty)
    wait_for(lambda:not w.io_busy)
    assert not w.resources and w.stations and w.data_view.latest_state is None
