"""Win32 APIs reached from WinMain (0x4c1080), emulated in the x86 reference with the
semantics the port's runtime will implement. Each entry: name -> (argument count,
handler(args) -> eax or None). Handlers get a small context with memory helpers.

Port model (single guest process, no real Windows):
- SystemParametersInfoA: accepted, no effect, returns TRUE.
- Paths: the game folder chosen by the user (SAF) appears to the guest as C:\\Manhunt\\
  and the executable as C:\\Manhunt\\manhunt.exe. The file layer maps paths under
  that prefix (case-insensitively, like Windows) onto the selected folder.
- GetModuleFileNameA(NULL or the image, buf, size): copies the executable path,
  truncating like Windows (no NUL when truncated, ERROR_INSUFFICIENT_BUFFER).
"""
GAME_DIR='C:\\Manhunt\\'
MODULE_PATH=GAME_DIR+'manhunt.exe'
IMAGE_BASE=0x400000
import os as _os
# Input script, shared with runtime/port_api.c: "key:from:to,..." (hex DIK scan code; the key is
# down while from <= presented frames < to).
MOUSE_STEP=8   # scripted mouse motion units per GetDeviceState (codes 0x200..0x203), as runtime/port_api.c
KEY_SCRIPT=[(int(k,16),int(f),int(t)) for k,f,t in (x.split(':') for x in _os.environ.get('MH_KEYS','').split(',') if x)]
def make(ctx):
    apis={};cpu,state=ctx['cpu'],ctx['state']
    def api(name,nargs):
        def register(fn):apis[name]=(nargs,fn);return fn
        return register
    def unsupported(what):raise SystemExit('unsupported: '+what)

    @api('SystemParametersInfoA',4)
    def _(a):return 1

    # Time (reference only): a deterministic virtual clock in milliseconds that starts at 0x10000
    # and advances 1 ms per query, so busy-waits terminate and translated code can reproduce the
    # run exactly. The device runtime uses the real clock (runtime/win_tick.c).
    # QueryPerformanceCounter runs on the same clock at 1 MHz.
    state.setdefault('clock',0x10000)
    def tick():
        state['clock']+=1;return state['clock']
    @api('timeGetTime',0)
    def _(a):return tick()&0xffffffff
    @api('timeBeginPeriod',1)
    def _(a):return 0
    @api('timeEndPeriod',1)
    def _(a):return 0
    @api('QueryPerformanceFrequency',1)
    def _(a):w32(a[0],1000000);w32(a[0]+4,0);return 1
    @api('QueryPerformanceCounter',1)
    def _(a):
        us=tick()*1000;w32(a[0],us&0xffffffff);w32(a[0]+4,us>>32);return 1

    # Language: the port takes it from the Android locale / app setting; the reference uses
    # English (United States) so that it is deterministic.
    # The user's language (MH_LANG, hex LANGID; as runtime/port_api.c). The game maps its primary
    # language: French 0x040c, Italian 0x0410, Spanish 0x0c0a, German only outside Germany
    # (0x0c07, 0x0807: German 0x0407 gets English), anything else English.
    LANGID=int(_os.environ.get('MH_LANG','0409'),16)
    @api('GetUserDefaultLangID',0)
    def _(a):return LANGID
    @api('GetSystemDefaultLangID',0)
    def _(a):return LANGID
    @api('GetUserDefaultLCID',0)
    def _(a):return LANGID
    @api('GetSystemDefaultLCID',0)
    def _(a):return LANGID

    # Error mode: stored and returned (there are no system error dialogs to suppress).
    state.setdefault('error_mode',0)
    @api('SetErrorMode',1)
    def _(a):old=state['error_mode'];state['error_mode']=a[0];return old

    @api('GetModuleFileNameA',3)
    def _(a):
        module,buf,size=a[0],a[1],a[2]
        if module not in (0,IMAGE_BASE):unsupported(f'GetModuleFileNameA for module {module:#x}')
        path=MODULE_PATH.encode('ascii')
        if size>len(path):cpu.mem_write(buf,path+b'\0');return len(path)
        if size:cpu.mem_write(buf,path[:size]);state['last_error']=122
        return size

    # Current directory: starts at the game folder; only folders inside it can be selected
    # (anything else: ERROR_PATH_NOT_FOUND). Stored without a trailing backslash, as Windows.
    state.setdefault('cwd',GAME_DIR.rstrip('\\'))
    def inside_game(path):
        p=path.replace('/','\\').rstrip('\\')
        return p.lower()==GAME_DIR.rstrip('\\').lower() or p.lower().startswith(GAME_DIR.lower())
    @api('SetCurrentDirectoryA',1)
    def _(a):
        path=ctx['cstr'](a[0])
        if not inside_game(path):
            if ':' in path or path.startswith('\\'):state['last_error']=3;return 0
            unsupported(f'SetCurrentDirectoryA with relative path {path!r}')
        state['cwd']=path.replace('/','\\').rstrip('\\');return 1
    @api('GetCurrentDirectoryA',2)
    def _(a):
        size,buf=a[0],a[1];cwd=state['cwd'].encode('ascii')
        if size>len(cwd):cpu.mem_write(buf,cwd+b'\0');return len(cwd)
        return len(cwd)+1

    # Environment variables set at run time (the start-up block stays empty).
    state.setdefault('env',{})
    @api('SetEnvironmentVariableA',2)
    def _(a):
        name=ctx['cstr'](a[0])
        if not name or '=' in name[1:]:state['last_error']=87;return 0
        if a[1]:state['env'][name.upper()]=(name,ctx['cstr'](a[1],32767))
        else:state['env'].pop(name.upper(),None)
        return 1
    @api('GetEnvironmentVariableA',3)
    def _(a):
        entry=state['env'].get(ctx['cstr'](a[0]).upper())
        if entry is None:state['last_error']=203;return 0   # ERROR_ENVVAR_NOT_FOUND
        value=entry[1].encode('latin-1')
        if a[2]>len(value):cpu.mem_write(a[1],value+b'\0');return len(value)
        return len(value)+1

    # user32. Handle spaces: system cursors 0x60000000|id, class atoms from 0xC000,
    # windows from 0x00020000 (step 4). No real window system: the Android surface is the
    # only "screen"; window state is kept here and messages go through the port's queue.
    r32=ctx['r32']
    state.setdefault('classes',{});state.setdefault('windows',{})
    @api('LoadCursorA',2)
    def _(a):
        if a[0]!=0 or a[1]>0xffff:unsupported(f'LoadCursorA({a[0]:#x}, {a[1]:#x}): only system cursors')
        return 0x60000000|a[1]
    @api('RegisterClassA',1)
    def _(a):
        w=[r32(a[0]+4*i) for i in range(10)]   # WNDCLASSA: style, lpfnWndProc, cbClsExtra, cbWndExtra, hInstance, hIcon, hCursor, hbrBackground, lpszMenuName, lpszClassName
        name=ctx['cstr'](w[9]) if w[9]>0xffff else f'#{w[9]}'
        if name.upper() in state['classes']:state['last_error']=1410;return 0   # ERROR_CLASS_ALREADY_EXISTS
        atom=0xC000+len(state['classes'])
        state['classes'][name.upper()]={'name':name,'atom':atom,'wndproc':w[1],'style':w[0],'extra':(w[2],w[3]),'hinstance':w[4]}
        return atom

    # System metrics: the screen is the virtual adapter's desktop mode (1280x720); windows have
    # no frame, caption or menu bar, so those metrics are 0.
    METRICS={0:1280,1:720,4:0,5:0,6:0,7:0,8:0,15:0,32:0,33:0,16:1280,17:720,61:1280,62:720,78:1280,79:720,80:1}
    @api('GetSystemMetrics',1)
    def _(a):
        if a[0] not in METRICS:unsupported(f'GetSystemMetrics({a[0]})')
        return METRICS[a[0]]

    # Cursor: a virtual position on the 1280x720 screen (touch feeds it later), a display counter
    # (starts at 0, cursor shown while >= 0) and the current cursor handle.
    state.setdefault('cursor',{'pos':[640,360],'count':0,'handle':0x60007f00,'clip':None})
    cur=state['cursor']
    @api('SetCursorPos',2)
    def _(a):
        cur['pos']=[max(0,min(1279,a[0]-(1<<32) if a[0]>>31 else a[0])),max(0,min(719,a[1]-(1<<32) if a[1]>>31 else a[1]))];return 1
    @api('GetCursorPos',1)
    def _(a):w32(a[0],cur['pos'][0]);w32(a[0]+4,cur['pos'][1]);return 1
    @api('ShowCursor',1)
    def _(a):cur['count']+=1 if a[0] else -1;return cur['count']&0xffffffff
    @api('SetCursor',1)
    def _(a):old=cur['handle'];cur['handle']=a[0];return old
    @api('ClipCursor',1)
    def _(a):cur['clip']=[ctx['r32'](a[0]+4*i) for i in range(4)] if a[0] else None;return 1

    # Windows in the port have no frame: the whole Android surface is client area, so
    # AdjustWindowRect leaves the rectangle unchanged.
    @api('AdjustWindowRect',3)
    def _(a):return 1

    # CreateWindowExA sends, synchronously, WM_CREATE (with a CREATESTRUCTA in guest memory)
    # and then the post-creation WM_SIZE (client size) and WM_MOVE (client origin), as Windows
    # does. Non-client messages (WM_NCCREATE, WM_NCCALCSIZE, WM_GETMINMAXINFO) are not sent:
    # there is no non-client area. A WM_CREATE result of -1 fails the creation.
    WM_CREATE,WM_MOVE,WM_SIZE=1,3,5
    SCRATCH=0x1f11000   # user32 scratch structures, outside image and heaps
    Callbacks=ctx['Callbacks']
    def lparam(lo,hi):return (lo&0xffff)|((hi&0xffff)<<16)
    @api('CreateWindowExA',12)
    def _(a):
        exstyle,cls,title,style,x,y,w,h,parent,menu,hinst,param=a[:12]
        name=ctx['cstr'](cls) if cls>0xffff else next((c['name'] for c in state['classes'].values() if c['atom']==cls),None)
        klass=state['classes'].get((name or '').upper())
        if not klass:state['last_error']=1407;return 0   # ERROR_CANNOT_FIND_WND_CLASS
        if parent or menu:unsupported('CreateWindowExA with a parent or menu')
        if x==0x80000000:x=y=0   # CW_USEDEFAULT position: the surface origin (y is ignored, as in Windows)
        if w==0x80000000:unsupported('CreateWindowExA with CW_USEDEFAULT size')
        hwnd=0x00020000+4*len(state['windows'])
        state['windows'][hwnd]={'class':klass['name'],'wndproc':klass['wndproc'],'style':style,'exstyle':exstyle,
                                'rect':[x,y,x+w,y+h],'title':ctx['cstr'](title) if title else '','visible':bool(style&0x10000000),'long':{}}
        cs=[param,hinst,menu,parent,h,w,y,x,style,title,cls,exstyle]   # CREATESTRUCTA
        for i,v in enumerate(cs):ctx['w32'](SCRATCH+4*i,v)
        calls=[(klass['wndproc'],[hwnd,WM_CREATE,0,SCRATCH]),(klass['wndproc'],[hwnd,WM_SIZE,0,lparam(w,h)]),(klass['wndproc'],[hwnd,WM_MOVE,0,lparam(x,y)])]
        def finish(results):
            if results[0]==0xffffffff:del state['windows'][hwnd];return 0
            return hwnd
        return Callbacks(calls,finish)

    # DefWindowProcA: the default for everything the game does not handle is 0 in the port
    # (no non-client area, no system menu); messages that need more are reported.
    @api('DefWindowProcA',4)
    def _(a):
        if a[1] in (0x10,):unsupported(f'DefWindowProcA for message {a[1]:#x}')   # WM_CLOSE would destroy the window
        return 0

    # Modules: only the game image is a module of the port (other DLLs are replaced by shims).
    @api('GetModuleHandleA',1)
    def _(a):
        if a[0]==0:return IMAGE_BASE
        name=ctx['cstr'](a[0]).lower().replace('/','\\').split('\\')[-1]
        if name in ('manhunt.exe','manhunt'):return IMAGE_BASE
        if name in ('kernel32.dll','kernel32'):return KERNEL32
        unsupported(f'GetModuleHandleA({name!r})')
    # kernel32 is a pseudo module: GetProcAddress resolves only functions the executable also
    # imports (the result is that import's address); the game probes GetDiskFreeSpaceExA.
    KERNEL32=0x7ff00000
    PROC_SLOTS={'GetDiskFreeSpaceExA':0x81b3c8}
    @api('GetProcAddress',2)
    def _(a):
        name=ctx['cstr'](a[1]) if a[1]>0xffff else None
        if a[0]!=KERNEL32 or name not in PROC_SLOTS:unsupported(f'GetProcAddress({a[0]:#x}, {name!r})')
        return ctx['r32'](PROC_SLOTS[name])
    # Save space: 8 GiB free of 16 GiB, for any directory.
    @api('GetDiskFreeSpaceExA',4)
    def _(a):
        for ptr,value in zip(a[1:4],(8<<30,16<<30,8<<30)):
            if ptr:w32(ptr,value&0xffffffff);w32(ptr+4,value>>32)
        return 1

    # ---- Files (read-only game data) --------------------------------------------------------
    # Guest paths under C:\Manhunt\ (absolute, or relative to the current directory) map onto
    # the user's game folder, resolving each component case-insensitively as Windows does
    # (Android's file systems are case-sensitive). Read-only: the original data is never
    # modified; any write access is reported (saves will go to a separate writable area).
    # Overlapped reads complete synchronously (allowed by Windows): OVERLAPPED.Internal = 0,
    # InternalHigh = bytes read, and the event, if any, is signalled.
    import os
    HOST_GAME=ctx['game_dir']
    state.setdefault('files',{});files=state['files'];state.setdefault('signalled',set())
    INVALID_HANDLE=0xffffffff
    def resolve(guest):
        p=guest.replace('/','\\')
        if not (len(p)>1 and p[1]==':') and not p.startswith('\\'):p=state['cwd']+'\\'+p
        if not p.lower().startswith(GAME_DIR.lower()):return None,3
        host=HOST_GAME;parts=[c for c in p[len(GAME_DIR):].split('\\') if c not in ('','.')]
        for i,c in enumerate(parts):
            if c=='..':return None,3
            try:names=os.listdir(host)
            except OSError:return None,3
            match=next((n for n in names if n.lower()==c.lower()),None)
            if match is None:return None,(2 if i==len(parts)-1 else 3)
            host=os.path.join(host,match)
        return host,0
    # Writable overlay files (saves): in memory, keyed by the case-folded full guest path; the
    # original data is never written. The port keeps them in memory too (and, in the app, also in
    # its private storage).
    state.setdefault('overlay_files',{});ovf=state['overlay_files']
    def guest_key(name):
        p=name.replace('/','\\')
        if not (len(p)>1 and p[1]==':') and not p.startswith('\\'):p=state['cwd']+'\\'+p
        return p.lower()
    def ov_index(key):   # as runtime/port_api.c: the position in the port's overlay table (tombstones included), + 1
        state['overlay_count']=state.get('overlay_count',0)+1;state.setdefault('overlay_index',{})[key]=state['overlay_count']
    def save_name(key):   # as runtime/port_api.c save_path: the path below the game folder, '\' -> '_'
        return key[len(GAME_DIR):].lstrip(chr(92)).replace(chr(92),'_')
    def ov_lookup(key):   # as runtime/port_api.c ov_find: a seeded save is loaded at its first lookup
        if key in ovf:return True
        if key in state.setdefault('overlay_deleted',set()):return False
        seed=os.environ.get('MH_SAVES')
        if not seed or not key.startswith(GAME_DIR.lower()):return False
        path=os.path.join(seed,save_name(key))
        if not os.path.isfile(path):return False
        ovf[key]=bytearray(open(path,'rb').read());state.setdefault('overlay_times',{})[key]=[0,0];ov_index(key);return True
    apis['ov_names']=(0,lambda:{save_name(k):bytes(v) for k,v in ovf.items()})
    def parent_exists(key):
        parent=key.rsplit('\\',1)[0]
        if parent in state.setdefault('overlay_dirs',set()):return True
        host,err=resolve(parent);return bool(host and os.path.isdir(host))
    @api('CreateFileA',7)
    def _(a):
        name=ctx['cstr'](a[0],1024);access,share,sec,disp,flags,template=a[1:7]
        key=guest_key(name)
        if access&0x40000000 or disp not in (3,4) or ov_lookup(key):
            if not key.startswith(GAME_DIR.lower()) or not parent_exists(key):state['last_error']=3;return INVALID_HANDLE
            host,err=resolve(name)
            if host and os.path.exists(host):unsupported(f'CreateFileA writing original data: {name!r}')
            exists=key in ovf
            if disp==1 and exists:state['last_error']=80;return INVALID_HANDLE   # ERROR_FILE_EXISTS
            if disp in (3,5) and not exists:state['last_error']=2;return INVALID_HANDLE
            if disp not in (1,2,3,4,5):state['last_error']=87;return INVALID_HANDLE
            if disp in (1,2,5) or not exists:ovf[key]=bytearray()
            if not exists:state.setdefault('overlay_times',{})[key]=[state['clock'],state['clock']];ov_index(key);state.setdefault('overlay_deleted',set()).discard(key)
            h=0x00F00004+4*len(files);files[h]={'path':None,'overlay':key,'guest':name,'pos':0,'size':0,'open':True,'overlapped':bool(flags&0x40000000)}
            state['last_error']=183 if exists and disp in (2,4) else 0;return h
        host,err=resolve(name)
        if host is None or not os.path.isfile(host):state['last_error']=err or 2;return INVALID_HANDLE
        h=0x00F00004+4*len(files);files[h]={'path':host,'guest':name,'pos':0,'size':os.path.getsize(host),'open':True,'overlapped':bool(flags&0x40000000)}
        state['last_error']=0;return h
    def file(h):
        f=files.get(h)
        if not f or not f['open']:return None
        return f
    @api('ReadFile',5)
    def _(a):
        h,buf,n,pread,pov=a[:5];f=file(h)
        if not f:state['last_error']=6;return 0
        offset=(ctx['r32'](pov+8)|(ctx['r32'](pov+12)<<32)) if pov else f['pos']
        if f.get('overlay'):data=bytes(ovf[f['overlay']][offset:offset+n])
        else:
            with open(f['path'],'rb') as fp:fp.seek(offset);data=fp.read(n)
        if data:cpu.mem_write(buf,data)
        if pread:w32(pread,len(data))
        if pov:
            w32(pov,0);w32(pov+4,len(data));ev=ctx['r32'](pov+16)
            if ev:state['signalled'].add(ev)
            if not data and n:state['last_error']=38;return 0   # ERROR_HANDLE_EOF
        else:f['pos']=offset+len(data)
        return 1
    @api('WriteFile',5)
    def _(a):
        h,buf,n,pwritten,pov=a[:5];f=file(h)
        if not f:state['last_error']=6;return 0
        if not f.get('overlay'):unsupported(f'WriteFile to original data: {f["guest"]!r}')
        offset=(ctx['r32'](pov+8)|(ctx['r32'](pov+12)<<32)) if pov else f['pos']
        d=ovf[f['overlay']];data=bytes(cpu.mem_read(buf,n)) if n else b''
        if len(d)<offset:d.extend(bytes(offset-len(d)))
        state['overlay_times'][f['overlay']][1]=state['clock']
        d[offset:offset+n]=data
        if pwritten:w32(pwritten,n)
        if pov:
            w32(pov,0);w32(pov+4,n);ev=ctx['r32'](pov+16)
            if ev:state['signalled'].add(ev)
        else:f['pos']=offset+n
        return 1
    FILE_EPOCH=(1072915200+11644473600)*10000000   # 2004-01-01 00:00 UTC (FILETIME), as runtime/port_api.c
    @api('DeleteFileA',1)
    def _(a):
        name=ctx['cstr'](a[0],1024);key=guest_key(name)
        if ov_lookup(key):
            if any(f['open'] and f.get('overlay')==key for f in files.values()):state['last_error']=32;return 0   # ERROR_SHARING_VIOLATION
            del ovf[key];state.setdefault('overlay_deleted',set()).add(key);return 1
        host,err=resolve(name)
        if host and os.path.exists(host):unsupported(f'DeleteFileA on original data: {name!r}')
        state['last_error']=2 if key.startswith(GAME_DIR.lower()) and parent_exists(key) else 3;return 0
    @api('GetFileInformationByHandle',2)
    def _(a):
        f=file(a[0])
        if not f:state['last_error']=6;return 0
        if f.get('overlay'):
            created,written=state['overlay_times'][f['overlay']];size=len(ovf[f['overlay']]);attr=0x20
            index=state['overlay_index'][f['overlay']]
        else:created=written=0;size=f['size'];attr=0x01;index=0
        info=[attr]
        for ms in (created,written,written):t=FILE_EPOCH+ms*10000;info+=[t&0xffffffff,t>>32]
        info+=[0x4d480001,size>>32,size&0xffffffff,1,0,index]
        for i,v in enumerate(info):w32(a[1]+4*i,v)
        return 1
    @api('FileTimeToLocalFileTime',2)
    def _(a):
        lo,hi=ctx['r32'](a[0]),ctx['r32'](a[0]+4);w32(a[1],lo);w32(a[1]+4,hi);return 1   # local time zone: UTC
    @api('FileTimeToSystemTime',2)
    def _(a):
        t=ctx['r32'](a[0])|(ctx['r32'](a[0]+4)<<32)
        if t>>63:state['last_error']=87;return 0
        ms_total=t//10000;days,ms=divmod(ms_total,86400000)
        z=days-134774+719468   # days since 1601-01-01 -> civil date (Howard Hinnant's algorithm)
        era=z//146097;doe=z-era*146097;yoe=(doe-doe//1460+doe//36524-doe//146096)//365
        y=yoe+era*400;doy=doe-(365*yoe+yoe//4-yoe//100);mp=(5*doy+2)//153
        d=doy-(153*mp+2)//5+1;m=mp+3 if mp<10 else mp-9;y+=m<=2
        dow=(days+1)%7   # 1601-01-01 was a Monday
        st=[y,m,dow,d,ms//3600000,ms//60000%60,ms//1000%60,ms%1000]
        cpu.mem_write(a[1],b''.join(v.to_bytes(2,'little') for v in st));return 1
    @api('GetOverlappedResult',4)
    def _(a):
        if not file(a[0]):state['last_error']=6;return 0
        w32(a[2],ctx['r32'](a[1]+4));return 1
    @api('SetFilePointer',4)
    def _(a):
        h,lo,phi,method=a[:4];f=file(h)
        if not f:state['last_error']=6;return INVALID_HANDLE
        dist=s32(lo) if not phi else ((ctx['r32'](phi)<<32)|lo) - ((1<<64) if ctx['r32'](phi)>>31 else 0)
        base={0:0,1:f['pos'],2:len(ovf[f['overlay']]) if f.get('overlay') else f['size']}.get(method)
        if base is None or base+dist<0:state['last_error']=131;return INVALID_HANDLE   # ERROR_NEGATIVE_SEEK
        f['pos']=base+dist
        if phi:w32(phi,f['pos']>>32)
        state['last_error']=0;return f['pos']&0xffffffff
    @api('GetFileSize',2)
    def _(a):
        f=file(a[0])
        if not f:state['last_error']=6;return INVALID_HANDLE
        size=len(ovf[f['overlay']]) if f.get('overlay') else f['size']
        if a[1]:w32(a[1],size>>32)
        return size&0xffffffff
    @api('CloseHandle',1)
    def _(a):
        f=file(a[0])
        if f:f['open']=False;return 1
        if 0x50000000<a[0]<=0x50000000+state['events']:return 1   # events (objects not freed yet)
        state['last_error']=6;return 0
    # Writable overlay: directories and files the game creates live outside the original data
    # (the app's private storage on the device, memory here), keyed by the case-folded guest path.
    state.setdefault('overlay_dirs',set())
    def guest_full(name):
        p=name.replace('/','\\').rstrip('\\')
        if not (len(p)>1 and p[1]==':') and not p.startswith('\\'):p=state['cwd']+'\\'+p
        return p
    @api('CreateDirectoryA',2)
    def _(a):
        full=guest_full(ctx['cstr'](a[0],1024))
        if not full.lower().startswith(GAME_DIR.lower()):state['last_error']=3;return 0
        host,err=resolve(full)
        if (host and os.path.isdir(host)) or full.lower() in state['overlay_dirs']:state['last_error']=183;return 0   # ERROR_ALREADY_EXISTS
        state['overlay_dirs'].add(full.lower());return 1
    @api('GetFileAttributesA',1)
    def _(a):
        name=ctx['cstr'](a[0],1024);key=guest_key(name).rstrip('\\')
        if ov_lookup(key):return 0x20   # FILE_ATTRIBUTE_ARCHIVE
        if key in state['overlay_dirs']:return 0x10
        host,err=resolve(name)
        if host is None:state['last_error']=err;return INVALID_HANDLE
        return 0x10 if os.path.isdir(host) else 0x01   # FILE_ATTRIBUTE_DIRECTORY / READONLY (game data is read-only)

    # ---- Registry (advapi32) ---------------------------------------------------------------
    # In-memory registry, empty at first run (a fresh install); the port persists it in the
    # app's storage. Keys are case-insensitive paths under the predefined roots; key handles
    # from 0x70000004 (step 4). Values: (type, bytes).
    ROOTS={0x80000000:'HKCR',0x80000001:'HKCU',0x80000002:'HKLM',0x80000003:'HKU'}
    state.setdefault('registry',{});state.setdefault('hkeys',{})
    reg,hkeys=state['registry'],state['hkeys']
    def key_path(hkey,sub):
        base=ROOTS.get(hkey) or hkeys.get(hkey)
        if base is None:return None
        sub=ctx['cstr'](sub,512).strip('\\') if sub else ''
        return (base+'\\'+sub if sub else base).upper(),(base+'\\'+sub if sub else base)
    def new_hkey(path):
        h=0x70000004+4*len(hkeys);hkeys[h]=path;return h
    ERROR_FILE_NOT_FOUND,ERROR_INVALID_HANDLE,ERROR_MORE_DATA=2,6,234
    @api('RegOpenKeyExA',5)
    def _(a):
        p=key_path(a[0],a[1])
        if p is None:return ERROR_INVALID_HANDLE
        if p[0] not in reg and p[0] not in [ROOTS[r].upper() for r in ROOTS]:return ERROR_FILE_NOT_FOUND
        w32(a[4],new_hkey(p[1]));return 0
    @api('RegCreateKeyExA',9)
    def _(a):
        p=key_path(a[0],a[1])
        if p is None:return ERROR_INVALID_HANDLE
        created=p[0] not in reg
        parts=p[1].split('\\')
        for i in range(2,len(parts)+1):reg.setdefault('\\'.join(parts[:i]).upper(),{'name':'\\'.join(parts[:i]),'values':{}})
        w32(a[7],new_hkey(p[1]))
        if a[8]:w32(a[8],1 if created else 2)   # REG_CREATED_NEW_KEY / REG_OPENED_EXISTING_KEY
        return 0
    @api('RegCloseKey',1)
    def _(a):
        if a[0] in ROOTS:return 0
        if a[0] not in hkeys:return ERROR_INVALID_HANDLE
        del hkeys[a[0]];return 0
    @api('RegSetValueExA',6)
    def _(a):
        p=key_path(a[0],0)
        if p is None or p[0] not in reg:return ERROR_INVALID_HANDLE
        name=ctx['cstr'](a[1]) if a[1] else ''
        reg[p[0]]['values'][name.upper()]=(a[3],bytes(cpu.mem_read(a[4],a[5])) if a[5] else b'');return 0
    @api('RegQueryValueExA',6)
    def _(a):
        p=key_path(a[0],0)
        if p is None or p[0] not in reg:return ERROR_INVALID_HANDLE
        value=reg[p[0]]['values'].get((ctx['cstr'](a[1]) if a[1] else '').upper())
        if value is None:return ERROR_FILE_NOT_FOUND
        vtype,data=value
        if a[3]:w32(a[3],vtype)
        if a[4]:
            size=ctx['r32'](a[5])
            if size<len(data):w32(a[5],len(data));return ERROR_MORE_DATA
            cpu.mem_write(a[4],data)
        if a[5]:w32(a[5],len(data))
        return 0

    # ---- Dialogs ---------------------------------------------------------------------------
    # No Win32 dialogs on Android. DialogBoxParamA runs the game's dialog procedure against
    # virtual controls: WM_INITDIALOG, then (unless the procedure already ended the dialog)
    # the user's confirmation, WM_COMMAND(IDOK). The port's Android settings UI may change
    # the controls' selection before that confirmation; for now the procedure's own default
    # is kept. Control handles: 0x00030000 + 4*id. Combo boxes keep strings, data and selection.
    WM_INITDIALOG,WM_COMMAND,IDOK=0x110,0x111,1
    state.setdefault('dialogs',{});state.setdefault('controls',{})
    dialogs,controls=state['dialogs'],state['controls']
    @api('DialogBoxParamA',5)
    def _(a):
        hinst,template,parent,proc,param=a[:5]
        hdlg=0x00028000+4*len(dialogs);dialogs[hdlg]={'template':template,'proc':proc,'ended':None}
        state['windows'][hdlg]={'class':'#32770','wndproc':None,'style':0,'exstyle':0,'rect':[0,0,0,0],'title':'','visible':True,'long':{}}
        def after_init(r):
            if dialogs[hdlg]['ended'] is not None:return dialogs[hdlg]['ended']
            return Callbacks([(proc,[hdlg,WM_COMMAND,IDOK,control(hdlg,IDOK)])],after_ok)
        def after_ok(r):
            if dialogs[hdlg]['ended'] is None:unsupported('dialog not ended after IDOK')
            return dialogs[hdlg]['ended']
        return Callbacks([(proc,[hdlg,WM_INITDIALOG,0,param])],after_init)
    @api('EndDialog',2)
    def _(a):
        if a[0] not in dialogs:state['last_error']=1400;return 0
        dialogs[a[0]]['ended']=a[1];return 1
    def control(hdlg,cid):
        h=0x00030000+4*cid;controls.setdefault(h,{'dialog':hdlg,'id':cid,'items':[],'data':[],'sel':0xffffffff,'check':0});return h
    @api('GetDlgItem',2)
    def _(a):
        if a[0] not in dialogs:state['last_error']=1400;return 0
        return control(a[0],a[1])
    CB_ADDSTRING,CB_GETCOUNT,CB_GETCURSEL,CB_GETLBTEXT,CB_GETITEMDATA,CB_RESETCONTENT,CB_SETCURSEL,CB_SETITEMDATA=0x143,0x146,0x147,0x148,0x150,0x14b,0x14e,0x151
    CB_ERR=0xffffffff
    def control_message(c,msg,wp,lp):
        n=len(c['items'])
        if msg==CB_ADDSTRING:c['items'].append(ctx['cstr'](lp,256));c['data'].append(0);return n
        if msg==CB_RESETCONTENT:c['items'].clear();c['data'].clear();c['sel']=CB_ERR;return 0
        if msg==CB_GETCOUNT:return n
        if msg==CB_SETCURSEL:
            if wp<n:c['sel']=wp;return wp
            c['sel']=CB_ERR;return CB_ERR
        if msg==CB_GETCURSEL:return c['sel']
        if msg==CB_SETITEMDATA:
            if wp>=n:return CB_ERR
            c['data'][wp]=lp;return 1
        if msg==CB_GETITEMDATA:return c['data'][wp] if wp<n else CB_ERR
        if msg==CB_GETLBTEXT:
            if wp>=n:return CB_ERR
            cpu.mem_write(lp,c['items'][wp].encode('latin-1')+b'\0');return len(c['items'][wp])
        unsupported(f'message {msg:#x} to dialog control {c["id"]}')
    # ---- Window management ------------------------------------------------------------------
    # Frameless windows: window rect == client area in screen coordinates. Size/position changes
    # notify WM_SIZE / WM_MOVE (what Windows ends up sending through DefWindowProc's handling of
    # WM_WINDOWPOSCHANGED). The first ShowWindow that makes a top-level window visible activates
    # the app: WM_ACTIVATEAPP(TRUE), WM_ACTIVATE(WA_ACTIVE), WM_SETFOCUS.
    WM_SETFOCUS,WM_ACTIVATE,WM_ACTIVATEAPP=7,6,0x1c
    def window(h):
        w=state['windows'].get(h)
        if w is None:unsupported(f'unknown window {h:#x}')
        return w
    def s32(v):return v-(1<<32) if v>>31 else v
    def write_rect(at,r):
        for i,v in enumerate(r):w32(at+4*i,v&0xffffffff)
    @api('GetWindowRect',2)
    def _(a):write_rect(a[1],window(a[0])['rect']);return 1
    @api('GetClientRect',2)
    def _(a):r=window(a[0])['rect'];write_rect(a[1],[0,0,r[2]-r[0],r[3]-r[1]]);return 1
    # MapVirtualKeyA on a US keyboard, as runtime/port_api.c: 0 VK->scan, 1 scan->VK, 2 VK->char, 3 scan->VK (left/right).
    VK_SC=[(0x1b,0x01),(0x08,0x0e),(0x09,0x0f),(0x0d,0x1c),(0x10,0x2a),(0x11,0x1d),(0x12,0x38),(0x20,0x39),(0x14,0x3a),(0x26,0x48),(0x28,0x50),(0x25,0x4b),(0x27,0x4d),(0x2d,0x52),(0x2e,0x53),(0x24,0x47),(0x23,0x4f),(0x21,0x49),(0x22,0x51),(0x90,0x45),(0x91,0x46),(0x6a,0x37),(0x6b,0x4e),(0x6d,0x4a),(0x6e,0x53),(0x6f,0x35),(0x60,0x52),(0x61,0x4f),(0x62,0x50),(0x63,0x51),(0x64,0x4b),(0x65,0x4c),(0x66,0x4d),(0x67,0x47),(0x68,0x48),(0x69,0x49),(0xa0,0x2a),(0xa1,0x36),(0xa2,0x1d),(0xa3,0x1d),(0xa4,0x38),(0xa5,0x38),(0xba,0x27),(0xbb,0x0d),(0xbc,0x33),(0xbd,0x0c),(0xbe,0x34),(0xbf,0x35),(0xc0,0x29),(0xdb,0x1a),(0xdc,0x2b),(0xdd,0x1b),(0xde,0x28),(0x51,0x10),(0x57,0x11),(0x45,0x12),(0x52,0x13),(0x54,0x14),(0x59,0x15),(0x55,0x16),(0x49,0x17),(0x4f,0x18),(0x50,0x19),(0x41,0x1e),(0x53,0x1f),(0x44,0x20),(0x46,0x21),(0x47,0x22),(0x48,0x23),(0x4a,0x24),(0x4b,0x25),(0x4c,0x26),(0x5a,0x2c),(0x58,0x2d),(0x43,0x2e),(0x56,0x2f),(0x42,0x30),(0x4e,0x31),(0x4d,0x32),(0x31,0x02),(0x32,0x03),(0x33,0x04),(0x34,0x05),(0x35,0x06),(0x36,0x07),(0x37,0x08),(0x38,0x09),(0x39,0x0a),(0x30,0x0b),(0x70,0x3b),(0x71,0x3c),(0x72,0x3d),(0x73,0x3e),(0x74,0x3f),(0x75,0x40),(0x76,0x41),(0x77,0x42),(0x78,0x43),(0x79,0x44),(0x7a,0x57),(0x7b,0x58)]
    VK_EX={0x1d:0xa2,0x2a:0xa0,0x36:0xa1,0x38:0xa4}
    VK_CH={0x08:0x08,0x09:0x09,0x0d:0x0d,0x1b:0x1b,0x20:0x20,0x30:0x30,0x31:0x31,0x32:0x32,0x33:0x33,0x34:0x34,0x35:0x35,0x36:0x36,0x37:0x37,0x38:0x38,0x39:0x39,0x41:0x41,0x42:0x42,0x43:0x43,0x44:0x44,0x45:0x45,0x46:0x46,0x47:0x47,0x48:0x48,0x49:0x49,0x4a:0x4a,0x4b:0x4b,0x4c:0x4c,0x4d:0x4d,0x4e:0x4e,0x4f:0x4f,0x50:0x50,0x51:0x51,0x52:0x52,0x53:0x53,0x54:0x54,0x55:0x55,0x56:0x56,0x57:0x57,0x58:0x58,0x59:0x59,0x5a:0x5a,0x60:0x30,0x61:0x31,0x62:0x32,0x63:0x33,0x64:0x34,0x65:0x35,0x66:0x36,0x67:0x37,0x68:0x38,0x69:0x39,0x6a:0x2a,0x6b:0x2b,0x6d:0x2d,0x6e:0x2e,0x6f:0x2f,0xba:0x3b,0xbb:0x3d,0xbc:0x2c,0xbd:0x2d,0xbe:0x2e,0xbf:0x2f,0xc0:0x60,0xdb:0x5b,0xdc:0x5c,0xdd:0x5d,0xde:0x27}
    @api('MapVirtualKeyA',2)
    def _(a):
        code,kind=a[0],a[1]
        if kind==0:return next((s for v,s in VK_SC if v==code),0)
        if kind in (1,3):
            if kind==3 and code in VK_EX:return VK_EX[code]
            return next((v for v,s in VK_SC if s==code),0)
        if kind==2:return VK_CH.get(code,0)
        return 0
    @api('ClientToScreen',2)
    def _(a):
        r=window(a[0])['rect'];w32(a[1],(s32(ctx['r32'](a[1]))+r[0])&0xffffffff);w32(a[1]+4,(s32(ctx['r32'](a[1]+4))+r[1])&0xffffffff);return 1
    @api('ScreenToClient',2)
    def _(a):
        r=window(a[0])['rect'];w32(a[1],(s32(ctx['r32'](a[1]))-r[0])&0xffffffff);w32(a[1]+4,(s32(ctx['r32'](a[1]+4))-r[1])&0xffffffff);return 1
    def reshape(h,x,y,cx,cy,move,size):
        w=window(h);r=w['rect'];old=list(r)
        if move:r[2]+=x-r[0];r[3]+=y-r[1];r[0],r[1]=x,y
        if size:r[2],r[3]=r[0]+cx,r[1]+cy
        calls=[]
        if size and (r[2]-r[0],r[3]-r[1])!=(old[2]-old[0],old[3]-old[1]):calls.append((w['wndproc'],[h,WM_SIZE,0,lparam(r[2]-r[0],r[3]-r[1])]))
        if move and (r[0],r[1])!=(old[0],old[1]):calls.append((w['wndproc'],[h,WM_MOVE,0,lparam(r[0],r[1])]))
        return Callbacks(calls,lambda res:1) if calls and w['wndproc'] else 1
    @api('SetWindowPos',7)
    def _(a):
        h,after,x,y,cx,cy,flags=a[:7]
        return reshape(h,s32(x),s32(y),s32(cx),s32(cy),not flags&2,not flags&1)   # SWP_NOMOVE 2, SWP_NOSIZE 1
    @api('MoveWindow',6)
    def _(a):return reshape(a[0],s32(a[1]),s32(a[2]),s32(a[3]),s32(a[4]),True,True)
    state.setdefault('active',0)
    @api('ShowWindow',2)
    def _(a):
        w=window(a[0]);was=w['visible'];w['visible']=a[1]!=0
        if w['visible'] and not was and w['wndproc'] and not state['active']:
            state['active']=a[0];state['focus']=a[0]
            return Callbacks([(w['wndproc'],[a[0],WM_ACTIVATEAPP,1,0]),(w['wndproc'],[a[0],WM_ACTIVATE,1,0]),(w['wndproc'],[a[0],WM_SETFOCUS,0,0])],lambda r:int(was))
        return int(was)
    # Window timers: kept per (window, id); the port's message loop posts WM_TIMER when due.
    state.setdefault('timers',{})
    @api('SetTimer',4)
    def _(a):
        if a[0]:window(a[0])
        if a[3]:unsupported('SetTimer with a TIMERPROC')
        tid=a[1] if a[0] else 0x7000+len(state['timers'])
        state['timers'][(a[0],tid)]=[max(a[2],10),state['clock']+max(a[2],10)];return tid
    @api('KillTimer',2)
    def _(a):
        if (a[0],a[1]) in state['timers']:del state['timers'][(a[0],a[1])];return 1
        state['last_error']=1402;return 0   # ERROR_INVALID_TIMER_HANDLE (FALSE, as Windows for an unknown timer)
    # Message queue. Posted messages are FIFO; WM_TIMER is generated when a timer is due on the
    # clock, with the lowest priority, as in Windows; WM_QUIT comes from PostQuitMessage. On the
    # device the touch/gamepad layer injects input messages here; the reference has no input.
    # MSG: hwnd, message, wParam, lParam, time, pt.x, pt.y.
    WM_TIMER,WM_QUIT=0x113,0x12
    state.setdefault('queue',[]);queue=state['queue']
    def next_message(hwnd,lo,hi,remove):
        def match(m):return (not hwnd or m[0]==hwnd) and ((lo==0 and hi==0) or lo<=m[1]<=hi)
        for i,m in enumerate(queue):
            if match(m):
                if remove:queue.pop(i)
                return m
        for (h,tid),t in sorted(state['timers'].items()):
            if state['clock']>=t[1] and match((h,WM_TIMER)):
                if remove:t[1]=state['clock']+t[0]
                return (h,WM_TIMER,tid,0)
        return None
    def write_msg(at,m):
        for i,v in enumerate((m[0],m[1],m[2],m[3],state['clock']&0xffffffff,cur['pos'][0],cur['pos'][1])):w32(at+4*i,v)
    @api('PeekMessageA',5)
    def _(a):
        m=next_message(a[1],a[2],a[3],a[4]&1)
        if m is None:return 0
        write_msg(a[0],m);return 1
    @api('GetMessageA',4)
    def _(a):
        m=next_message(a[1],a[2],a[3],True)
        if m is None:unsupported('GetMessageA would block with an empty queue (no input in the reference)')
        write_msg(a[0],m);return 0 if m[1]==WM_QUIT else 1
    @api('PostMessageA',4)
    def _(a):
        if a[0] and a[0] not in state['windows']:state['last_error']=1400;return 0
        queue.append((a[0],a[1],a[2],a[3]));return 1
    @api('PostQuitMessage',1)
    def _(a):queue.append((0,WM_QUIT,a[0],0));return None
    @api('TranslateMessage',1)
    def _(a):return 0   # WM_CHAR is produced by the port's input layer directly
    @api('DispatchMessageA',1)
    def _(a):
        hwnd,msg,wp,lp=[ctx['r32'](a[0]+4*i) for i in range(4)]
        if msg==WM_TIMER and lp:unsupported('WM_TIMER with a TIMERPROC')
        w=state['windows'].get(hwnd)
        if not w or not w['wndproc']:return 0
        return Callbacks([(w['wndproc'],[hwnd,msg,wp,lp])],lambda r:r[0])
    @api('SetWindowTextA',2)
    def _(a):window(a[0])['title']=ctx['cstr'](a[1],1024) if a[1] else '';return 1
    @api('GetWindowTextA',3)
    def _(a):
        t=window(a[0])['title'].encode('latin-1')[:max(a[2],1)-1]
        if a[2]:cpu.mem_write(a[1],t+b'\0')
        return len(t)
    @api('UpdateWindow',1)
    def _(a):window(a[0]);return 1
    @api('IsIconic',1)
    def _(a):window(a[0]);return 0
    @api('IsWindowVisible',1)
    def _(a):return int(window(a[0])['visible'])
    @api('SetForegroundWindow',1)
    def _(a):window(a[0]);state['active']=a[0];return 1
    @api('GetForegroundWindow',0)
    def _(a):return state['active']
    @api('GetActiveWindow',0)
    def _(a):return state['active']
    GWL={0xfffffffc:'wndproc',0xfffffff0:'style',0xffffffec:'exstyle'}
    @api('GetWindowLongA',2)
    def _(a):
        w=window(a[0])
        if a[1] in GWL:return w[GWL[a[1]]]
        return w['long'].get(a[1],0)
    @api('SetWindowLongA',3)
    def _(a):
        w=window(a[0])
        if a[1] in GWL:old=w[GWL[a[1]]];w[GWL[a[1]]]=a[2];return old
        old=w['long'].get(a[1],0);w['long'][a[1]]=a[2];return old

    state.setdefault('focus',0)
    @api('SetFocus',1)
    def _(a):
        if a[0] and a[0] not in controls and a[0] not in state['windows']:state['last_error']=1400;return 0
        old=state['focus'];state['focus']=a[0];return old
    @api('GetFocus',0)
    def _(a):return state['focus']
    @api('SendMessageA',4)
    def _(a):
        hwnd,msg,wp,lp=a[:4]
        if hwnd in controls:return control_message(controls[hwnd],msg,wp,lp)
        win=state['windows'].get(hwnd)
        if win and win['wndproc']:return Callbacks([(win['wndproc'],[hwnd,msg,wp,lp])],lambda r:r[0])
        unsupported(f'SendMessageA to {hwnd:#x} message {msg:#x}')

    # ---- COM objects of the port's shims ------------------------------------------------
    # Object: guest structure, +0 vtable, +4 reference count; vtables hold fake addresses
    # COM_VA + 0x400*interface + 4*method (up to 256 methods per interface; the scheme of runtime/d3d8.c).
    COM_VA,COM_HEAP,COM_LIMIT=0x1e10000,0x1e40000,0x1e80000
    state.setdefault('com',{'next':COM_HEAP,'ifaces':[],'objects':{}})
    com=state['com'];w32=ctx['w32']
    def com_alloc(size):
        start=(com['next']+15)&~15
        if start+size>COM_LIMIT:unsupported('COM heap exhausted')
        cpu.mem_write(start,bytes(size));com['next']=start+size;return start
    def interface(name,methods):
        """methods: list of (method name, argument count including this, handler(self, args) or None)."""
        index=len(com['ifaces']);vtable=com_alloc(4*len(methods))
        for i in range(len(methods)):w32(vtable+4*i,COM_VA+0x400*index+4*i)
        com['ifaces'].append((name,methods,vtable));return index
    def new_object(index,data=None):
        obj=com_alloc(16);w32(obj,com['ifaces'][index][2]);w32(obj+4,1)
        com['objects'][obj]={'iface':index,'data':data or {}};return obj
    def dispatch(address,arg):
        index,method=(address-COM_VA)//0x400,((address-COM_VA)%0x400)//4
        if index>=len(com['ifaces']) or address&3:unsupported(f'unknown COM address {address:#x}')
        name,methods,_=com['ifaces'][index]
        if method>=len(methods):unsupported(f'{name} method {method}')
        mname,nargs,handler=methods[method];args=[arg(i) for i in range(nargs)]
        if args[0] not in com['objects'] or com['objects'][args[0]]['iface']!=index:unsupported(f'{name}::{mname} on a bad object {args[0]:#x}')
        if handler is None:unsupported(f'{name}::{mname} not implemented')
        return nargs,handler(com['objects'][args[0]],args),f'{name}::{mname}'
    apis['com']=(0,dispatch)
    def addref(o,a):
        refs=ctx['r32'](a[0]+4)+1;w32(a[0]+4,refs);return refs
    release_hooks=[]
    def release(o,a):
        refs=max(ctx['r32'](a[0]+4)-1,0);w32(a[0]+4,refs)
        if refs==0:
            for hook in release_hooks:hook(o)
        return refs
    def unknown(rest):return [('QueryInterface',3,None),('AddRef',1,addref),('Release',1,release)]+rest

    # ---- DirectInput 8 -------------------------------------------------------------------
    # The system keyboard and mouse exist; their state is zero (no keys, no motion) until the
    # port's touch/gamepad layer feeds them. No DirectInput joysticks (the Android gamepad
    # is mapped later). DI_OK = 0.
    import uuid
    def guid(addr):return str(uuid.UUID(bytes_le=bytes(cpu.mem_read(addr,16))))
    SYS_KEYBOARD,SYS_MOUSE='6f1d2b61-d5a0-11cf-bfc7-444553540000','6f1d2b60-d5a0-11cf-bfc7-444553540000'
    IID_DI8A='bf798030-483a-4da2-aa99-5d64ed369700'
    DIERR_INVALIDPARAM,DIERR_DEVICENOTREG,DIERR_NOTACQUIRED,DIERR_NOINTERFACE=0x80070057,0x80040154,0x8007000c,0x80004002
    def dev_set_data_format(o,a):
        size,objsize,flags,datasize=[ctx['r32'](a[1]+4*i) for i in range(4)]
        if size!=0x18 or objsize!=0x10:return DIERR_INVALIDPARAM
        o['data']['format']=datasize;return 0
    def dev_set_cooperative_level(o,a):o['data']['coop']=(a[1],a[2]);return 0
    def dev_acquire(o,a):
        if 'format' not in o['data']:return DIERR_INVALIDPARAM
        o['data']['acquired']=True;return 0
    def dev_unacquire(o,a):
        was=o['data'].get('acquired',False);o['data']['acquired']=False;return 0 if was else 1   # DI_NOEFFECT
    def dev_get_device_state(o,a):
        if not o['data'].get('acquired'):return DIERR_NOTACQUIRED
        if a[1]!=o['data'].get('format'):return DIERR_INVALIDPARAM
        data=bytearray(a[1])
        if o['data']['kind']=='keyboard' and a[1]==256:   # input script MH_KEYS="1c:10:14,..." (as runtime/port_api.c)
            frames=state.get('frames',0)
            for k,f,t in KEY_SCRIPT:
                if k<256 and f<=frames<t:data[k]=0x80
        if o['data']['kind']=='mouse' and a[1] in (16,20):   # buttons at +12: script codes 0x100+n
            frames=state.get('frames',0);dx=dy=0
            for k,f,t in KEY_SCRIPT:
                if 0x100<=k<0x100+a[1]-12 and f<=frames<t:data[12+k-0x100]=0x80
                if 0x200<=k<=0x203 and f<=frames<t:   # scripted motion: +X, -X, +Y, -Y (MOUSE_STEP per read)
                    s=MOUSE_STEP if k in (0x200,0x202) else -MOUSE_STEP
                    if k<0x202:dx+=s
                    else:dy+=s
            data[0:4]=(dx&0xffffffff).to_bytes(4,'little');data[4:8]=(dy&0xffffffff).to_bytes(4,'little')
        cpu.mem_write(a[2],bytes(data));return 0
    # Virtual devices: a 3-axis, 3-button traditional mouse and an enhanced 101/102-key keyboard,
    # attached, no POVs, no force feedback.
    def dev_get_capabilities(o,a):
        if ctx['r32'](a[1])!=0x2c:return DIERR_INVALIDPARAM
        caps=(0x2c,1,0x212,3,3,0) if o['data']['kind']=='mouse' else (0x2c,1,0x413,0,128,0)
        cpu.mem_write(a[1],bytes(0x2c))
        for i,v in enumerate(caps):w32(a[1]+4*i,v)
        return 0
    DEVICE=interface('IDirectInputDevice8A',unknown([
        ('GetCapabilities',2,dev_get_capabilities),('EnumObjects',4,None),('GetProperty',3,None),('SetProperty',3,None),
        ('Acquire',1,dev_acquire),('Unacquire',1,dev_unacquire),('GetDeviceState',3,dev_get_device_state),('GetDeviceData',5,None),
        ('SetDataFormat',2,dev_set_data_format),('SetEventNotification',2,None),('SetCooperativeLevel',3,dev_set_cooperative_level),
        ('GetObjectInfo',4,None),('GetDeviceInfo',2,None),('RunControlPanel',3,None),('Initialize',4,None),('CreateEffect',5,None),
        ('EnumEffects',4,None),('GetEffectInfo',3,None),('GetForceFeedbackState',2,None),('SendForceFeedbackCommand',2,None),
        ('EnumCreatedEffectObjects',4,None),('Escape',2,None),('Poll',1,None),('SendDeviceData',5,None),('EnumEffectsInFile',5,None),
        ('WriteEffectToFile',5,None),('BuildActionMap',4,None),('SetActionMap',4,None),('GetImageInfo',2,None)]))
    def di_create_device(o,a):
        g=guid(a[1])
        if g not in (SYS_KEYBOARD,SYS_MOUSE):w32(a[2],0);return DIERR_DEVICENOTREG
        if a[3]:return 0x80040110   # CLASS_E_NOAGGREGATION
        w32(a[2],new_object(DEVICE,{'kind':'keyboard' if g==SYS_KEYBOARD else 'mouse'}));return 0
    def di_enum_devices(o,a):
        dev_type=a[1]
        if dev_type in (4,0x14,0x15,0x16,0x17,0x18):return 0   # game controllers: none, the callback is not called
        unsupported(f'IDirectInput8A::EnumDevices for device type {dev_type:#x}')
    DINPUT=interface('IDirectInput8A',unknown([
        ('CreateDevice',4,di_create_device),('EnumDevices',5,di_enum_devices),('GetDeviceStatus',2,None),('RunControlPanel',3,None),
        ('Initialize',3,None),('FindDevice',4,None),('EnumDevicesBySemantics',6,None),('ConfigureDevices',5,None)]))
    # ---- Direct3D 8 (same semantics as runtime/d3d8.c) --------------------------------------
    # One adapter, a virtual "Android OpenGL ES" display; modes: six sizes x (X8R8G8B8, R5G6B5)
    # at 60 Hz; desktop mode 1280x720 X8R8G8B8. HAL device only.
    D3D_OK,D3DERR_INVALIDCALL,D3DERR_NOTAVAILABLE=0,0x8876086c,0x8876086a
    X8R8G8B8,R5G6B5=22,23
    SIZES=((640,480),(800,600),(1024,768),(1280,720),(1280,960),(1920,1080));FORMATS=(X8R8G8B8,R5G6B5)
    MODES=[(w,h,60,f) for (w,h) in SIZES for f in FORMATS];DESKTOP=MODES[3*2]
    def write_mode(at,mode):
        for i,v in enumerate(mode):w32(at+4*i,v)
    def d3d_mode_count(o,a):return len(MODES) if a[1]==0 else 0
    def d3d_enum_modes(o,a):
        if a[1]!=0 or a[2]>=len(MODES) or not a[3]:return D3DERR_INVALIDCALL
        write_mode(a[3],MODES[a[2]]);return D3D_OK
    def d3d_display_mode(o,a):
        if a[1]!=0 or not a[2]:return D3DERR_INVALIDCALL
        write_mode(a[2],DESKTOP);return D3D_OK
    def d3d_check_device_type(o,a):
        display_ok=a[3] in FORMATS;back_ok=a[4]==a[3] or (a[5] and a[4] in FORMATS)
        return D3D_OK if a[1]==0 and a[2]==1 and display_ok and back_ok else D3DERR_NOTAVAILABLE
    # D3DCAPS8 of the port's device: a GeForce2/GeForce4 MX-class fixed-function HAL with hardware
    # T&L and no vertex/pixel shaders (the profile the GLES backend reproduces most directly).
    import struct as _struct
    F=lambda v:_struct.unpack('<I',_struct.pack('<f',v))[0]
    CAPS8=[1,0,                       # DeviceType HAL, AdapterOrdinal
        0,0x200A0000,0,0x80000001,0,  # Caps, Caps2 (FULLSCREENGAMMA|CANRENDERWINDOWED|DYNAMICTEXTURES), Caps3, PresentationIntervals (ONE|IMMEDIATE), CursorCaps
        0x0009BAF0,                   # DevCaps: execute/TL vertex in system+video memory, video textures, DrawPrimitives2(Ex), HW T&L, HW rasterization
        0x000008F2,0x00332191,        # PrimitiveMiscCaps (MASKZ, cull none/cw/ccw, COLORWRITEENABLE, BLENDOP), RasterCaps (dither, z test, fog vertex/table/range, LOD bias, z bias, anisotropy, w/z fog)
        0xFF,0x1FFF,0x1FFF,0xFF,      # ZCmpCaps, SrcBlendCaps, DestBlendCaps, AlphaCmpCaps
        0x00084208,0x00014C05,        # ShadeCaps (Gouraud colour/specular/alpha/fog), TextureCaps (perspective, alpha, projected, cube, mipmap, mip cube)
        0x03030700,0x03030700,0,      # Texture/CubeTexture/VolumeTexture filter caps (point/linear/anisotropic min, point/linear mip and mag)
        0x1F,0,0x1F,                  # TextureAddressCaps (wrap, mirror, clamp, border, independent UV), VolumeTextureAddressCaps, LineCaps
        2048,2048,0,8192,2048,4,      # MaxTextureWidth/Height, MaxVolumeExtent, MaxTextureRepeat, MaxTextureAspectRatio, MaxAnisotropy
        F(1e10),F(0.0),F(0.0),F(0.0),F(0.0),F(0.0),   # MaxVertexW, guard band (none), ExtentsAdjust
        0xFF,0x00080008,0x03FFFFFF,   # StencilCaps (all ops), FVFCaps (8 texcoords, DONOTSTRIPELEMENTS), TextureOpCaps (all)
        8,4,0x3B,8,6,4,0,             # MaxTextureBlendStages, MaxSimultaneousTextures, VertexProcessingCaps, MaxActiveLights, MaxUserClipPlanes, MaxVertexBlendMatrices, MaxVertexBlendMatrixIndex
        F(64.0),0xFFFFF,0xFFFFF,16,255,   # MaxPointSize, MaxPrimitiveCount, MaxVertexIndex, MaxStreams, MaxStreamStride
        0xFFFE0000,0,0xFFFF0000,F(0.0)]   # VertexShaderVersion 0.0, MaxVertexShaderConst, PixelShaderVersion 0.0, MaxPixelShaderValue
    assert len(CAPS8)==53
    def d3d_get_caps(o,a):
        if a[1]!=0 or a[2]!=1 or not a[3]:return D3DERR_INVALIDCALL
        for i,v in enumerate(CAPS8):w32(a[3]+4*i,v)
        return D3D_OK
    # Formats of the port's device. DXT textures are accepted (decompressed on upload where the
    # GPU lacks S3TC). No volume textures. Multisampling: none for now.
    FOURCC=lambda s:int.from_bytes(s.encode('ascii'),'little')
    TEXTURE_FORMATS={21,22,23,24,25,26,28,50,51}|{FOURCC(f'DXT{i}') for i in range(1,6)}
    DEPTH_FORMATS={80,75,77}               # D16, D24S8, D24X8
    TARGET_FORMATS={21,22,23}
    def d3d_check_format(o,a):
        adapter,devtype,adapter_fmt,usage,rtype,fmt=a[1:7]
        if adapter!=0 or devtype!=1 or adapter_fmt not in FORMATS:return D3DERR_INVALIDCALL
        if usage&2:ok=fmt in DEPTH_FORMATS and rtype==1                          # DEPTHSTENCIL surface
        elif usage&1:ok=fmt in TARGET_FORMATS and rtype in (1,3)                 # RENDERTARGET surface/texture
        elif rtype in (1,3,5):ok=fmt in TEXTURE_FORMATS or fmt in TARGET_FORMATS  # plain/texture/cube
        else:ok=False                                                            # volumes, buffers
        return D3D_OK if ok else D3DERR_NOTAVAILABLE
    def d3d_check_multisample(o,a):
        adapter,devtype,fmt,windowed,ms=a[1:6]
        if adapter!=0 or devtype!=1:return D3DERR_INVALIDCALL
        return D3D_OK if ms==0 else D3DERR_NOTAVAILABLE
    def d3d_check_depth_match(o,a):
        adapter,devtype,adapter_fmt,rt_fmt,ds_fmt=a[1:6]
        if adapter!=0 or devtype!=1:return D3DERR_INVALIDCALL
        return D3D_OK if rt_fmt in TARGET_FORMATS and ds_fmt in DEPTH_FORMATS else D3DERR_NOTAVAILABLE
    # D3DADAPTER_IDENTIFIER8 (0x42c bytes): the port's own name; vendor/device IDs zero so that no
    # vendor-specific workaround of the game is triggered; WHQL level 1.
    def d3d_identifier(o,a):
        if a[1]!=0 or not a[3]:return D3DERR_INVALIDCALL
        cpu.mem_write(a[3],bytes(0x42c))
        cpu.mem_write(a[3],b'mh-androidevolved\0');cpu.mem_write(a[3]+512,b'Android OpenGL ES (Manhunt port)\0')
        w32(a[3]+1024,0);w32(a[3]+1028,0x00080001)   # DriverVersion 8.1.0.0
        w32(a[3]+0x428,1);return D3D_OK
    # IDirect3DDevice8: the 97 methods in DirectX 8 order with their argument counts (this
    # included); handlers are added as the game reaches them. The device records the state the
    # GLES backend reproduces. A windowed device with a 0x0 back buffer takes the client size.
    DEVICE_METHODS=[('QueryInterface',3),('AddRef',1),('Release',1),('TestCooperativeLevel',1),('GetAvailableTextureMem',1),
        ('ResourceManagerDiscardBytes',2),('GetDirect3D',2),('GetDeviceCaps',2),('GetDisplayMode',2),('GetCreationParameters',2),
        ('SetCursorProperties',4),('SetCursorPosition',4),('ShowCursor',2),('CreateAdditionalSwapChain',3),('Reset',2),('Present',5),
        ('GetBackBuffer',4),('GetRasterStatus',2),('SetGammaRamp',3),('GetGammaRamp',2),('CreateTexture',8),('CreateVolumeTexture',9),
        ('CreateCubeTexture',7),('CreateVertexBuffer',6),('CreateIndexBuffer',6),('CreateRenderTarget',7),('CreateDepthStencilSurface',6),
        ('CreateImageSurface',5),('CopyRects',6),('UpdateTexture',3),('GetFrontBuffer',2),('SetRenderTarget',3),('GetRenderTarget',2),
        ('GetDepthStencilSurface',2),('BeginScene',1),('EndScene',1),('Clear',7),('SetTransform',3),('GetTransform',3),('MultiplyTransform',3),
        ('SetViewport',2),('GetViewport',2),('SetMaterial',2),('GetMaterial',2),('SetLight',3),('GetLight',3),('LightEnable',3),
        ('GetLightEnable',3),('SetClipPlane',3),('GetClipPlane',3),('SetRenderState',3),('GetRenderState',3),('BeginStateBlock',1),
        ('EndStateBlock',2),('ApplyStateBlock',2),('CaptureStateBlock',2),('DeleteStateBlock',2),('CreateStateBlock',3),('SetClipStatus',2),
        ('GetClipStatus',2),('GetTexture',3),('SetTexture',3),('GetTextureStageState',4),('SetTextureStageState',4),('ValidateDevice',2),
        ('GetInfo',4),('SetPaletteEntries',3),('GetPaletteEntries',3),('SetCurrentTexturePalette',2),('GetCurrentTexturePalette',2),
        ('DrawPrimitive',4),('DrawIndexedPrimitive',6),('DrawPrimitiveUP',5),('DrawIndexedPrimitiveUP',9),('ProcessVertices',6),
        ('CreateVertexShader',5),('SetVertexShader',2),('GetVertexShader',2),('DeleteVertexShader',2),('SetVertexShaderConstant',4),
        ('GetVertexShaderConstant',4),('GetVertexShaderDeclaration',4),('GetVertexShaderFunction',4),('SetStreamSource',4),
        ('GetStreamSource',4),('SetIndices',3),('GetIndices',3),('CreatePixelShader',3),('SetPixelShader',2),('GetPixelShader',2),
        ('DeletePixelShader',2),('SetPixelShaderConstant',4),('GetPixelShaderConstant',4),('GetPixelShaderFunction',4),
        ('DrawRectPatch',4),('DrawTriPatch',4),('DeletePatch',2)]
    assert len(DEVICE_METHODS)==97
    device_handlers={}
    def device_method(name):
        def register(fn):device_handlers[name]=fn;return fn
        return register
    # Surfaces: IDirect3DSurface8 objects with a D3DSURFACE_DESC; pixel storage is the backend's
    # (LockRect is added when the game first needs CPU access).
    SURFACE_IFACE=[None]
    def surface_get_desc(o,a):
        d=o['data']
        for i,v in enumerate((d['format'],1,d['usage'],d['pool'],d['size'],0,d['width'],d['height'])):w32(a[1]+4*i,v)
        return D3D_OK
    # LockRect: a texture level's surface shares the level's memory; other surfaces get guest
    # memory on first lock (the backend reads it back from / uploads it to the GPU).
    def surface_lock(o,a):
        d=o['data']
        if d.get('locked'):return D3DERR_INVALIDCALL
        if 'memory' not in d:
            pitch,size=level_layout(d['format'],d['width'],d['height']);d['pitch'],d['memory']=pitch,res_alloc(size)
        offset=0
        if a[2]:
            left,top=ctx['r32'](a[2]),ctx['r32'](a[2]+4)
            offset=(top//4)*d['pitch']+(left//4)*(8 if d['format']==DXT1 else 16) if d['format']>0xffff else top*d['pitch']+left*bytes_per_pixel(d['format'])
        d['locked']=True;w32(a[1],d['pitch']);w32(a[1]+4,d['memory']+offset);return D3D_OK
    def surface_unlock(o,a):
        d=o['data']
        if not d.get('locked'):return D3DERR_INVALIDCALL
        d['locked']=False;d['version']=d.get('version',0)+1
        if d.get('level') is not None:d['level']['version']+=1
        return D3D_OK
    def bytes_per_pixel(fmt):return {21:4,22:4,23:2,24:2,25:2,26:2,28:1,50:1,51:2,80:2,75:4,77:4}.get(fmt,0)
    def new_surface(device,width,height,fmt,usage,pool):
        if SURFACE_IFACE[0] is None:
            SURFACE_IFACE[0]=interface('IDirect3DSurface8',unknown([('GetDevice',2,None),('SetPrivateData',5,None),('GetPrivateData',4,None),
                ('FreePrivateData',2,None),('GetContainer',3,None),('GetDesc',2,surface_get_desc),('LockRect',4,surface_lock),('UnlockRect',1,surface_unlock)]))
        return new_object(SURFACE_IFACE[0],{'device':device,'width':width,'height':height,'format':fmt,'usage':usage,'pool':pool,
                                            'size':width*height*bytes_per_pixel(fmt)})
    def give(obj):   # return an existing object with its reference count incremented
        w32(obj+4,ctx['r32'](obj+4)+1);return obj
    @device_method('GetRenderTarget')
    def _(o,a):w32(a[1],give(o['data']['render_target']));return D3D_OK
    @device_method('GetDepthStencilSurface')
    def _(o,a):
        ds=o['data']['depth_stencil']
        if not ds:w32(a[1],0);return 0x88760827   # D3DERR_NOTFOUND
        w32(a[1],give(ds));return D3D_OK
    @device_method('GetBackBuffer')
    def _(o,a):
        if a[1]!=0 or a[2]!=0:return D3DERR_INVALIDCALL   # one back buffer, D3DBACKBUFFER_TYPE_MONO
        w32(a[3],give(o['data']['back_buffer']));return D3D_OK
    # Resource memory: vertex/index buffers (and later lockable textures) live in guest memory so
    # translated code can write them after Lock; region 0x10000000-0x20000000, 16-byte aligned,
    # bump allocation (released resources are not reused yet).
    RES_BASE,RES_LIMIT=0x10000000,0x20000000
    if not state.get('res_mapped'):cpu.mem_map(RES_BASE,RES_LIMIT-RES_BASE);state['res_mapped']=True;state['res_next']=RES_BASE
    # Released resources return their memory (as runtime/port_api.c): sizes rounded to 16, first
    # fit in address order over the free blocks, else the top; reused memory is zeroed.
    state.setdefault('res_free',[])
    def res_alloc(size):
        size=(size+15)&~15;free=state['res_free']
        for i,(s,e) in enumerate(free):
            if e-s>=size:
                if e-s==size:free.pop(i)
                else:free[i]=(s+size,e)
                cpu.mem_write(s,bytes(size));return s
        start=state['res_next']
        if start+size>RES_LIMIT:unsupported('Direct3D resource memory exhausted')
        state['res_next']=start+size;return start
    def res_release(start,size):
        size=(size+15)&~15;free=state['res_free'];i=0
        while i<len(free) and free[i][0]<start:i+=1
        free.insert(i,(start,start+size))
        if i+1<len(free) and free[i][1]==free[i+1][0]:free[i]=(free[i][0],free[i+1][1]);free.pop(i+1)
        if i>0 and free[i-1][1]==free[i][0]:free[i-1]=(free[i-1][0],free[i][1]);free.pop(i);i-=1
        if free and free[-1][1]==state['res_next']:state['res_next']=free.pop()[0]
    def destroy(o):
        # Last reference released: the object's own resource memory returns (a texture level's
        # surface belongs to its texture; device surfaces keep the device's reference).
        d=o['data']
        if d.get('destroyed'):return
        if 'levels' in d:
            for lv in d['levels']:res_release(lv['memory'],lv['size'])
        elif 'length' in d and 'memory' in d:res_release(d['memory'],d['length'])
        elif 'memory' in d and 'width' in d and d.get('level') is None:res_release(d['memory'],level_layout(d['format'],d['width'],d['height'])[1])
        else:return
        d['destroyed']=True
    release_hooks.append(destroy)
    BUFFER_IFACES={}
    def buffer_iface(kind):
        if kind not in BUFFER_IFACES:
            def lock(o,a):
                d=o['data'];offset,size,out,flags=a[1:5]
                if offset>d['length'] or (size and offset+size>d['length']):return D3DERR_INVALIDCALL
                d['locks']+=1;w32(out,d['memory']+offset);return D3D_OK
            def unlock(o,a):
                d=o['data']
                if not d['locks']:return D3DERR_INVALIDCALL
                d['locks']-=1;d['version']+=1;return D3D_OK
            def desc(o,a):
                d=o['data']   # D3DVERTEXBUFFER_DESC / D3DINDEXBUFFER_DESC: Format, Type, Usage, Pool, Size, FVF (vertex only)
                vals=(d['format'],6 if kind=='vertex' else 7,d['usage'],d['pool'],d['length'])+((d['fvf'],) if kind=='vertex' else ())
                for i,v in enumerate(vals):w32(a[1]+4*i,v)
                return D3D_OK
            BUFFER_IFACES[kind]=interface('IDirect3DVertexBuffer8' if kind=='vertex' else 'IDirect3DIndexBuffer8',unknown([
                ('GetDevice',2,None),('SetPrivateData',5,None),('GetPrivateData',4,None),('FreePrivateData',2,None),('SetPriority',2,None),
                ('GetPriority',1,None),('PreLoad',1,lambda o,a:None),('GetType',1,lambda o,a:6 if kind=='vertex' else 7),('Lock',5,lock),('Unlock',1,unlock),('GetDesc',2,desc)]))
        return BUFFER_IFACES[kind]
    def create_buffer(device,kind,length,usage,fmt,fvf,pool,out):
        if not length or not out or pool>3:return D3DERR_INVALIDCALL
        if kind=='index' and fmt not in (101,102):return D3DERR_INVALIDCALL   # D3DFMT_INDEX16 / INDEX32
        buf=new_object(buffer_iface(kind),{'device':device,'length':length,'usage':usage,'format':fmt,'fvf':fvf,'pool':pool,
                                           'memory':res_alloc(length),'locks':0,'version':0})
        w32(out,buf);return D3D_OK
    # Textures: every mip level lives in guest memory (LockRect returns it); DXT levels use 4x4
    # blocks of 8 (DXT1) or 16 bytes. Levels=0 builds the full chain down to 1x1.
    DXT1=FOURCC('DXT1')
    def level_layout(fmt,w,h):
        if fmt in TEXTURE_FORMATS and fmt>0xffff:   # DXTn
            bw,bh=max(1,(w+3)//4),max(1,(h+3)//4);block=8 if fmt==DXT1 else 16
            return bw*block,bw*block*bh
        bpp=bytes_per_pixel(fmt)
        if not bpp:unsupported(f'texture format {fmt:#x}')
        return w*bpp,w*bpp*h
    TEXTURE_IFACE=[None]
    def texture_iface():
        if TEXTURE_IFACE[0] is None:
            def level(o,i):
                lv=o['data']['levels']
                return lv[i] if i<len(lv) else None
            def lock(o,a):
                lv=level(o,a[1])
                if lv is None or lv['locked']:return D3DERR_INVALIDCALL
                offset=0
                if a[3]:   # sub-rectangle
                    left,top=ctx['r32'](a[3]),ctx['r32'](a[3]+4)
                    offset=(top//4)*lv['pitch']+(left//4)*(8 if o['data']['format']==DXT1 else 16) if o['data']['format']>0xffff else top*lv['pitch']+left*bytes_per_pixel(o['data']['format'])
                lv['locked']=True;w32(a[2],lv['pitch']);w32(a[2]+4,lv['memory']+offset);return D3D_OK
            def unlock(o,a):
                lv=level(o,a[1])
                if lv is None or not lv['locked']:return D3DERR_INVALIDCALL
                lv['locked']=False;lv['version']+=1;return D3D_OK
            def level_desc(o,a):
                lv=level(o,a[1]);d=o['data']
                if lv is None:return D3DERR_INVALIDCALL
                for i,v in enumerate((d['format'],1,d['usage'],d['pool'],lv['size'],0,lv['width'],lv['height'])):w32(a[2]+4*i,v)
                return D3D_OK
            def surface_level(o,a):
                lv=level(o,a[1])
                if lv is None:return D3DERR_INVALIDCALL
                if not lv.get('surface'):
                    lv['surface']=new_surface(o['data']['device'],lv['width'],lv['height'],o['data']['format'],o['data']['usage'],o['data']['pool'])
                    com['objects'][lv['surface']]['data'].update(memory=lv['memory'],pitch=lv['pitch'],level=lv)
                w32(a[2],give(lv['surface']));return D3D_OK
            TEXTURE_IFACE[0]=interface('IDirect3DTexture8',unknown([('GetDevice',2,None),('SetPrivateData',5,None),('GetPrivateData',4,None),
                ('FreePrivateData',2,None),('SetPriority',2,None),('GetPriority',1,None),('PreLoad',1,lambda o,a:None),('GetType',1,lambda o,a:3),
                ('SetLOD',2,None),('GetLOD',1,None),('GetLevelCount',1,lambda o,a:len(o['data']['levels'])),('GetLevelDesc',3,level_desc),
                ('GetSurfaceLevel',3,surface_level),('LockRect',5,lock),('UnlockRect',2,unlock),('AddDirtyRect',2,lambda o,a:D3D_OK)]))
        return TEXTURE_IFACE[0]
    @device_method('CreateTexture')
    def _(o,a):
        width,height,levels,usage,fmt,pool,out=a[1:8]
        if not width or not height or width>2048 or height>2048 or not out:return D3DERR_INVALIDCALL
        if usage&1:ok=fmt in TARGET_FORMATS
        else:ok=fmt in TEXTURE_FORMATS or fmt in TARGET_FORMATS
        if not ok:return D3DERR_INVALIDCALL
        chain=[];w,h=width,height
        while True:
            pitch,size=level_layout(fmt,w,h);chain.append({'width':w,'height':h,'pitch':pitch,'size':size,'memory':res_alloc(size),'locked':False,'version':0})
            if (levels and len(chain)>=levels) or (w==1 and h==1):break
            w,h=max(1,w//2),max(1,h//2)
        tex=new_object(texture_iface(),{'device':a[0],'format':fmt,'usage':usage,'pool':pool,'levels':chain})
        w32(out,tex);return D3D_OK
    # CopyRects: copies rectangles between surfaces of the same format (whole source when
    # cRects is 0). Surfaces get guest memory on first use; DXT copies whole 4x4 blocks.
    def surface_memory(s):
        d=com['objects'][s]['data']
        if 'memory' not in d:
            pitch,size=level_layout(d['format'],d['width'],d['height']);d['pitch'],d['memory']=pitch,res_alloc(size)
        return d
    @device_method('CopyRects')
    def _(o,a):
        src,rects,count,dst,points=a[1:6]
        if src not in com['objects'] or dst not in com['objects']:return D3DERR_INVALIDCALL
        s,d=surface_memory(src),surface_memory(dst)
        if s['format']!=d['format']:return D3DERR_INVALIDCALL
        dxt=s['format']>0xffff;unit=4 if dxt else 1;bpp=(8 if s['format']==DXT1 else 16) if dxt else bytes_per_pixel(s['format'])
        boxes=[[ctx['r32'](rects+16*i+4*k) for k in range(4)] for i in range(count)] if count else [[0,0,s['width'],s['height']]]
        for i,(l,t,r,b) in enumerate(boxes):
            px,py=(ctx['r32'](points+8*i),ctx['r32'](points+8*i+4)) if points else (l,t)
            if r>s['width'] or b>s['height'] or px+(r-l)>d['width'] or py+(b-t)>d['height']:return D3DERR_INVALIDCALL
            row=((r-l+unit-1)//unit)*bpp
            for y in range(t//unit,(b+unit-1)//unit):
                data=bytes(cpu.mem_read(s['memory']+y*s['pitch']+(l//unit)*bpp,row))
                cpu.mem_write(d['memory']+(py//unit+y-t//unit)*d['pitch']+(px//unit)*bpp,data)
        d['version']=d.get('version',0)+1
        if d.get('level') is not None:d['level']['version']+=1
        return D3D_OK
    @device_method('CreateDepthStencilSurface')
    def _(o,a):
        width,height,fmt,ms,out=a[1:6]
        if not width or not height or fmt not in DEPTH_FORMATS or ms!=0 or not out:return D3DERR_INVALIDCALL
        w32(out,new_surface(a[0],width,height,fmt,2,0));return D3D_OK
    @device_method('CreateRenderTarget')
    def _(o,a):
        width,height,fmt,ms,lockable,out=a[1:7]
        if not width or not height or fmt not in TARGET_FORMATS or ms!=0 or not out:return D3DERR_INVALIDCALL
        w32(out,new_surface(a[0],width,height,fmt,1,0));return D3D_OK
    @device_method('CreateImageSurface')
    def _(o,a):
        width,height,fmt,out=a[1:5]
        if not width or not height or not out or not (fmt in TEXTURE_FORMATS or fmt in TARGET_FORMATS):return D3DERR_INVALIDCALL
        w32(out,new_surface(a[0],width,height,fmt,0,2));return D3D_OK   # D3DPOOL_SYSTEMMEM
    @device_method('SetRenderTarget')
    def _(o,a):
        d=dev(o)
        if a[1]:d['render_target']=a[1]
        d['depth_stencil']=a[2];return D3D_OK
    @device_method('CreateVertexBuffer')
    def _(o,a):return create_buffer(a[0],'vertex',a[1],a[2],100,a[3],a[4],a[5])   # D3DFMT_VERTEXDATA
    @device_method('CreateIndexBuffer')
    def _(o,a):return create_buffer(a[0],'index',a[1],a[2],a[3],0,a[4],a[5])
    # ---- Device state (recorded; the GLES backend reproduces it) ----------------------------
    # Defaults are DirectX 8's documented initial values; querying a state without a known
    # default is reported instead of inventing one.
    RS_DEFAULTS={7:1,8:3,9:2,10:0,14:1,15:0,16:1,19:2,20:1,22:3,23:4,24:0,25:8,26:0,27:0,28:0,29:0,30:0,34:0,35:0,
        36:F(0.0),37:F(1.0),38:F(1.0),40:0,47:0,48:0,52:0,53:1,54:1,55:1,56:8,57:0,58:0xffffffff,59:0xffffffff,60:0xffffffff,
        **{w:0 for w in range(128,136)},136:1,137:1,139:0,140:0,141:1,142:1,143:0,145:1,146:2,147:0,148:0,151:0,152:0,153:0,
        154:F(1.0),155:F(1.0),156:0,157:0,158:F(1.0),159:F(0.0),160:F(0.0),161:1,162:0xffffffff,163:0,164:F(1.0),166:F(64.0),
        167:0,168:0xf,170:F(0.0),171:1}
    def tss_default(stage,t):
        table={1:4 if stage==0 else 1,2:2,3:1,4:2 if stage==0 else 1,5:2,6:1,7:0,8:0,9:0,10:0,11:stage,13:1,14:1,15:0,16:1,17:1,18:0,
               19:0,20:0,21:1,22:0,23:0,24:0,25:1,26:1,27:1,28:1}
        if t not in table:unsupported(f'texture stage state {t} has no known default')
        return table[t]
    def dev(o):return o['data']
    @device_method('SetRenderState')
    def _(o,a):dev(o)['rs'][a[1]]=a[2];return D3D_OK
    @device_method('GetRenderState')
    def _(o,a):
        rs=dev(o)['rs']
        if a[1] not in rs and a[1] not in RS_DEFAULTS:unsupported(f'render state {a[1]} has no known default')
        w32(a[2],rs.get(a[1],RS_DEFAULTS.get(a[1])));return D3D_OK
    @device_method('SetTextureStageState')
    def _(o,a):
        if a[1]>=8:return D3DERR_INVALIDCALL
        dev(o)['tss'][(a[1],a[2])]=a[3];return D3D_OK
    @device_method('GetTextureStageState')
    def _(o,a):
        if a[1]>=8:return D3DERR_INVALIDCALL
        w32(a[3],dev(o)['tss'].get((a[1],a[2]),tss_default(a[1],a[2]))if (a[1],a[2]) in dev(o)['tss'] else tss_default(a[1],a[2]));return D3D_OK
    @device_method('SetTexture')
    def _(o,a):
        if a[1]>=8:return D3DERR_INVALIDCALL
        dev(o)['textures'][a[1]]=a[2];return D3D_OK
    @device_method('GetTexture')
    def _(o,a):
        t=dev(o)['textures'].get(a[1],0);w32(a[2],give(t) if t else 0);return D3D_OK
    IDENTITY=[F(1.0),0,0,0, 0,F(1.0),0,0, 0,0,F(1.0),0, 0,0,0,F(1.0)]
    @device_method('SetTransform')
    def _(o,a):dev(o)['transforms'][a[1]]=[ctx['r32'](a[2]+4*i) for i in range(16)];return D3D_OK
    @device_method('GetTransform')
    def _(o,a):
        for i,v in enumerate(dev(o)['transforms'].get(a[1],IDENTITY)):w32(a[2]+4*i,v)
        return D3D_OK
    @device_method('SetViewport')
    def _(o,a):dev(o)['viewport']=[ctx['r32'](a[1]+4*i) for i in range(6)];return D3D_OK
    @device_method('GetViewport')
    def _(o,a):
        p=dev(o)['params'];vp=dev(o).get('viewport',[0,0,p['width'],p['height'],F(0.0),F(1.0)])
        for i,v in enumerate(vp):w32(a[1]+4*i,v)
        return D3D_OK
    @device_method('SetMaterial')
    def _(o,a):dev(o)['material']=[ctx['r32'](a[1]+4*i) for i in range(17)];return D3D_OK
    @device_method('SetLight')
    def _(o,a):dev(o).setdefault('lights',{})[a[1]]=[ctx['r32'](a[2]+4*i) for i in range(26)];return D3D_OK
    @device_method('LightEnable')
    def _(o,a):dev(o).setdefault('light_enable',{})[a[1]]=a[2];return D3D_OK
    @device_method('SetStreamSource')
    def _(o,a):dev(o)['streams'][a[1]]=(a[2],a[3]);return D3D_OK
    @device_method('SetIndices')
    def _(o,a):dev(o)['indices']=(a[1],a[2]);return D3D_OK
    @device_method('SetVertexShader')
    def _(o,a):dev(o)['vertex_shader']=a[1];return D3D_OK   # an FVF code (no programmable shaders in the port's caps)
    @device_method('SetPixelShader')
    def _(o,a):
        if a[1]:unsupported('SetPixelShader with a shader (the port reports no pixel shaders)')
        return D3D_OK
    @device_method('BeginScene')
    def _(o,a):
        if dev(o)['scene']:return D3DERR_INVALIDCALL
        dev(o)['scene']=True;return D3D_OK
    @device_method('EndScene')
    def _(o,a):
        if not dev(o)['scene']:return D3DERR_INVALIDCALL
        dev(o)['scene']=False;return D3D_OK
    @device_method('Clear')
    def _(o,a):dev(o)['clears']=dev(o).get('clears',0)+1;return D3D_OK
    class FramesReached(Exception):pass
    apis['FramesReached']=(0,FramesReached)
    # Keyboard messages (as runtime/port_api.c): the game's menus read WM_KEYDOWN/WM_CHAR, not
    # DirectInput. At each Present the scripted keyboard state for the new frame count is compared
    # with the one delivered; each change posts WM_KEYDOWN (+ WM_CHAR) or WM_KEYUP to the focus window.
    KEY_VK={0x01:(0x1b,0x1b),0x1c:(0x0d,0x0d),0x39:(0x20,0x20),0xc8:(0x26,0),0xd0:(0x28,0),0xcb:(0x25,0),0xcd:(0x27,0),   # DIK: (VK, char)
            0x0f:(0x09,0x09),0x2a:(0x10,0),0x1d:(0x11,0),0x11:(0x57,0x77),0x1e:(0x41,0x61),0x1f:(0x53,0x73),0x20:(0x44,0x64),
            0x21:(0x46,0x66),0x10:(0x51,0x71),0x12:(0x45,0x65),0x13:(0x52,0x72),0x2d:(0x58,0x78),
            0x02:(0x31,0x31),0x03:(0x32,0x32),0x04:(0x33,0x33),0x05:(0x34,0x34)}
    state.setdefault('keys_delivered',set())
    def key_messages():
        frames=state['frames'];target=state['focus'] or state['active']
        want={k for k,f,t in KEY_SCRIPT if k in KEY_VK and f<=frames<t}
        for k in sorted(want^state['keys_delivered']):
            vk,ch=KEY_VK[k];lp=1|((k&0x7f)<<16)|((1<<24) if k&0x80 else 0)
            if k in want:
                queue.append((target,0x100,vk,lp))
                if ch:queue.append((target,0x102,ch,lp))
            else:queue.append((target,0x101,vk,lp|0xc0000000))
        state['keys_delivered']=want
    @device_method('Present')
    def _(o,a):
        dev(o)['frames']+=1;state['frames']=dev(o)['frames']
        key_messages()
        if state['frames']>=ctx['frames']:raise FramesReached(f'{state["frames"]} frames presented')
        return D3D_OK
    for _name in ('DrawPrimitive','DrawIndexedPrimitive','DrawPrimitiveUP','DrawIndexedPrimitiveUP'):
        def _draw(o,a,_name=_name):
            if not dev(o)['scene']:return D3DERR_INVALIDCALL
            d=dev(o).setdefault('draws',{});d[_name]=d.get(_name,0)+1;return D3D_OK
        device_handlers[_name]=_draw
    @device_method('TestCooperativeLevel')
    def _(o,a):return D3D_OK
    @device_method('GetAvailableTextureMem')
    def _(o,a):return 256<<20   # 256 MiB
    @device_method('ResourceManagerDiscardBytes')
    def _(o,a):return D3D_OK
    @device_method('ValidateDevice')
    def _(o,a):w32(a[1],1);return D3D_OK
    @device_method('GetDeviceCaps')
    def _(o,a):return d3d_get_caps(o,[0,0,1,a[1]])
    @device_method('GetDisplayMode')
    def _(o,a):
        p=dev(o)['params'];write_mode(a[1],(p['width'],p['height'],60,p['format']) if not p['windowed'] else DESKTOP);return D3D_OK
    @device_method('GetCreationParameters')
    def _(o,a):
        p=dev(o)['params']
        for i,v in enumerate((0,1,p['window'],p['flags'])):w32(a[1]+4*i,v)
        return D3D_OK
    @device_method('SetGammaRamp')
    def _(o,a):dev(o)['gamma']=bytes(cpu.mem_read(a[2],0x600));return None
    @device_method('ShowCursor')
    def _(o,a):old=dev(o).get('cursor_shown',0);dev(o)['cursor_shown']=a[1];return old
    @device_method('SetCursorPosition')
    def _(o,a):return None
    DEVICE_IFACE=[None]
    def presentation(ppp,hwnd):
        """Validates D3DPRESENT_PARAMETERS; returns the parameters or an HRESULT. A windowed 0x0
        back buffer takes the window's client size. The chosen values are written back."""
        pp=[ctx['r32'](ppp+4*i) for i in range(13)]
        width,height,fmt,count,ms,swap,devwin,windowed,autodepth,depthfmt=pp[:10]
        win=devwin or hwnd
        if win not in state['windows'] or ms!=0 or count>1 or (autodepth and depthfmt not in DEPTH_FORMATS):return D3DERR_INVALIDCALL
        if windowed:
            r=state['windows'][win]['rect']
            if not width:width=r[2]-r[0]
            if not height:height=r[3]-r[1]
            if fmt==0:fmt=DESKTOP[3]
        elif (width,height,60 if pp[11] in (0,60) else pp[11],fmt) not in MODES:return D3DERR_INVALIDCALL
        if fmt not in TARGET_FORMATS:return D3DERR_NOTAVAILABLE
        w32(ppp,width);w32(ppp+4,height);w32(ppp+8,fmt);w32(ppp+12,max(count,1))
        return {'width':width,'height':height,'format':fmt,'windowed':windowed,'depth':depthfmt if autodepth else 0,'swap':swap,'window':win,
                'refresh':pp[11],'interval':pp[12]}
    def attach_buffers(dev,data):
        p=data['params']
        data['back_buffer']=new_surface(dev,p['width'],p['height'],p['format'],1,0)        # D3DUSAGE_RENDERTARGET, D3DPOOL_DEFAULT
        data['render_target']=data['back_buffer']
        data['depth_stencil']=new_surface(dev,p['width'],p['height'],p['depth'],2,0) if p['depth'] else 0   # D3DUSAGE_DEPTHSTENCIL
    def d3d_create_device(o,a):
        adapter,devtype,hwnd,flags,ppp,out=a[1:7]
        if adapter!=0 or devtype!=1 or not out or not flags&0x70:return D3DERR_INVALIDCALL
        params=presentation(ppp,hwnd)
        if not isinstance(params,dict):return params
        params['flags']=flags
        if DEVICE_IFACE[0] is None:
            DEVICE_IFACE[0]=interface('IDirect3DDevice8',[(n,k,device_handlers.get(n,addref if n=='AddRef' else release if n=='Release' else None)) for n,k in DEVICE_METHODS])
        dev=new_object(DEVICE_IFACE[0],{'params':params,'rs':{},'tss':{},'transforms':{},'textures':{},'streams':{},'scene':False,'frames':0,'resets':0})
        attach_buffers(dev,com['objects'][dev]['data']);w32(out,dev);return D3D_OK
    # Reset: new presentation parameters and new implicit buffers; render and texture-stage
    # states return to their defaults, as DirectX 8 documents.
    @device_method('Reset')
    def _(o,a):
        d=o['data'];params=presentation(a[1],d['params']['window'])
        if not isinstance(params,dict):return params
        params['flags']=d['params']['flags'];d['params']=params
        d['rs'].clear();d['tss'].clear();d['transforms'].clear();d['textures'].clear();d['streams'].clear();d.pop('viewport',None)
        d['resets']+=1;state.setdefault('resets',[]).append(dict(params))
        attach_buffers(a[0],d);return D3D_OK
    D3D8=interface('IDirect3D8',[('QueryInterface',3,lambda o,a:(w32(a[2],0) if a[2] else None,0x80004002)[1]),('AddRef',1,addref),('Release',1,release),
        ('RegisterSoftwareDevice',2,None),('GetAdapterCount',1,lambda o,a:1),('GetAdapterIdentifier',4,d3d_identifier),('GetAdapterModeCount',2,d3d_mode_count),
        ('EnumAdapterModes',4,d3d_enum_modes),('GetAdapterDisplayMode',3,d3d_display_mode),('CheckDeviceType',6,d3d_check_device_type),
        ('CheckDeviceFormat',7,d3d_check_format),('CheckDeviceMultiSampleType',6,d3d_check_multisample),('CheckDepthStencilMatch',6,d3d_check_depth_match),('GetDeviceCaps',4,d3d_get_caps),
        ('GetAdapterMonitor',2,None),('CreateDevice',7,d3d_create_device)])
    @api('Direct3DCreate8',1)
    def _(a):return new_object(D3D8) if a[0]==220 else 0

    # ---- Miles Sound System (mss32) ---------------------------------------------------------
    # The port replaces Miles with its own mixer over Android audio. One digital driver and one
    # 3D provider ("Miles Fast 2D Positional Audio": positional panning/attenuation, no HRTF or
    # EAX); 32 voices. Playback progresses with the reference's virtual clock. Strings returned
    # to the game live in a guest scratch area. Handles: driver 0x6D000001, provider 0x6E000001,
    # samples 0x6F000004 + 4n.
    MSS_SCRATCH=0x1f12000
    state.setdefault('mss',{'redist':MSS_SCRATCH,'prefs':{},'driver':0,'provider_open':False,'samples':{},'scratch':MSS_SCRATCH+0x10})
    mss=state['mss']
    def mss_string(text):
        at=mss['scratch'];data=text.encode('latin-1')+b'\0';cpu.mem_write(at,data);mss['scratch']=(at+len(data)+3)&~3;return at
    if mss['scratch']==MSS_SCRATCH+0x10:cpu.mem_write(MSS_SCRATCH,b'\0')
    PROVIDER,PROVIDER_NAME=0x6E000001,'Miles Fast 2D Positional Audio'
    @api('_AIL_set_redist_directory@4',1)
    def _(a):old=mss['redist'];mss['redist']=mss_string(ctx['cstr'](a[0])) if a[0] else MSS_SCRATCH;return old
    @api('_AIL_startup@0',0)
    def _(a):mss['started']=True;return 1
    @api('_AIL_shutdown@0',0)
    def _(a):mss['started']=False;return None
    @api('_AIL_set_preference@8',2)
    def _(a):old=mss['prefs'].get(a[0],0);mss['prefs'][a[0]]=a[1];return old
    # AIL_process_digital_audio(dest, dest_size, dest_rate, dest_format, num_srcs, AILMIXINFO*):
    # the game decompresses streamed IMA ADPCM (WAVE_FORMAT 0x11, mono, 4 bits) to 16-bit PCM
    # at the same rate, block by block (each block: int16 sample, index, reserved, nibbles low
    # first). Returns the bytes written. Other conversions are not modelled (fail closed).
    IMA_INDEX=(-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8)
    IMA_STEP=(7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,
              337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,
              4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767)
    @api('_AIL_process_digital_audio@24',6)
    def _(a):
        dest,size,rate,fmt,count,info=a[:6];r32=ctx['r32']
        fields=[r32(info+4*i) for i in range(9)]   # AILSOUNDINFO: format, data, length, rate, bits, channels, samples, block, initial
        if count!=1 or fmt!=1 or fields[0]!=0x11 or fields[4]!=4 or fields[5]!=1 or fields[3]!=rate or fields[7]<5:
            unsupported(f'AIL_process_digital_audio conversion {fields} to rate {rate} format {fmt} ({count} sources)')
        block=fields[7];src=bytes(cpu.mem_read(fields[1],fields[2]));out=bytearray();limit=size//2
        for b in range(0,len(src)-block+1,block):
            pred=int.from_bytes(src[b:b+2],'little',signed=True);index=min(src[b+2],88);out+=pred.to_bytes(2,'little',signed=True)
            for byte in src[b+4:b+block]:
                for n in (byte&15,byte>>4):
                    step=IMA_STEP[index];diff=step>>3
                    if n&4:diff+=step
                    if n&2:diff+=step>>1
                    if n&1:diff+=step>>2
                    pred=max(-32768,min(32767,pred-diff if n&8 else pred+diff));index=max(0,min(88,index+IMA_INDEX[n]))
                    out+=pred.to_bytes(2,'little',signed=True)
        out=out[:2*limit];cpu.mem_write(dest,bytes(out));return len(out)
    @api('_AIL_ms_count@0',0)
    def _(a):return tick()&0xffffffff
    @api('_AIL_open_digital_driver@16',4)
    def _(a):
        freq,bits,channels,flags=a[:4]
        if bits not in (8,16) or channels not in (1,2):return 0
        mss['driver']=0x6D000001;mss['driver_format']=(freq,bits,channels);return mss['driver']
    @api('_AIL_close_digital_driver@4',1)
    def _(a):mss['driver']=0;return None
    @api('_AIL_enumerate_3D_providers@12',3)
    def _(a):
        nxt,dest,name=a[:3];i=ctx['r32'](nxt)
        if i!=0:return 0
        w32(nxt,1);w32(dest,PROVIDER);w32(name,mss_string(PROVIDER_NAME));return 1
    @api('_AIL_open_3D_provider@4',1)
    def _(a):
        if a[0]!=PROVIDER:return 1   # M3D_NOTINIT-style failure
        mss['provider_open']=True;return 0   # M3D_NOERR
    @api('_AIL_close_3D_provider@4',1)
    def _(a):mss['provider_open']=False;return None
    @api('_AIL_set_3D_provider_preference@12',3)
    def _(a):mss['prefs'][('3d',ctx['cstr'](a[1]))]=ctx['r32'](a[2]);return 0
    @api('_AIL_3D_provider_attribute@12',3)
    def _(a):
        name=ctx['cstr'](a[1])
        if name not in mss['prefs'] and ('3d',name) not in mss['prefs']:unsupported(f'AIL_3D_provider_attribute({name!r})')
        w32(a[2],mss['prefs'].get(('3d',name),0));return None
    # Room types (EAX environments): stored only; the port's mixer applies no reverb yet.
    @api('_AIL_set_3D_room_type@8',2)
    def _(a):mss['room']=a[1];return None
    @api('_AIL_3D_room_type@4',1)
    def _(a):return mss.get('room',0)

    # 3D samples. AILSOUNDINFO: format, data_ptr, data_len, rate, bits, channels, samples,
    # block_size, initial_ptr. Accepted: PCM (1) and IMA ADPCM (0x11), mono or stereo.
    # Status: SMP_FREE 1, SMP_DONE 2, SMP_PLAYING 4, SMP_STOPPED 8. A started sample plays for
    # its length in ms of the virtual clock (times the loop count; 0 loops = forever).
    SMP_DONE,SMP_PLAYING,SMP_STOPPED=2,4,8
    def sample(h):
        s=mss['samples'].get(h)
        if s is None:unsupported(f'unknown 3D sample handle {h:#x}')
        return s
    def sample_ms(s):
        info=s.get('info')
        if not info:return 0
        fmt,ptr,length,rate,bits,channels,samples,block=info[:8]
        frames=samples if fmt==0x11 else length//max(1,(bits//8)*channels)
        return frames*1000//max(1,rate*(s['rate']/rate if s.get('rate') else 1))
    def update(s):
        if s['status']==SMP_PLAYING and s['loops']:
            if state['clock']-s['started']>=sample_ms(s)*s['loops']:s['status']=SMP_DONE
        return s['status']
    @api('_AIL_allocate_3D_sample_handle@4',1)
    def _(a):
        if a[0]!=PROVIDER or not mss['provider_open']:return 0
        live=[h for h,s in mss['samples'].items() if not s['released']]
        if len(live)>=32:return 0
        h=0x6F000004+4*len(mss['samples']);mss['samples'][h]={'released':False,'status':SMP_DONE,'loops':1,'volume':1.0,'pos':(0,0,0),
                                                               'info':None,'started':0,'offset':0,'rate':0}
        return h
    @api('_AIL_release_3D_sample_handle@4',1)
    def _(a):sample(a[0])['released']=True;return None
    @api('_AIL_set_3D_sample_info@8',2)
    def _(a):
        s=sample(a[0]);info=[ctx['r32'](a[1]+4*i) for i in range(9)]
        if info[0] not in (1,0x11) or info[5] not in (1,2):return 0
        s.update(info=info,status=SMP_DONE,offset=0);return 1
    @api('_AIL_start_3D_sample@4',1)
    def _(a):s=sample(a[0]);s.update(status=SMP_PLAYING,started=state['clock'],offset=0);return None
    @api('_AIL_stop_3D_sample@4',1)
    def _(a):
        s=sample(a[0])
        if update(s)==SMP_PLAYING:s['status']=SMP_STOPPED;s['offset']=state['clock']-s['started']
        return None
    @api('_AIL_resume_3D_sample@4',1)
    def _(a):
        s=sample(a[0])
        if s['status']==SMP_STOPPED:s['status']=SMP_PLAYING;s['started']=state['clock']-s['offset']
        return None
    @api('_AIL_end_3D_sample@4',1)
    def _(a):sample(a[0])['status']=SMP_DONE;return None
    @api('_AIL_3D_sample_status@4',1)
    def _(a):return update(sample(a[0]))
    @api('_AIL_3D_sample_length@4',1)
    def _(a):s=sample(a[0]);return s['info'][2] if s['info'] else 0
    @api('_AIL_3D_sample_offset@4',1)
    def _(a):
        s=sample(a[0])
        if not s['info'] or update(s)!=SMP_PLAYING:return 0 if s['status']!=SMP_STOPPED else min(s['info'][2],s['offset'])
        ms=max(1,sample_ms(s));return (s['info'][2]*((state['clock']-s['started'])%ms))//ms
    @api('_AIL_set_3D_sample_loop_count@8',2)
    def _(a):sample(a[0])['loops']=a[1];return None
    @api('_AIL_set_3D_sample_loop_block@12',3)
    def _(a):sample(a[0])['loop_block']=(a[1],a[2]);return None
    for _n,_k in (('_AIL_set_3D_position@16',4),('_AIL_set_3D_sample_volume@8',2),('_AIL_set_3D_sample_distances@12',3),
                  ('_AIL_set_3D_sample_effects_level@8',2),('_AIL_set_3D_sample_occlusion@8',2),('_AIL_set_3D_sample_playback_rate@8',2)):
        def _setter(a,_n=_n):sample(a[0]).setdefault('params',{})[_n]=a[1:];return None
        apis[_n]=(_k,_setter)

    # ---- Bink video (binkw32) ---------------------------------------------------------------
    # The port decodes .bik with a Bink decoder (FFmpeg's bink/binkaudio). In the reference a
    # movie is opened from its real header (frames, size, frame rate) and advances on the
    # virtual clock; frames copied to the game are black (same control flow; pixels come from
    # the decoder on the device). BINK struct (guest): +0 Width, +4 Height, +8 Frames,
    # +0xc FrameNum (1-based), +0x10 LastFrameNum, +0x14 FrameRate, +0x18 FrameRateDiv.
    state.setdefault('bink',{})
    binks=state['bink']
    @api('_BinkSetSoundSystem@8',2)
    def _(a):state['bink_sound']=(a[0],a[1]);return 1
    @api('_BinkOpen@8',2)
    def _(a):
        name=ctx['cstr'](a[0],1024);host,err=resolve(name)
        if host is None or not os.path.isfile(host):return 0
        with open(host,'rb') as fp:head=fp.read(44)
        if len(head)<44 or head[:3] not in (b'BIK',b'KB2'):return 0
        import struct as st
        frames,width,height,rate,div=st.unpack_from('<I',head,8)[0],*st.unpack_from('<IIII',head,20)
        h=com_alloc(0x400)
        for i,v in enumerate((width,height,frames,1,0,rate,div)):w32(h+4*i,v)
        binks[h]={'name':name,'frames':frames,'rate':rate,'div':max(div,1),'start':state['clock']};return h
    def bink(h):
        b=binks.get(h)
        if b is None:unsupported(f'unknown Bink handle {h:#x}')
        return b
    @api('_BinkBufferOpen@16',4)
    def _(a):
        hwnd,w,h,flags=a[:4];buf=com_alloc(0x100)
        for i,v in enumerate((w,h,w,h)):w32(buf+4*i,v)   # Width, Height, WindowWidth, WindowHeight
        return buf
    @api('_BinkSetVolume@12',3)
    def _(a):bink(a[0])['volume']=(a[1],a[2]);return None
    @api('_BinkWait@4',1)
    def _(a):   # 1 while the current frame is not yet due
        b=bink(a[0]);frame=ctx['r32'](a[0]+0xc)
        due=b['start']+(frame-1)*1000*b['div']//max(b['rate'],1)
        return 1 if state['clock']<due else 0
    @api('_BinkDoFrame@4',1)
    def _(a):bink(a[0])['decoded']=ctx['r32'](a[0]+0xc);return 0
    @api('_BinkCopyToBufferRect@44',11)
    def _(a):
        h,dest,pitch,dest_h,dx,dy,sx,sy,sw,sh,flags=a[:11];bink(h)
        bpp={3:4,4:4,0xa:2,0xb:2,0xc:2,0xd:2}.get(flags&0x1f)
        if bpp is None:unsupported(f'BinkCopyToBufferRect surface type {flags:#x}')
        rows=min(sh,dest_h-dy) if dest_h>dy else 0
        for r in range(rows):cpu.mem_write(dest+(dy+r)*pitch+dx*bpp,bytes(sw*bpp))
        return 0
    @api('_BinkNextFrame@4',1)
    def _(a):
        b=bink(a[0]);frame=ctx['r32'](a[0]+0xc);w32(a[0]+0x10,frame)
        w32(a[0]+0xc,frame+1 if frame<b['frames'] else 1);return None
    @api('_BinkClose@4',1)
    def _(a):bink(a[0]);del binks[a[0]];return None

    # ---- Game functions replaced by the port (HLE) -----------------------------------------
    # 0x4becc0 probes the host's DirectX by loading DDRAW.DLL, D3D8.DLL, dpnhpast.dll and
    # D3D9.DLL and returns 0x700/0x800/0x801/0x900. Meaningless on Android: the port provides
    # DirectX 8.1 (its Direct3D 8 and DirectInput 8 shims), so the probe returns 0x801.
    apis['replaced']=(0,{0x4becc0:('GetDXVersion (HLE)',lambda:0x801)})

    @api('DirectInput8Create',5)
    def _(a):
        hinst,version,riid,out,outer=a[:5]
        if version!=0x800 or guid(riid)!=IID_DI8A:w32(out,0);return DIERR_NOINTERFACE
        if outer:return 0x80040110
        w32(out,new_object(DINPUT));return 0

    return apis
