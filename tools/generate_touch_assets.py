"""Generate original control graphics with reproducible Pillow drawing operations."""
from pathlib import Path
import hashlib, json, math
from PIL import Image, ImageDraw, ImageChops
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'android/app/src/main/assets/touch_hud'
DESIGN=ROOT/'design/touch_hud'
NAMES=('joystick_base joystick_knob move_forward move_backward move_left move_right run run_toggle sneak sneak_toggle camera_drag look_back peek_left peek_right first_person attack_light attack_heavy aim fire reload execution_charge execution_release target_lock target_next target_previous interact pickup drop carry_body release_body use_item throw_lure wall_cover weapon_next weapon_previous weapon_slot_1 weapon_slot_2 weapon_slot_3 weapon_slot_4 inventory inventory_expand pause resume settings confirm cancel back nav_up nav_down nav_left nav_right skip_cutscene hud_editor reset_layout').split()
STATES=('normal','pressed','disabled')

def draw_icon(name,state):
 im=Image.new('RGBA',(256,256));d=ImageDraw.Draw(im);svg=[]
 fg={'normal':(222,225,210,245),'pressed':(255,238,231,255),'disabled':(148,155,145,110)}[state]
 border={'normal':(161,174,159,220),'pressed':(215,91,77,255),'disabled':(106,116,107,100)}[state]
 bg={'normal':(32,39,37,205),'pressed':(104,37,35,230),'disabled':(30,34,32,100)}[state]
 def color(c): return f'rgb({c[0]},{c[1]},{c[2]})'
 def line(points,width=9,fill=fg):
  d.line(points,fill=fill,width=width,joint='curve')
  for x,y in (points[0],points[-1]):d.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=fill)
  coords=' '.join(f'{x},{y}' for x,y in points)
  svg.append(f'<polyline points="{coords}" fill="none" stroke="{color(fill)}" stroke-opacity="{fill[3]/255:.3f}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')
 def circle(box,fill=None,outline=fg,width=8):
  d.ellipse(box,fill=fill,outline=outline,width=width);x,y,x2,y2=box;f='none' if fill is None else color(fill);fa=1 if fill is None else fill[3]/255
  svg.append(f'<ellipse cx="{(x+x2)/2}" cy="{(y+y2)/2}" rx="{(x2-x)/2}" ry="{(y2-y)/2}" fill="{f}" fill-opacity="{fa:.3f}" stroke="{color(outline)}" stroke-opacity="{outline[3]/255:.3f}" stroke-width="{width}"/>')
 def arrow(direction,x=128,y=128,size=42):
  a={'up':-math.pi/2,'down':math.pi/2,'left':math.pi,'right':0}[direction];dx,dy=math.cos(a),math.sin(a);px,py=-dy,dx
  def pt(u,v):return (round(x+u*dx+v*px),round(y+u*dy+v*py))
  line([pt(-size,0),pt(size,0)]);line([pt(size-23,-20),pt(size,0),pt(size-23,20)])
 def cross():
  circle((88,88,168,168),None,fg,7)
  for a,b in [((128,70),(128,100)),((128,156),(128,186)),((70,128),(100,128)),((156,128),(186,128))]:line([a,b],7)
 def person(crouch=False):
  circle((115,66,141,92),None,fg,7)
  if crouch:line([(128,100),(111,128),(142,142),(166,143)],9);line([(112,128),(96,153),(77,155)],9);line([(141,141),(126,169),(102,173)],9)
  else:line([(128,99),(121,133),(102,156),(82,162)],9);line([(121,132),(149,145),(160,171)],9)
  line([(120,108),(151,121),(166,114)],8)
 def box():line([(86,91),(170,91),(170,166),(86,166),(86,91)],8);line([(86,112),(170,112)],6)
 circle((15,15,241,241),bg,border,5);circle((27,27,229,229),None,(border[0],border[1],border[2],max(30,border[3]//3)),2)
 dirs={'move_forward':'up','move_backward':'down','move_left':'left','move_right':'right','nav_up':'up','nav_down':'down','nav_left':'left','nav_right':'right','back':'left'}
 if name in dirs:arrow(dirs[name])
 elif name=='joystick_base':circle((79,79,177,177),None,fg,6);arrow('up',128,66,10);arrow('down',128,190,10);arrow('left',66,128,10);arrow('right',190,128,10)
 elif name=='joystick_knob':circle((75,75,181,181),None,fg,9);circle((105,105,151,151),fg,fg,2)
 elif name.startswith(('run','sneak')):
  person(name.startswith('sneak'))
  if name.endswith('toggle'):circle((161,159,187,185),bg,fg,5);line([(174,164),(174,179)],4)
 elif name=='camera_drag':circle((91,91,165,165),None,fg,7);arrow('left',63,128,17);arrow('right',193,128,17)
 elif name=='look_back':circle((78,91,164,167),None,fg,7);arrow('left',100,83,25)
 elif name.startswith('peek_'):person(True);arrow('left' if name.endswith('left') else 'right',128,176,33)
 elif name=='first_person':circle((77,99,179,157),None,fg,8);circle((111,111,145,145),fg,fg,2)
 elif name in ('attack_light','attack_heavy','execution_charge','execution_release'):
  line([(82,164),(160,86)],11);line([(145,80),(177,80),(177,112)],8);line([(74,151),(105,182)],8)
  if name=='attack_heavy':line([(72,127),(102,97)],7)
  if name.startswith('execution'):arrow('down' if name.endswith('charge') else 'up',166,162,19)
 elif name in ('aim','target_lock','target_next','target_previous','fire'):
  cross()
  if name=='fire':line([(128,112),(117,131),(130,131),(122,148)],7)
  if name=='target_lock':line([(112,132),(112,120),(128,107),(144,120),(144,132)],6)
  if name in ('target_next','target_previous'):arrow('right' if name.endswith('next') else 'left',128,191,22)
 elif name=='reload':circle((83,83,173,173),None,fg,8);arrow('right',155,91,21)
 elif name in ('interact','pickup','drop','carry_body','release_body','use_item','throw_lure','wall_cover'):
  if name in ('carry_body','release_body'):person(True);circle((153,78,175,100),None,fg,6);line([(162,102),(153,129),(175,145)],7)
  elif name=='wall_cover':line([(90,70),(90,186)],10);person(True)
  else:box();arrow('up' if name in ('pickup','use_item') else 'down' if name=='drop' else 'right',128,137,24)
  if name=='release_body':arrow('down',175,174,16)
  if name=='throw_lure':line([(165,77),(180,65)],6)
 elif name.startswith('weapon_'):
  line([(83,151),(151,83)],10);line([(77,141),(105,169)],8)
  if name.endswith('next'):arrow('right',147,166,22)
  elif name.endswith('previous'):arrow('left',109,166,22)
  elif 'slot_' in name:
   for i in range(int(name[-1])):circle((73+i*25,177,85+i*25,189),fg,fg,2)
 elif name.startswith('inventory'):
  box();line([(104,137),(152,137)],7)
  if name.endswith('expand'):line([(128,116),(128,158)],7)
 elif name=='pause':line([(109,90),(109,166)],14);line([(147,90),(147,166)],14)
 elif name=='resume':line([(102,84),(169,128),(102,172),(102,84)],10)
 elif name=='settings':
  circle((100,100,156,156),None,fg,8)
  for i in range(8):
   a=i*math.pi/4;line([(round(128+37*math.cos(a)),round(128+37*math.sin(a))),(round(128+53*math.cos(a)),round(128+53*math.sin(a)))],8)
 elif name=='confirm':line([(78,129),(111,160),(178,92)],11)
 elif name=='cancel':line([(94,94),(162,162)],10);line([(162,94),(94,162)],10)
 elif name=='skip_cutscene':line([(88,90),(136,128),(88,166),(88,90)],8);line([(151,90),(151,166)],10)
 elif name=='hud_editor':line([(83,167),(157,93),(174,110),(100,184),(83,184),(83,167)],8);line([(146,104),(163,121)],6)
 elif name=='reset_layout':circle((83,83,173,173),None,fg,8);arrow('left',101,88,22);line([(111,128),(145,128)],6)
 else:raise ValueError(name)
 return im,'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'+''.join(svg)+'</svg>\n'

def generate():
 OUT.mkdir(parents=True,exist_ok=True);(DESIGN/'svg').mkdir(parents=True,exist_ok=True);entries=[];thumbs=[]
 for name in NAMES:
  for state in STATES:
   im,svg=draw_icon(name,state);path=OUT/f'{name}_{state}.png';im.save(path,optimize=False)
   (DESIGN/'svg'/f'{name}_{state}.svg').write_text(svg,encoding='utf-8',newline='\n')
   entries.append({'id':name,'state':state,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()});thumbs.append((name,state,im))
 (DESIGN/'assets_manifest.json').write_text(json.dumps({'version':1,'size':[256,256],'states':list(STATES),'actions_verified':False,'assets':entries},indent=2)+'\n',encoding='utf-8')
 cols=6;w=176;h=150;sheet=Image.new('RGB',(cols*w,math.ceil(len(thumbs)/cols)*h),(24,29,27));d=ImageDraw.Draw(sheet)
 for i,(name,state,im) in enumerate(thumbs):
  x=i%cols*w;y=i//cols*h;thumb=im.resize((108,108),Image.Resampling.LANCZOS);sheet.paste(thumb,(x+34,y+3),thumb);d.text((x+4,y+113),name,fill=(230,230,220));d.text((x+4,y+128),state,fill=(172,185,170))
 sheet.save(DESIGN/'preview.png');print(f'Generated {len(entries)} PNGs, SVGs and contact sheet')
if __name__=='__main__':generate()
