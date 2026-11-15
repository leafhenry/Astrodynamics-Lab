"""Bounded background jobs: one running job and one replaceable pending job.

No worker touches widgets, OpenGL or scene-graph objects. Results are polled
on the GUI thread, so even results cannot accumulate in Qt's event queue.
"""
from threading import Condition
from PySide6.QtCore import QThread


class LatestWorker(QThread):
    def __init__(self,name,parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.condition = Condition()
        self.pending = self.result = None
        self.stopping = False
        self.busy = False
        self.start()

    def submit(self,key,function,*args):
        with self.condition:
            self.pending = (key,function,args)
            self.condition.notify()

    def take(self):
        with self.condition:
            result,self.result = self.result,None
            return result

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.stopping or self.pending is not None)
                if self.stopping:
                    return
                key,function,args = self.pending
                self.pending = None
                self.busy = True
            try:
                value,error = function(*args),None
            except Exception as exc:
                value,error = None,exc
            with self.condition:
                self.result = (key,value,error)
                self.busy = False

    def stop(self):
        with self.condition:
            self.stopping = True
            self.pending = None
            self.condition.notify()
        self.wait()
