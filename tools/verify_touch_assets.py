"""Verify completeness, transparency, bounds, manifest, states and deterministic pixels."""
import hashlib,json,sys
from pathlib import Path
from PIL import Image,ImageChops
import generate_touch_assets as gen

def verify():
 m=json.loads((gen.DESIGN/'assets_manifest.json').read_text(encoding='utf-8'));errors=[]
 expected={(n,s) for n in gen.NAMES for s in gen.STATES};got={(e['id'],e['state']) for e in m['assets']}
 if got!=expected or len(m['assets'])!=len(expected):errors.append('manifest mismatch')
 for e in m['assets']:
  p=gen.OUT/e['file'];svg=gen.DESIGN/'svg'/(p.stem+'.svg')
  try:
   data=p.read_bytes();im=Image.open(p);im.load()
   if im.mode!='RGBA' or im.size!=(256,256):errors.append(f'{p.name}: mode or size')
   elif im.getpixel((0,0))[3]!=0 or not im.getchannel('A').getbbox():errors.append(f'{p.name}: alpha')
   elif (box:=im.getchannel('A').getbbox()) and (box[0]<=0 or box[1]<=0 or box[2]>=256 or box[3]>=256):errors.append(f'{p.name}: clipped')
   if hashlib.sha256(data).hexdigest()!=e['sha256']:errors.append(f'{p.name}: hash')
   fresh,source=gen.draw_icon(e['id'],e['state'])
   if im.tobytes()!=fresh.tobytes():errors.append(f'{p.name}: different pixels')
   if svg.read_text(encoding='utf-8')!=source:errors.append(f'{svg.name}: different SVG')
  except (OSError,ValueError,KeyError) as exc:errors.append(f'{p.name}: {exc}')
 for name in gen.NAMES:
  imgs=[Image.open(gen.OUT/f'{name}_{s}.png').tobytes() for s in gen.STATES]
  if len(set(imgs))!=3:errors.append(f'{name}: identical states')
 if errors:print('\n'.join(errors));return 1
 print(f'OK: {len(expected)} PNGs and SVGs; alpha, bounds, manifest, states and deterministic pixels');return 0
if __name__=='__main__':sys.exit(verify())
