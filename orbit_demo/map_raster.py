"""Worker-side packed rasterization, bounded temporary memory, no GUI objects."""
import numpy as np
from PySide6.QtGui import QImage


def image_from_rgba(rgba):
    rgba = np.ascontiguousarray(rgba,dtype=np.uint8)
    return QImage(rgba.data,rgba.shape[1],rgba.shape[0],rgba.strides[0],QImage.Format.Format_RGBA8888).copy()


def raster_lines(layers,width=1600,height=800):
    pixels = np.zeros((height,width,4),dtype=np.uint8)
    scale = np.array([width-1,height-1])
    for layer in layers:
        points,colors = layer[:2]
        widths = np.ones(len(points)) if len(layer)==2 else layer[2]
        segments = points.reshape(-1,2,2)*scale
        colors = (np.clip(colors[::2],0,1)*255).astype(np.uint8)
        for start in range(0,len(segments),2048):
            piece = segments[start:start+2048]
            delta = piece[:,1]-piece[:,0]
            count = np.ceil(np.abs(delta).max(axis=1)).astype(int)+1
            steps = np.arange(max(count,default=0))
            valid = steps[None,:]<count[:,None]
            t = steps[None,:]/np.maximum(count[:,None]-1,1)
            xy = np.rint(piece[:,0,None,:]+delta[:,None,:]*t[...,None]).astype(int)
            rows,cols = np.nonzero(valid)
            x,y = xy[rows,cols].T
            np.clip(x,0,width-1,out=x)
            np.clip(y,0,height-1,out=y)
            pixels[y,x,:3] = colors[start+rows]
            pixels[y,x,3] = 180
            pixels[np.minimum(y+1,height-1),x,:3] = colors[start+rows]
            pixels[np.minimum(y+1,height-1),x,3] = 150
            radii = np.ceil(np.maximum(widths[::2][start+rows]-1,0)*.65).astype(int)
            for offset in range(1,int(radii.max(initial=0))+1):
                thick = radii>=offset
                for dx,dy in ((offset,0),(-offset,0),(0,offset),(0,-offset)):
                    xx,yy = np.clip(x[thick]+dx,0,width-1),np.clip(y[thick]+dy,0,height-1)
                    pixels[yy,xx,:3],pixels[yy,xx,3] = colors[start+rows[thick]],180
    return image_from_rgba(pixels)


def raster_points(points,colors,width=1600,height=800):
    pixels = np.zeros((height,width,4),dtype=np.uint8)
    xy = np.rint(np.clip(points,0,1)*[width-1,height-1]).astype(int)
    rgb = (np.clip(colors,0,1)*255).astype(np.uint8)
    for dx,dy in ((0,0),(1,0),(-1,0),(0,1),(0,-1)):
        x = np.clip(xy[:,0]+dx,0,width-1)
        y = np.clip(xy[:,1]+dy,0,height-1)
        pixels[y,x,:3],pixels[y,x,3] = rgb,255
    return image_from_rgba(pixels)
