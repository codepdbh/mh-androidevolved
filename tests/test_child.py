import ctypes as c, json, subprocess, sys, time
if sys.argv[1:] == ['sleep']: time.sleep(10)
elif sys.argv[1:] == ['stdin']: print(sys.stdin.read(),flush=True)
elif sys.argv[1:] == ['tree']:
 child=subprocess.Popen([sys.executable,__file__,'sleep'])
 print(json.dumps({'child_pid':child.pid}),flush=True)
 time.sleep(10)
else:
 k=c.WinDLL('kernel32'); k.GetCurrentProcess.restype=c.c_void_p; h=k.GetCurrentProcess()
 k.GetPriorityClass.argtypes=[c.c_void_p]; k.GetPriorityClass.restype=c.c_ulong
 k.GetProcessAffinityMask.argtypes=[c.c_void_p,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]
 a=c.c_size_t(); b=c.c_size_t(); assert k.GetProcessAffinityMask(h,c.byref(a),c.byref(b))
 print(json.dumps({'priority':k.GetPriorityClass(h),'affinity':a.value}),flush=True)
