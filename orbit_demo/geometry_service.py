"""Keep large GIL-holding SGP4 sampling outside the GUI Python interpreter.

The Qt geometry thread owns the IPC wait. Only NumPy arrays/bytes cross the
process boundary; neither OSG objects nor widgets are shared.
"""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from threading import Lock
from .resources import Spacecraft,AlignedModel,is_sgp4
from .propagators import SGP4Model,TwoBodyModel
from .batch import GeometryEngine

_process_engine = None


def process_build(specs,epoch,seconds,visibility,selected,mode,styles=None):
    global _process_engine
    if specs is not None:
        crafts = []
        for kind,data,source_epoch,color in specs:
            source = SGP4Model(data) if kind=='sgp4' else TwoBodyModel(data,source_epoch)
            crafts.append(Spacecraft('',AlignedModel(source,epoch),color=color))
        _process_engine = GeometryEngine(crafts)
    result = _process_engine.build(seconds,visibility,selected,mode,styles)
    if 'image' in result:
        image = result.pop('image')
        result['raster'] = (image.width(),image.height(),bytes(image.constBits()))
        # Raster is already complete; do not send redundant 2D vertex buffers.
        result.pop('orbit')
        result.pop('trail')
        result.pop('line_widths',None)
    return result


class GeometryService:
    def __init__(self,crafts):
        self.isolated = sum(is_sgp4(c.model) for c in crafts)>128
        self.engine = None if self.isolated else GeometryEngine(crafts)
        self.epoch = crafts[0].model.epoch
        self.specs = [(('sgp4',c.model.tle,c.model.source.epoch,c.color) if is_sgp4(c.model)
                       else ('two',c.model.source.elements,c.model.source.epoch,c.color)) for c in crafts] if self.isolated else None
        self.pool = None
        self.configured = False
        self.retired = False
        self.running = False
        self.lock = Lock()

    def build(self,*args):
        with self.lock:
            if self.retired: raise ValueError('旧场景采样已取消。')
            self.running = True
        try:
            if not self.isolated: return self.engine.build(*args)
            if self.pool is None:
                self.pool = ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'))
            result = self.pool.submit(process_build,self.specs if not self.configured else None,self.epoch,*args).result()
            self.configured = True
            if 'raster' in result:
                from PySide6.QtGui import QImage
                width,height,data = result.pop('raster')
                result['image'] = QImage(data,width,height,width*4,QImage.Format.Format_RGBA8888).copy()
            return result
        finally:
            with self.lock:
                self.running = False
                if self.retired and self.pool:
                    self.pool.shutdown(wait=False,cancel_futures=True)
                    self.pool = None

    def retire(self):
        with self.lock:
            self.retired = True
            if not self.running and self.pool:
                self.pool.shutdown(wait=False,cancel_futures=True)
                self.pool = None

    def close(self):
        # Called after the Qt geometry thread has joined.
        if self.pool:
            self.pool.shutdown(wait=True,cancel_futures=True)
            self.pool = None
