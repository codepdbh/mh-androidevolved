"""Headless Windows process supervisor. Only explicitly approved command lines are safe.

Job restrictions do not sandbox a program or stop a GUI from changing display state.
Callers must never launch untrusted/GUI/game programs. No interactive mode exists.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import json, os, subprocess, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
class WorkSafeError(RuntimeError): pass

def available_memory_mb():
    if os.name != 'nt': raise WorkSafeError('Windows required')
    class MEMORYSTATUS(c.Structure):
        _fields_ = [('length',w.DWORD),('load',w.DWORD),('total_phys',c.c_ulonglong),('avail_phys',c.c_ulonglong),('total_page',c.c_ulonglong),('avail_page',c.c_ulonglong),('total_virtual',c.c_ulonglong),('avail_virtual',c.c_ulonglong),('avail_extended',c.c_ulonglong)]
    status=MEMORYSTATUS(); status.length=c.sizeof(status)
    if not c.windll.kernel32.GlobalMemoryStatusEx(c.byref(status)): raise c.WinError(c.get_last_error())
    actual=status.avail_phys // (1024*1024)
    # Owner-authorized temporary override of the free-RAM thresholds (never set by default).
    # Per-job memory caps, priority, affinity and deadlines still apply; below 512 MiB it is ignored.
    if os.environ.get('MHAE_OWNER_RAM_OVERRIDE')=='1' and actual>=512:
        log=ROOT/'logs'/'ram-override.log';log.parent.mkdir(exist_ok=True)
        with log.open('a',encoding='utf-8') as f:f.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} actual={actual}MiB thresholds bypassed by owner\n')
        return max(actual,4096)
    return actual

def build_android():
    """One fixed offline build. Refuse to start under memory pressure."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    free=available_memory_mb()
    if free < int(cfg['build_min_free_memory_mb']):
        raise WorkSafeError(f'insufficient available RAM: {free} MiB; minimum {cfg["build_min_free_memory_mb"]} MiB')
    java=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Android'/'Android Studio'/'jbr'/'bin'/'java.exe'
    dist=Path.home()/'.gradle'/'wrapper'/'dists'/'gradle-8.11.1-bin'
    jars=list(dist.glob('*/gradle-8.11.1/lib/gradle-launcher-8.11.1.jar'))
    if not java.is_file() or len(jars)!=1: raise WorkSafeError('expected local JDK 21 and one Gradle 8.11.1 distribution')
    argv=[str(java),'-Xmx256m','-Djava.awt.headless=true','-cp',str(jars[0]),'org.gradle.launcher.GradleMain', '--offline','--no-daemon','--max-workers=1','--console=plain','-p',str(ROOT/'android'),'assembleDebug']
    return _run_job(argv,int(cfg['build_timeout_seconds']),'android-build',cfg,max_processes=int(cfg['build_max_processes']),memory_mb=int(cfg['build_job_memory_mb']))

def check_android_java():
    """Compile only the launcher against the installed Android API, without Gradle."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    free=available_memory_mb()
    if free < 1024: raise WorkSafeError(f'insufficient available RAM: {free} MiB')
    javac=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Android'/'Android Studio'/'jbr'/'bin'/'javac.exe'
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platforms'/'android-35'/'android.jar'
    source=ROOT/'android/app/src/main/java/com/manhuntae/android/MainActivity.java'
    if not javac.is_file() or not sdk.is_file() or not source.is_file(): raise WorkSafeError('JDK, Android 35 SDK or launcher source missing')
    output=ROOT/'build'/'android-java-check'; output.mkdir(parents=True,exist_ok=True)
    argv=[str(javac),'-J-Xmx128m','-J-Djava.awt.headless=true','-proc:none','-source','11','-target','11','-classpath',str(sdk),'-d',str(output),
          *sorted(str(p) for p in source.parent.glob('*.java'))]
    return _run_job(argv,60,'android-java-check',cfg,max_processes=1,memory_mb=384)

def check_android_guest_memory():
    """Compile the guest-memory translation unit for Android ARM64, without linking."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    free=available_memory_mb()
    if free < 1024: raise WorkSafeError(f'insufficient available RAM: {free} MiB')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'; source=ROOT/'runtime'/'guest_memory.c'
    if not clang.is_file() or not source.is_file(): raise WorkSafeError('NDK 28.2 clang or guest memory source missing')
    output=ROOT/'build'/'android-native-check'; output.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-Wall','-Wextra','-Werror','-c',str(source),'-o',str(output/'guest_memory.o')]
    return _run_job(argv,60,'android-native-check',cfg,max_processes=1,memory_mb=384)

def build_android_native_diagnostics():
    """Build only the diagnostic JNI library with the installed NDK."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536: raise WorkSafeError('insufficient available RAM for native link')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'
    if not clang.is_file(): raise WorkSafeError('NDK clang missing')
    output=ROOT/'build'/'android-native-check';output.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-fPIC','-shared','-Wall','-Wextra','-Werror','-Wl,--no-undefined','-I',str(ROOT/'runtime'),str(ROOT/'android/app/src/main/cpp/native_diagnostics.c'),str(ROOT/'runtime/guest_memory.c'),str(ROOT/'runtime/pe32_image.c'),str(ROOT/'runtime/pe32_imports.c'),str(ROOT/'runtime/pe32_import_plan.c'),'-o',str(output/'libmh_runtime.so')]
    built=_run_job(argv,60,'android-jni-build',cfg,max_processes=4,memory_mb=512)
    if built['returncode']!=0 or built['timed_out']: return {'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_android_native.py')],30,'android-jni-verify',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'verify':verified}

def check_android_cmake():
    """Configure and build the app's native CMake target with one worker."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536: raise WorkSafeError('insufficient available RAM for CMake')
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'
    ndk=sdk/'ndk'/'28.2.13676358'
    cmake=sdk/'cmake'/'3.22.1'/'bin'/'cmake.exe';ninja=sdk/'cmake'/'3.22.1'/'bin'/'ninja.exe'
    toolchain=ndk/'build'/'cmake'/'android.toolchain.cmake';output=ROOT/'build'/'android-cmake-check'
    if not all(p.is_file() for p in (cmake,ninja,toolchain)): raise WorkSafeError('CMake, Ninja or NDK toolchain missing')
    argv=[str(cmake),'-S',str(ROOT/'android/app/src/main/cpp'),'-B',str(output),'-G','Ninja',
          '-DCMAKE_MAKE_PROGRAM='+str(ninja),'-DCMAKE_TOOLCHAIN_FILE='+str(toolchain),
          '-DANDROID_ABI=arm64-v8a','-DANDROID_PLATFORM=android-29','-DCMAKE_BUILD_TYPE=Debug']
    configured=_run_job(argv,60,'android-cmake-configure',cfg,max_processes=8,memory_mb=512)
    if configured['returncode']!=0 or configured['timed_out']:return {'configure':configured,'build':None,'verify':None}
    if available_memory_mb()<1536:raise WorkSafeError('insufficient RAM for CMake build')
    built=_run_job([str(cmake),'--build',str(output),'--parallel','1'],60,'android-cmake-build',cfg,max_processes=8,memory_mb=512)
    if built['returncode']!=0 or built['timed_out']:return {'configure':configured,'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_android_native.py'),'--cmake'],30,'android-cmake-verify',cfg,max_processes=1,memory_mb=256)
    return {'configure':configured,'build':built,'verify':verified}

def test_jni_diagnostics_host():
    """Exercise JNI C entry points with a fake JNI table, using the PE as read-only data."""
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    game=ROOT/'Manhunt Collection'/'Manhunt'/'manhunt.exe'
    expected='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
    def sha():
        with game.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    if sha()!=expected:raise WorkSafeError('unexpected executable hash')
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk';ndk=sdk/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    jni=ndk/'sysroot'/'usr'/'include'/'jni.h'
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10';sdkver='10.0.26100.0';link=vs/'bin'/'Hostx64'/'x64'/'link.exe';cl=link.parent/'cl.exe'
    include=[vs/'include',kits/'Include'/sdkver/'ucrt',kits/'Include'/sdkver/'shared',kits/'Include'/sdkver/'um'];lib=[vs/'lib'/'x64',kits/'Lib'/sdkver/'ucrt'/'x64',kits/'Lib'/sdkver/'um'/'x64']
    if not all(p.is_file() for p in (cl,jni,link)) or not all(p.is_dir() for p in include+lib):raise WorkSafeError('host compiler, JNI header or SDK missing')
    out=ROOT/'build'/'jni-host-check';out.mkdir(parents=True,exist_ok=True)
    header=jni.read_text(encoding='utf-8');marker='#define JNIEXPORT  __attribute__ ((visibility ("default")))'
    if header.count(marker)!=1:raise WorkSafeError('unexpected JNI header visibility declaration')
    # Host-only test executable: visibility is irrelevant; signatures remain unchanged.
    (out/'jni.h').write_text(header.replace(marker,'#define JNIEXPORT'),encoding='utf-8')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,include));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(link.parent)+os.pathsep+env.get('PATH','')
    exe=out/'jni-test.exe';argv=[str(cl),'/nologo','/Od','/std:c11','/utf-8','/I',str(out),'/I',str(ROOT/'runtime'),'/Fo'+str(out/'jni-test.obj'),'/Fe'+str(exe),str(ROOT/'tests'/'test_jni_diagnostics.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'jni-host-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'test':None}
    if available_memory_mb()<1536:raise WorkSafeError('insufficient RAM for JNI host test')
    tested=_run_job([str(exe),str(game)],30,'jni-host-test',cfg,max_processes=1,memory_mb=256)
    if sha()!=expected:raise WorkSafeError('original executable hash changed during read-only test')
    return {'build':built,'test':tested}

def test_guest_memory_wasm():
    """Compile and run only the project's freestanding guest-memory test."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    free=available_memory_mb()
    if free < 1024: raise WorkSafeError(f'insufficient available RAM: {free} MiB')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'
    node=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'nodejs'/'node.exe'
    if not clang.is_file() or not node.is_file(): raise WorkSafeError('NDK clang or Node missing')
    output=ROOT/'build'/'wasm-test'; output.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=wasm32-unknown-unknown','-ffreestanding','-fno-builtin','-nostdlib','-std=c11','-Wall','-Wextra','-Werror','-DMH_NO_MAIN','-I',str(ROOT/'tests'/'wasm_include'),'-I',str(ROOT/'runtime'),str(ROOT/'runtime'/'guest_memory.c'),str(ROOT/'tests'/'test_guest_memory.c'),str(ROOT/'tests'/'wasm_memmove.c'),'-Wl,--no-entry','-Wl,--export=mh_memory_tests','-o',str(output/'guest_memory.wasm')]
    compiled=_run_job(argv,60,'guest-memory-wasm-build',cfg,max_processes=2,memory_mb=384)
    if compiled['returncode'] != 0 or compiled['timed_out']: return {'compile':compiled,'test':None}
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient memory to run WebAssembly test')
    tested=_run_job([str(node),str(ROOT/'tests'/'run_guest_memory_wasm.js')],30,'guest-memory-wasm-test',cfg,max_processes=1,memory_mb=256)
    return {'compile':compiled,'test':tested}

def test_pe_image_wasm():
    """Compile and run synthetic PE32 loader tests without a game executable."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe';node=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'nodejs'/'node.exe'
    if not clang.is_file() or not node.is_file():raise WorkSafeError('NDK clang or Node missing')
    output=ROOT/'build'/'wasm-test';output.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=wasm32-unknown-unknown','-ffreestanding','-fno-builtin','-nostdlib','-std=c11','-Wall','-Wextra','-Werror','-DMH_NO_MAIN','-DMH_TEST_IMPORT_REGISTRY','-I',str(ROOT/'tests'/'wasm_include'),'-I',str(ROOT/'runtime'),str(ROOT/'runtime'/'guest_memory.c'),str(ROOT/'runtime'/'pe32_image.c'),str(ROOT/'runtime'/'pe32_imports.c'),str(ROOT/'runtime'/'pe32_import_plan.c'),str(ROOT/'runtime'/'import_registry.c'),str(ROOT/'tests'/'test_pe_image.c'),str(ROOT/'tests'/'wasm_memmove.c'),'-Wl,--no-entry','-Wl,--export=mh_pe_tests','-o',str(output/'pe_image.wasm')]
    built=_run_job(argv,60,'pe-image-wasm-build',cfg,max_processes=2,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'test':None}
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for PE test')
    tested=_run_job([str(node),str(ROOT/'tests'/'run_pe_wasm.js')],30,'pe-image-wasm-test',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'test':tested}

def test_local_pe_mapping():
    """Map the known executable as data in a bounded WASM test; never execute it."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM for local PE mapping')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe';node=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'nodejs'/'node.exe'
    if not clang.is_file() or not node.is_file():raise WorkSafeError('NDK clang or Node missing')
    output=ROOT/'build'/'wasm-test';output.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=wasm32-unknown-unknown','-ffreestanding','-fno-builtin','-nostdlib','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'tests'/'wasm_include'),'-I',str(ROOT/'runtime'),str(ROOT/'runtime'/'guest_memory.c'),str(ROOT/'runtime'/'pe32_image.c'),str(ROOT/'runtime'/'pe32_imports.c'),str(ROOT/'runtime'/'pe32_import_plan.c'),str(ROOT/'tests'/'pe_real_wasm.c'),str(ROOT/'tests'/'wasm_memmove.c'),'-Wl,--no-entry','-Wl,--export=pe_source','-Wl,--export=pe_image','-Wl,--export=pe_capacity','-Wl,--export=pe_size','-Wl,--export=pe_entry','-Wl,--export=pe_map','-Wl,--export=pe_collect_imports','-Wl,--export=pe_import','-Wl,--export=pe_plan_missing','-Wl,--export-memory','-o',str(output/'pe_real.wasm')]
    built=_run_job(argv,60,'pe-real-wasm-build',cfg,max_processes=2,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'test':None}
    if available_memory_mb()<1536:raise WorkSafeError('insufficient RAM for local PE mapping')
    tested=_run_job([str(node),str(ROOT/'tests'/'run_pe_real_wasm.js')],30,'pe-real-wasm-test',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'test':tested}

def inspect_game_entrypoint():
    """Run the fixed bounded static analysis script; never execute the PE."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM for static analysis')
    script=ROOT/'tools'/'inspect_entrypoint.py'
    if not script.is_file(): raise WorkSafeError('entrypoint inspector missing')
    return _run_job([sys.executable,str(script)],30,'pcrecomp-entrypoint',cfg,max_processes=1,memory_mb=384)

def map_import_references():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'map_import_references.py')],30,'import-references',cfg,max_processes=1,memory_mb=384)

def inspect_tick_candidate():
    """Analyze fixed GetTickCount byte windows without executing the game."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/inspect_tick_candidate.py')],30,'tick-candidate-inspection',cfg,max_processes=1,memory_mb=384)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('static tick inspection failed; inspect logs')
    return result

def inspect_timegettime_candidates():
    """Analyze fixed multimedia timer call windows as read-only PE data."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/inspect_timegettime_candidates.py')],30,'timegettime-candidate-inspection',cfg,max_processes=1,memory_mb=384)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('static multimedia timer inspection failed')
    return result

def lift_time_candidate():
    """Lift one fixed bounded timer-related candidate; output remains private."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_candidate.py')],45,'time-candidate-lift',cfg,max_processes=1,memory_mb=384)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('timer candidate lift failed; inspect logs')
    return result

def probe_time_candidate_x86(mode='normal'):
    """Run one bounded isolated x86 routine with synthetic dependency stubs."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if mode not in ('normal','null-object','missing-timer','missing-virtual','null-virtual-object'):raise WorkSafeError('unknown timer reference mode')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    args=[] if mode=='normal' else ['--'+mode]
    result=_run_job([sys.executable,str(ROOT/'tools/probe_time_candidate_x86.py'),*args],45,'time-x86-reference-'+mode,cfg,max_processes=1,memory_mb=512)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('isolated time reference failed; inspect logs')
    return result

def inspect_time_dependencies():
    """Inspect fixed direct-dependency windows without executing the PE."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/inspect_time_dependencies.py')],30,'time-dependencies-inspect',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('time dependency inspection failed')
    return result

def inspect_time_unresolved_low_memory():
    """Stream the PE hash and decode fixed windows within a 128 MiB job."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for bounded static windows')
    result=_run_job([sys.executable,str(ROOT/'tools/inspect_time_unresolved.py')],30,'time-unresolved-low-memory',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('bounded static inspection failed; inspect logs')
    return result

def analyze_time_recorded_cfg_low_memory():
    """Walk four recorded instruction windows, with opaque callees and 64 MiB."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<256:raise WorkSafeError('insufficient RAM for recorded-window analysis')
    result=_run_job([sys.executable,str(ROOT/'tools/analyze_time_recorded_cfg.py')],15,'time-recorded-cfg',cfg,max_processes=1,memory_mb=64)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('recorded-window analysis failed')
    return result

def lift_time_free_wrapper_low_memory():
    """Lift four fixed instructions in a limited process, no image-wide analysis."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for tiny translation')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_free_wrapper.py')],30,'time-free-wrapper-lift',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('four-instruction translation failed; inspect logs')
    return result

def lift_time_loader_low_memory():
    """Lift only a fixed 584-byte candidate window, without image-wide analysis."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for bounded translation')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_loader_window.py')],30,'time-loader-window-lift',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('bounded loader translation failed; inspect logs')
    return result

def lift_time_loader_helpers_low_memory():
    """Translate three fixed tiny windows, within a 128 MiB job."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for bounded helpers')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_loader_helpers.py')],30,'time-loader-helpers-lift',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('helper translation failed; inspect logs')
    return result

def prepare_file_lifecycle_low_memory():
    """Translate and assemble three exact private lifecycle wrapper windows."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for lifecycle translation')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_file_lifecycle.py')],30,'file-lifecycle-lift',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('lifecycle translation failed; inspect logs')
    folder=ROOT/'private/analysis/candidate_time/dependencies';report=json.loads((folder/'file_lifecycle_report.json').read_text());parts=[]
    if [i['address'] for i in report['items']]!=['0x60feb0','0x60fec0','0x60ff40']:raise WorkSafeError('unexpected lifecycle set')
    for item in report['items']:
        if item['source'] not in ('dep_0060feb0_precise.c','dep_0060fec0_precise.c','dep_0060ff40_precise.c'):raise WorkSafeError('unexpected lifecycle filename')
        source=(folder/item['source']).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(source.encode()).hexdigest()!=item['adapted_sha256']:raise WorkSafeError('lifecycle source changed')
        parts.append(source)
    (folder/'file_lifecycle_unit.c').write_text('\n'.join(parts)+'\n',encoding='utf-8');return result

def compile_time_loader_low_memory():
    """Compile just the bounded 180-instruction candidate, never link or run it."""
    import hashlib,struct
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for bounded object compilation')
    folder=ROOT/'private/analysis/candidate_time/dependencies'
    report=json.loads((folder/'loader_report.json').read_text());source=(folder/'dep_00605750_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x605750' or hashlib.sha256(source.encode()).hexdigest()!=report['adapted_sha256']:raise WorkSafeError('bounded candidate source changed')
    unit=folder/'loader_checked_unit.c';unit.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    output=folder/'loader-checked-arm64.o'
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(unit),'-o',str(output)]
    result=_run_job(argv,30,'time-loader-window-compile',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('bounded candidate compilation failed')
    data=output.read_bytes()
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<HH',data,16)!=(1,183):raise WorkSafeError('unexpected ARM64 relocatable object format')
    (folder/'loader_object_report.json').write_text(json.dumps({'architecture':'AArch64','format':'ELF64 relocatable','sha256':hashlib.sha256(data).hexdigest(),
        'source_sha256':report['adapted_sha256'],'size':len(data),'limitations':['not linked','not executed','nine direct callees unresolved','not integrated in harness or game']},indent=2)+'\n',encoding='utf-8')
    return result

def compile_time_free_wrapper_low_memory():
    """Compile only the four-instruction private wrapper, within 128 MiB."""
    import hashlib,re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for tiny wrapper compilation')
    folder=ROOT/'private/analysis/candidate_time/dependencies'
    report=json.loads((folder/'free_wrapper_report.json').read_text())
    source=(folder/'dep_00401030_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x401030' or hashlib.sha256(source.encode()).hexdigest()!=report['adapted_sha256']:raise WorkSafeError('free wrapper source hash mismatch')
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset({'MEM32','PUSH32','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported wrapper operations')
    unit=folder/'free_wrapper_unit.c'
    unit.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(unit),'-o',str(folder/'free-wrapper-arm64.o')]
    result=_run_job(argv,30,'time-free-wrapper-compile',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('tiny wrapper compilation failed')
    return result

def test_time_free_wrapper_low_memory():
    """Build and run sixteen tiny cases with a synthetic allocator callee."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<768:raise WorkSafeError('insufficient RAM for tiny host test')
    compile_time_free_wrapper_low_memory()
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio/18/Community/VC/Tools/MSVC/14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits/10';version='10.0.26100.0'
    cl=vs/'bin/Hostx64/x64/cl.exe';inc=[vs/'include',kits/'Include'/version/'ucrt',kits/'Include'/version/'shared',kits/'Include'/version/'um']
    lib=[vs/'lib/x64',kits/'Lib'/version/'ucrt/x64',kits/'Lib'/version/'um/x64']
    if not cl.is_file() or not all(p.is_dir() for p in inc+lib):raise WorkSafeError('host compiler or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,inc));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    folder=ROOT/'private/analysis/candidate_time/dependencies';exe=folder/'free-wrapper-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime'),'/I',str(folder),'/Fo'+str(folder/'free-wrapper-test.obj'),'/Fe'+str(exe),str(ROOT/'tests/time_free_wrapper_native.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,30,'time-free-wrapper-host-build',cfg,max_processes=4,memory_mb=256,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('tiny host compilation failed')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for tiny execution')
    result=_run_job([str(exe)],15,'time-free-wrapper-host-test',cfg,max_processes=1,memory_mb=64)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('isolated wrapper test failed')
    return result

def test_time_loader_helpers_low_memory():
    """Compile three tiny private helpers for ARM64 and test with mocked I/O."""
    import hashlib,struct
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<768:raise WorkSafeError('insufficient RAM for small helper tests')
    folder=ROOT/'private/analysis/candidate_time/dependencies';report=json.loads((folder/'loader_helpers_report.json').read_text())
    if {i['address'] for i in report['items']}!={'0x605e40','0x60fea0','0x60ff60'}:raise WorkSafeError('unexpected helper set')
    sources=[]
    for item in report['items']:
        if item['source'] not in ('dep_00605e40_precise.c','dep_0060fea0_precise.c','dep_0060ff60_precise.c'):raise WorkSafeError('unexpected helper source')
        source=(folder/item['source']).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(source.encode()).hexdigest()!=item['adapted_sha256']:raise WorkSafeError('helper source hash mismatch')
        sources.append(source)
    unit=folder/'loader_helpers_unit.c';unit.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'+'\n'.join(sources)+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    obj=folder/'loader-helpers-arm64.o';includes=[ROOT/'private/pcrecomp/runtime/recomp32',ROOT/'recomp',ROOT/'runtime']
    args=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11',*[a for p in includes for a in ('-I',str(p))],'-c',str(unit),'-o',str(obj)]
    built=_run_job(args,30,'loader-helpers-arm64-build',cfg,max_processes=1,memory_mb=128)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('helper ARM64 compilation failed')
    data=obj.read_bytes()
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<HH',data,16)!=(1,183):raise WorkSafeError('unexpected helper object format')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio/18/Community/VC/Tools/MSVC/14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits/10';v='10.0.26100.0';cl=vs/'bin/Hostx64/x64/cl.exe'
    inc=[vs/'include',kits/'Include'/v/'ucrt',kits/'Include'/v/'shared',kits/'Include'/v/'um'];lib=[vs/'lib/x64',kits/'Lib'/v/'ucrt/x64',kits/'Lib'/v/'um/x64']
    if not cl.is_file() or not all(p.is_dir() for p in inc+lib):raise WorkSafeError('host compiler or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,inc));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    exe=folder/'loader-helpers-test.exe'
    args=[str(cl),'/nologo','/Od','/std:c11',*[a for p in includes+[folder] for a in ('/I',str(p))],'/Fo'+str(folder/'loader-helpers-test.obj'),'/Fe'+str(exe),str(ROOT/'tests/time_loader_helpers_native.c'),'/link','/INCREMENTAL:NO']
    host=_run_job(args,30,'loader-helpers-host-build',cfg,max_processes=4,memory_mb=256,env=env)
    if host['returncode']!=0 or host['timed_out']:raise WorkSafeError('helper host compilation failed')
    tests={}
    for mode,expected in (('normal',0),('missing-readfile',74),('bad-object',70)):
        if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for helper execution')
        result=_run_job([str(exe),*([] if mode=='normal' else ['--'+mode])],15,'loader-helpers-'+mode,cfg,max_processes=1,memory_mb=64)
        if result['returncode']!=expected or result['timed_out']:raise WorkSafeError('helper test failed: '+mode)
        tests[mode]=result
    return {'arm64':built,'host':host,'tests':tests}

def run_time_loader_helpers_s25():
    """Build the tiny helper harness, verify, run and clean only its own file."""
    import base64,hashlib,re,secrets,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for helper ARM64 link')
    folder=ROOT/'private/analysis/candidate_time/dependencies';entry=ROOT/'tests/time_loader_helpers_native.c'
    sources=_time_harness_input_hashes(entry)
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    clang=ndk/'bin/clang.exe';adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    if not clang.is_file() or not adb.is_file():raise WorkSafeError('Android tools missing')
    binary_path=folder/'loader-helpers-device-test'
    args=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie',
          '-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-I',str(folder),str(entry),'-o',str(binary_path)]
    built=_run_job(args,60,'loader-helpers-device-build',cfg,max_processes=4,memory_mb=256)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('helper device build failed')
    if sources!=_time_harness_input_hashes(entry):raise WorkSafeError('helper sources changed during compilation')
    payload=binary_path.read_bytes()
    if len(payload)>1024*1024 or payload[:6]!=b'\x7fELF\x02\x01' or payload[16:20]!=b'\x03\x00\xb7\x00':raise WorkSafeError('unexpected helper device binary')
    digest=hashlib.sha256(payload).hexdigest()
    manifest={'sha256':digest,'source_inputs':sources,'scope':'private translated helpers, synthetic ReadFile; no game launch'}
    (folder/'loader_helpers_device_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    listing=_run_job([str(adb),'devices','-l'],15,'loader-helpers-device-list',cfg,max_processes=4,memory_mb=128)
    if listing['returncode']!=0 or listing['timed_out']:raise WorkSafeError('helper device listing failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8);encoded='\n'.join(textwrap.wrap(base64.b64encode(payload).decode('ascii'),76))
    script=('model=$(getprop ro.product.model)\ncase "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 80;; esac\n'
            'case ",$(getprop ro.product.cpu.abilist)," in *,arm64-v8a,*) ;; *) exit 81;; esac\n'
            'printf "MHAE_MODEL=%s\\n" "$model"\n'+f'd={remote}\np="$d/loader_helpers"\n'+
            'mkdir "$d" || exit 82\nfinish() { rc=$?; trap - EXIT; if rm -f "$p" && rmdir "$d"; then echo MHAE_CLEANUP_OK; else rc=91; fi; exit "$rc"; }\ntrap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
            'base64 -d > "$p" <<\'MHAE_PAYLOAD\'\n'+encoded+'\nMHAE_PAYLOAD\n'
            'set -- $(sha256sum "$p")\n'+f'[ "${{1:-}}" = "{digest}" ] || exit 83\n'+
            'chmod 700 "$p" || exit 84\n"$p" || exit 85\n'
            '"$p" --missing-readfile; rc=$?\n[ "$rc" -eq 74 ] || exit 86\n'
            '"$p" --bad-object; rc=$?\n[ "$rc" -eq 70 ] || exit 87\necho MHAE_TESTS_PASSED\n').encode('ascii')
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git/bin/sh.exe'
    if not shell.is_file():raise WorkSafeError('Git shell missing for syntax check')
    syntax=_run_job([str(shell),'-n'],15,'loader-helpers-device-shell-check',cfg,max_processes=2,memory_mb=128,input_bytes=script)
    if syntax['returncode']!=0 or syntax['timed_out']:raise WorkSafeError('helper device script syntax failed')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM before helper device session')
    attempt=ROOT/'logs/loader-helpers-device-attempt.json'
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'})+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],60,'loader-helpers-device-session',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace');cleaned='MHAE_CLEANUP_OK' in output
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'confirmed' if cleaned else 'unconfirmed'})+'\n',encoding='utf-8')
    if result['returncode']!=0 or result['timed_out'] or not cleaned or 'MHAE_TESTS_PASSED' not in output:raise WorkSafeError('helper device tests failed or cleanup unconfirmed')
    if sources!=_time_harness_input_hashes(entry):raise WorkSafeError('helper source changed during device tests; review evidence')
    return {'sha256':digest,'tests':'64 helper checks, missing ReadFile and bad object passed','cleanup':'confirmed','scope':'ReadFile simulated; game unavailable'}

def run_real_readonly_stream_s25(with_handles=False,build_only=False):
    """Read only a private fixture and the known copied PE through the wrapper."""
    import base64,hashlib,re,secrets,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not isinstance(with_handles,bool) or not isinstance(build_only,bool):raise WorkSafeError('invalid read-only test profile')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for read-only stream test')
    if with_handles:prepare_file_lifecycle_low_memory()
    folder=ROOT/'private/analysis/candidate_time/dependencies';entry=ROOT/('tests/time_file_handles_native.c' if with_handles else 'tests/time_readonly_stream_native.c')
    label='readonly-handles' if with_handles else 'readonly-stream'
    report=json.loads((folder/'loader_helpers_report.json').read_text());parts=[]
    if [x['address'] for x in report['items']]!=['0x605e40','0x60fea0','0x60ff60']:raise WorkSafeError('unexpected helper set')
    for item in report['items']:
        if item['source'] not in ('dep_00605e40_precise.c','dep_0060fea0_precise.c','dep_0060ff60_precise.c'):raise WorkSafeError('unexpected helper filename')
        content=(folder/item['source']).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(content.encode()).hexdigest()!=item['adapted_sha256']:raise WorkSafeError('helper source changed')
        parts.append(content)
    expected='#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'+'\n'.join(parts)+'\n'
    if (folder/'loader_helpers_unit.c').read_text(encoding='utf-8')!=expected:raise WorkSafeError('helper unit changed; rebuild helpers first')
    sources=_time_harness_input_hashes(entry)
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    clang=ndk/'bin/clang.exe';adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    if not clang.is_file() or not adb.is_file():raise WorkSafeError('Android tools missing')
    binary_path=folder/(label+'-device-test')
    args=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie','-Wall','-Wextra',
          '-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-I',str(folder),str(entry),'-o',str(binary_path)]
    built=_run_job(args,60,label+'-device-build',cfg,max_processes=4,memory_mb=256)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('read-only stream compilation failed; inspect logs')
    if sources!=_time_harness_input_hashes(entry):raise WorkSafeError('read-only stream sources changed while compiling')
    payload=binary_path.read_bytes()
    if len(payload)>1024*1024 or payload[:6]!=b'\x7fELF\x02\x01' or payload[16:20]!=b'\x03\x00\xb7\x00':raise WorkSafeError('unexpected test binary')
    digest=hashlib.sha256(payload).hexdigest();fixture=b'0123456789abcdefghijklmnopqrstuv';fixture_hash=hashlib.sha256(fixture).hexdigest()
    if build_only:return {'build':built,'sha256':digest,'source_inputs':sources,'device_execution':'not requested'}
    game_hash='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
    listing=_run_job([str(adb),'devices','-l'],15,label+'-device-list',cfg,max_processes=4,memory_mb=128)
    if listing['returncode']!=0 or listing['timed_out']:raise WorkSafeError('device listing failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8);encoded='\n'.join(textwrap.wrap(base64.b64encode(payload).decode('ascii'),76))
    cleanup=('rm -f "$p" "$f" "$d/nested/data" "$d/link" "$d/linked" "$d/pipe" && { [ ! -d "$d/nested" ] || rmdir "$d/nested"; } && rmdir "$d"' if with_handles else 'rm -f "$p" "$f" && rmdir "$d"')
    prepare=('mkdir "$d/nested" && cat "$f" > "$d/nested/data" && ln -s fixture "$d/link" && ln -s nested "$d/linked" || exit 90\nif ! mkfifo "$d/pipe"; then echo MHAE_FIFO_UNAVAILABLE; fi\n' if with_handles else '')
    invoke='"$p" "$d" || exit 87\n' if with_handles else '"$p" "$f" || exit 87\n'
    nested_check=('set -- $(sha256sum "$d/nested/data")\n'+f'[ "${{1:-}}" = "{fixture_hash}" ] || exit 88\n') if with_handles else ''
    script=('model=$(getprop ro.product.model)\ncase "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 80;; esac\n'
            'case ",$(getprop ro.product.cpu.abilist)," in *,arm64-v8a,*) ;; *) exit 81;; esac\n'
            'game=/sdcard/mh-androidevolved/manhunt.exe\nset -- $(sha256sum "$game")\n'+f'[ "${{1:-}}" = "{game_hash}" ] || exit 82\n'+
            'printf "MHAE_MODEL=%s\\n" "$model"\n'+f'd={remote}\np="$d/read_test"\nf="$d/fixture"\n'+
            'mkdir "$d" || exit 83\nfinish() { rc=$?; trap - EXIT; if '+cleanup+'; then echo MHAE_CLEANUP_OK; else rc=91; fi; exit "$rc"; }\ntrap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
            'base64 -d > "$p" <<\'MHAE_PAYLOAD\'\n'+encoded+'\nMHAE_PAYLOAD\n'
            'set -- $(sha256sum "$p")\n'+f'[ "${{1:-}}" = "{digest}" ] || exit 84\n'+
            f'printf %s {base64.b64encode(fixture).decode("ascii")} | base64 -d > "$f"\n'+
            'set -- $(sha256sum "$f")\n'+f'[ "${{1:-}}" = "{fixture_hash}" ] || exit 85\n'+
            prepare+'chmod 700 "$p" || exit 86\n'+invoke+nested_check+
            'set -- $(sha256sum "$f")\n'+f'[ "${{1:-}}" = "{fixture_hash}" ] || exit 88\n'+
            'set -- $(sha256sum "$game")\n'+f'[ "${{1:-}}" = "{game_hash}" ] || exit 89\n'+
            'echo MHAE_SOURCES_UNCHANGED\necho MHAE_TESTS_PASSED\n').encode('ascii')
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git/bin/sh.exe'
    if not shell.is_file():raise WorkSafeError('Git shell missing')
    checked=_run_job([str(shell),'-n'],15,label+'-shell-check',cfg,max_processes=2,memory_mb=128,input_bytes=script)
    if checked['returncode']!=0 or checked['timed_out']:raise WorkSafeError('read-only device script syntax failed')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM before device read-only test')
    attempt=ROOT/'logs'/(label+'-device-attempt.json');attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'})+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],60,label+'-device-session',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace');cleaned='MHAE_CLEANUP_OK' in output
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'confirmed' if cleaned else 'unconfirmed'})+'\n',encoding='utf-8')
    if result['returncode']!=0 or result['timed_out'] or not cleaned or 'MHAE_TESTS_PASSED' not in output:raise WorkSafeError('real read-only stream device test failed; inspect logs')
    if sources!=_time_harness_input_hashes(entry):raise WorkSafeError('read-only stream source changed during test')
    evidence={'sha256':digest,'source_inputs':sources,'game_sha256_before_after':game_hash,'fixture_sha256_before_after':fixture_hash,
              'tests':'real relative opens and handle reads passed' if with_handles else 'real file reads through translated wrapper passed','cleanup':'confirmed',
              'scope':'rooted read-only paths and generation handles; no game execution' if with_handles else 'read-only subset, one test handle; no game execution'}
    evidence['skipped']=['FIFO fixture blocked by device policy'] if 'MHAE_FIFO_UNAVAILABLE' in output else []
    (folder/('readonly_handles_device_report.json' if with_handles else 'readonly_stream_device_report.json')).write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8');return evidence

def check_readonly_stream_arm64(component='stream'):
    """Compile the own-code backend alone with strict warnings and low memory."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if component not in ('stream','handles','path'):raise WorkSafeError('unknown read-only component')
    if available_memory_mb()<512:raise WorkSafeError('insufficient RAM for backend compilation')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    clang=ndk/'bin/clang.exe';out=ROOT/'build/android-native-check';out.mkdir(parents=True,exist_ok=True)
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    args=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),'-c',str(ROOT/'runtime'/('readonly_'+component+'.c')),'-o',str(out/('readonly_'+component+'.o'))]
    result=_run_job(args,30,'readonly-'+component+'-strict-compile',cfg,max_processes=1,memory_mb=128)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('backend strict compilation failed; inspect logs')
    return result

def test_readonly_path_host():
    """Compile and exercise path normalization without device or file access."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<768:raise WorkSafeError('insufficient RAM for path tests')
    out=ROOT/'build/readonly-path-check';out.mkdir(parents=True,exist_ok=True)
    unit=out/'path_test_unit.c';unit.write_text('#include "'+(ROOT/'runtime/readonly_path.c').as_posix()+'"\n#include "'+(ROOT/'tests/test_readonly_path.c').as_posix()+'"\n',encoding='utf-8')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio/18/Community/VC/Tools/MSVC/14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits/10';v='10.0.26100.0';cl=vs/'bin/Hostx64/x64/cl.exe'
    inc=[vs/'include',kits/'Include'/v/'ucrt',kits/'Include'/v/'shared',kits/'Include'/v/'um'];lib=[vs/'lib/x64',kits/'Lib'/v/'ucrt/x64',kits/'Lib'/v/'um/x64']
    if not cl.is_file() or not all(p.is_dir() for p in inc+lib):raise WorkSafeError('host compiler or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,inc));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    exe=out/'readonly-path-test.exe'
    args=[str(cl),'/nologo','/Od','/std:c11','/I',str(ROOT/'runtime'),'/Fo'+str(out/'test.obj'),'/Fe'+str(exe),str(unit),'/link','/INCREMENTAL:NO']
    built=_run_job(args,30,'readonly-path-host-build',cfg,max_processes=4,memory_mb=256,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('path tests compilation failed')
    result=_run_job([str(exe)],15,'readonly-path-host-test',cfg,max_processes=1,memory_mb=64)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('path tests failed')
    return result

def lift_time_dependencies():
    """Lift only three fixed, statically checked tiny dependencies."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_dependencies.py')],45,'time-dependencies-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('time dependency lift failed; inspect logs')
    return result

def lift_time_copy_dependency():
    """Lift one fixed bounded structure-copy candidate without running it."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_copy_dependency.py')],45,'time-copy-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('copy candidate lift failed; inspect logs')
    return result

def lift_time_inner_dependency():
    """Lift the fixed three-instruction structure setter as private C."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_inner_dependency.py')],30,'time-inner-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('structure setter lift failed')
    return result

def lift_time_branch_dependency():
    """Lift the fixed nine-instruction mode dispatcher 0x5daa20 as private C."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_branch_dependency.py')],45,'time-branch-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('mode dispatcher lift failed')
    return result

def lift_time_memcpy_dependency():
    """Lift 0x481340 and its copy routine 0x611640 as private C with checked rep movs."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_memcpy_dependency.py')],45,'time-memcpy-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('buffer copy dependency lift failed')
    return result

def lift_time_stack_probe():
    """Lift the fixed aligned stack probe 0x648540 as private C."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_stack_probe.py')],45,'time-stack-probe-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('stack probe lift failed')
    return result

def lift_time_x87_dependency():
    """Lift 0x5daa50 (x87) and the getter 0x5ea2b0 as private C with audited rewrites."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_x87_dependency.py')],45,'time-x87-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('x87 dependency lift failed')
    return result

def lift_time_indirect_dependency():
    """Lift one bounded indirect-call candidate without executing it."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/lift_time_indirect_dependency.py')],45,'time-indirect-lift',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('indirect candidate lift failed')
    return result

def prepare_time_indirect_precise():
    """Validate six calls and prepare a checked private indirect candidate."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/prepare_time_indirect_precise.py')],30,'time-indirect-precise',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('indirect call preparation failed; inspect logs')
    return result

def compile_checked_time_indirect():
    """Compile one adapted indirect dependency with checked memory and calls."""
    import hashlib,re,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    prepared=prepare_time_indirect_precise();folder=ROOT/'private/analysis/candidate_time/dependencies'
    report=json.loads((folder/'indirect_precise_report.json').read_text())
    source=(folder/'dep_00604dc0_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(source.encode()).hexdigest()!=report['adapted_sha256']:raise WorkSafeError('indirect source hash mismatch')
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset({'MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported indirect operations: '+str(sorted(operations)))
    unit=folder/'indirect_checked_unit.c'
    unit.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_00401030(void);\nvoid sub_004932F0(void);\nvoid sub_00493230(void);\n'+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(unit),'-o',str(folder/'indirect-checked-arm64.o')]
    built=_run_job(argv,60,'time-indirect-checked-build',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('checked indirect compilation failed')
    verification=_run_job([sys.executable,str(ROOT/'tools/verify_graphics_object.py'),'--time-indirect'],30,'time-indirect-object-verify',cfg,max_processes=1,memory_mb=256)
    if verification['returncode']!=0 or verification['timed_out']:raise WorkSafeError('indirect object verification failed')
    return {'prepare':prepared,'build':built,'verification':verification}

def prepare_time_copy_precise():
    """Validate and adapt exactly two calls in the private copy dependency."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/prepare_time_copy_precise.py')],30,'time-copy-precise',cfg,max_processes=1,memory_mb=384)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('copy call preparation failed')
    return result

def _check_time_harness_sources(base):
    """Verify hashes of every private translated source the time harness includes."""
    import hashlib
    wrapper_report=json.loads((base/'dependencies/free_wrapper_report.json').read_text())
    wrapper=(base/'dependencies/dep_00401030_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if wrapper_report['address']!='0x401030' or hashlib.sha256(wrapper.encode()).hexdigest()!=wrapper_report['adapted_sha256']:raise WorkSafeError('wrapper source hash mismatch')
    dep_report=json.loads((base/'dependencies/report.json').read_text())
    if {x['address'] for x in dep_report['items']}!={'0x426ef0','0x481330','0x608410'}:raise WorkSafeError('unexpected dependency set')
    for item in dep_report['items']:
        name=item['source']
        if name not in ('dep_00426ef0.c','dep_00481330.c','dep_00608410.c'):raise WorkSafeError('unexpected dependency filename')
        content=(base/'dependencies'/name).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(content.encode()).hexdigest()!=item['sha256']:raise WorkSafeError('dependency source hash mismatch')
    copy_report=json.loads((base/'dependencies/copy_precise_report.json').read_text())
    copy_source=(base/'dependencies/dep_00604d20_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(copy_source.encode()).hexdigest()!=copy_report['adapted_sha256']:raise WorkSafeError('copy source hash mismatch')
    inner_report=json.loads((base/'dependencies/inner_report.json').read_text())
    inner_source=(base/'dependencies/dep_00604f30.c').read_text(encoding='utf-8').removesuffix('\n')
    if inner_report['address']!='0x604f30' or hashlib.sha256(inner_source.encode()).hexdigest()!=inner_report['source_sha256']:raise WorkSafeError('inner setter source hash mismatch')
    indirect_report=json.loads((base/'dependencies/indirect_precise_report.json').read_text())
    indirect_source=(base/'dependencies/dep_00604dc0_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(indirect_source.encode()).hexdigest()!=indirect_report['adapted_sha256']:raise WorkSafeError('indirect source hash mismatch')
    branch_report=json.loads((base/'dependencies/branch_report.json').read_text())
    branch_source=(base/'dependencies/dep_005daa20_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if branch_report['address']!='0x5daa20' or hashlib.sha256(branch_source.encode()).hexdigest()!=branch_report['adapted_sha256']:raise WorkSafeError('dispatcher source hash mismatch')
    memcpy_report=json.loads((base/'dependencies/memcpy_report.json').read_text())
    if [x['address'] for x in memcpy_report['items']]!=['0x481340','0x611640']:raise WorkSafeError('unexpected buffer copy dependency set')
    for item in memcpy_report['items']:
        if item['source'] not in ('dep_00481340_precise.c','dep_00611640_precise.c'):raise WorkSafeError('unexpected buffer copy filename')
        content=(base/'dependencies'/item['source']).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(content.encode()).hexdigest()!=item['adapted_sha256']:raise WorkSafeError('buffer copy source hash mismatch')
    probe_report=json.loads((base/'dependencies/stack_probe_report.json').read_text())
    probe_source=(base/'dependencies/dep_00648540.c').read_text(encoding='utf-8').removesuffix('\n')
    if probe_report['address']!='0x648540' or hashlib.sha256(probe_source.encode()).hexdigest()!=probe_report['source_sha256']:raise WorkSafeError('stack probe source hash mismatch')
    x87_report=json.loads((base/'dependencies/x87_report.json').read_text())
    if [x['address'] for x in x87_report['items']]!=['0x5daa50','0x5ea2b0']:raise WorkSafeError('unexpected x87 dependency set')
    for item in x87_report['items']:
        if item['source'] not in ('dep_005daa50_precise.c','dep_005ea2b0_precise.c'):raise WorkSafeError('unexpected x87 filename')
        content=(base/'dependencies'/item['source']).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(content.encode()).hexdigest()!=item['adapted_sha256']:raise WorkSafeError('x87 source hash mismatch')

def compare_time_candidate_native():
    """Compile an isolated private C candidate with test doubles and compare it."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    prepared=compile_checked_time_candidate();copy_prepared=prepare_time_copy_precise();indirect_prepared=prepare_time_indirect_precise();lift_time_branch_dependency();lift_time_memcpy_dependency();lift_time_stack_probe();lift_time_x87_dependency()
    lift_time_free_wrapper_low_memory()
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio/18/Community/VC/Tools/MSVC/14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits/10';version='10.0.26100.0'
    cl=vs/'bin/Hostx64/x64/cl.exe';inc=[vs/'include',kits/'Include'/version/'ucrt',kits/'Include'/version/'shared',kits/'Include'/version/'um']
    lib=[vs/'lib/x64',kits/'Lib'/version/'ucrt/x64',kits/'Lib'/version/'um/x64']
    if not cl.is_file() or not all(x.is_dir() for x in inc+lib):raise WorkSafeError('host compiler or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,inc));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    base=ROOT/'private/analysis/candidate_time';exe=base/'short-test.exe'
    _check_time_harness_sources(base)
    argv=[str(cl),'/nologo','/Od','/std:c11','/DMH_REAL_SMALL_DEPS','/I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime'),'/I',str(base),'/Fo'+str(base/'short-test.obj'),'/Fe'+str(exe),str(ROOT/'tests/time_candidate_native.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'time-native-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('time native test build failed')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    ran=_run_job([str(exe)],30,'time-native-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('time native test failed')
    compared=_run_job([sys.executable,str(ROOT/'tests/compare_time_native.py')],30,'time-native-compare',cfg,max_processes=1,memory_mb=256)
    if compared['returncode']!=0 or compared['timed_out']:raise WorkSafeError('time comparison mismatch; inspect logs')
    fault_results={}
    for mode,expected in (('null-object',70),('missing-timer',74),('missing-virtual',75),('null-virtual-object',71)):
        reference=probe_time_candidate_x86(mode)
        if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
        fault=_run_job([str(exe),'--'+mode],30,'time-native-'+mode,cfg,max_processes=1,memory_mb=256)
        if fault['timed_out'] or fault['returncode']!=expected:raise WorkSafeError('time fault test mismatch: '+mode)
        fault_results[mode]={'reference':reference,'native':fault}
    return {'prepare':prepared,'copy_prepare':copy_prepared,'indirect_prepare':indirect_prepared,'build':built,'run':ran,'comparison':compared,'faults':fault_results}

def compare_time_indirect_zero():
    """Compare the isolated zero-argument virtual branch with synthetic methods."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    prior=compare_time_candidate_native()
    ref=_run_job([sys.executable,str(ROOT/'tools/probe_time_indirect_zero_x86.py')],30,'time-indirect-zero-x86',cfg,max_processes=1,memory_mb=512)
    if ref['returncode']!=0 or ref['timed_out']:raise WorkSafeError('zero-argument x86 reference failed')
    exe=ROOT/'private/analysis/candidate_time/short-test.exe'
    native=_run_job([str(exe),'--virtual-zero'],30,'time-indirect-zero-native',cfg,max_processes=1,memory_mb=256)
    if native['returncode']!=0 or native['timed_out']:raise WorkSafeError('zero-argument native test failed')
    compare=_run_job([sys.executable,str(ROOT/'tests/compare_time_indirect_zero.py')],30,'time-indirect-zero-compare',cfg,max_processes=1,memory_mb=256)
    if compare['returncode']!=0 or compare['timed_out']:raise WorkSafeError('zero-argument comparison mismatch')
    return {'prior':prior,'x86':ref,'native':native,'comparison':compare}

def _time_arm64_paths():
    base=ROOT/'private/analysis/candidate_time';return base,base/'android'/'time_test'

def _time_harness_input_hashes(entry=None, include_dirs=()):
    """Hash the workspace-local quoted-include graph, including inactive arms.

    This is conservative: changing an unused local include also requires a
    rebuild. SDK system headers and compiler identity are not covered here.
    """
    import hashlib,re
    root=ROOT.resolve();base=root/'private/analysis/candidate_time'
    search=[root/'private/pcrecomp/runtime/recomp32',root/'recomp',root/'runtime',base,base/'dependencies',*include_dirs]
    pending=[root/'tests/time_candidate_native.c' if entry is None else Path(entry)];seen={}
    while pending:
        path=pending.pop().resolve()
        if not path.is_relative_to(root):raise WorkSafeError('time harness include outside workspace')
        name=path.relative_to(root).as_posix()
        if name in seen:continue
        if len(seen)>=256 or not path.is_file():raise WorkSafeError('time harness include graph invalid')
        data=path.read_bytes();seen[name]=hashlib.sha256(data).hexdigest()
        for include in re.findall(r'^\s*#\s*include\s*"([^"\r\n]+)"',data.decode('utf-8'),re.MULTILINE):
            candidates=[path.parent/include,*[directory/include for directory in search]]
            found=next((p for p in candidates if p.is_file()),None)
            if found is None:raise WorkSafeError('local time harness include missing: '+include)
            pending.append(found)
    return dict(sorted(seen.items()))

def build_time_candidate_arm64_test():
    """Cross-compile the isolated time harness and six translated dependencies.

    The binary contains game-derived translated code, so it stays in private/.
    """
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    prepared=compile_checked_time_candidate();copy_prepared=prepare_time_copy_precise();indirect_prepared=prepare_time_indirect_precise();lift_time_branch_dependency();lift_time_memcpy_dependency();lift_time_stack_probe();lift_time_x87_dependency()
    lift_time_free_wrapper_low_memory()
    base,out=_time_arm64_paths();_check_time_harness_sources(base)
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    out.parent.mkdir(parents=True,exist_ok=True)
    source_inputs=_time_harness_input_hashes()
    if available_memory_mb()<1536:raise WorkSafeError('insufficient RAM for ARM64 time harness compilation')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie','-DMH_REAL_SMALL_DEPS',
          '-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-I',str(base),
          str(ROOT/'tests/time_candidate_native.c'),'-o',str(out)]
    built=_run_job(argv,120,'time-arm64-build',cfg,max_processes=4,memory_mb=512)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'manifest':None}
    if _time_harness_input_hashes()!=source_inputs:raise WorkSafeError('time harness inputs changed during compilation; rebuild required')
    data=out.read_bytes()
    # ELF64, little-endian, ET_DYN (PIE), EM_AARCH64.
    if data[:4]!=b'\x7fELF' or data[4]!=2 or data[5]!=1 or int.from_bytes(data[16:18],'little')!=3 or int.from_bytes(data[18:20],'little')!=183:
        raise WorkSafeError('time harness is not an ARM64 PIE ELF')
    if len(data)>4*1024*1024:raise WorkSafeError('time harness larger than expected')
    manifest={'abi':'arm64-v8a','name':'time_test','sha256':hashlib.sha256(data).hexdigest(),'size':len(data),
              'harness_sha256':hashlib.sha256((ROOT/'tests/time_candidate_native.c').read_bytes()).hexdigest(),
              'source_inputs':source_inputs}
    (out.parent/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return {'prepare':prepared,'copy_prepare':copy_prepared,'indirect_prepare':indirect_prepared,'build':built,'manifest':manifest}

def _time_device_script(remote,digest,encoded):
    """Shell script for one bounded S25 session; exits non-zero on any mismatch."""
    faults=(('null-object',70),('missing-timer',74),('missing-virtual',75),('null-virtual-object',71))
    return (
        'model=$(getprop ro.product.model)\n'
        'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) echo MHAE_BAD_MODEL; exit 80;; esac\n'
        'abi=$(getprop ro.product.cpu.abilist)\n'
        'case ",$abi," in *,arm64-v8a,*) ;; *) echo MHAE_BAD_ABI; exit 81;; esac\n'
        'printf "MHAE_MODEL=%s\\n" "$model"\n'
        f'd={remote}\n'
        'p="$d/time_test"\n'
        'if ! mkdir "$d"; then echo MHAE_MKDIR_FAILED; exit 82; fi\n'
        'cleanup() { rm -f "$p" && rmdir "$d"; }\n'
        'finish() { rc=$?; trap - EXIT; if cleanup; then echo MHAE_CLEANUP_OK; else echo MHAE_CLEANUP_FAILED >&2; if [ "$rc" -eq 0 ]; then rc=91; fi; fi; exit "$rc"; }\n'
        'trap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
        "if ! base64 -d > \"$p\" <<'MHAE_PAYLOAD'\n"+encoded+'\nMHAE_PAYLOAD\n'
        'then echo MHAE_DECODE_FAILED; exit 83; fi\n'
        'set -- $(sha256sum "$p")\n'
        f'if [ "${{1:-}}" != "{digest}" ]; then echo MHAE_HASH_FAILED; exit 84; fi\n'
        'if ! chmod 700 "$p"; then echo MHAE_CHMOD_FAILED; exit 85; fi\n'
        'echo MHAE_BEGIN_MAIN\n"$p"; rc=$?\necho MHAE_END_MAIN\n'
        'if [ "$rc" -ne 0 ]; then echo MHAE_MAIN_FAILED; exit 86; fi\n'
        'echo MHAE_BEGIN_ZERO\n"$p" --virtual-zero; rc=$?\necho MHAE_END_ZERO\n'
        'if [ "$rc" -ne 0 ]; then echo MHAE_ZERO_FAILED; exit 87; fi\n'
        +''.join(f'"$p" --{mode} >/dev/null; rc=$?\nif [ "$rc" -ne {code} ]; then echo MHAE_FAULT_MISMATCH_{mode.replace("-","_")}=$rc; exit 88; fi\n' for mode,code in faults)+
        '"$p" --x87-semantics; rc=$?\nif [ "$rc" -ne 0 ]; then echo MHAE_X87_SEMANTICS_FAILED; exit 89; fi\n'
        'echo MHAE_TESTS_PASSED\nexit 0\n').encode('ascii')

def _split_time_device_output(output):
    """Return the MAIN and ZERO JSONL sections of a device session transcript."""
    import re
    output=output.replace('\r\n','\n');sections={}
    for name in ('MAIN','ZERO'):
        m=re.search(rf'^MHAE_BEGIN_{name}\n(.*?)^MHAE_END_{name}$',output,re.MULTILINE|re.DOTALL)
        if not m:raise WorkSafeError('missing '+name.lower()+' output section')
        sections[name]=m.group(1)
    return sections

def run_time_candidate_on_s25():
    """Run the private ARM64 time harness on one S25 in one bounded ADB shell.

    Uploads to a fresh random directory, verifies the hash, runs the 256 main
    cases, the 12 zero-argument cases and four expected faults, then removes
    exactly that file and directory. Outputs are compared on the PC against the
    stored Unicorn x86 references. No APK, game file or UI is touched.
    """
    import base64,hashlib,re,secrets,sys,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    base,binary_path=_time_arm64_paths()
    manifest=json.loads((binary_path.parent/'manifest.json').read_text(encoding='utf-8'))
    binary=binary_path.read_bytes();digest=hashlib.sha256(binary).hexdigest()
    if manifest.get('abi')!='arm64-v8a' or manifest.get('name')!='time_test' or digest!=manifest.get('sha256') or len(binary)>4*1024*1024:
        raise WorkSafeError('time harness manifest, hash or size mismatch')
    if hashlib.sha256((ROOT/'tests/time_candidate_native.c').read_bytes()).hexdigest()!=manifest.get('harness_sha256'):
        raise WorkSafeError('harness source changed since ARM64 build')
    if manifest.get('source_inputs')!=_time_harness_input_hashes():
        raise WorkSafeError('time harness inputs changed or unrecorded; rebuild before device upload')
    listing=_run_job([str(adb),'devices','-l'],15,'device-time-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('ADB device listing failed')
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    entries=[line.split() for line in text.splitlines()[1:] if line.strip()]
    ready=[parts[0] for parts in entries if len(parts)>=2 and parts[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    if available_memory_mb()<1024:raise WorkSafeError('memory pressure before device session')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    script=_time_device_script(remote,digest,'\n'.join(textwrap.wrap(base64.b64encode(binary).decode('ascii'),76)))
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git'/'bin'/'sh.exe'
    if not shell.is_file():raise WorkSafeError('Git shell missing for syntax-only validation')
    syntax=_run_job([str(shell),'-n'],15,'device-time-shell-check',cfg,max_processes=2,memory_mb=256,input_bytes=script)
    if syntax['timed_out'] or syntax['returncode']!=0:raise WorkSafeError('device script failed syntax check')
    attempt=ROOT/'logs'/'device-time-attempt.json';attempt.parent.mkdir(exist_ok=True)
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],120,'device-time-session',cfg,max_processes=4,memory_mb=512,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    cleanup='confirmed' if 'MHAE_CLEANUP_OK' in output else 'unconfirmed'
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':cleanup},indent=2)+'\n',encoding='utf-8')
    if result['timed_out'] or result['returncode']!=0 or cleanup!='confirmed' or 'MHAE_TESTS_PASSED' not in output:
        raise WorkSafeError('time harness session failed or cleanup unconfirmed; inspect device-time logs')
    paths={};output_hashes={}
    for name,body in _split_time_device_output(output).items():
        paths[name]=ROOT/'logs'/f'time-arm64-{name.lower()}.jsonl';paths[name].write_text(body,encoding='utf-8')
        output_hashes[name.lower()]=hashlib.sha256(body.encode('utf-8')).hexdigest()  # exact LF stdout bytes
    compared=_run_job([sys.executable,str(ROOT/'tests/compare_time_native.py'),str(paths['MAIN']),'android-arm64'],60,'time-arm64-compare',cfg,max_processes=1,memory_mb=512)
    zero=_run_job([sys.executable,str(ROOT/'tests/compare_time_indirect_zero.py'),str(paths['ZERO']),'android-arm64'],30,'time-arm64-zero-compare',cfg,max_processes=1,memory_mb=256)
    models=re.findall(r'^MHAE_MODEL=(\S+)\s*$',output,re.MULTILINE)
    passed=all(r['returncode']==0 and not r['timed_out'] for r in (compared,zero))
    record=binary_path.parent/'validated.json'
    if passed:
        # Lets the diagnostic APK check that in-app runs reproduce this S25-validated output.
        record.write_text(json.dumps({'binary_sha256':digest,'model':models[0] if len(models)==1 else None,
            'main_output_sha256':output_hashes['main'],'zero_output_sha256':output_hashes['zero'],
            'compared_against':'Unicorn x86 reference (tests/compare_time_native.py, tests/compare_time_indirect_zero.py)'},indent=2)+'\n',encoding='utf-8')
    elif record.is_file():record.unlink()
    return {'model':models[0] if len(models)==1 else None,'sha256':digest,'cleanup':cleanup,'faults':'matched',
            'comparison':compared,'zero_comparison':zero,'passed':passed}

def lift_game_candidate(x87=False):
    """Analyze an ordinary .text candidate; generated source remains private."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM for static analysis')
    if not isinstance(x87,bool): raise WorkSafeError('invalid x87 profile')
    argv=[sys.executable,str(ROOT/'tools'/'lift_candidate.py')]+(['--x87'] if x87 else [])
    return _run_job(argv,30,'pcrecomp-candidate-x87' if x87 else 'pcrecomp-candidate',cfg,max_processes=1,memory_mb=384)

def lift_graphics_candidate():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'lift_graphics_candidate.py')],30,'pcrecomp-graphics-candidate',cfg,max_processes=1,memory_mb=384)

def lift_input_candidate():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'lift_input_candidate.py')],30,'pcrecomp-input-candidate',cfg,max_processes=1,memory_mb=384)

def lift_d3d8_thunk():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'lift_d3d8_thunk.py')],30,'pcrecomp-d3d8-thunk',cfg,max_processes=1,memory_mb=384)

def lift_dinput8_thunk():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'lift_dinput8_thunk.py')],30,'pcrecomp-dinput8-thunk',cfg,max_processes=1,memory_mb=384)

def list_android_devices():
    """Read ADB device states only; never install, launch, or modify a device."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    return _run_job([str(adb),'devices','-l'],15,'android-devices',cfg,max_processes=4,memory_mb=256)

def build_android_device_tests():
    """Cross-compile only synthetic memory and PE tests for a future device run."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';clang=ndk/'bin'/'clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    out=ROOT/'build'/'device-tests';out.mkdir(parents=True,exist_ok=True)
    common=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-fPIE','-pie','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime')]
    specs=[('guest_memory_test',['runtime/guest_memory.c','tests/test_guest_memory.c']),
           ('pe32_test',['runtime/guest_memory.c','runtime/pe32_image.c','runtime/pe32_imports.c','runtime/pe32_import_plan.c','tests/test_pe_image.c'])]
    results={}
    for name,paths in specs:
        if available_memory_mb()<1536:raise WorkSafeError('insufficient RAM for Android test compilation')
        argv=common+[str(ROOT/path) for path in paths]+['-o',str(out/name)]
        result=_run_job(argv,60,'android-device-build-'+name,cfg,max_processes=4,memory_mb=512)
        results[name]=result
        if result['returncode']!=0 or result['timed_out']:return {'builds':results,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_device_tests.py')],30,'android-device-build-verify',cfg,max_processes=1,memory_mb=256)
    return {'builds':results,'verify':verified}

def build_android_dispatch_test():
    """Cross-compile the synthetic fail-closed dispatch test for Android ARM64."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';clang=ndk/'bin'/'clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    out=ROOT/'build'/'device-tests';out.mkdir(parents=True,exist_ok=True)
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-fPIE','-pie','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),str(ROOT/'tests/test_checked_dispatch.c'),str(ROOT/'runtime/win_tick.c'),str(ROOT/'runtime/android_boot_clock.c'),'-o',str(out/'dispatch_test')]
    built=_run_job(argv,60,'android-dispatch-build',cfg,max_processes=4,memory_mb=512)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools/verify_dispatch_device.py')],30,'android-dispatch-verify',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'verify':verified}

def run_android_device_tests(dispatch_only=False):
    """Run only fixed synthetic test binaries on one authorized Galaxy S25.

    Creates a fresh random directory, checks uploaded hashes, then removes only
    the selected files and that directory. No APK, game files or UI are touched.
    """
    import hashlib,re,secrets
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not isinstance(dispatch_only,bool):raise WorkSafeError('invalid device test profile')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    base=ROOT/'build'/'device-tests';manifest=json.loads((base/('dispatch_manifest.json' if dispatch_only else 'manifest.json')).read_text(encoding='utf-8'))
    expected_names=['dispatch_test'] if dispatch_only else ['guest_memory_test','pe32_test']
    if manifest.get('abi')!='arm64-v8a' or [x['name'] for x in manifest['tests']]!=expected_names:
        raise WorkSafeError('unexpected device test manifest')
    for item in manifest['tests']:
        path=base/item['name']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise WorkSafeError('device test hash mismatch')
    def command(args,label,timeout=30,expected=0):
        if not label.startswith('cleanup-') and available_memory_mb()<1024:
            raise WorkSafeError('memory pressure during device test')
        result=_run_job([str(adb)]+args,timeout,'device-'+label,cfg,max_processes=4,memory_mb=256)
        if result['timed_out'] or result['returncode']!=expected:raise WorkSafeError('ADB '+label+' failed; see its logs')
        return Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').strip()
    listing=command(['devices','-l'],'list',15)
    entries=[line.split() for line in listing.splitlines()[1:] if line.strip()]
    ready=[parts[0] for parts in entries if len(parts)>=2 and parts[1]=='device']
    if len(ready)!=1:raise WorkSafeError('need exactly one authorized ADB device')
    serial=ready[0]
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',serial):raise WorkSafeError('invalid ADB serial')
    prefix=['-s',serial]
    model=command(prefix+['shell','getprop','ro.product.model'],'model',15)
    abi=command(prefix+['shell','getprop','ro.product.cpu.abilist'],'abi',15)
    if not model.upper().startswith(('SM-S931','SM-S936','SM-S937','SM-S938','SM-S731')):
        raise WorkSafeError('the authorized device is not an identified Galaxy S25')
    if 'arm64-v8a' not in abi.split(','):raise WorkSafeError('device does not report arm64-v8a')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    intent=ROOT/'logs'/'device-last-directory.json';intent.parent.mkdir(exist_ok=True)
    intent.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    try:command(prefix+['shell','mkdir',remote],'mkdir',15)
    except WorkSafeError as exc:raise WorkSafeError('ADB mkdir result uncertain; attempted directory recorded in device-last-directory.json') from exc
    cleanup=[];results={}
    try:
        for item in manifest['tests']:
            name=item['name'];dest=remote+'/'+name;cleanup.append(dest)
            command(prefix+['push',str(base/name),dest],'push-'+name,30)
            remote_hash=command(prefix+['shell','sha256sum',dest],'hash-'+name,15).split()
            if not remote_hash or remote_hash[0].lower()!=item['sha256']:raise WorkSafeError('device test hash mismatch')
            command(prefix+['shell','chmod','700',dest],'chmod-'+name,15)
            command(prefix+['shell',dest],'run-'+name,30)
            if dispatch_only:
                for argument in ('missing-call','missing-tail','missing-precise'):
                    command(prefix+['shell',dest,'--'+argument],'run-'+argument,30,expected=74)
            results[name]='passed'
    finally:
        # Exact files in the newly created directory only; never recursive.
        try:
            if cleanup:command(prefix+['shell','rm','-f']+cleanup,'cleanup-files',15)
            command(prefix+['shell','rmdir',remote],'cleanup-dir',15)
            intent.write_text(json.dumps({'remote_directory':remote,'cleanup':'confirmed'},indent=2)+'\n',encoding='utf-8')
        except WorkSafeError:
            results['cleanup']='failed; see device cleanup logs'
    return {'model':model,'abi':abi,'tests':results}

def run_android_dispatch_single_session():
    """Upload, test and clean one synthetic binary in one bounded ADB shell."""
    import base64,hashlib,re,secrets,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe';base=ROOT/'build'/'device-tests'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    manifest=json.loads((base/'dispatch_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('abi')!='arm64-v8a' or [x['name'] for x in manifest['tests']]!=['dispatch_test']:raise WorkSafeError('unexpected dispatch manifest')
    binary=(base/'dispatch_test').read_bytes();digest=hashlib.sha256(binary).hexdigest()
    if digest!=manifest['tests'][0]['sha256'] or len(binary)>1024*1024:raise WorkSafeError('dispatch binary hash or size mismatch')
    listing=_run_job([str(adb),'devices','-l'],15,'device-dispatch-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('ADB device listing failed')
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    entries=[line.split() for line in text.splitlines()[1:] if line.strip()]
    ready=[parts[0] for parts in entries if len(parts)>=2 and parts[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    if available_memory_mb()<1024:raise WorkSafeError('memory pressure before device session')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    encoded='\n'.join(textwrap.wrap(base64.b64encode(binary).decode('ascii'),76))
    script=(
        'model=$(getprop ro.product.model)\n'
        'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) echo MHAE_BAD_MODEL; exit 70;; esac\n'
        'abi=$(getprop ro.product.cpu.abilist)\n'
        'case ",$abi," in *,arm64-v8a,*) ;; *) echo MHAE_BAD_ABI; exit 71;; esac\n'
        'printf "MHAE_MODEL=%s\\nMHAE_ABI=%s\\n" "$model" "$abi"\n'
        f'd={remote}\n'
        'p="$d/dispatch_test"\n'
        'if ! mkdir "$d"; then echo MHAE_MKDIR_FAILED; exit 72; fi\n'
        'cleanup() { rm -f "$p" && rmdir "$d"; }\n'
        'finish() { rc=$?; trap - EXIT; if cleanup; then echo MHAE_CLEANUP_OK; else echo MHAE_CLEANUP_FAILED >&2; if [ "$rc" -eq 0 ]; then rc=91; fi; fi; exit "$rc"; }\n'
        'trap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
        'if ! base64 -d > "$p" <<\'MHAE_PAYLOAD\'\n'+encoded+'\nMHAE_PAYLOAD\n'
        'then echo MHAE_DECODE_FAILED; exit 73; fi\n'
        'set -- $(sha256sum "$p")\n'
        f'if [ "${{1:-}}" != "{digest}" ]; then echo MHAE_HASH_FAILED; exit 74; fi\n'
        'if ! chmod 700 "$p"; then echo MHAE_CHMOD_FAILED; exit 75; fi\n'
        'if ! "$p"; then echo MHAE_SUCCESS_CASE_FAILED; exit 76; fi\n'
        'for arg in missing-call missing-tail missing-precise; do\n'
        '  "$p" "--$arg"; rc=$?\n'
        '  if [ "$rc" -ne 74 ]; then echo MHAE_EXPECTED_FAILURE_MISMATCH; exit 77; fi\n'
        'done\n'
        '"$p" --tick-return-mismatch; rc=$?\n'
        'if [ "$rc" -ne 78 ]; then echo MHAE_RETURN_MISMATCH_NOT_REJECTED; exit 78; fi\n'
        'echo MHAE_TESTS_PASSED\nexit 0\n').encode('ascii')
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git'/'bin'/'sh.exe'
    if not shell.is_file():raise WorkSafeError('Git shell missing for syntax-only validation')
    syntax=_run_job([str(shell),'-n'],15,'device-dispatch-shell-check',cfg,max_processes=2,memory_mb=256,input_bytes=script)
    if syntax['timed_out'] or syntax['returncode']!=0:raise WorkSafeError('device script failed syntax check')
    attempt=ROOT/'logs'/'device-dispatch-attempt.json';attempt.parent.mkdir(exist_ok=True)
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],45,'device-dispatch-session',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    cleanup='confirmed' if 'MHAE_CLEANUP_OK' in output else 'unconfirmed'
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':cleanup},indent=2)+'\n',encoding='utf-8')
    if result['timed_out'] or result['returncode']!=0 or cleanup!='confirmed' or 'MHAE_TESTS_PASSED' not in output:
        raise WorkSafeError('dispatch session failed or cleanup unconfirmed; inspect device-dispatch logs')
    models=re.findall(r'^MHAE_MODEL=(\S+)\s*$',output,re.MULTILINE)
    if len(models)!=1:raise WorkSafeError('device model result missing')
    return {'model':models[0],'abi':'arm64-v8a','tests':{'dispatch_test':'passed'},'cleanup':cleanup}

def inspect_android_temp_dirs():
    """Read only the names of project-prefixed temporary directories on one S25."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    listing=_run_job([str(adb),'devices','-l'],15,'device-temp-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('ADB device listing failed')
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    entries=[line.split() for line in text.splitlines()[1:] if line.strip()]
    ready=[parts[0] for parts in entries if len(parts)>=2 and parts[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    script=(b'model=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'find /data/local/tmp -maxdepth 1 -type d -name "mhae_*" -print\n')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],20,'device-temp-inspect',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('read-only device directory inspection failed')
    lines=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()
    if any(not re.fullmatch(r'/data/local/tmp/mhae_[0-9a-f]{16}',line) for line in lines):raise WorkSafeError('unexpected device directory listing')
    return lines

def inspect_s25_game_destination():
    """Read model, free storage and requested destination state; no device writes."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    if not adb.is_file():raise WorkSafeError('Android SDK adb missing')
    listing=_run_job([str(adb),'devices','-l'],15,'device-data-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('ADB device listing failed')
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    entries=[line.split() for line in text.splitlines()[1:] if line.strip()]
    ready=[parts[0] for parts in entries if len(parts)>=2 and parts[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    script=(b'model=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'printf "MHAE_MODEL=%s\\n" "$model"\n'
            b'if [ -e /sdcard/mh-androidevolved ]; then echo MHAE_DEST_EXISTS; else echo MHAE_DEST_ABSENT; fi\n'
            b'echo MHAE_DF_BEGIN\ndf -k /sdcard\n')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],20,'device-data-inspect',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('read-only destination inspection failed')
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    if 'MHAE_DF_BEGIN' not in output or not re.search(r'^MHAE_MODEL=SM-S(?:931|936|937|938|731)\S*$',output,re.MULTILINE):raise WorkSafeError('unexpected device response')
    return output

def copy_game_to_s25():
    """Copy the user's local game into a new, exclusively created S25 folder."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    source=ROOT/'Manhunt Collection'/'Manhunt'
    if not source.is_dir(): raise WorkSafeError('local game directory missing')
    count=0; total=0
    for directory, dirs, files in os.walk(source,followlinks=False):
        for name in dirs+files:
            path=Path(directory)/name
            info=path.stat(follow_symlinks=False)
            if info.st_file_attributes & 0x400: raise WorkSafeError('source contains a reparse point')
            if name in files: count+=1; total+=info.st_size
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    listing=_run_job([str(adb),'devices','-l'],15,'game-copy-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0: raise WorkSafeError('ADB device listing failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]): raise WorkSafeError('need exactly one authorized ADB device')
    serial=ready[0]
    # mkdir itself is atomic: fail if another process created the destination.
    check=(b'set -e\nmodel=$(getprop ro.product.model)\n'
           b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
           + f"free=$(df -k /sdcard | awk 'NR==2 {{print $4}}')\n[ \"$free\" -ge {(total+2*1024**3+1023)//1024} ] || exit 71\n".encode()
           + b'mkdir /sdcard/mh-androidevolved\necho MHAE_CREATED\n')
    made=_run_job([str(adb),'-s',serial,'shell','-T','sh'],30,'game-copy-create',cfg,max_processes=4,memory_mb=256,input_bytes=check)
    if made['timed_out'] or made['returncode']!=0 or 'MHAE_CREATED' not in Path(made['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace'):
        raise WorkSafeError('destination creation failed or uncertain; inspect before retrying')
    children=sorted(source.iterdir(),key=lambda p:p.name.lower())
    copied=_run_job([str(adb),'-s',serial,'push','-Z','-q',*[str(p) for p in children],'/sdcard/mh-androidevolved/'],1800,'game-copy-transfer',cfg,max_processes=4,memory_mb=512)
    if copied['timed_out'] or copied['returncode']!=0:
        raise WorkSafeError('transfer incomplete; preserve destination and inspect game-copy-transfer logs')
    return {'source_files':count,'source_bytes':total,'transfer':'completed','destination':'/sdcard/mh-androidevolved'}

def verify_game_on_s25():
    """Read-only verification of file count, bytes, and the expected executable."""
    import hashlib,re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    source=ROOT/'Manhunt Collection'/'Manhunt'; count=0; total=0
    for directory, dirs, files in os.walk(source,followlinks=False):
        for name in dirs+files:
            info=(Path(directory)/name).stat(follow_symlinks=False)
            if info.st_file_attributes & 0x400: raise WorkSafeError('source contains a reparse point')
            if name in files: count+=1; total+=info.st_size
    digest=hashlib.sha256((source/'manhunt.exe').read_bytes()).hexdigest()
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    listing=_run_job([str(adb),'devices','-l'],15,'game-verify-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0: raise WorkSafeError('ADB device listing failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]): raise WorkSafeError('need exactly one authorized ADB device')
    script=(b'set -e\nmodel=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'echo MHAE_SIZES\nfind /sdcard/mh-androidevolved -type f -exec stat -c %s {} + | awk \'{n++;s+=$1} END {printf "%.0f %.0f\\n",n,s}\'\n'
            b'echo MHAE_EXE\nsha256sum /sdcard/mh-androidevolved/manhunt.exe\n')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],180,'game-verify',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['timed_out'] or result['returncode']!=0: raise WorkSafeError('device verification failed')
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    match=re.search(r'MHAE_SIZES\s+(\d+)\s+(\d+)\s+MHAE_EXE\s+([0-9a-f]{64})\s+',output)
    if not match: raise WorkSafeError('unexpected verification output')
    device_count,device_total=int(match[1]),int(match[2])
    if (device_count,device_total,match[3])!=(count,total,digest): raise WorkSafeError('device copy verification mismatch: '+output)
    return {'files':count,'bytes':total,'executable_sha256':digest,'verification':'counts, total bytes, executable SHA-256'}

def compile_android_resources():
    """Compile Android resources only, without Gradle or producing an APK."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    aapt=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'build-tools'/'35.0.0'/'aapt2.exe'
    if not aapt.is_file(): raise WorkSafeError('aapt2 missing')
    output=ROOT/'build'/'android-resource-check';output.mkdir(parents=True,exist_ok=True)
    result=_run_job([str(aapt),'compile','--dir',str(ROOT/'android/app/src/main/res'),'-o',str(output/'compiled.zip')],120,'android-resources-compile',cfg,max_processes=1,memory_mb=512)
    if result['timed_out'] or result['returncode']!=0: raise WorkSafeError('resource compilation failed; inspect android-resources-compile logs')
    return result

def test_import_registry():
    """Compile the synthetic registry tests to WASM and run them headlessly."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'
    clang=sdk/'ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe'
    node=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'nodejs/node.exe'
    if not clang.is_file() or not node.is_file():raise WorkSafeError('test tools missing')
    out=ROOT/'build/wasm-test';out.mkdir(parents=True,exist_ok=True);binary=out/'import_registry.wasm'
    argv=[str(clang),'--target=wasm32-unknown-unknown','-ffreestanding','-fno-builtin','-nostdlib','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'tests/wasm_include'),'-I',str(ROOT/'runtime'),str(ROOT/'runtime/guest_memory.c'),str(ROOT/'runtime/import_registry.c'),str(ROOT/'runtime/win_tick.c'),str(ROOT/'runtime/win_tick_x86.c'),str(ROOT/'tests/wasm_memmove.c'),str(ROOT/'tests/test_import_registry.c'),str(ROOT/'tests/test_win_tick.c'),'-Wl,--no-entry','-Wl,--export=mh_registry_tests','-Wl,--export=mh_tick_tests','-o',str(binary)]
    built=_run_job(argv,60,'import-registry-build',cfg,max_processes=2,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('registry test build failed')
    js="const fs=require('fs'); WebAssembly.instantiate(fs.readFileSync(process.argv[1])).then(x=>{for(const n of ['mh_registry_tests','mh_tick_tests']){let r=x.instance.exports[n](); if(r){console.error(n,'failed line',r);process.exit(1)}} console.log('registry and tick tests passed')}).catch(e=>{console.error(e);process.exit(1)})"
    tested=_run_job([str(node),'-e',js,str(binary)],30,'import-registry-test',cfg,max_processes=1,memory_mb=256)
    if tested['returncode']!=0 or tested['timed_out']:raise WorkSafeError('registry tests failed')
    return tested

def check_android_boot_clock():
    """Compile the Android boot-clock provider to ARM64 without linking."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    clang=ndk/'bin/clang.exe';out=ROOT/'build/android-native-check';out.mkdir(parents=True,exist_ok=True)
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),'-c',str(ROOT/'runtime/android_boot_clock.c'),'-o',str(out/'android_boot_clock.o')]
    result=_run_job(argv,60,'android-boot-clock-check',cfg,max_processes=2,memory_mb=384)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('Android clock compile failed; inspect logs')
    return result

def test_import_registry_on_s25():
    """Build and run synthetic registry and PE integration tests on an S25."""
    import base64,hashlib,re,secrets,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk';ndk=sdk/'ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    clang=ndk/'bin/clang.exe';adb=sdk/'platform-tools/adb.exe'
    if not clang.is_file() or not adb.is_file():raise WorkSafeError('Android build tools missing')
    out=ROOT/'build/device-tests';out.mkdir(parents=True,exist_ok=True)
    main=out/'registry_main.c';main.write_text('int mh_registry_tests(void); int mh_pe_tests(void); int mh_tick_tests(void); int main(void){int r=mh_registry_tests();if(r)return r;r=mh_pe_tests();return r?r:mh_tick_tests();}\n',encoding='ascii')
    binary=out/'registry_test'
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=c11','-Wall','-Wextra','-Werror','-DMH_NO_MAIN','-DMH_TEST_IMPORT_REGISTRY','-DMH_TEST_ANDROID_BOOT_CLOCK','-I',str(ROOT/'runtime'),str(ROOT/'runtime/guest_memory.c'),str(ROOT/'runtime/pe32_image.c'),str(ROOT/'runtime/pe32_imports.c'),str(ROOT/'runtime/pe32_import_plan.c'),str(ROOT/'runtime/import_registry.c'),str(ROOT/'runtime/win_tick.c'),str(ROOT/'runtime/win_tick_x86.c'),str(ROOT/'runtime/android_boot_clock.c'),str(ROOT/'tests/test_import_registry.c'),str(ROOT/'tests/test_pe_image.c'),str(ROOT/'tests/test_win_tick.c'),str(main),'-o',str(binary)]
    built=_run_job(argv,60,'registry-arm64-build',cfg,max_processes=4,memory_mb=512)
    if built['timed_out'] or built['returncode']!=0:raise WorkSafeError('ARM64 registry build failed')
    payload=binary.read_bytes()
    if len(payload)>1024*1024 or payload[:4]!=b'\x7fELF' or payload[18:20]!=b'\xb7\x00':raise WorkSafeError('unexpected ARM64 test binary')
    digest=hashlib.sha256(payload).hexdigest()
    listing=_run_job([str(adb),'devices','-l'],15,'registry-device-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('ADB device listing failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    encoded='\n'.join(textwrap.wrap(base64.b64encode(payload).decode('ascii'),76))
    script=('model=$(getprop ro.product.model)\ncase "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            'case ",$(getprop ro.product.cpu.abilist)," in *,arm64-v8a,*) ;; *) exit 71;; esac\n'
            f'd={remote}\np="$d/registry_test"\n'
            'mkdir "$d" || exit 72\n'
            'finish() { rc=$?; trap - EXIT; if rm -f "$p" && rmdir "$d"; then echo MHAE_CLEANUP_OK; else rc=91; fi; exit "$rc"; }\n'
            'trap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
            'base64 -d > "$p" <<\'MHAE_PAYLOAD\'\n'+encoded+'\nMHAE_PAYLOAD\n'
            'set -- $(sha256sum "$p")\n'+f'[ "${{1:-}}" = "{digest}" ] || exit 74\n'+
            'chmod 700 "$p" || exit 75\n"$p" || exit 76\necho MHAE_TESTS_PASSED\n').encode('ascii')
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git/bin/sh.exe'
    if not shell.is_file():raise WorkSafeError('Git shell missing for syntax-only validation')
    syntax=_run_job([str(shell),'-n'],15,'registry-device-shell-check',cfg,max_processes=2,memory_mb=256,input_bytes=script)
    if syntax['timed_out'] or syntax['returncode']!=0:raise WorkSafeError('registry device script syntax failed')
    attempt=ROOT/'logs/registry-device-attempt.json';attempt.parent.mkdir(exist_ok=True)
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],60,'registry-device-test',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    cleaned='MHAE_CLEANUP_OK' in output
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'confirmed' if cleaned else 'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    if result['timed_out'] or result['returncode']!=0 or not cleaned or 'MHAE_TESTS_PASSED' not in output:raise WorkSafeError('registry device test failed or cleanup unconfirmed')
    return {'tests':'registry, synthetic PE integration and Android boot clock passed','abi':'arm64-v8a','sha256':digest,'cleanup':'confirmed'}

def _winmain_input_hashes():
    """Exact local C inputs and comparison references, including optional seeded saves."""
    import hashlib
    base=ROOT/'private/analysis/winmain'
    inputs=_time_harness_input_hashes(ROOT/'tests/winmain_native.c',include_dirs=(base,))
    paths=[base/'winmain_report.json',base/'x86_reference.json',ROOT/'tests/compare_harness.py',
           *sorted((base/'scenarios').glob('*/x86_reference.json')),
           *sorted((base/'seed_saves').glob('*'))]
    for path in paths:
        if not path.is_file():raise WorkSafeError('invalid winmain comparison input')
        inputs[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(inputs.items()))

def _require_validated_winmain():
    import hashlib
    base=ROOT/'private/analysis/winmain';record_path=base/'android/validated.json'
    if not record_path.is_file():raise WorkSafeError('winmain has not been validated on the S25')
    record=json.loads(record_path.read_text(encoding='utf-8'))
    if record.get('source_inputs')!=_winmain_input_hashes():raise WorkSafeError('winmain inputs changed or unrecorded; rerun test_winmain on the S25')
    binary=base/'android/winmain_test'
    if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest()!=record.get('binary_sha256'):
        raise WorkSafeError('validated winmain binary changed')
    return record_path

def _game_library_input_hashes():
    return _time_harness_input_hashes(ROOT/'android/app/src/main/cpp/game_jni.c',include_dirs=(ROOT/'private/analysis/winmain',))

def _require_current_game_library():
    import hashlib
    validation=_require_validated_winmain()
    base=ROOT/'private/analysis/game/android';library=base/'libmh_game.so';manifest=base/'built.json'
    if not manifest.is_file():raise WorkSafeError('game library build inputs unrecorded; rebuild it')
    record=json.loads(manifest.read_text(encoding='utf-8'))
    if record.get('source_inputs')!=_game_library_input_hashes() or record.get('validation_sha256')!=hashlib.sha256(validation.read_bytes()).hexdigest():
        raise WorkSafeError('game library inputs changed; rebuild it')
    if not library.is_file() or record.get('library_sha256')!=hashlib.sha256(library.read_bytes()).hexdigest():
        raise WorkSafeError('game library binary changed; rebuild it')
    return library

def promote_prepared_game_library():
    """Attach completed device validation to an unchanged prepared library; no recompilation."""
    import hashlib
    validation=_require_validated_winmain()
    out=ROOT/'private/analysis/game/android';lib=out/'libmh_game.so'
    prepared=out/'prepared.json'
    if not prepared.is_file():raise WorkSafeError('no prepared game library')
    record=json.loads(prepared.read_text(encoding='utf-8'))
    if record.get('source_inputs')!=_game_library_input_hashes() or record.get('winmain_inputs')!=_winmain_input_hashes():
        raise WorkSafeError('prepared game library inputs changed')
    if not lib.is_file() or record.get('library_sha256')!=hashlib.sha256(lib.read_bytes()).hexdigest():
        raise WorkSafeError('prepared game library binary changed')
    record['validation_sha256']=hashlib.sha256(validation.read_bytes()).hexdigest()
    (out/'built.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return {'library':str(lib),'sha256':record['library_sha256'],'status':'device validation attached'}

def build_game_library(prepare_only=False):
    """Private build of libmh_game.so: the translated boot and WinMain (runtime/game_runner.c) with the
    OpenGL ES backend, for GameActivity. prepare_only compiles without an approval record;
    it cannot be packaged until promote_prepared_game_library attaches completed S25 validation."""
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    base=ROOT/'private/analysis/winmain';report=json.loads((base/'winmain_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256((base/'winmain_unit.c').read_bytes()).hexdigest()!=report['unit_sha256']:raise WorkSafeError('winmain unit changed since lift')
    validation=None if prepare_only else _require_validated_winmain()
    validation_hash=hashlib.sha256(validation.read_bytes()).hexdigest() if validation else None
    winmain_inputs=_winmain_input_hashes()
    inputs=_game_library_input_hashes()
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    includes=[str(ROOT/'private/pcrecomp/runtime/recomp32'),str(ROOT/'recomp'),str(ROOT/'runtime'),str(base)]
    out=ROOT/'private/analysis/game/android';out.mkdir(parents=True,exist_ok=True);lib=out/'libmh_game.so'
    built=_run_job([str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O1','-fPIC','-shared',
                    *[x for d in includes for x in ('-I',d)],str(ROOT/'android/app/src/main/cpp/game_jni.c'),'-o',str(lib),
                    '-lGLESv3','-lEGL','-landroid','-llog','-laaudio','-lm','-Wl,-z,max-page-size=16384'],1800,'game-library-build',cfg,max_processes=4,memory_mb=6144)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('game library build failed; inspect game-library-build logs')
    if inputs!=_game_library_input_hashes() or winmain_inputs!=_winmain_input_hashes():
        raise WorkSafeError('game library inputs changed during compilation')
    record={'library_sha256':hashlib.sha256(lib.read_bytes()).hexdigest(),'source_inputs':inputs,'winmain_inputs':winmain_inputs}
    if validation:
        if validation_hash!=hashlib.sha256(_require_validated_winmain().read_bytes()).hexdigest():raise WorkSafeError('game validation changed during compilation')
        record['validation_sha256']=validation_hash
    (out/('prepared.json' if prepare_only else 'built.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return {'library':str(lib),'sha256':record['library_sha256'],'status':'compiled; device validation pending' if prepare_only else 'validated inputs',
            'distribution':'private: contains translated game code'}

def _android_app_input_hashes():
    import hashlib
    src=ROOT/'android/app/src/main'
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(src.rglob('*')) if p.is_file()}

def finalize_prepared_apk():
    """Make an unchanged prepared APK installable only after completed S25 validation."""
    import hashlib,zipfile
    library=_require_current_game_library()
    out=ROOT/'build/android-diagnostic-apk';prepared=out/'prepared-debug.apk'
    record=json.loads((out/'prepared-apk.json').read_text(encoding='utf-8'))
    if record.get('app_inputs')!=_android_app_input_hashes() or record.get('apk_sha256')!=hashlib.sha256(prepared.read_bytes()).hexdigest():
        raise WorkSafeError('prepared APK inputs changed; rebuild it')
    with zipfile.ZipFile(prepared) as apk:
        if hashlib.sha256(apk.read('lib/arm64-v8a/libmh_game.so')).hexdigest()!=hashlib.sha256(library.read_bytes()).hexdigest():
            raise WorkSafeError('prepared APK contains a different game library')
    destination=out/'diagnostic-debug.apk';destination.write_bytes(prepared.read_bytes())
    return {'apk':str(destination),'sha256':record['apk_sha256'],'status':'prepared APK matched completed device validation'}

def build_diagnostic_apk(prepare_only=False):
    """Build a private diagnostic APK in bounded sequential jobs, without Gradle."""
    import sys, zipfile, xml.etree.ElementTree as ET
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    app_inputs=_android_app_input_hashes()
    sdk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'; tools=sdk/'build-tools'/'35.0.0'
    java=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Android'/'Android Studio'/'jbr'/'bin'/'java.exe'
    android=sdk/'platforms'/'android-35'/'android.jar'; key=Path.home()/'.android'/'debug.keystore'
    aapt=tools/'aapt2.exe'; align=tools/'zipalign.exe'; d8=tools/'lib'/'d8.jar'; signer=tools/'lib'/'apksigner.jar'
    lib=ROOT/'build/android-cmake-check/libmh_runtime.so'; src=ROOT/'android/app/src/main'
    if not all(p.is_file() for p in (java,android,key,aapt,align,d8,signer,lib)):
        raise WorkSafeError('diagnostic build prerequisites missing')
    import re as _re
    cmake_text=(src/'cpp/CMakeLists.txt').read_text(encoding='utf-8')
    runtime_used=[ROOT/'runtime'/n for n in _re.findall(r'\$\{MH_ROOT\}/runtime/(\w+\.c)',cmake_text)]
    if not runtime_used:raise WorkSafeError('could not read the native source list')
    native_sources=[src/'cpp/native_diagnostics.c',src/'cpp/native_selftest.c',src/'cpp/CMakeLists.txt',ROOT/'tests/test_x87_semantics.c',
                    *runtime_used,*(p.with_suffix('.h') for p in runtime_used if p.with_suffix('.h').is_file()),*list((ROOT/'recomp').glob('*.h'))]
    if any(p.stat().st_mtime>lib.stat().st_mtime for p in native_sources): raise WorkSafeError('native library may be stale; rebuild it first')
    def run(argv,name,seconds=120,memory=512):
        if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM; diagnostic build paused')
        r=_run_job(argv,seconds,name,cfg,max_processes=1,memory_mb=memory)
        if r['timed_out'] or r['returncode']!=0: raise WorkSafeError(name+' failed; inspect its logs')
        return r
    checked=check_android_java()
    if checked['timed_out'] or checked['returncode']!=0: raise WorkSafeError('Java compilation failed')
    compile_android_resources()
    out=ROOT/'build/android-diagnostic-apk';out.mkdir(parents=True,exist_ok=True)
    manifest=ET.parse(src/'AndroidManifest.xml'); root=manifest.getroot();root.set('package','com.manhuntae.android')
    ns='http://schemas.android.com/apk/res/android';ET.register_namespace('android',ns)
    root.set('{%s}versionCode'%ns,'1');root.set('{%s}versionName'%ns,'0.1-research')
    root.find('application').set('{%s}extractNativeLibs'%ns,'true')
    root.find('application').set('{%s}debuggable'%ns,'true')   # private debug build: inspect saves with run-as
    manifest.write(out/'AndroidManifest.xml',encoding='utf-8',xml_declaration=True)
    unsigned=out/'resources.apk'
    run([str(aapt),'link','-o',str(unsigned),'-I',str(android),'--manifest',str(out/'AndroidManifest.xml'),'--min-sdk-version','29','--target-sdk-version','35','-A',str(src/'assets'),str(ROOT/'build/android-resource-check/compiled.zip')],'diagnostic-aapt-link')
    classes=sorted((ROOT/'build/android-java-check').rglob('*.class'))
    if not classes:raise WorkSafeError('no compiled Java classes')
    run([str(java),'-Xmx256m','-Djava.awt.headless=true','-cp',str(d8),'com.android.tools.r8.D8','--min-api','29','--output',str(out),*[str(p) for p in classes]],'diagnostic-d8')
    # Optional private payload: the translated time harness, only when its exact binary passed on the S25.
    import hashlib
    harness=ROOT/'private/analysis/candidate_time/android/time_test';validated=harness.parent/'validated.json';translated=None
    if harness.is_file() and validated.is_file():
        record=json.loads(validated.read_text(encoding='utf-8'))
        if hashlib.sha256(harness.read_bytes()).hexdigest()==record.get('binary_sha256'):
            translated={'binary_sha256':record['binary_sha256'],'main_output_sha256':record['main_output_sha256'],'zero_output_sha256':record['zero_output_sha256']}
    with zipfile.ZipFile(unsigned,'a',compression=zipfile.ZIP_DEFLATED) as apk:
        apk.write(out/'classes.dex','classes.dex');apk.write(lib,'lib/arm64-v8a/libmh_runtime.so')
        if translated:
            apk.write(harness,'lib/arm64-v8a/libmhae_time_test.so')
            apk.writestr('assets/translated/time_expected.json',json.dumps(translated,indent=2)+'\n')
        # Further private payloads: each binary only if its exact hash passed on the S25.
        for source,library,asset in (('loader/android/loader_test','libmhae_loader_test.so','loader_expected.json'),
                                     ('allocator/android/allocator_test','libmhae_allocator_test.so','allocator_expected.json'),
                                     ('heap/android/heap_test','libmhae_heap_test.so','heap_expected.json')):
            binary=ROOT/'private/analysis'/source;record_path=binary.parent/'validated.json'
            if not (binary.is_file() and record_path.is_file()):continue
            record=json.loads(record_path.read_text(encoding='utf-8'))
            if hashlib.sha256(binary.read_bytes()).hexdigest()!=record.get('binary_sha256'):continue
            apk.write(binary,'lib/arm64-v8a/'+library)
            apk.writestr('assets/translated/'+asset,json.dumps({k:record[k] for k in ('binary_sha256','output_sha256')},indent=2)+'\n')
            translated=translated or {};translated[library]=True
        game=ROOT/'private/analysis/game/android/libmh_game.so'
        if game.is_file():
            if prepare_only:
                staged=json.loads((game.parent/'prepared.json').read_text(encoding='utf-8'))
                if staged.get('source_inputs')!=_game_library_input_hashes() or staged.get('winmain_inputs')!=_winmain_input_hashes() or staged.get('library_sha256')!=hashlib.sha256(game.read_bytes()).hexdigest():
                    raise WorkSafeError('prepared game library changed')
            else:_require_current_game_library()
            apk.write(game,'lib/arm64-v8a/libmh_game.so');translated=translated or {};translated['libmh_game.so']=True
    aligned=out/'aligned.apk'; signed=out/('prepared-debug.apk' if prepare_only else 'diagnostic-debug.apk')
    run([str(align),'-f','4',str(unsigned),str(aligned)],'diagnostic-zipalign')
    run([str(java),'-Xmx128m','-Djava.awt.headless=true','-jar',str(signer),'sign','--ks',str(key),'--ks-pass','pass:android','--key-pass','pass:android','--out',str(signed),str(aligned)],'diagnostic-sign')
    run([str(java),'-Xmx128m','-Djava.awt.headless=true','-jar',str(signer),'verify','--verbose',str(signed)],'diagnostic-sign-verify')
    if app_inputs!=_android_app_input_hashes():raise WorkSafeError('Android app sources changed during packaging')
    if prepare_only:
        (out/'prepared-apk.json').write_text(json.dumps({'apk_sha256':hashlib.sha256(signed.read_bytes()).hexdigest(),
            'app_inputs':app_inputs,'status':'compiled and signed; device validation pending'},indent=2)+'\n',encoding='utf-8')
    return {'apk':str(signed),'scope':'development game and diagnostics' if translated and translated.get('libmh_game.so') else 'diagnostic only','translated_payload':bool(translated),
            'status':'prepared; device validation pending; not installed' if prepare_only else 'packaged',
            'distribution':'private: contains translated game code' if translated else 'public sources only'}

def install_diagnostic_on_s25():
    """Install the diagnostic package only if its application ID is absent."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    apk=ROOT/'build/android-diagnostic-apk/diagnostic-debug.apk'
    if not apk.is_file():raise WorkSafeError('diagnostic APK missing')
    def run(args,name,seconds=30,input_bytes=None):
        result=_run_job([str(adb),*args],seconds,name,cfg,max_processes=4,memory_mb=256,input_bytes=input_bytes)
        if result['timed_out'] or result['returncode']!=0:raise WorkSafeError(name+' failed; inspect logs')
        return Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    listing=run(['devices','-l'],'diagnostic-device-list')
    ready=[p[0] for line in listing.splitlines()[1:] if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    serial=ready[0]
    script=(b'set -e\nmodel=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'[ "$(getprop ro.product.cpu.abi)" = arm64-v8a ] || exit 71\n'
            b'if pm path com.manhuntae.android | grep -q .; then exit 72; fi\n'
            b'echo MHAE_PACKAGE_ABSENT\n')
    if 'MHAE_PACKAGE_ABSENT' not in run(['-s',serial,'shell','-T','sh'],'diagnostic-install-preflight',input_bytes=script):
        raise WorkSafeError('package state uncertain')
    output=run(['-s',serial,'install',str(apk)],'diagnostic-install',120)
    if 'Success' not in output:raise WorkSafeError('installation result uncertain')
    return {'installation':'success','package':'com.manhuntae.android','scope':'diagnostic only'}

def run_loader_on_s25():
    """Compile the isolated slot-loader harness for ARM64, run it on one S25 and compare with x86.

    The binary embeds translated game code and stays in private/. The device
    session uses a fresh random directory; the harness creates and removes its
    own synthetic slot files there, then the session removes exactly the binary
    and the directory (non-recursive). No APK, game file or UI is touched."""
    import base64,hashlib,re,secrets,sys,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    deps=ROOT/'private/analysis/candidate_time/dependencies'
    strings=json.loads((deps/'loader_strings_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256((deps/'loader_strings_unit.c').read_bytes()).hexdigest()!=strings['unit_sha256']:raise WorkSafeError('loader strings unit changed since lift')
    reference=json.loads((ROOT/'private/analysis/loader/x86_reference.json').read_text(encoding='utf-8'))
    if reference.get('strings_unit_sha256')!=strings['unit_sha256']:raise WorkSafeError('x86 reference is stale; rerun tools/probe_loader_x86.py')
    inputs=[ROOT/'tests/loader_native.c',*(deps/n for n in ('loader_helpers_unit.c','file_lifecycle_unit.c','dep_00611640_precise.c','dep_00401030_precise.c','loader_strings_unit.c','dep_00605750_precise.c')),
            ROOT/'private/analysis/allocator/allocator_unit.c',ROOT/'private/analysis/heap/heap_unit.c',ROOT/'private/analysis/heap/heap_data.h',ROOT/'runtime/win32_memory.c',ROOT/'runtime/win32_memory.h',
            *(ROOT/'runtime'/n for n in ('guest_memory.c','guest_memory.h','readonly_stream.c','readonly_stream.h','readonly_path.c','readonly_path.h','readonly_handles.c','readonly_handles.h')),
            ROOT/'recomp/checked_memory_adapter.h',ROOT/'recomp/checked_dispatch_adapter.h',ROOT/'private/pcrecomp/runtime/recomp32/recomp_types.h']
    manifest={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    if not clang.is_file() or not adb.is_file():raise WorkSafeError('NDK clang or adb missing')
    out=ROOT/'private/analysis/loader/android';out.mkdir(parents=True,exist_ok=True);binary_path=out/'loader_test'
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie',
          '-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-I',str(ROOT/'private/analysis/candidate_time'),
          str(ROOT/'tests/loader_native.c'),'-o',str(binary_path)]
    built=_run_job(argv,180,'loader-arm64-build',cfg,max_processes=4,memory_mb=768)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('loader ARM64 build failed; inspect loader-arm64-build logs')
    binary=binary_path.read_bytes();digest=hashlib.sha256(binary).hexdigest()
    if binary[:4]!=b'\x7fELF' or int.from_bytes(binary[18:20],'little')!=183 or len(binary)>4*1024*1024:raise WorkSafeError('loader binary is not a bounded ARM64 ELF')
    (out/'manifest.json').write_text(json.dumps({'binary_sha256':digest,'source_inputs':manifest},indent=2)+'\n',encoding='utf-8')
    listing=_run_job([str(adb),'devices','-l'],15,'device-loader-list',cfg,max_processes=4,memory_mb=256)
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    ready=[p[0] for line in text.splitlines()[1:] if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    encoded='\n'.join(textwrap.wrap(base64.b64encode(binary).decode('ascii'),76))
    script=('model=$(getprop ro.product.model)\n'
        'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) echo MHAE_BAD_MODEL; exit 80;; esac\n'
        'case ",$(getprop ro.product.cpu.abilist)," in *,arm64-v8a,*) ;; *) exit 81;; esac\n'
        'printf "MHAE_MODEL=%s\\n" "$model"\n'
        f'd={remote}\np="$d/loader_test"\n'
        'if ! mkdir "$d"; then echo MHAE_MKDIR_FAILED; exit 82; fi\n'
        'cleanup() { rm -f "$p" && rmdir "$d"; }\n'
        'finish() { rc=$?; trap - EXIT; if cleanup; then echo MHAE_CLEANUP_OK; else echo MHAE_CLEANUP_FAILED >&2; [ "$rc" -eq 0 ] && rc=91; fi; exit "$rc"; }\n'
        'trap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
        "if ! base64 -d > \"$p\" <<'MHAE_PAYLOAD'\n"+encoded+'\nMHAE_PAYLOAD\n'
        'then echo MHAE_DECODE_FAILED; exit 83; fi\n'
        'set -- $(sha256sum "$p")\n'
        f'if [ "${{1:-}}" != "{digest}" ]; then echo MHAE_HASH_FAILED; exit 84; fi\n'
        'chmod 700 "$p" || exit 85\n'
        'echo MHAE_BEGIN_LOADER\n"$p" "$d"; rc=$?\necho MHAE_END_LOADER\n'
        'if [ "$rc" -ne 0 ]; then echo MHAE_LOADER_FAILED=$rc; exit 86; fi\n'
        'echo MHAE_TESTS_PASSED\nexit 0\n').encode('ascii')
    shell=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Git'/'bin'/'sh.exe'
    if shell.is_file():
        syntax=_run_job([str(shell),'-n'],15,'device-loader-shell-check',cfg,max_processes=2,memory_mb=256,input_bytes=script)
        if syntax['timed_out'] or syntax['returncode']!=0:raise WorkSafeError('device script failed syntax check')
    attempt=ROOT/'logs/device-loader-attempt.json'
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],120,'device-loader-session',cfg,max_processes=4,memory_mb=512,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').replace('\r\n','\n')
    cleanup='confirmed' if 'MHAE_CLEANUP_OK' in output else 'unconfirmed'
    attempt.write_text(json.dumps({'remote_directory':remote,'cleanup':cleanup},indent=2)+'\n',encoding='utf-8')
    if result['timed_out'] or result['returncode']!=0 or cleanup!='confirmed' or 'MHAE_TESTS_PASSED' not in output:
        raise WorkSafeError('loader session failed or cleanup unconfirmed; inspect device-loader-session logs')
    m=re.search(r'^MHAE_BEGIN_LOADER\n(.*?)^MHAE_END_LOADER$',output,re.MULTILINE|re.DOTALL)
    if not m:raise WorkSafeError('missing loader output section')
    jsonl=ROOT/'logs/loader-arm64.jsonl';jsonl.write_text(m.group(1),encoding='utf-8')
    compared=_run_job([sys.executable,str(ROOT/'tests/compare_harness.py'),str(ROOT/'private/analysis/loader/x86_reference.json'),str(jsonl),'android-arm64'],60,'loader-arm64-compare',cfg,max_processes=1,memory_mb=512)
    passed=compared['returncode']==0 and not compared['timed_out']
    models=re.findall(r'^MHAE_MODEL=(\S+)\s*$',output,re.MULTILINE)
    record=out/'validated.json'
    if passed:
        # Lets the diagnostic APK check that in-app runs reproduce this S25-validated output.
        record.write_text(json.dumps({'binary_sha256':digest,'model':models[0] if len(models)==1 else None,
            'output_sha256':hashlib.sha256(m.group(1).encode('utf-8')).hexdigest(),
            'compared_against':'Unicorn x86 reference (tools/probe_loader_x86.py, tests/compare_loader.py)'},indent=2)+'\n',encoding='utf-8')
    elif record.is_file():record.unlink()
    return {'model':models[0] if len(models)==1 else None,'binary_sha256':digest,'cleanup':cleanup,'passed':passed,
            'comparison':Path(compared['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').strip()}

def _run_binary_on_s25(binary,label,args='',max_size=4*1024*1024,timeout=180,env=None,saves=None):
    """Upload one private ARM64 test binary to a fresh random directory on one S25, run it
    once with `"$d"` substituted in args, and remove exactly that file and directory.
    saves: optional {name: bytes} written to "$d/saves" (the test's saves present at start), removed too.
    Returns the program's stdout (LF). Raises on failure or unconfirmed cleanup."""
    import base64,hashlib,re,secrets,textwrap
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not re.fullmatch(r'[a-z0-9-]{1,32}',label) or args not in ('','"$d"','/sdcard/mh-androidevolved/manhunt.exe','/sdcard/mh-androidevolved/manhunt.exe /sdcard/mh-androidevolved') or max_size>32*1024*1024:raise WorkSafeError('invalid device run parameters')
    env=env or {};saves=saves or {}
    if len(saves)>8 or any(not re.fullmatch(r'[a-z0-9][a-z0-9_. ]{0,63}',n) or len(d)>1024*1024 for n,d in saves.items()):raise WorkSafeError('invalid device saves')
    if any(not re.fullmatch(r'MH_[A-Z_]{1,24}',k) or not re.fullmatch(r'[0-9a-f:,]{0,1024}',v) for k,v in env.items()):raise WorkSafeError('invalid device environment')
    prefix=''.join(f'{k}={v} ' for k,v in sorted(env.items()))
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    if not adb.is_file():raise WorkSafeError('adb missing')
    if binary[:4]!=b'\x7fELF' or int.from_bytes(binary[18:20],'little')!=183 or len(binary)>max_size:raise WorkSafeError('not a bounded ARM64 ELF')
    digest=hashlib.sha256(binary).hexdigest()
    listing=_run_job([str(adb),'devices','-l'],15,f'device-{label}-list',cfg,max_processes=4,memory_mb=256)
    text=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    ready=[p[0] for line in text.splitlines()[1:] if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    model_check=_run_job([str(adb),'-s',ready[0],'shell','getprop','ro.product.model'],15,f'device-{label}-model',cfg,max_processes=4,memory_mb=256)
    model=Path(model_check['log']+'.stdout.log').read_text(encoding='utf-8').strip()
    if model_check['timed_out'] or model_check['returncode']!=0 or not re.fullmatch(r'SM-S(?:93[1678]|731)[A-Za-z0-9/]*',model):
        raise WorkSafeError('device is not a supported S25; nothing uploaded')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    # Small binaries travel inside the shell script (base64); large ones (over the bounded stdin) are
    # pushed with `adb push` into the fresh directory first. Either way the script checks the SHA-256,
    # runs the binary once and removes exactly that file and directory.
    pushed=len(binary)>1024*1024
    if pushed:
        local=ROOT/f'logs/device-{label}.bin';local.write_bytes(binary)
        try:
            made=_run_job([str(adb),'-s',ready[0],'shell','mkdir',remote],30,f'device-{label}-mkdir',cfg,max_processes=4,memory_mb=256)
            if made['returncode']!=0 or made['timed_out']:raise WorkSafeError(f'{label}: cannot create the remote directory')
            push=_run_job([str(adb),'-s',ready[0],'push',str(local),remote+'/test'],600,f'device-{label}-push',cfg,max_processes=4,memory_mb=512)
        finally:
            local.unlink(missing_ok=True)
        if push['returncode']!=0 or push['timed_out']:
            _run_job([str(adb),'-s',ready[0],'shell',f'rm -f {remote}/test; rmdir {remote}'],30,f'device-{label}-cleanup',cfg,max_processes=4,memory_mb=256)
            raise WorkSafeError(f'{label}: adb push failed')
        payload='[ -d "$d" ] && [ -f "$p" ] || exit 82\n'
    else:
        encoded='\n'.join(textwrap.wrap(base64.b64encode(binary).decode('ascii'),76))
        payload='mkdir "$d" || exit 82\n'
    script=('case "$(getprop ro.product.model)" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 80;; esac\n'
        'case ",$(getprop ro.product.cpu.abilist)," in *,arm64-v8a,*) ;; *) exit 81;; esac\n'
        f'd={remote}\np="$d/test"\n'
        +payload+
        'cleanup() { rm -f "$p" && { [ ! -d "$d/saves" ] || { rm -f "$d"/saves/* && rmdir "$d/saves"; }; } && rmdir "$d"; }\n'
        'finish() { rc=$?; trap - EXIT; if cleanup; then echo MHAE_CLEANUP_OK; else echo MHAE_CLEANUP_FAILED >&2; [ "$rc" -eq 0 ] && rc=91; fi; exit "$rc"; }\n'
        'trap finish EXIT\ntrap "exit 93" HUP INT TERM\n'
        +''.join(f'mkdir -p "$d/saves" || exit 87\nbase64 -d > "$d/saves/{n}" <<\'MHAE_SAVE\' || exit 88\n'+'\n'.join(textwrap.wrap(base64.b64encode(data).decode('ascii'),76))+'\nMHAE_SAVE\n' for n,data in sorted(saves.items()))
        +('' if pushed else "base64 -d > \"$p\" <<'MHAE_PAYLOAD' || exit 83\n"+encoded+'\nMHAE_PAYLOAD\n')+
        'set -- $(sha256sum "$p")\n'
        f'[ "${{1:-}}" = "{digest}" ] || exit 84\n'
        'chmod 700 "$p" || exit 85\n'
        f'echo MHAE_BEGIN\n{prefix}"$p" {args}; rc=$?\necho MHAE_END\n'
        '[ "$rc" -eq 0 ] || { echo MHAE_PROGRAM_FAILED=$rc; exit 86; }\n'
        'echo MHAE_TESTS_PASSED\nexit 0\n').encode('ascii')
    attempt=ROOT/f'logs/device-{label}-attempt.json'
    attempt.write_text(json.dumps({'serial':ready[0],'remote_directory':remote,'cleanup':'unconfirmed'},indent=2)+'\n',encoding='utf-8')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],timeout,f'device-{label}-session',cfg,max_processes=4,memory_mb=512,input_bytes=script)
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').replace('\r\n','\n')
    cleanup='confirmed' if 'MHAE_CLEANUP_OK' in output else 'unconfirmed'
    attempt.write_text(json.dumps({'serial':ready[0],'remote_directory':remote,'cleanup':cleanup},indent=2)+'\n',encoding='utf-8')
    if result['timed_out'] or result['returncode']!=0 or cleanup!='confirmed' or 'MHAE_TESTS_PASSED' not in output:
        raise WorkSafeError(f'{label} device session failed or cleanup unconfirmed; inspect device-{label}-session logs')
    m=re.search(r'^MHAE_BEGIN\n(.*?)^MHAE_END$',output,re.MULTILINE|re.DOTALL)
    if not m:raise WorkSafeError('missing program output')
    return m.group(1)

def test_allocator(on_device=True):
    """Compare the translated pool allocator with the x86 reference on Windows x64 and, optionally, the S25."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private/analysis/allocator';report=json.loads((base/'allocator_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256((base/'allocator_unit.c').read_bytes()).hexdigest()!=report['unit_sha256']:raise WorkSafeError('allocator unit changed since lift')
    reference=json.loads((base/'x86_reference.json').read_text(encoding='utf-8'))
    if reference.get('unit_sha256')!=report['unit_sha256']:raise WorkSafeError('x86 reference is stale; rerun tools/probe_allocator_x86.py')
    includes=['-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-I',str(base)]
    cl,env=_msvc_env();exe=base/'allocator-test.exe'
    built=_run_job([str(cl),'/nologo','/Od','/std:c11',*[a.replace('-I','/I') for a in includes],'/Fo'+str(base)+'\\','/Fe'+str(exe),
                    str(ROOT/'tests/allocator_native.c'),'/link','/INCREMENTAL:NO'],120,'allocator-host-build',cfg,max_processes=4,memory_mb=768,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('allocator host build failed; inspect allocator-host-build logs')
    ran=_run_job([str(exe)],60,'allocator-host-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('allocator host run failed with code '+str(ran['returncode']))
    host=_run_job([sys.executable,str(ROOT/'tests/compare_allocator.py'),ran['log']+'.stdout.log','windows-x64'],60,'allocator-host-compare',cfg,max_processes=1,memory_mb=512)
    results={'windows-x64':Path(host['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').strip() if host['returncode']==0 else 'MISMATCH'}
    if host['returncode']!=0:raise WorkSafeError('allocator differs on Windows x64; inspect allocator-host-compare logs')
    if on_device:
        ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
        out=base/'android';out.mkdir(exist_ok=True);binary=out/'allocator_test'
        arm=_run_job([str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie',*includes,
                      str(ROOT/'tests/allocator_native.c'),'-o',str(binary)],180,'allocator-arm64-build',cfg,max_processes=4,memory_mb=768)
        if arm['returncode']!=0 or arm['timed_out']:raise WorkSafeError('allocator ARM64 build failed')
        output=_run_binary_on_s25(binary.read_bytes(),'allocator')
        jsonl=ROOT/'logs/allocator-arm64.jsonl';jsonl.write_text(output,encoding='utf-8')
        dev=_run_job([sys.executable,str(ROOT/'tests/compare_allocator.py'),str(jsonl),'android-arm64'],60,'allocator-arm64-compare',cfg,max_processes=1,memory_mb=512)
        if dev['returncode']!=0:raise WorkSafeError('allocator differs on the S25; inspect allocator-arm64-compare logs')
        results['android-arm64']=Path(dev['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').strip()
        (out/'validated.json').write_text(json.dumps({'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'output_sha256':hashlib.sha256(output.encode('utf-8')).hexdigest(),'compared_against':'tools/probe_allocator_x86.py'},indent=2)+'\n',encoding='utf-8')
    return results

def _validate_unit_harness(name,source,runtime_sources=(),on_device=True,game_arg=False):
    """Build a portable harness for private/analysis/<name>, run it on Windows x64 and
    optionally on the S25, compare both with <name>/x86_reference.json and record the
    validated ARM64 binary for the diagnostic APK."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private/analysis'/name;report=json.loads((base/f'{name}_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256((base/f'{name}_unit.c').read_bytes()).hexdigest()!=report['unit_sha256']:raise WorkSafeError(f'{name} unit changed since lift')
    reference=base/'x86_reference.json'
    if json.loads(reference.read_text(encoding='utf-8')).get('unit_sha256')!=report['unit_sha256']:raise WorkSafeError(f'{name} x86 reference is stale')
    includes=[str(ROOT/'private/pcrecomp/runtime/recomp32'),str(ROOT/'recomp'),str(ROOT/'runtime'),str(base)]
    cl,env=_msvc_env();exe=base/f'{name}-test.exe'
    built=_run_job([str(cl),'/nologo','/Od','/std:c11',*[x for d in includes for x in ('/I',d)],'/Fo'+str(base)+'\\','/Fe'+str(exe),
                    str(ROOT/source),'/link','/INCREMENTAL:NO'],180,f'{name}-host-build',cfg,max_processes=4,memory_mb=768,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError(f'{name} host build failed; inspect {name}-host-build logs')
    game=ROOT/'Manhunt Collection'/'Manhunt'/'manhunt.exe'
    ran=_run_job([str(exe)]+([str(game)] if game_arg else []),300,f'{name}-host-run',cfg,max_processes=1,memory_mb=1024)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError(f'{name} host run failed with code {ran["returncode"]}')
    def compare(path,platform):
        r=_run_job([sys.executable,str(ROOT/'tests/compare_harness.py'),str(reference),str(path),platform],120,f'{name}-{platform}-compare',cfg,max_processes=1,memory_mb=768)
        text=(Path(r['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')+Path(r['log']+'.stderr.log').read_text(encoding='utf-8',errors='replace')).strip()
        if r['returncode']!=0 or r['timed_out']:raise WorkSafeError(f'{name} differs on {platform}: {text[-300:]}')
        return text
    results={'windows-x64':compare(ran['log']+'.stdout.log','windows-x64')}
    if on_device:
        ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
        out=base/'android';out.mkdir(exist_ok=True);binary=out/f'{name}_test'
        arm=_run_job([str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIE','-pie',
                      *[x for d in includes for x in ('-I',d)],str(ROOT/source),'-o',str(binary),'-lm'],180,f'{name}-arm64-build',cfg,max_processes=4,memory_mb=768)
        if arm['returncode']!=0 or arm['timed_out']:raise WorkSafeError(f'{name} ARM64 build failed')
        output=_run_binary_on_s25(binary.read_bytes(),name.replace('_','-'),'/sdcard/mh-androidevolved/manhunt.exe' if game_arg else '')
        jsonl=ROOT/f'logs/{name}-arm64.jsonl';jsonl.write_text(output,encoding='utf-8')
        results['android-arm64']=compare(jsonl,'android-arm64')
        (out/'validated.json').write_text(json.dumps({'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'output_sha256':hashlib.sha256(output.encode('utf-8')).hexdigest(),'compared_against':f'private/analysis/{name}/x86_reference.json'},indent=2)+'\n',encoding='utf-8')
    return results

def test_static_init(on_device=True):
    """Boot phase 1: map manhunt.exe and run the supported C++ static initialisers, on Windows x64 and the S25."""
    return _validate_unit_harness('static_init','tests/static_init_native.c',on_device=on_device,game_arg=True)

def test_boot_phase2(on_device=True):
    """Boot phase 2: CRT start-up and all 98 static initialisers translated, past the protection, on Windows x64 and the S25."""
    return _validate_unit_harness('boot_phase2','tests/boot_phase2_native.c',on_device=on_device,game_arg=True)

def test_winmain(on_device=True,calls=False):
    """The boot and WinMain, translated, over runtime/port_api.c, on Windows x64 and the S25, compared with
    the x86 references: private/analysis/winmain/x86_reference.json and every scenario (another language
    or input script) in winmain/scenarios/<name>/x86_reference.json, each replayed as it was traced
    (frames, MH_KEYS, MH_LANG). With calls, the host also writes every call of the main reference."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    base=ROOT/'private/analysis/winmain';report=json.loads((base/'winmain_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256((base/'winmain_unit.c').read_bytes()).hexdigest()!=report['unit_sha256']:raise WorkSafeError('winmain unit changed since lift')
    references={'main':base/'x86_reference.json',**{p.parent.name:p for p in sorted((base/'scenarios').glob('*/x86_reference.json'))}}
    for name,reference in references.items():
        if json.loads(reference.read_text(encoding='utf-8')).get('unit_sha256')!=report['unit_sha256']:raise WorkSafeError(f'winmain x86 reference {name} is stale')
    includes=[str(ROOT/'private/pcrecomp/runtime/recomp32'),str(ROOT/'recomp'),str(ROOT/'runtime'),str(base)]
    inputs=_winmain_input_hashes()
    def unchanged():
        if inputs!=_winmain_input_hashes():raise WorkSafeError('winmain inputs changed during validation')
    cl,env=_msvc_env();exe=base/'winmain-test.exe'
    built=_run_job([str(cl),'/nologo','/Od','/std:c11',*[x for d in includes for x in ('/I',d)],'/Fo'+str(base)+'\\','/Fe'+str(exe),
                    str(ROOT/'tests/winmain_native.c'),'/link','/INCREMENTAL:NO'],1800,'winmain-host-build',cfg,max_processes=4,memory_mb=4096,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('winmain host build failed; inspect winmain-host-build logs')
    unchanged()
    game=ROOT/'Manhunt Collection'/'Manhunt'
    def replay(reference):   # as the reference was traced
        ref=json.loads(reference.read_text(encoding='utf-8'))
        return {'MH_FRAMES':str(ref['cases'][0]['frames']),'MH_KEYS':ref.get('keys',''),'MH_LANG':ref.get('lang','0409'),**({'MH_SAVES':'1'} if ref.get('saves') else {})}
    def seeds(reference):   # the saves present at the start of a scenario (winmain/seed_saves), or none
        ref=json.loads(reference.read_text(encoding='utf-8'))
        return {p.name:p.read_bytes() for p in sorted((base/'seed_saves').glob('*'))} if ref.get('saves') else {}
    def compare(reference,path,platform,name):
        r=_run_job([sys.executable,str(ROOT/'tests/compare_harness.py'),str(reference),str(path),platform],120,f'winmain-{name}-{platform}-compare',cfg,max_processes=1,memory_mb=768)
        text=(Path(r['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')+Path(r['log']+'.stderr.log').read_text(encoding='utf-8',errors='replace')).strip()
        if r['returncode']!=0 or r['timed_out']:raise WorkSafeError(f'winmain {name} differs on {platform}: {text[-300:]}')
        return text
    results={}
    for name,reference in references.items():
        run_env=dict(os.environ);run_env.update(replay(reference))
        if run_env.get('MH_SAVES'):run_env['MH_SAVES']=str(base/'seed_saves')
        if calls and name=='main':run_env['MH_CALLLOG']=str(ROOT/'logs/winmain-calls-windows-x64.txt')
        ran=_run_job([str(exe),str(game/'manhunt.exe'),str(game)],1800,f'winmain-{name}-host-run',cfg,max_processes=1,memory_mb=2048,env=run_env)
        if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError(f'winmain {name} host run failed with code {ran["returncode"]}')
        results[name+' windows-x64']=compare(reference,ran['log']+'.stdout.log','windows-x64',name)
    unchanged()
    if on_device:
        ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
        out=base/'android';out.mkdir(exist_ok=True);binary=out/'winmain_test'
        arm=_run_job([str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O1','-fPIE','-pie',
                      *[x for d in includes for x in ('-I',d)],str(ROOT/'tests/winmain_native.c'),'-o',str(binary),'-lm'],1800,'winmain-arm64-build',cfg,max_processes=4,memory_mb=6144)
        if arm['returncode']!=0 or arm['timed_out']:raise WorkSafeError('winmain ARM64 build failed')
        unchanged()
        binary_hash=hashlib.sha256(binary.read_bytes()).hexdigest()
        outputs={}
        checkpoint={'binary_sha256':binary_hash,'source_inputs':inputs,'output_sha256':outputs,
                    'host_binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                    'host_output_sha256':{name:hashlib.sha256((ROOT/f'logs/winmain-{name}-host-run.stdout.log').read_bytes()).hexdigest() for name in references}}
        pending=out/'pending-validation.json'
        pending.write_text(json.dumps(checkpoint,indent=2)+'\n',encoding='utf-8')
        for name,reference in references.items():
            unchanged()
            if hashlib.sha256(binary.read_bytes()).hexdigest()!=binary_hash:raise WorkSafeError('winmain binary changed during validation')
            try:
                output=_run_binary_on_s25(binary.read_bytes(),'winmain','/sdcard/mh-androidevolved/manhunt.exe /sdcard/mh-androidevolved',max_size=32*1024*1024,timeout=1800,env=replay(reference),saves=seeds(reference))
            except WorkSafeError:
                attempt=ROOT/'logs/device-winmain-attempt.json'
                if attempt.is_file():checkpoint['cleanup_attempt']=json.loads(attempt.read_text(encoding='utf-8'))
                pending.write_text(json.dumps(checkpoint,indent=2)+'\n',encoding='utf-8')
                raise
            jsonl=ROOT/f'logs/winmain-{name}-arm64.jsonl';jsonl.write_text(output,encoding='utf-8')
            results[name+' android-arm64']=compare(reference,jsonl,'android-arm64',name)
            outputs[name]=hashlib.sha256(output.encode('utf-8')).hexdigest()
            pending.write_text(json.dumps(checkpoint,indent=2)+'\n',encoding='utf-8')
        unchanged()
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=binary_hash:raise WorkSafeError('winmain binary changed during validation')
        (out/'validated.json').write_text(json.dumps({'binary_sha256':binary_hash,'source_inputs':inputs,
            'output_sha256':outputs,'compared_against':{k:str(v.relative_to(ROOT)) for k,v in references.items()}},indent=2)+'\n',encoding='utf-8')
        pending.unlink()
    return results

def _finish_interrupted_winmain_cleanup(attempt,binary_hash,cfg):
    """Reconcile one recorded test directory on its original device; never recursively delete."""
    import re
    if not attempt or attempt.get('cleanup')=='confirmed':return
    remote=attempt.get('remote_directory','');serial=attempt.get('serial','')
    if not re.fullmatch(r'/data/local/tmp/mhae_[0-9a-f]{16}',remote) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',serial) or not re.fullmatch(r'[0-9a-f]{64}',binary_hash):
        raise WorkSafeError('interrupted test directory/device is unrecorded')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    # The fixed device serial and the model check precede all filesystem operations.
    script=('set -e\ncase "$(getprop ro.product.model)" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 80;; esac\n'
            f'd={remote}\nif [ -e "$d" ]; then\n[ ! -L "$d" ] && [ -d "$d" ] || exit 83\n'
            'if [ -e "$d/test" ]; then\n[ ! -L "$d/test" ] && [ -f "$d/test" ] || exit 81\n'
            f'set -- $(sha256sum "$d/test")\n[ "${{1:-}}" = "{binary_hash}" ] || exit 82\n'
            'rm -f "$d/test"\nfi\nrmdir "$d"\nfi\necho MHAE_CLEANUP_OK\n').encode('ascii')
    ran=_run_job([str(adb),'-s',serial,'shell','-T','sh'],20,'winmain-interrupted-cleanup',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    output=Path(ran['log']+'.stdout.log').read_text(encoding='utf-8')
    if ran['returncode']!=0 or ran['timed_out'] or 'MHAE_CLEANUP_OK' not in output:
        raise WorkSafeError('interrupted winmain cleanup still unconfirmed on the original S25')
    attempt['cleanup']='confirmed'

def resume_winmain_on_s25():
    """Resume a checkpoint of this exact compiled binary and inputs, preserving verified scenarios."""
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    base=ROOT/'private/analysis/winmain';binary=base/'android/winmain_test';pending=base/'android/pending-validation.json'
    if not pending.is_file():raise WorkSafeError('no pending winmain validation; run test_winmain')
    record=json.loads(pending.read_text(encoding='utf-8'))
    def unchanged():
        if record.get('source_inputs')!=_winmain_input_hashes():raise WorkSafeError('pending winmain inputs changed')
        if not binary.is_file() or record.get('binary_sha256')!=hashlib.sha256(binary.read_bytes()).hexdigest():raise WorkSafeError('pending winmain binary changed')
    unchanged()
    host=base/'winmain-test.exe'
    if not host.is_file() or record.get('host_binary_sha256')!=hashlib.sha256(host.read_bytes()).hexdigest():raise WorkSafeError('pending winmain host binary changed')
    references={'main':base/'x86_reference.json',**{p.parent.name:p for p in sorted((base/'scenarios').glob('*/x86_reference.json'))}}
    if set(record.get('host_output_sha256',{}))!=set(references):raise WorkSafeError('pending host results incomplete')
    def compare(reference,path,name,platform):
        r=_run_job([sys.executable,str(ROOT/'tests/compare_harness.py'),str(reference),str(path),platform],30,
                    f'winmain-{name}-{platform}-resume-compare',cfg,max_processes=1,memory_mb=256)
        if r['returncode']!=0 or r['timed_out']:raise WorkSafeError('pending winmain comparison failed: '+name+' '+platform)
        return Path(r['log']+'.stdout.log').read_text(encoding='utf-8').strip()
    import sys
    for name,reference in references.items():
        path=ROOT/f'logs/winmain-{name}-host-run.stdout.log'
        if not path.is_file() or record['host_output_sha256'][name]!=hashlib.sha256(path.read_bytes()).hexdigest():raise WorkSafeError('pending host output changed: '+name)
        compare(reference,path,name,'windows-x64')
    _finish_interrupted_winmain_cleanup(record.get('cleanup_attempt'),record['binary_sha256'],cfg)
    results={};outputs=record.setdefault('output_sha256',{})
    for name,reference in references.items():
        unchanged();path=ROOT/f'logs/winmain-{name}-arm64.jsonl'
        if name in outputs and path.is_file() and outputs[name]==hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest():
            results[name]=compare(reference,path,name,'android-arm64')
            continue
        ref=json.loads(reference.read_text(encoding='utf-8'))
        env={'MH_FRAMES':str(ref['cases'][0]['frames']),'MH_KEYS':ref.get('keys',''),'MH_LANG':ref.get('lang','0409')}
        saves={}
        if ref.get('saves'):
            env['MH_SAVES']='1';saves={p.name:p.read_bytes() for p in sorted((base/'seed_saves').glob('*'))}
        try:
            output=_run_binary_on_s25(binary.read_bytes(),'winmain','/sdcard/mh-androidevolved/manhunt.exe /sdcard/mh-androidevolved',
                        max_size=32*1024*1024,timeout=1800,env=env,saves=saves)
        except WorkSafeError:
            attempt=ROOT/'logs/device-winmain-attempt.json'
            if attempt.is_file():record['cleanup_attempt']=json.loads(attempt.read_text(encoding='utf-8'))
            pending.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
            raise
        path.write_text(output,encoding='utf-8');results[name]=compare(reference,path,name,'android-arm64')
        outputs[name]=hashlib.sha256(output.encode('utf-8')).hexdigest()
        pending.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    unchanged()
    (base/'android/validated.json').write_text(json.dumps({'binary_sha256':record['binary_sha256'],'source_inputs':record['source_inputs'],
        'output_sha256':outputs,'compared_against':{k:str(v.relative_to(ROOT)) for k,v in references.items()}},indent=2)+'\n',encoding='utf-8')
    pending.unlink()
    return results

def stage_save_load_candidates():
    """Static-only candidate generation and ARM64 object build; never link, run or package it."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    generated=_run_job([sys.executable,str(ROOT/'tools/lift_save_load_candidates.py')],180,'save-load-stage',cfg,max_processes=1,memory_mb=1024)
    if generated['returncode']!=0 or generated['timed_out']:raise WorkSafeError('save/load candidate generation failed')
    base=ROOT/'private/analysis/save_load_candidates';entry=base/'compile_only.c'
    inputs=_time_harness_input_hashes(entry,include_dirs=(base,))
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
    includes=[ROOT/'private/pcrecomp/runtime/recomp32',ROOT/'recomp',ROOT/'runtime',base];obj=base/'save_load_candidates.o'
    built=_run_job([str(ndk/'bin/clang.exe'),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-O0','-fPIC','-c',
                    *[x for p in includes for x in ('-I',str(p))],str(entry),'-o',str(obj)],90,'save-load-arm64-object',cfg,max_processes=4,memory_mb=768)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('save/load candidate ARM64 compilation failed')
    if inputs!=_time_harness_input_hashes(entry,include_dirs=(base,)):raise WorkSafeError('candidate sources changed during compilation')
    record={'object_sha256':hashlib.sha256(obj.read_bytes()).hexdigest(),'source_inputs':inputs,'status':'ARM64 object only; not linked or executed'}
    (base/'compiled.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return {**json.loads((base/'staging.json').read_text(encoding='utf-8')),**record}

def test_graphics_d3d8(on_device=True):
    """The game's refresh-rate selector over the port's Direct3D 8 shim, on Windows x64 and the S25."""
    return _validate_unit_harness('graphics_d3d8','tests/graphics_d3d8_native.c',on_device=on_device)

def test_heap(on_device=True):
    """The game's own heap (malloc 0x610be0) over the Win32 memory shims, on Windows x64 and the S25."""
    return _validate_unit_harness('heap','tests/heap_native.c',on_device=on_device)

def update_diagnostic_on_s25():
    """Replace the installed diagnostic package in place (same debug signature), keeping its data.

    Refuses when the package is absent, so it never installs anything new; no
    other package is touched and nothing is launched."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    apk=ROOT/'build/android-diagnostic-apk/diagnostic-debug.apk'
    if not apk.is_file():raise WorkSafeError('diagnostic APK missing')
    def run(args,name,seconds=30,input_bytes=None):
        result=_run_job([str(adb),*args],seconds,name,cfg,max_processes=4,memory_mb=256,input_bytes=input_bytes)
        if result['timed_out'] or result['returncode']!=0:raise WorkSafeError(name+' failed; inspect logs')
        return Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    listing=run(['devices','-l'],'diagnostic-update-list')
    ready=[p[0] for line in listing.splitlines()[1:] if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    serial=ready[0]
    script=(b'set -e\nmodel=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'[ "$(getprop ro.product.cpu.abi)" = arm64-v8a ] || exit 71\n'
            b'pm path com.manhuntae.android | grep -q . || exit 73\n'
            b'echo MHAE_PACKAGE_PRESENT\n')
    if 'MHAE_PACKAGE_PRESENT' not in run(['-s',serial,'shell','-T','sh'],'diagnostic-update-preflight',input_bytes=script):
        raise WorkSafeError('package state uncertain')
    output=run(['-s',serial,'install','-r',str(apk)],'diagnostic-update',120)
    if 'Success' not in output:raise WorkSafeError('update result uncertain')
    return {'update':'success','package':'com.manhuntae.android','scope':'diagnostic only'}

def launch_diagnostic_on_s25():
    """Start the installed diagnostic activity on one authorized S25."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    listing=_run_job([str(adb),'devices','-l'],15,'diagnostic-launch-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('device list failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    script=(b'set -e\nmodel=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'am start -W -n com.manhuntae.android/.MainActivity\n'
            b'echo MHAE_PID\npidof com.manhuntae.android\n')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],45,'diagnostic-launch',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('diagnostic launch failed; inspect logs')
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    if 'Status: ok' not in output or not re.search(r'MHAE_PID\s+\d+',output):raise WorkSafeError('activity or process not confirmed')
    return output

def launch_game_on_s25():
    """Launch the installed app and tap its visible Play button on the S25. No host UI/input."""
    import re,xml.etree.ElementTree as ET
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM for game UI inspection')
    launch_diagnostic_on_s25()
    inspect_diagnostic_ui_on_s25()   # verifies the foreground package before interpreting its UI
    root=ET.fromstring((ROOT/'logs/diagnostic-ui-inspect.stdout.log').read_text(encoding='utf-8'))
    buttons=[node for node in root.iter('node') if node.get('text','').startswith('Jugar') and
             node.get('clickable')=='true' and node.get('enabled')=='true']
    if len(buttons)!=1:raise WorkSafeError('need one visible enabled Play button')
    bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',buttons[0].get('bounds',''))
    if not bounds:raise WorkSafeError('invalid Play button bounds')
    x0,y0,x1,y1=map(int,bounds.groups())
    if not (0<=x0<x1<=10000 and 0<=y0<y1<=10000):raise WorkSafeError('Play button is outside the viewport')
    listing=(ROOT/'logs/diagnostic-ui-list.stdout.log').read_text(encoding='utf-8').splitlines()[1:]
    ready=[p[0] for line in listing if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('ambiguous device')
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'
    script=('set -e\ndumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | '
            'grep -q "com.manhuntae.android/" || exit 71\n'
            f'input tap {(x0+x1)//2} {(y0+y1)//2}\n').encode('ascii')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],
                    15,'game-launch-tap',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('Play tap failed')
    return {'launch':'Play tapped','serial':ready[0],'verification':'inspect game log and frame next'}

def inspect_diagnostic_ui_on_s25():
    """Inspect the foreground diagnostic app's accessibility text, then clean up."""
    import re, secrets, xml.etree.ElementTree as ET
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    adb=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'platform-tools'/'adb.exe'
    listing=_run_job([str(adb),'devices','-l'],15,'diagnostic-ui-list',cfg,max_processes=4,memory_mb=256)
    if listing['timed_out'] or listing['returncode']!=0:raise WorkSafeError('device list failed')
    lines=Path(listing['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').splitlines()[1:]
    ready=[p[0] for line in lines if len(p:=line.split())>=2 and p[1]=='device']
    if len(ready)!=1 or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',ready[0]):raise WorkSafeError('need exactly one authorized ADB device')
    remote='/data/local/tmp/mhae_'+secrets.token_hex(8)
    script=(b'set -e\nmodel=$(getprop ro.product.model)\n'
            b'case "$model" in SM-S931*|SM-S936*|SM-S937*|SM-S938*|SM-S731*) ;; *) exit 70;; esac\n'
            b'dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | grep -q "com.manhuntae.android/" || exit 71\n'
            +f'd={remote}\n'.encode()+
            b'mkdir "$d"\ntrap \'rm -f "$d/ui.xml"; rmdir "$d"\' EXIT\n'
            b'uiautomator dump "$d/ui.xml" >/dev/null\n'
            b'dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | grep -q "com.manhuntae.android/" || exit 72\n'
            b'cat "$d/ui.xml"\n')
    result=_run_job([str(adb),'-s',ready[0],'shell','-T','sh'],90,'diagnostic-ui-inspect',cfg,max_processes=4,memory_mb=256,input_bytes=script)
    if result['timed_out'] or result['returncode']!=0:raise WorkSafeError('foreground diagnostic UI inspection failed; inspect logs')
    output=Path(result['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace')
    try:root=ET.fromstring(output)
    except ET.ParseError as exc:raise WorkSafeError('unexpected UI dump') from exc
    packages={node.attrib.get('package') for node in root.iter('node') if node.attrib.get('package')}
    if packages!={'com.manhuntae.android'}:raise WorkSafeError('UI includes another package; not interpreting contents')
    return [node.attrib['text'] for node in root.iter('node') if node.attrib.get('text')]

def link_graphics_candidates():
    """Link only the two precompiled ARM64 candidates into a relocatable object."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    linker=ndk/'bin'/'ld.lld.exe';base=ROOT/'private'/'analysis'
    one=base/'candidate_graphics'/'candidate-arm64.o';two=base/'d3d8_thunk'/'candidate-arm64.o'
    if not linker.is_file() or not one.is_file() or not two.is_file(): raise WorkSafeError('linker or candidate object missing')
    output=base/'candidate_graphics'/'graphics-with-thunk-arm64.o'
    linked=_run_job([str(linker),'-r',str(one),str(two),'-o',str(output)],30,'pcrecomp-graphics-link',cfg,max_processes=1,memory_mb=256)
    if linked['returncode']!=0 or linked['timed_out']: return {'link':linked,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_graphics_object.py')],30,'pcrecomp-graphics-verify',cfg,max_processes=1,memory_mb=256)
    return {'link':linked,'verify':verified}

def link_input_candidates():
    """Link the two precompiled input candidates into an ARM64 relocatable object."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';linker=ndk/'bin'/'ld.lld.exe';base=ROOT/'private'/'analysis'
    one=base/'candidate_input'/'candidate-arm64.o';two=base/'dinput8_thunk'/'candidate-arm64.o'
    if not linker.is_file() or not one.is_file() or not two.is_file():raise WorkSafeError('linker or candidate object missing')
    output=base/'candidate_input'/'input-with-thunk-arm64.o'
    linked=_run_job([str(linker),'-r',str(one),str(two),'-o',str(output)],30,'pcrecomp-input-link',cfg,max_processes=1,memory_mb=256)
    if linked['returncode']!=0 or linked['timed_out']:return {'link':linked,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_graphics_object.py'),'--input'],30,'pcrecomp-input-verify',cfg,max_processes=1,memory_mb=256)
    return {'link':linked,'verify':verified}

def compile_checked_graphics_arm64():
    """Compile the two audited graphics candidates with strict adapters."""
    import hashlib,re,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private'/'analysis';sources=[]
    allowed={'MEM32','POP32_VAL','PUSH32','RECOMP_CALL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT','RECOMP_ICALL','RECOMP_ITAIL'}
    for name,address in (('candidate_graphics','0x4c0830'),('d3d8_thunk','0x64408c')):
        folder=base/name;report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
        source=(folder/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
        if report['address']!=address or hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['source_sha256']:
            raise WorkSafeError('unexpected generated source')
        used=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not used.issubset(allowed): raise WorkSafeError('unsupported generated operations: '+str(sorted(used-allowed)))
        sources.append(source)
    folder=base/'candidate_graphics';wrapper=folder/'graphics_checked_unit.c'
    wrapper.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_0064408C(void);\n'+'\n'.join(sources)+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';clang=ndk/'bin'/'clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(wrapper),'-o',str(folder/'graphics-checked-arm64.o')]
    built=_run_job(argv,60,'pcrecomp-graphics-checked-build',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_graphics_object.py'),'--checked'],30,'pcrecomp-graphics-checked-verify',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'verify':verified}

def compile_precise_graphics_arm64():
    """Prepare audited return-address adaptations and compile one ARM64 object."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    prepared=_run_job([sys.executable,str(ROOT/'tools'/'prepare_graphics_precise.py')],30,'graphics-precise-prepare',cfg,max_processes=1,memory_mb=384)
    if prepared['returncode']!=0 or prepared['timed_out']:return {'prepare':prepared,'build':None,'verify':None}
    base=ROOT/'private'/'analysis';folder=base/'candidate_graphics';thunk=base/'d3d8_thunk'
    report=json.loads((folder/'precise_report.json').read_text(encoding='utf-8'));t_report=json.loads((thunk/'report.json').read_text(encoding='utf-8'))
    source=(folder/'candidate_precise.c').read_text(encoding='utf-8').removesuffix('\n');t_source=(thunk/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['adapted_sha256'] or hashlib.sha256(t_source.encode('utf-8')).hexdigest()!=t_report['source_sha256']:raise WorkSafeError('source hash mismatch')
    wrapper=folder/'graphics_precise_unit.c'
    wrapper.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_0064408C(void);\n'+source+'\n'+t_source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';clang=ndk/'bin'/'clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(wrapper),'-o',str(folder/'graphics-precise-arm64.o')]
    built=_run_job(argv,60,'graphics-precise-arm64',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:return {'prepare':prepared,'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_graphics_object.py'),'--precise'],30,'graphics-precise-verify',cfg,max_processes=1,memory_mb=256)
    return {'prepare':prepared,'build':built,'verify':verified}

def compile_precise_input_arm64():
    """Adapt audited DirectInput candidate calls and compile an ARM64 object."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    prepared=_run_job([sys.executable,str(ROOT/'tools'/'prepare_input_precise.py')],30,'input-precise-prepare',cfg,max_processes=1,memory_mb=384)
    if prepared['returncode']!=0 or prepared['timed_out']:return {'prepare':prepared,'build':None,'verify':None}
    base=ROOT/'private'/'analysis';folder=base/'candidate_input';thunk=base/'dinput8_thunk'
    report=json.loads((folder/'precise_report.json').read_text(encoding='utf-8'));t_report=json.loads((thunk/'report.json').read_text(encoding='utf-8'))
    source=(folder/'candidate_precise.c').read_text(encoding='utf-8').removesuffix('\n');t_source=(thunk/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['adapted_sha256'] or hashlib.sha256(t_source.encode('utf-8')).hexdigest()!=t_report['source_sha256']:raise WorkSafeError('source hash mismatch')
    wrapper=folder/'input_precise_unit.c'
    prefix='#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_00644098(void);\nvoid sub_0060F110(void);\n'
    wrapper.write_text(prefix+source+'\n'+t_source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64';clang=ndk/'bin'/'clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(wrapper),'-o',str(folder/'input-precise-arm64.o')]
    built=_run_job(argv,60,'input-precise-arm64',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:return {'prepare':prepared,'build':built,'verify':None}
    verified=_run_job([sys.executable,str(ROOT/'tools'/'verify_graphics_object.py'),'--input-precise'],30,'input-precise-verify',cfg,max_processes=1,memory_mb=256)
    return {'prepare':prepared,'build':built,'verify':verified}

def compile_game_candidate(kind='candidate'):
    """Compile the locally generated single candidate for ARM64, without linking."""
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM for compilation')
    if kind not in ('candidate', 'candidate_deterministic', 'candidate_x87', 'candidate_graphics', 'candidate_input', 'candidate_time', 'd3d8_thunk', 'dinput8_thunk'): raise WorkSafeError('unknown candidate')
    base=ROOT/'private'/'analysis'/kind
    report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    source=(base/'candidate.c').read_text(encoding='utf-8')
    if hashlib.sha256(source.removesuffix('\n').encode('utf-8')).hexdigest() != report['source_sha256']:
        raise WorkSafeError('candidate source differs from generated report')
    wrapper=base/'translation_unit.c'
    prototype=('void sub_0064408C(void);\n' if kind=='candidate_graphics' else
               ('void sub_00644098(void);\nvoid sub_0060F110(void);\n' if kind=='candidate_input' else
                ('void sub_00426EF0(void);\nvoid sub_00481330(void);\nvoid sub_00481340(void);\nvoid sub_005DAA20(void);\nvoid sub_005DAA50(void);\nvoid sub_00604D20(void);\nvoid sub_00605750(void);\nvoid sub_00608410(void);\nvoid sub_00648540(void);\n' if kind=='candidate_time' else '')))
    wrapper.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n'+prototype+source,encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'
    if not clang.is_file(): raise WorkSafeError('NDK clang not found')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-c',str(wrapper),'-o',str(base/'candidate-arm64.o')]
    return _run_job(argv,60,'pcrecomp-'+kind+'-arm64',cfg,max_processes=1,memory_mb=384)

def verify_time_candidate_arm64(checked=False):
    """Inspect one private candidate object without executing or distributing it."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not isinstance(checked,bool):raise WorkSafeError('invalid verification profile')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    result=_run_job([sys.executable,str(ROOT/'tools/verify_graphics_object.py'),'--time-checked' if checked else '--time'],30,'time-candidate-object-verify',cfg,max_processes=1,memory_mb=256)
    if result['returncode']!=0 or result['timed_out']:raise WorkSafeError('timer object verification failed')
    return result

def compile_checked_time_candidate():
    """Prepare and compile one audited timer candidate using checked adapters."""
    import hashlib,re,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    prepared=_run_job([sys.executable,str(ROOT/'tools/prepare_time_precise.py')],30,'time-precise-prepare',cfg,max_processes=1,memory_mb=384)
    if prepared['returncode']!=0 or prepared['timed_out']:raise WorkSafeError('precise candidate preparation failed')
    base=ROOT/'private/analysis/candidate_time';report=json.loads((base/'precise_report.json').read_text())
    source=(base/'candidate_precise.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(source.encode()).hexdigest()!=report['adapted_sha256']:raise WorkSafeError('adapted source hash mismatch')
    used=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    allowed={'MEM32','POP32_VAL','PUSH32','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
    if not used.issubset(allowed):raise WorkSafeError('unsupported operations: '+str(sorted(used-allowed)))
    prototypes=''.join('void sub_'+name+'(void);\n' for name in ('00426EF0','00481330','00481340','005DAA20','005DAA50','00604D20','00605750','00608410','00648540'))
    unit=base/'time_checked_unit.c';unit.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'+prototypes+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(unit),'-o',str(base/'time-checked-arm64.o')]
    built=_run_job(argv,60,'time-checked-build',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('checked timer compilation failed')
    return {'prepare':prepared,'build':built}

def compile_time_with_small_dependencies(include_copy=False,include_indirect=False):
    """Compile the checked private candidate and three validated dependencies."""
    import hashlib,re,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not isinstance(include_copy,bool) or not isinstance(include_indirect,bool) or (include_indirect and not include_copy):raise WorkSafeError('invalid dependency profile')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    prepared=compile_checked_time_candidate();base=ROOT/'private/analysis/candidate_time'
    report=json.loads((base/'dependencies/report.json').read_text(encoding='utf-8'));items=report['items']
    if {x['address'] for x in items}!={'0x426ef0','0x481330','0x608410'}:raise WorkSafeError('unexpected dependency set')
    sources=[]
    for item in items:
        name=item['source']
        if name not in ('dep_00426ef0.c','dep_00481330.c','dep_00608410.c'):raise WorkSafeError('unexpected dependency source')
        source=(base/'dependencies'/name).read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(source.encode()).hexdigest()!=item['sha256']:raise WorkSafeError('dependency hash mismatch')
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not operations.issubset({'MEM32','RECOMP_ENTER','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported dependency operations')
        sources.append(source)
    if include_copy:
        prepare_time_copy_precise()
        copy_report=json.loads((base/'dependencies/copy_precise_report.json').read_text())
        copy_source=(base/'dependencies/dep_00604d20_precise.c').read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(copy_source.encode()).hexdigest()!=copy_report['adapted_sha256']:raise WorkSafeError('copy dependency hash mismatch')
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',copy_source))
        if not operations.issubset({'MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported copy operations')
        sources.append('void sub_00604DC0(void);\nvoid sub_00604F30(void);\n'+copy_source)
        inner_report=json.loads((base/'dependencies/inner_report.json').read_text())
        inner=(base/'dependencies/dep_00604f30.c').read_text(encoding='utf-8').removesuffix('\n')
        if inner_report['address']!='0x604f30' or hashlib.sha256(inner.encode()).hexdigest()!=inner_report['source_sha256']:raise WorkSafeError('inner setter hash mismatch')
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',inner))
        if not operations.issubset({'MEM32','RECOMP_ENTER','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported inner setter operations')
        sources.append(inner)
    if include_indirect:
        prepare_time_indirect_precise()
        indirect_report=json.loads((base/'dependencies/indirect_precise_report.json').read_text())
        indirect=(base/'dependencies/dep_00604dc0_precise.c').read_text(encoding='utf-8').removesuffix('\n')
        if hashlib.sha256(indirect.encode()).hexdigest()!=indirect_report['adapted_sha256']:raise WorkSafeError('indirect source hash mismatch')
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',indirect))
        if not operations.issubset({'MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise WorkSafeError('unsupported indirect operations')
        sources.append('void sub_00401030(void);\nvoid sub_004932F0(void);\nvoid sub_00493230(void);\n'+indirect)
    unit=base/('time_all_unit.c' if include_indirect else ('time_copy_linked_unit.c' if include_copy else 'time_linked_unit.c'));unit.write_text((base/'time_checked_unit.c').read_text(encoding='utf-8')+'\n'+'\n'.join(sources)+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64';clang=ndk/'bin/clang.exe'
    if not clang.is_file():raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private/pcrecomp/runtime/recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(unit),'-o',str(base/('time-all-arm64.o' if include_indirect else ('time-copy-linked-arm64.o' if include_copy else 'time-linked-arm64.o')))]
    built=_run_job(argv,60,'time-small-deps-build',cfg,max_processes=1,memory_mb=384)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('time dependency compilation failed')
    verify=_run_job([sys.executable,str(ROOT/'tools/verify_graphics_object.py'),'--time-all' if include_indirect else ('--time-copy-linked' if include_copy else '--time-linked')],30,'time-small-deps-verify',cfg,max_processes=1,memory_mb=256)
    if verify['returncode']!=0 or verify['timed_out']:raise WorkSafeError('time dependency object verification failed')
    return {'prepare':prepared,'build':built,'verification':verify}

def compile_checked_candidate_arm64():
    """Compile the bounded-memory candidate for Android ARM64, without linking."""
    import hashlib, re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private'/'analysis'/'candidate_deterministic'
    report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    source=(base/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x40a020' or hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['source_sha256']:
        raise WorkSafeError('unexpected candidate')
    if re.search(r'\b(?:ADDR|MEM64|MEMF|MEMD|recomp_rep_movs)\s*\(',source):
        raise WorkSafeError('unsupported memory form')
    wrapper=base/'checked_translation_unit.c'
    wrapper.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n'+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'
    if not clang.is_file(): raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(wrapper),'-o',str(base/'candidate-checked-arm64.o')]
    return _run_job(argv,60,'pcrecomp-checked-arm64',cfg,max_processes=1,memory_mb=384)

def prepare_compile_x87_checked():
    """Adapt three known float loads and compile that candidate for ARM64."""
    import hashlib, sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    prepared=_run_job([sys.executable,str(ROOT/'tools'/'prepare_x87_checked.py')],30,'pcrecomp-x87-prepare',cfg,max_processes=1,memory_mb=256)
    if prepared['returncode']!=0 or prepared['timed_out']: return {'prepare':prepared,'compile':None}
    base=ROOT/'private'/'analysis'/'candidate_x87'
    report=json.loads((base/'checked_report.json').read_text(encoding='utf-8'))
    source=(base/'candidate_checked.c').read_text(encoding='utf-8').removesuffix('\n')
    if hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['adapted_sha256']: raise WorkSafeError('adapted source hash mismatch')
    wrapper=base/'checked_translation_unit.c'
    wrapper.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n'+source+'\n',encoding='utf-8')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'
    if not clang.is_file(): raise WorkSafeError('NDK clang missing')
    argv=[str(clang),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),'-std=gnu11','-I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'-I',str(ROOT/'recomp'),'-I',str(ROOT/'runtime'),'-c',str(wrapper),'-o',str(base/'candidate-checked-arm64.o')]
    compiled=_run_job(argv,60,'pcrecomp-x87-checked-arm64',cfg,max_processes=1,memory_mb=384)
    return {'prepare':prepared,'compile':compiled}

def probe_candidate_x86():
    """Run the fixed candidate in isolated Unicorn with synthetic data only."""
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM for isolated probe')
    return _run_job([sys.executable,str(ROOT/'tools'/'probe_candidate_x86.py')],30,'pcrecomp-x86-reference',cfg,max_processes=1,memory_mb=384)

def probe_candidate_x87(special=False):
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    if not isinstance(special,bool): raise WorkSafeError('invalid special profile')
    argv=[sys.executable,str(ROOT/'tools'/'probe_candidate_x87.py')]+(['--special'] if special else [])
    return _run_job(argv,30,'pcrecomp-x87-special-reference' if special else 'pcrecomp-x87-reference',cfg,max_processes=1,memory_mb=384)

def compare_candidate_wasm():
    """Compile the fixed generated candidate with test macros and compare to x86 reference."""
    import hashlib
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private'/'analysis'/'candidate_deterministic'
    report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    source=(base/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x40a020' or hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['source_sha256']:
        raise WorkSafeError('unexpected candidate')
    ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android'/'Sdk'/'ndk'/'28.2.13676358'/'toolchains'/'llvm'/'prebuilt'/'windows-x86_64'
    clang=ndk/'bin'/'clang.exe'; node=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'nodejs'/'node.exe'
    if not clang.is_file() or not node.is_file(): raise WorkSafeError('NDK clang or Node missing')
    argv=[str(clang),'--target=wasm32-unknown-unknown','-ffreestanding','-fno-builtin','-fno-strict-aliasing','-nostdlib','-std=c11','-I',str(base),str(ROOT/'tests'/'candidate_wasm_harness.c'),'-Wl,--no-entry','-Wl,--export=run_case','-Wl,--export=get_result','-Wl,--export=get_reg','-Wl,--export=get_flags','-Wl,--export=get_guest_memory','-Wl,--export-memory','-o',str(base/'difftest.wasm')]
    compiled=_run_job(argv,60,'pcrecomp-difftest-build',cfg,max_processes=2,memory_mb=384)
    if compiled['returncode'] != 0 or compiled['timed_out']: return {'compile':compiled,'test':None}
    if available_memory_mb()<1024: raise WorkSafeError('insufficient RAM for differential test')
    tested=_run_job([str(node),str(ROOT/'tests'/'compare_candidate_wasm.js')],30,'pcrecomp-difftest',cfg,max_processes=1,memory_mb=256)
    return {'compile':compiled,'test':tested}

def compare_candidate_native_runtime(checked=False, x87=False, special=False):
    """Compare one generated function with the actual PCRecomp header in a headless x64 test."""
    import hashlib, re, sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb() < 1024: raise WorkSafeError('insufficient available RAM')
    if not all(isinstance(x,bool) for x in (checked,x87,special)) or (x87 and not checked) or (special and not x87): raise WorkSafeError('invalid comparison profile')
    base=ROOT/'private'/'analysis'/('candidate_x87' if x87 else 'candidate_deterministic')
    report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    source=(base/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!=('0x409960' if x87 else '0x40a020') or hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['source_sha256']:
        raise WorkSafeError('unexpected candidate')
    if x87:
        adapted=(base/'candidate_checked.c').read_text(encoding='utf-8').removesuffix('\n')
        adjusted=json.loads((base/'checked_report.json').read_text(encoding='utf-8'))
        if adjusted['original_sha256']!=report['source_sha256'] or hashlib.sha256(adapted.encode('utf-8')).hexdigest()!=adjusted['adapted_sha256']:
            raise WorkSafeError('unexpected adapted source')
        source=adapted
    if checked and re.search(r'\b(?:ADDR|recomp_rep_movs)\s*\(',source):
        raise WorkSafeError('candidate uses memory forms not covered by adapter')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10'
    cl=vs/'bin'/'Hostx64'/'x64'/'cl.exe'; sdk='10.0.26100.0'
    include=[vs/'include',kits/'Include'/sdk/'ucrt',kits/'Include'/sdk/'shared',kits/'Include'/sdk/'um']
    lib=[vs/'lib'/'x64',kits/'Lib'/sdk/'ucrt'/'x64',kits/'Lib'/sdk/'um'/'x64']
    if not cl.is_file() or not all(p.is_dir() for p in include+lib): raise WorkSafeError('fixed MSVC toolchain or SDK missing')
    env=os.environ.copy(); env['INCLUDE']=os.pathsep.join(map(str,include)); env['LIB']=os.pathsep.join(map(str,lib)); env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    label=('x87-special' if special else 'x87') if x87 else ('checked' if checked else 'native')
    exe=base/(label+'-difftest.exe')
    argv=[str(cl),'/nologo','/Od','/std:c11','/I',str(base),'/I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime')]
    if checked: argv.append('/DMH_CHECKED_TEST')
    if x87: argv.append('/DMH_X87_TEST')
    argv += ['/Fo'+str(base/(label+'-difftest.obj')),'/Fe'+str(exe),str(ROOT/'tests'/'candidate_native_runtime.c'),'/link','/INCREMENTAL:NO']
    compiled=_run_job(argv,60,'pcrecomp-'+label+'-build',cfg,max_processes=4,memory_mb=512,env=env)
    if compiled['returncode']!=0 or compiled['timed_out']: return {'compile':compiled,'run':None,'compare':None}
    if available_memory_mb()<1024: raise WorkSafeError('insufficient RAM for native runtime test')
    run=_run_job([str(exe)]+(['--special'] if special else []),30,'pcrecomp-'+label+'-runtime',cfg,max_processes=1,memory_mb=256)
    if run['returncode']!=0 or run['timed_out']: return {'compile':compiled,'run':run,'compare':None}
    compare_args=[sys.executable,str(ROOT/'tests'/'compare_candidate_native.py')]+(['--x87-special' if special else '--x87'] if x87 else (['--checked'] if checked else []))
    compared=_run_job(compare_args,30,'pcrecomp-'+label+'-compare',cfg,max_processes=1,memory_mb=256)
    result={'compile':compiled,'run':run,'compare':compared}
    if checked and not x87 and compared['returncode']==0 and not compared['timed_out']:
        for name in ('oob','oob64','unaligned','widths'):
            fault=_run_job([str(exe),'--'+name],10,'pcrecomp-checked-'+name,cfg,max_processes=1,memory_mb=256)
            result[name]=fault
            expected = 70 if name.startswith('oob') else 0
            if fault['timed_out'] or fault['returncode']!=expected: raise WorkSafeError(name+' check failed')
    return result

def test_checked_dispatch():
    """Compile and run synthetic fail-closed dispatch tests, no game code."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10'
    cl=vs/'bin'/'Hostx64'/'x64'/'cl.exe';sdk='10.0.26100.0'
    include=[vs/'include',kits/'Include'/sdk/'ucrt',kits/'Include'/sdk/'shared',kits/'Include'/sdk/'um']
    lib=[vs/'lib'/'x64',kits/'Lib'/sdk/'ucrt'/'x64',kits/'Lib'/sdk/'um'/'x64']
    if not cl.is_file() or not all(p.is_dir() for p in include+lib): raise WorkSafeError('MSVC toolchain or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,include));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    output=ROOT/'build'/'dispatch-test';output.mkdir(parents=True,exist_ok=True);exe=output/'dispatch-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime'),'/Fo'+str(output/'dispatch-test.obj'),'/Fe'+str(exe),str(ROOT/'tests'/'test_checked_dispatch.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'checked-dispatch-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'tests':None}
    results={}
    for name,args,expected in (('success',[],0),('missing-call',['--missing-call'],74),('missing-tail',['--missing-tail'],74),('missing-precise',['--missing-precise'],74),('tick-return-mismatch',['--tick-return-mismatch'],78)):
        if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM during dispatch test')
        result=_run_job([str(exe)]+args,10,'checked-dispatch-'+name,cfg,max_processes=1,memory_mb=256)
        results[name]=result
        if result['timed_out'] or result['returncode']!=expected:raise WorkSafeError('dispatch test failed: '+name)
    return {'build':built,'tests':results}

def _msvc_env():
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10'
    cl=vs/'bin'/'Hostx64'/'x64'/'cl.exe';sdk='10.0.26100.0'
    include=[vs/'include',kits/'Include'/sdk/'ucrt',kits/'Include'/sdk/'shared',kits/'Include'/sdk/'um']
    lib=[vs/'lib'/'x64',kits/'Lib'/sdk/'ucrt'/'x64',kits/'Lib'/sdk/'um'/'x64']
    if not cl.is_file() or not all(p.is_dir() for p in include+lib): raise WorkSafeError('MSVC toolchain or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,include));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    return cl,env

def test_checked_rep_movs():
    """Compile and run synthetic checks of the checked rep movs helper; no game code."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    cl,env=_msvc_env()
    output=ROOT/'build'/'rep-movs-test';output.mkdir(parents=True,exist_ok=True);exe=output/'rep-movs-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/W4','/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime'),'/Fo'+str(output)+'\\','/Fe'+str(exe),
          str(ROOT/'tests'/'test_checked_rep_movs.c'),str(ROOT/'runtime'/'guest_memory.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'rep-movs-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('rep movs test build failed; inspect rep-movs-build logs')
    ran=_run_job([str(exe)],30,'rep-movs-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('rep movs test failed with code '+str(ran['returncode']))
    return {'build':built,'run':ran}

def test_win32_memory():
    """Compile and run synthetic checks of the Win32 memory shims on the host; no game code."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    cl,env=_msvc_env()
    output=ROOT/'build'/'win32-memory-test';output.mkdir(parents=True,exist_ok=True);exe=output/'win32-memory-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/W4','/I',str(ROOT/'runtime'),'/Fo'+str(output)+'\\','/Fe'+str(exe),
          str(ROOT/'tests'/'test_win32_memory.c'),str(ROOT/'runtime'/'win32_memory.c'),str(ROOT/'runtime'/'guest_memory.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'win32-memory-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('win32 memory test build failed; inspect win32-memory-build logs')
    ran=_run_job([str(exe)],30,'win32-memory-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('win32 memory test failed with code '+str(ran['returncode']))
    return {'build':built,'run':ran}

def _host_unit_test(name,sources):
    """Compile `sources` (repo-relative) with MSVC /W4 and run the resulting synthetic test; no game code."""
    import re
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if not re.fullmatch(r'[a-z0-9-]{1,32}',name):raise WorkSafeError('invalid test name')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    cl,env=_msvc_env()
    output=ROOT/'build'/f'{name}-test';output.mkdir(parents=True,exist_ok=True);exe=output/f'{name}-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/W4','/I',str(ROOT/'runtime'),'/I',str(ROOT/'recomp'),'/Fo'+str(output)+'\\','/Fe'+str(exe),
          *[str(ROOT/s) for s in sources],'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,f'{name}-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError(f'{name} test build failed; inspect {name}-build logs')
    ran=_run_job([str(exe)],30,f'{name}-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError(f'{name} test failed with code {ran["returncode"]}')
    return Path(ran['log']+'.stdout.log').read_text(encoding='utf-8',errors='replace').strip()

def test_port_saves(on_device=True):
    """Synthetic persistent-save lifecycle, failures and cleanup. No original game data."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    sources=['tests/test_port_saves.c','runtime/port_api.c','runtime/guest_memory.c',
             'runtime/win32_memory.c','runtime/win32_thread.c','runtime/win32_process.c']
    out=ROOT/'build/port-saves-test';out.mkdir(parents=True,exist_ok=True)
    # Each run owns a fresh directory, so existing test files are never overwritten.
    data=out/uuid.uuid4().hex;data.mkdir()
    cl,env=_msvc_env();exe=out/'port-saves.exe'
    built=_run_job([str(cl),'/nologo','/Od','/std:c11','/I',str(ROOT/'runtime'),'/Fo'+str(out)+'\\','/Fe'+str(exe),
                    *[str(ROOT/s) for s in sources],'/link','/INCREMENTAL:NO'],60,'port-saves-host-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('save lifecycle build failed; inspect port-saves-host-build logs')
    ran=_run_job([str(exe),str(data)],30,'port-saves-host-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('save lifecycle failed; inspect port-saves-host-run logs')
    data.rmdir()
    results={'windows-x64':Path(ran['log']+'.stdout.log').read_text(encoding='utf-8').strip()}
    if on_device:
        ndk=Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64'
        binary=out/'port_saves_test'
        arm=_run_job([str(ndk/'bin/clang.exe'),'--target=aarch64-linux-android29','--sysroot='+str(ndk/'sysroot'),
                      '-std=gnu11','-O1','-fPIE','-pie','-I',str(ROOT/'runtime'),*[str(ROOT/s) for s in sources],'-o',str(binary),'-lm'],
                     90,'port-saves-arm64-build',cfg,max_processes=4,memory_mb=768)
        if arm['returncode']!=0 or arm['timed_out']:raise WorkSafeError('save lifecycle ARM64 build failed')
        results['android-arm64']=_run_binary_on_s25(binary.read_bytes(),'port-saves','"$d"').strip()
    return results

def test_d3d8():
    """Synthetic checks of the Direct3D 8 shim on the host."""
    return _host_unit_test('d3d8',['tests/test_d3d8.c','runtime/d3d8.c','runtime/guest_memory.c'])

def test_protection_redirect():
    """Synthetic checks of the Win32 thread state and the protection-redirect replacement on the host."""
    return _host_unit_test('protection-redirect',['tests/test_protection_redirect.c','runtime/win32_thread.c','runtime/protection_redirect.c','runtime/guest_memory.c'])

def test_x87_semantics():
    """Compile and run synthetic checks of the x87 arithmetic helpers on the host; no game code."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024: raise WorkSafeError('insufficient available RAM')
    cl,env=_msvc_env()
    output=ROOT/'build'/'x87-semantics-test';output.mkdir(parents=True,exist_ok=True);exe=output/'x87-semantics-test.exe'
    argv=[str(cl),'/nologo','/Od','/std:c11','/W4','/I',str(ROOT/'recomp'),'/Fo'+str(output)+'\\','/Fe'+str(exe),
          str(ROOT/'tests'/'test_x87_semantics.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'x87-semantics-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:raise WorkSafeError('x87 semantics build failed; inspect x87-semantics-build logs')
    ran=_run_job([str(exe)],30,'x87-semantics-run',cfg,max_processes=1,memory_mb=256)
    if ran['returncode']!=0 or ran['timed_out']:raise WorkSafeError('x87 semantics test failed with code '+str(ran['returncode']))
    return {'build':built,'run':ran}

def probe_graphics_x86(modes=False, null_case=False, multi=False):
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    if not all(isinstance(x,bool) for x in (modes,null_case,multi)) or sum((modes,null_case,multi))>1:raise WorkSafeError('invalid graphics reference profile')
    argv=[sys.executable,str(ROOT/'tools'/'probe_graphics_x86.py')]+(['--multi'] if multi else (['--modes'] if modes else (['--null'] if null_case else [])))
    label='graphics-multi-x86-reference' if multi else ('graphics-modes-x86-reference' if modes else ('graphics-null-x86-reference' if null_case else 'graphics-x86-reference'))
    return _run_job(argv,30,label,cfg,max_processes=1,memory_mb=384)

def probe_input_x86():
    import sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1024:raise WorkSafeError('insufficient available RAM')
    return _run_job([sys.executable,str(ROOT/'tools'/'probe_input_x86.py')],30,'input-x86-reference',cfg,max_processes=1,memory_mb=384)

def compare_input_native():
    """Test the input candidate with synthetic Win32/DirectInput doubles only."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private'/'analysis';folder=base/'candidate_input';thunk=base/'dinput8_thunk'
    report=json.loads((folder/'report.json').read_text(encoding='utf-8'));adjusted=json.loads((folder/'precise_report.json').read_text(encoding='utf-8'));t_report=json.loads((thunk/'report.json').read_text(encoding='utf-8'))
    source=(folder/'candidate.c').read_text(encoding='utf-8').removesuffix('\n');adapted=(folder/'candidate_precise.c').read_text(encoding='utf-8').removesuffix('\n');t_source=(thunk/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    sha=lambda value:hashlib.sha256(value.encode('utf-8')).hexdigest()
    if report['address']!='0x4c1ba0' or sha(source)!=report['source_sha256'] or adjusted['original_sha256']!=report['source_sha256'] or sha(adapted)!=adjusted['adapted_sha256'] or sha(t_source)!=t_report['source_sha256']:
        raise WorkSafeError('input candidate source mismatch')
    prefix='#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_00644098(void);\nvoid sub_0060F110(void);\n'
    if (folder/'input_precise_unit.c').read_text(encoding='utf-8')!=prefix+adapted+'\n'+t_source+'\n':raise WorkSafeError('input unit differs from verified candidates')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10';cl=vs/'bin'/'Hostx64'/'x64'/'cl.exe';sdk='10.0.26100.0'
    include=[vs/'include',kits/'Include'/sdk/'ucrt',kits/'Include'/sdk/'shared',kits/'Include'/sdk/'um'];lib=[vs/'lib'/'x64',kits/'Lib'/sdk/'ucrt'/'x64',kits/'Lib'/sdk/'um'/'x64']
    if not cl.is_file() or not all(p.is_dir() for p in include+lib):raise WorkSafeError('MSVC or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,include));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    exe=folder/'input-mock-difftest.exe';argv=[str(cl),'/nologo','/Od','/std:c11','/I',str(folder),'/I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime'),'/Fo'+str(folder/'input-mock-difftest.obj'),'/Fe'+str(exe),str(ROOT/'tests'/'input_candidate_native.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'input-mock-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'run':None,'compare':None}
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for input mock test')
    run=_run_job([str(exe)],30,'input-mock-runtime',cfg,max_processes=1,memory_mb=256)
    if run['returncode']!=0 or run['timed_out']:return {'build':built,'run':run,'compare':None}
    compared=_run_job([sys.executable,str(ROOT/'tests'/'compare_input_native.py')],30,'input-mock-compare',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'run':run,'compare':compared}

def compare_graphics_native(precise=False,modes=False,multi=False):
    """Test the graphics candidate only with synthetic Direct3D/COM doubles."""
    import hashlib,sys
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    if not all(isinstance(x,bool) for x in (precise,modes,multi)) or ((modes or multi) and not precise) or (modes and multi):raise WorkSafeError('invalid comparison profile')
    if available_memory_mb()<1536:raise WorkSafeError('insufficient available RAM')
    base=ROOT/'private'/'analysis';sources=[]
    for name,address in (('candidate_graphics','0x4c0830'),('d3d8_thunk','0x64408c')):
        folder=base/name;report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
        source=(folder/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
        if report['address']!=address or hashlib.sha256(source.encode('utf-8')).hexdigest()!=report['source_sha256']:raise WorkSafeError('unexpected candidate')
        sources.append(source)
    folder=base/'candidate_graphics'
    if precise:
        report=json.loads((folder/'precise_report.json').read_text(encoding='utf-8'));adapted=(folder/'candidate_precise.c').read_text(encoding='utf-8').removesuffix('\n')
        if report['original_sha256']!=hashlib.sha256(sources[0].encode('utf-8')).hexdigest() or report['adapted_sha256']!=hashlib.sha256(adapted.encode('utf-8')).hexdigest():raise WorkSafeError('precise source mismatch')
        sources[0]=adapted
    expected='#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\nvoid sub_0064408C(void);\n'+'\n'.join(sources)+'\n'
    if (folder/('graphics_precise_unit.c' if precise else 'graphics_checked_unit.c')).read_text(encoding='utf-8')!=expected:raise WorkSafeError('unit differs from verified candidates')
    vs=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft Visual Studio'/'18'/'Community'/'VC'/'Tools'/'MSVC'/'14.51.36231'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10';cl=vs/'bin'/'Hostx64'/'x64'/'cl.exe';sdk='10.0.26100.0'
    include=[vs/'include',kits/'Include'/sdk/'ucrt',kits/'Include'/sdk/'shared',kits/'Include'/sdk/'um'];lib=[vs/'lib'/'x64',kits/'Lib'/sdk/'ucrt'/'x64',kits/'Lib'/sdk/'um'/'x64']
    if not cl.is_file() or not all(p.is_dir() for p in include+lib):raise WorkSafeError('MSVC or SDK missing')
    env=os.environ.copy();env['INCLUDE']=os.pathsep.join(map(str,include));env['LIB']=os.pathsep.join(map(str,lib));env['PATH']=str(cl.parent)+os.pathsep+env.get('PATH','')
    label=('precise-multi' if multi else ('precise-modes' if modes else 'precise')) if precise else 'mock';exe=folder/(label+'-difftest.exe');argv=[str(cl),'/nologo','/Od','/std:c11','/I',str(folder),'/I',str(ROOT/'private'/'pcrecomp'/'runtime'/'recomp32'),'/I',str(ROOT/'recomp'),'/I',str(ROOT/'runtime')]
    if precise:argv.append('/DMH_PRECISE_RETURN')
    argv+=['/Fo'+str(folder/(label+'-difftest.obj')),'/Fe'+str(exe),str(ROOT/'tests'/'graphics_candidate_native.c'),'/link','/INCREMENTAL:NO']
    built=_run_job(argv,60,'graphics-'+label+'-build',cfg,max_processes=4,memory_mb=512,env=env)
    if built['returncode']!=0 or built['timed_out']:return {'build':built,'run':None,'compare':None}
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for graphics mock test')
    run=_run_job([str(exe)]+(['--multi'] if multi else (['--modes'] if modes else [])),30,'graphics-'+label+'-runtime',cfg,max_processes=1,memory_mb=256)
    if run['returncode']!=0 or run['timed_out']:return {'build':built,'run':run,'compare':None}
    compared=_run_job([sys.executable,str(ROOT/'tests'/'compare_graphics_native.py')]+(['--precise-multi' if multi else ('--precise-modes' if modes else '--precise')] if precise else []),30,'graphics-'+label+'-compare',cfg,max_processes=1,memory_mb=256)
    return {'build':built,'run':run,'compare':compared}

def test_graphics_null_failure():
    """Confirm synthetic null creation fails in both x86 and checked code."""
    cfg=json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True:raise WorkSafeError('work-safe mode required')
    ref=probe_graphics_x86(null_case=True)
    if ref['returncode']!=0 or ref['timed_out']:return {'reference':ref,'control':None,'fault':None}
    control=compare_graphics_native(precise=True)
    if not control['compare'] or control['compare']['returncode']!=0 or control['compare']['timed_out']:
        return {'reference':ref,'control':control,'fault':None}
    if available_memory_mb()<1024:raise WorkSafeError('insufficient RAM for null fault test')
    exe=ROOT/'private/analysis/candidate_graphics/precise-difftest.exe'
    fault=_run_job([str(exe),'--null'],10,'graphics-null-checked',cfg,max_processes=1,memory_mb=256)
    if fault['timed_out'] or fault['returncode']!=70:raise WorkSafeError('null read was not rejected at guest address zero')
    return {'reference':ref,'control':control,'fault':fault}

def run(argv, *, timeout=None, log_name=None, _profile='test'):
    if os.name != 'nt': raise WorkSafeError('Windows Job Objects required')
    cfg = json.loads((ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    if cfg.get('enabled') is not True: raise WorkSafeError('work-safe mode required')
    if not argv or not all(isinstance(x, str) for x in argv): raise WorkSafeError('argv required')
    exe = Path(argv[0]).name.lower()
    if _profile not in ('test', 'tree_test'):
        raise WorkSafeError('unknown profile')
    if exe not in {'python.exe', 'pythonw.exe'} or len(argv) < 2 or Path(argv[1]).resolve() != (ROOT/'tests'/'test_child.py').resolve():
        raise WorkSafeError('command not on the audited headless allowlist')
    seconds = cfg['timeout_seconds'] if timeout is None else timeout
    if not 0 < seconds <= cfg['timeout_seconds']: raise WorkSafeError('invalid timeout')
    return _run_job(argv, seconds, log_name, cfg, max_processes=2 if _profile == 'tree_test' else 1, memory_mb=cfg['memory_limit_mb'])

def _run_job(argv, seconds, log_name, cfg, *, max_processes, memory_mb, env=None, input_bytes=None):
    if input_bytes is not None and (not isinstance(input_bytes,bytes) or len(input_bytes)>2*1024*1024):
        raise WorkSafeError('invalid bounded stdin')
    k = c.WinDLL('kernel32', use_last_error=True)
    class BASIC(c.Structure):
        _fields_ = [('PerProcessUserTimeLimit',c.c_longlong),('PerJobUserTimeLimit',c.c_longlong),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',c.c_size_t),('MaximumWorkingSetSize',c.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',c.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
    class IO(c.Structure):
        _fields_ = [(x,c.c_ulonglong) for x in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class EXT(c.Structure):
        _fields_ = [('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',c.c_size_t),('JobMemoryLimit',c.c_size_t),('PeakProcessMemoryUsed',c.c_size_t),('PeakJobMemoryUsed',c.c_size_t)]
    k.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR]; k.CreateJobObjectW.restype=w.HANDLE
    k.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]; k.SetInformationJobObject.restype=w.BOOL
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]; k.AssignProcessToJobObject.restype=w.BOOL
    k.CloseHandle.argtypes=[w.HANDLE]; k.CloseHandle.restype=w.BOOL
    nt=c.WinDLL('ntdll'); nt.NtResumeProcess.argtypes=[w.HANDLE]; nt.NtResumeProcess.restype=c.c_long
    job=k.CreateJobObjectW(None,None)
    if not job: raise c.WinError(c.get_last_error())
    proc=None
    try:
        limits=EXT(); b=limits.BasicLimitInformation
        b.LimitFlags=0x2000|0x8|0x200|0x10|0x20 # kill on close, process count, job memory, affinity, priority
        b.ActiveProcessLimit=max_processes
        b.PriorityClass=0x4000
        # Select from current process affinity, never assume CPU numbering starts at zero.
        process_mask=c.c_size_t(); system_mask=c.c_size_t()
        k.GetCurrentProcess.restype=w.HANDLE
        k.GetProcessAffinityMask.argtypes=[w.HANDLE,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]
        if not k.GetProcessAffinityMask(k.GetCurrentProcess(),c.byref(process_mask),c.byref(system_mask)): raise c.WinError(c.get_last_error())
        available=[i for i in range(c.sizeof(c.c_size_t)*8) if process_mask.value & (1<<i)]
        count=max(1,min(int(cfg['max_jobs']), int(len(available)*float(cfg['cpu_fraction']))))
        b.Affinity=sum(1<<i for i in available[:count]); limits.JobMemoryLimit=int(memory_mb)*1024*1024
        if not k.SetInformationJobObject(job,9,c.byref(limits),c.sizeof(limits)): raise c.WinError(c.get_last_error())
        logs=ROOT/'logs'; logs.mkdir(exist_ok=True)
        name=log_name or uuid.uuid4().hex
        if Path(name).name != name: raise WorkSafeError('invalid log name')
        with (logs/(name+'.stdout.log')).open('wb') as out, (logs/(name+'.stderr.log')).open('wb') as err:
            # Suspended until the job has been assigned, so limits apply before user code.
            proc=subprocess.Popen(argv, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL, stdout=out, stderr=err, shell=False, env=env, creationflags=0x08000000|0x00004000|0x00000004)
            if not k.AssignProcessToJobObject(job,w.HANDLE(int(proc._handle))): raise c.WinError(c.get_last_error())
            if nt.NtResumeProcess(w.HANDLE(int(proc._handle))) != 0: raise WorkSafeError('cannot resume child')
            try:
                if input_bytes is None: code=proc.wait(timeout=seconds)
                else: proc.communicate(input=input_bytes,timeout=seconds);code=proc.returncode
                timed_out=False
            except subprocess.TimeoutExpired:
                k.CloseHandle(job); job=None # kill-on-close applies to only our job
                proc.wait(); code=proc.returncode; timed_out=True
        return {'returncode':code,'timed_out':timed_out,'log':str(logs/name),'cpu_count':count}
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill(); proc.wait()
        if proc is not None and proc.stdin is not None and not proc.stdin.closed:proc.stdin.close()
        if job: k.CloseHandle(job)
