import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess,QRectF,Qt,Signal,QTimer
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from .storage import ROOT
from .waveform import HOP,RATE,cache_path,load_peaks,source_key


class WaveformWidget(QWidget):
    seekRequested=Signal(int)
    rangeSelected=Signal(int,int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setMaximumHeight(115)
        self.setToolTip('Klik: przewiń. Przeciągnij: zakres ASR / pipeline. Kółko: zoom. Prawy klik: cały film.')
        self.peaks=b'';self.duration=0;self.position=0;self.left=0;self.span=30000
        self.segments=[];self.drag_start=None;self.selection=None
        self.message='Waveform pojawi się po odczytaniu audio.'

    def set_peaks(self,peaks,duration):
        self.peaks,self.duration,self.left=peaks,duration,0
        self.span=min(30000,max(1000,duration));self.message='';self.update()

    def time_at(self,x):
        return max(0,min(self.duration,round(self.left+x/max(1,self.width())*self.span)))

    def set_position(self,position):
        self.position=position
        if self.duration and not self.left<=position<=self.left+self.span:
            self.left=max(0,min(max(0,self.duration-self.span),position-self.span//3))
        self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#171c27'))
        width,height=self.width(),self.height()
        if not self.peaks:
            p.setPen(QColor('#96a1b8'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.message)
            return
        p.setPen(QColor('#91c7c1'))
        center=(height-28)/2+16
        for x in range(width):
            a=max(0,int((self.left+x/max(1,width)*self.span)*RATE/1000/HOP))
            b=min(len(self.peaks),max(a+1,int((self.left+(x+1)/max(1,width)*self.span)*RATE/1000/HOP)))
            peak=max(self.peaks[a:b],default=0)/255*(height-42)/2
            p.drawLine(x,round(center-peak),x,round(center+peak))
        for s in self.segments:
            if s.end<self.left or s.start>self.left+self.span:
                continue
            x=(s.start-self.left)/self.span*width
            end=(s.end-self.left)/self.span*width
            p.fillRect(QRectF(x,height-23,max(1,end-x),11),QColor('#7864d9' if not s.bookmarked else '#d6b65f'))
        if self.selection:
            a,b=self.selection
            p.fillRect(QRectF((a-self.left)/self.span*width,0,(b-a)/self.span*width,height),QColor(120,100,217,55))
        p.setPen(QColor('#acb8d2'))
        for n in range(5):
            ms=self.left+self.span*n/4
            p.drawText(round(width*n/4) if n<4 else max(0,width-58),13,f'{int(ms)//60000}:{int(ms)//1000%60:02}')
        x=(self.position-self.left)/self.span*width
        p.setPen(QPen(QColor('#ffca83'),2));p.drawLine(round(x),0,round(x),height)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:
            self.left=0;self.span=max(1000,self.duration);self.update();return
        if event.button()==Qt.MouseButton.LeftButton and self.peaks:
            self.drag_start=event.position().x()

    def mouseMoveEvent(self,event):
        if self.drag_start is not None:
            self.selection=tuple(sorted((self.time_at(self.drag_start),self.time_at(event.position().x()))))
            self.update()

    def mouseReleaseEvent(self,event):
        if self.drag_start is None:
            return
        x=event.position().x()
        if abs(x-self.drag_start)>6:
            a,b=sorted((self.time_at(self.drag_start),self.time_at(x)))
            if b>a:
                self.selection=(a,b);self.rangeSelected.emit(a,b)
        else:
            self.seekRequested.emit(self.time_at(x))
        self.drag_start=None;self.update()

    def wheelEvent(self,event):
        if not self.duration:
            return
        at=self.time_at(event.position().x())
        ratio=event.position().x()/max(1,self.width())
        self.span=max(1000,min(self.duration,round(self.span*(.75 if event.angleDelta().y()>0 else 1.3333))))
        self.left=max(0,min(self.duration-self.span,round(at-self.span*ratio)))
        self.update();event.accept()


class WaveformController:
    def __init__(self,owner,widget):
        self.owner,self.widget=owner,widget
        self.process=None;self.key=None;self.request=None
        self.closed=False

    def stop(self):
        process=self.process
        self.process=None
        if process and isValid(process) and process.state()!=QProcess.ProcessState.NotRunning:
            pid=process.processId()
            if os.name=='nt' and pid:
                QProcess.startDetached('taskkill',['/PID',str(pid),'/T','/F'])
            process.kill()

    def schedule(self):
        if not self.closed: QTimer.singleShot(500,self.ensure)

    def ensure(self):
        if self.closed: return
        owner=self.owner
        media=owner.project.media
        if not media or not Path(media).is_file():
            self.stop();self.key=None;self.widget.peaks=b'';self.widget.duration=0
            self.widget.message='Otwórz dostępny film / audio, aby zobaczyć waveform.';self.widget.update()
            return
        if owner.busy:
            return
        key=source_key(media,owner.project.audio_track)
        if key==self.key and self.widget.peaks:
            return
        if self.process and self.request==key:
            return
        self.stop()
        path=cache_path(owner.settings.cache_dir,media,owner.project.audio_track)
        if path.is_file():
            try:
                peaks,duration=load_peaks(path,key)
                self.widget.set_peaks(peaks,duration);self.key=key
                return
            except (ValueError,KeyError,OSError):
                pass
        if not owner.settings.ffmpeg or not Path(owner.settings.ffmpeg).is_file():
            self.widget.message='Wskaż FFmpeg, aby utworzyć waveform.';self.widget.update();return
        self.widget.peaks=b'';self.widget.message='Analiza waveformu w tle…';self.widget.update()
        process=self.process=QProcess(owner)
        self.request=key
        spec={'media':media,'track':owner.project.audio_track,'output':str(path),
              'ffmpeg':owner.settings.ffmpeg,'reserve_gib':owner.settings.reserve_gib}
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe':
            executable=executable.with_name('python.exe')
        process.setWorkingDirectory(str(ROOT))
        pending=bytearray()
        def read():
            if isValid(process):
                pending.extend(bytes(process.readAllStandardOutput()))
        process.readyReadStandardOutput.connect(read)
        finished=False
        def done(code,*_):
            nonlocal finished
            if finished: return
            finished=True
            if not isValid(process): return
            if self.process is process:
                self.process=None
                read()
                try:
                    if code:
                        messages=[json.loads(line) for line in pending.splitlines()]
                        error=next((m['message'] for m in messages if m['type']=='error'),'Nie udało się utworzyć waveformu.')
                        raise ValueError(error)
                    peaks,duration=load_peaks(path,key)
                    if owner.project.media==media and owner.project.audio_track==spec['track']:
                        self.widget.set_peaks(peaks,duration);self.key=key
                except (ValueError,KeyError,OSError) as exc:
                    self.widget.message='Waveform niedostępny • szczegóły w logach';self.widget.update()
                    owner.log('Waveform: '+str(exc))
            process.deleteLater()
        process.finished.connect(done)
        process.errorOccurred.connect(lambda error:done(-1) if error==QProcess.ProcessError.FailedToStart else None)
        process.start(str(executable),['-m','studio.audio_worker',json.dumps(spec,ensure_ascii=False)])
        QTimer.singleShot(300000,lambda:self.stop() if self.process is process else None)
