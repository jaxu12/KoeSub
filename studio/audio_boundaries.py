"""Quiet-boundary hints for mono PCM audio, not a speech recognizer."""
from array import array
import math
import sys
import wave
import hashlib


def audio_digest(path):
    value=hashlib.sha256()
    with open(path,'rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def quiet_regions(path,offset=0):
    energies=[]
    with wave.open(str(path),'rb') as audio:
        if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=16000:
            raise ValueError('Boundary analysis requires mono 16 kHz PCM16 WAV.')
        while block:=audio.readframes(320):
            values=array('h',block)
            if sys.byteorder!='little':values.byteswap()
            energies.append(math.sqrt(sum(v*v for v in values)/len(values)))
    if not energies:return []
    floor=sorted(energies)[len(energies)//5]
    threshold=min(200,max(30,floor*1.5))
    runs=[];start=None
    for index,value in enumerate(energies+[float('inf')]):
        if value<=threshold and start is None:start=index
        elif value>threshold and start is not None:
            if index-start>=8:runs.append([offset+start*20,offset+index*20])
            start=None
    return runs


def context_window(track,target,padding,start,end,quiet,max_window=45000):
    """Include whole cues and prefer quiet edges without trimming the target."""
    left=max(start,target.start-padding);right=min(end,target.end+padding)
    left_options=[(a+b)//2 for a,b in quiet if abs((a+b)//2-left)<=800 and start<=(a+b)//2<=target.start]
    right_options=[(a+b)//2 for a,b in quiet if abs((a+b)//2-right)<=800 and target.end<=(a+b)//2<=end]
    if left_options:left=min(left_options,key=lambda t:abs(t-left))
    if right_options:right=min(right_options,key=lambda t:abs(t-right))
    while True:
        cues=[s for s in track.segments if s.start<right and s.end>left]
        expanded=(min([left]+[s.start for s in cues]),max([right]+[s.end for s in cues]))
        if expanded==(left,right):break
        left,right=expanded
    if right-left>max_window or any(s.status=='manual' or s.review_status=='reviewed' for s in cues):return None
    return {'start':left,'end':right,'cue_ids':[s.id for s in cues],
            'quiet_left':any(a<=left<=b for a,b in quiet),'quiet_right':any(a<=right<=b for a,b in quiet)}
