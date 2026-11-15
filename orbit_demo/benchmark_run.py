"""Non-blocking benchmark controller: exercises the application's real event loop."""
import json
import platform
import time
import traceback
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject,QTimer,Qt
from .resources import create_walker,parse_tle_catalog,GroundStation


class Benchmark(QObject):
    def __init__(self,w,app,catalog):
        super().__init__(w)
        self.w,self.app,self.catalog = w,app,catalog
        self.out = Path(__file__).resolve().parent.parent/'artifacts'
        w.view.makeCurrent()
        gpu = w.view.context().functions().glGetString(7937)
        w.view.doneCurrent()
        self.report = dict(platform=platform.platform(),python=platform.python_version(),gpu=gpu,
                           window_logical_px=[w.width(),w.height()],device_pixel_ratio=w.devicePixelRatioF(),
                           count=10000,trials=[],sgp4_catalog='Synthetic Vallado-based stress fixture, not live TLE')
        self.cases = [(kind,view) for kind in ('two_body','sgp4') for view in (0,1,2)]
        self.case = -1
        self.current_kind = None
        self.gaps = []
        self.beat_time = time.perf_counter()
        self.heartbeat = QTimer(self)
        self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
        self.heartbeat.timeout.connect(self.beat)
        self.heartbeat.start(10)
        self.control = QTimer(self)
        self.control.timeout.connect(self.safe_step)
        self.control.start(100)
        self.stage = 'next'
        w.install_station(GroundStation('Beijing',116.4,39.9))

    def beat(self):
        now = time.perf_counter()
        self.gaps.append((now-self.beat_time)*1000)
        self.beat_time = now

    def safe_step(self):
        try:
            self.step()
        except Exception:
            traceback.print_exc()
            self.finish(1)

    def step(self):
        w = self.w
        now = time.perf_counter()
        if self.stage=='next':
            self.case += 1
            if self.case==len(self.cases):
                (self.out/'benchmark_10000.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding='utf-8')
                print('BENCH PASS: artifacts/benchmark_10000.json',flush=True)
                self.finish(0)
                return
            kind,view = self.cases[self.case]
            if self.current_kind!=kind:
                print('BENCH loading '+kind,flush=True)
                start = time.perf_counter()
                crafts = create_walker('Walker-10000',10000,100,1,550,53) if kind=='two_body' else parse_tle_catalog(self.catalog(10000))
                w.install_resources(crafts)
                self.load_ms = (time.perf_counter()-start)*1000
                self.current_kind = kind
            w.view_tabs.setCurrentIndex(view)
            w.raise_()
            w.activateWindow()
            if not w.playing: w.toggle_play()
            self.wait_start = time.perf_counter()
            self.stage = 'ready'
            return
        kind,view = self.cases[self.case]
        if self.stage=='ready':
            ready = (w.view.batch_nodes['orbit'].drawables[0].primitiveSets[0].count>10000 if view==0 else
                     not w.ground_view.track_image.isNull() if view==1 else w.data_view.cache_key==w.data_view.requested_key)
            if not ready:
                if now-self.wait_start>30: raise RuntimeError('等待轨迹采样超时。')
                return
            self.stage,self.warm_until = 'warm',now+.6
        elif self.stage=='warm' and now>=self.warm_until:
            w.view.frame_times.clear()
            w.timings.clear()
            self.gaps.clear()
            self.beat_time = self.start = now
            self.frames = w.view.frame_count
            self.sim_times,self.foreground = [],[]
            self.actions = set()
            self.stage = 'measure'
        elif self.stage=='measure':
            elapsed = now-self.start
            if view==0:
                w.view.yaw += .5
                w.view.update()
            if elapsed>=2 and 'scroll' not in self.actions:
                w.resource_panel.tree.verticalScrollBar().setValue(5000)
                self.actions.add('scroll')
            if elapsed>=3 and 'seek' not in self.actions:
                w.advance_to(w.elements.period*.4)
                self.actions.add('seek')
            if w.last_frame: self.sim_times.append(w.last_frame.elapsed_ms)
            self.foreground.append(w.isActiveWindow())
            if elapsed<6: return
            if not w.isVisible() or w.isMinimized() or not self.gaps: raise RuntimeError('窗口不可见，本轮压测无效。')
            item = dict(model=kind,view=['3d_all_layers','2d_all_layers','charts'][view],
                duration_s=round(elapsed,2),load_ms=round(self.load_ms,2),
                gui_function_max_ms={k:round(v,2) for k,v in w.timings.items()},
                foreground_fraction=sum(self.foreground)/len(self.foreground),
                gui_heartbeat_p95_ms=round(float(np.percentile(self.gaps,95)),2),
                gui_heartbeat_max_ms=round(max(self.gaps),2),
                propagation_median_ms=round(float(np.median(self.sim_times)),2))
            if view==0:
                if not w.view.frame_times: raise RuntimeError('未采集到绘制帧。')
                item.update(render_fps=round((w.view.frame_count-self.frames)/elapsed,1),
                            osg_render_p95_ms=round(float(np.percentile(w.view.frame_times,95)),2),batch_drawables=len(w.view.batch_nodes))
                for key in ('body','orbit','trail'):
                    item[key+'_vertices'] = w.view.batch_nodes[key].drawables[0].primitiveSets[0].count
                assert item['body_vertices']==9999
            assert w.last_frame.valid.all()
            w.grab().save(str(self.out/f'benchmark_{kind}_{view}.png'))
            self.report['trials'].append(item)
            print(json.dumps(item),flush=True)
            self.stage = 'next'

    def finish(self,code):
        self.control.stop()
        self.heartbeat.stop()
        self.w.close()
        self.app.exit(code)
