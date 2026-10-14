"""Render the code-native BaroEditor mark; Pillow is a build-only dependency."""
from pathlib import Path
from PIL import Image, ImageDraw
root = Path(__file__).resolve().parents[1]
size = 1024
im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
def box(rect, radius, fill, outline=None, width=1):
    x0,y0,x1,y1 = (int(x*4) for x in rect); r=int(radius*4)
    def rounded(a,b,c,e,rad,color):
        d.rectangle((a+rad,b,c-rad,e),fill=color); d.rectangle((a,b+rad,c,e-rad),fill=color)
        for x,y in [(a,b),(c-2*rad,b),(a,e-2*rad),(c-2*rad,e-2*rad)]: d.ellipse((x,y,x+2*rad,y+2*rad),fill=color)
    rounded(x0,y0,x1,y1,r,outline or fill)
    if outline:
        w=width*4; rounded(x0+w,y0+w,x1-w,y1-w,r-w,fill)
box((8, 8, 248, 248), 52, '#101e2c', '#314e62', 2)
d.arc((29*4,29*4,227*4,227*4), 28, 326, fill='#325b70', width=5*4)
d.arc((29*4,29*4,227*4,227*4), 204, 292, fill='#80dbea', width=5*4)
for points in [((85,128),(122,128),(148,76),(180,76)), ((85,128),(122,128),(148,180),(180,180))]:
    d.line([(x*4,y*4) for x,y in points], fill='#8fe0ed', width=7*4, joint='curve')
box((46,103,109,153), 13, '#23485b', '#a0e7ef', 3)
box((151,54,207,98), 11, '#2b5667', '#b3eaf0', 3)
box((151,158,207,202), 11, '#294554', '#dcc78d', 3)
for x,y,c in [(77,128,'#d3f4f5'),(179,76,'#b3eaf0'),(179,180,'#e9d7a2')]:
    d.ellipse(((x-5)*4,(y-5)*4,(x+5)*4,(y+5)*4), fill=c)
out = root/'Assets/app.ico'
im.resize((256,256),Image.LANCZOS).save(out,format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
im.resize((256,256),Image.LANCZOS).save(root/'Publishing/icon.png')
print(out)
