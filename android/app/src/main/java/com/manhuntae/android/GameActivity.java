package com.manhuntae.android;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.Toast;
import java.io.File;

/**
 * Full-screen game view: runs the translated game (libmh_game, a private build) on a SurfaceView.
 * Runs in its own process, so a fault in the guest does not take the launcher with it.
 * Reads the user's own copy from /sdcard/mh-androidevolved (all-files access).
 */
public final class GameActivity extends Activity implements SurfaceHolder.Callback {
    static final String GAME_DIR = "/sdcard/mh-androidevolved";
    /** No frame limit: the game runs until it reaches code not translated yet (the last frame stays). */
    static final int FRAMES = 0;
    private static boolean loaded;
    private boolean started;

    private static native boolean nativeStart(Object surface, String exe, String dir, int frames, boolean realtime, int langid, float scale, boolean stretch);
    private static native void nativeMouseMove(int dx, int dy);
    /** Intent extras: internal resolution (times the game's 640x480; 0 = the screen's), stretch to
     *  the whole screen, on-screen controls. */
    static final String EXTRA_SCALE = "scale", EXTRA_STRETCH = "stretch", EXTRA_CONTROLS = "controls";
    /** Intent extra: the game's language as a Windows LANGID (see LANGUAGES). */
    static final String EXTRA_LANGID = "langid";
    /** The languages of the game's texts (levels/GLOBAL/PC_TEXT) and the LANGID that selects each:
     *  the game reads GetUserDefaultLangID; its German is chosen by Austrian German (it gives
     *  English to German as spoken in Germany). */
    static final String[] LANGUAGE_NAMES = {"English", "Español", "Français", "Deutsch", "Italiano"};
    static final int[] LANGUAGES = {0x0409, 0x0c0a, 0x040c, 0x0c07, 0x0410};
    static final String[] LANGUAGE_CODES = {"en", "es", "fr", "de", "it"};
    /** DirectInput scan code, or 0x100 + n for mouse button n. */
    private static native void nativeKey(int key, boolean down);
    static final int MOUSE_LEFT = 0x100;

    /** Whether the private game library is part of this build (checked without loading it). */
    static boolean bundled(android.content.Context context) {
        return new File(context.getApplicationInfo().nativeLibraryDir, "libmh_game.so").isFile();
    }
    static boolean available() {
        if (loaded) return true;
        try { System.loadLibrary("mh_game"); loaded = true; } catch (LinkageError | SecurityException e) { loaded = false; }
        return loaded;
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        SurfaceView view = new SurfaceView(this);
        view.getHolder().addCallback(this);
        android.widget.FrameLayout root = new android.widget.FrameLayout(this);
        root.addView(view);
        if (getIntent().getBooleanExtra(EXTRA_CONTROLS, true)) {
            root.addView(new TouchControls(this, new TouchControls.Input() {
                @Override public void key(int scanCode, boolean down) { if (started) nativeKey(scanCode, down); }
                @Override public void mouseMove(int dx, int dy) { if (started) nativeMouseMove(dx, dy); }
            }));
        }
        setContentView(root);
        immersive();
        if (!available()) { Toast.makeText(this, "Biblioteca del juego no incluida", Toast.LENGTH_LONG).show(); finish(); return; }
        if (Build.VERSION.SDK_INT >= 30 && !Environment.isExternalStorageManager()) {
            Toast.makeText(this, "Permite el acceso a archivos para leer " + GAME_DIR, Toast.LENGTH_LONG).show();
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:" + getPackageName())));
        }
    }
    @Override public void onWindowFocusChanged(boolean focus) { super.onWindowFocusChanged(focus); if (focus) immersive(); }
    private void immersive() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    /** Without on-screen controls, a touch is the left mouse button (it skips the intro movie). */
    @Override public boolean onTouchEvent(MotionEvent e) {
        if (!started) return super.onTouchEvent(e);
        int action = e.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) nativeKey(MOUSE_LEFT, true);
        else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) nativeKey(MOUSE_LEFT, false);
        return true;
    }
    /** Hardware keys: Enter, Escape (Back), arrows. */
    private static int scanCode(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_ENTER: case KeyEvent.KEYCODE_DPAD_CENTER: case KeyEvent.KEYCODE_BUTTON_A: return 0x1c;
            case KeyEvent.KEYCODE_ESCAPE: case KeyEvent.KEYCODE_BUTTON_B: return 0x01;
            case KeyEvent.KEYCODE_DPAD_UP: return 0xc8;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 0xd0;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 0xcb;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 0xcd;
            default: return -1;
        }
    }
    @Override public boolean onKeyDown(int keyCode, KeyEvent e) {
        int k = scanCode(keyCode); if (!started || k < 0) return super.onKeyDown(keyCode, e);
        nativeKey(k, true); return true;
    }
    @Override public boolean onKeyUp(int keyCode, KeyEvent e) {
        int k = scanCode(keyCode); if (!started || k < 0) return super.onKeyUp(keyCode, e);
        nativeKey(k, false); return true;
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {}
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        if (started || !loaded) return;
        File exe = new File(GAME_DIR, "manhunt.exe");
        if (!exe.canRead()) { Toast.makeText(this, "No se puede leer " + exe, Toast.LENGTH_LONG).show(); return; }
        started = nativeStart(holder.getSurface(), exe.getPath(), GAME_DIR, FRAMES, false, getIntent().getIntExtra(EXTRA_LANGID, 0x0409),
                              getIntent().getFloatExtra(EXTRA_SCALE, 0f), getIntent().getBooleanExtra(EXTRA_STRETCH, false));
    }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        // The guest cannot be paused or moved to a new surface yet: leaving the game ends its process.
        if (started) { finish(); android.os.Process.killProcess(android.os.Process.myPid()); }
    }
}
