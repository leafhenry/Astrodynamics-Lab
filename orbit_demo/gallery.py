"""Rebuild bundled examples and documentation using real Qt / OSG screenshots."""
import traceback
from pathlib import Path
from .smoke import pump,wait_for
from .resources import create_walker,create_single,parse_tle_catalog,GroundStation
from .mechanics import Elements
from .propagators import DEMO_TLE
from .configuration import ConfigurationDialog
from .stations import StationDialog
from .line_style import LineStyleDialog


def run(window,app):
    try:
        build(window)
    except Exception:
        traceback.print_exc()
        window.close()
        app.exit(1)
    else:
        print('GALLERY PASS: three portable examples and documentation screenshots',flush=True)
        window.close()
        app.exit(0)


def build(w):
    project = Path(__file__).resolve().parent.parent
    images,examples = project/'docs'/'images',project/'examples'
    images.mkdir(parents=True,exist_ok=True)
    examples.mkdir(exist_ok=True)
    def picture(name,widget=None):
        pump(180)
        assert (widget or w).grab().save(str(images/name))
    scenes = [
        ('01-Walker全球覆盖',create_walker('全球覆盖星座',24,6,1,550,53)),
        ('02-椭圆轨道实验',[create_single('椭圆轨道观测星',Elements(a=15000,e=.5,inclination=63.4,raan=40,arg_periapsis=270,true_anomaly=30))]),
        ('03-SGP4历史回放',parse_tle_catalog(DEMO_TLE)),
    ]
    for index,(name,crafts) in enumerate(scenes):
        w.create_empty_scene()
        w.install_resources(crafts)
        w.install_station(GroundStation('北京站',116.4,39.9,.05))
        w.install_station(GroundStation('喀什站',75.99,39.47,1.3))
        w.advance_to(600)
        wait_for(lambda:w.last_frame is not None and w.seconds==600)
        w.view.home()
        w.view_tabs.setCurrentIndex(0)
        pump(250)
        w.save_scene(path=examples/f'{name}.astro.json')
        wait_for(lambda:not w.io_busy)
        assert not w.scene_dirty,w.message.text()
        picture(['orbit.png','elliptic.png','sgp4.png'][index])
        if index==0:
            picture('scene_saved.png')
            w.view_tabs.setCurrentIndex(1)
            wait_for(lambda:not w.ground_view.track_image.isNull())
            picture('groundtrack.png')
            dialog = ConfigurationDialog(w,w.resources[0],w.resources)
            dialog.show()
            picture('walker_configuration.png',dialog)
            dialog.reject()
            dialog = StationDialog(w,w.stations[0])
            dialog.show()
            picture('station_configuration.png',dialog)
            dialog.reject()
            dialog = LineStyleDialog('星座轨道 / 尾迹样式（全部成员）',(.26,.82,.88),2.,w)
            dialog.show()
            picture('line_style.png',dialog)
            dialog.reject()
        if index==1:
            w.view_tabs.setCurrentIndex(2)
            wait_for(lambda:w.data_view.cache_key==w.data_view.requested_key and w.data_view.cache_key is not None)
            picture('data.png')
    w.show_welcome()
    picture('welcome_recent.png')
    # Empty first-run history is explicit; examples are never fake recent entries.
    saved_recent = w.welcome.recent
    from .scene_store import RecentScenes
    w.welcome.recent = RecentScenes(project/'artifacts'/'gallery_first_run'/'recent.json')
    w.welcome.reload()
    w.welcome.resume.hide()
    picture('welcome.png')
    w.welcome.recent = saved_recent
    w.create_empty_scene()
    picture('empty_scene.png')
