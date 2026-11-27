package com.manhuntae.android;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.SparseArray;
import android.view.MotionEvent;
import android.view.View;
import java.io.InputStream;

/**
 * On-screen controls over the game view (multi-touch), mapped to the game's default PC controls
 * (its REMAP CONTROLS screen): the arrow keys move (and navigate menus), Shift runs, left Ctrl
 * sneaks, the left mouse button attacks, the right one locks on/aims, Space uses, F looks back,
 * Tab swaps the inventory, R reloads, Enter accepts and Escape goes back/pauses.
 *
 * Left half: a virtual stick (arrow keys, 8 directions). Right half, outside the buttons: a drag
 * turns the camera (mouse motion) and a tap is a left click (it also skips movies).
 * Keys reach the port as DirectInput scan codes (mouse buttons as 0x100 + n).
 * Buttons are drawn with the project's own icons (assets/touch_hud, see design/touch_hud), normal
 * and pressed; a missing icon falls back to a labelled circle.
 */
final class TouchControls extends View {
    interface Input {
        void key(int scanCode, boolean down);
        void mouseMove(int dx, int dy);
    }
    private static final int UP = 0xc8, DOWN = 0xd0, LEFT = 0xcb, RIGHT = 0xcd, ENTER = 0x1c, ESCAPE = 0x01,
            SHIFT = 0x2a, LCTRL = 0x1d, SPACE = 0x39, F = 0x21, TAB = 0x0f, R = 0x13, MOUSE_LEFT = 0x100, MOUSE_RIGHT = 0x101;
    /** Mouse units per screen pixel of drag. */
    private static final float MOUSE_GAIN = 0.6f;

    private static final class Button {
        final String label, icon; final int key; final float radius; final boolean toggle; float x, y, scale = 1; int pressed; boolean latched;
        Bitmap normal, down;
        Button(String label, String icon, int key, float radius, boolean toggle) { this.label = label; this.icon = icon; this.key = key; this.radius = radius; this.toggle = toggle; }
    }
    private final Button[] buttons;
    private final Input input;
    private final float density;
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG), ring = new Paint(Paint.ANTI_ALIAS_FLAG), text = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** pointer id -> button index; -1 = camera/click area; -2 = stick */
    private final SparseArray<Integer> owner = new SparseArray<>();
    private final SparseArray<float[]> mouse = new SparseArray<>();   // last x, y, start time, travelled
    private final Handler handler = new Handler(Looper.getMainLooper());
    // virtual stick
    private float stickX, stickY, knobX, knobY, stickRadius; private int stickPointer = -1;
    private final boolean[] arrows = new boolean[4];   // up, down, left, right
    private Bitmap stickBase, knobNormal, knobDown;
    private final Paint bitmapPaint = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
    private final RectF dst = new RectF();
    private static Bitmap icon(Context context, String name) {
        try (InputStream in = context.getAssets().open("touch_hud/" + name + ".png")) { return BitmapFactory.decodeStream(in); }
        catch (java.io.IOException e) { return null; }
    }
    private void drawIcon(Canvas canvas, Bitmap bmp, float x, float y, float r) { dst.set(x - r, y - r, x + r, y + r); canvas.drawBitmap(bmp, null, dst, bitmapPaint); }
    private static final int[] ARROW_KEYS = {UP, DOWN, LEFT, RIGHT};

    /* Layout editor: the editor button toggles it; while editing, a drag moves a button or the
     * stick, a two-finger pinch resizes it, the reset button restores the defaults, and nothing
     * reaches the game. Positions (fractions of the view) and scales persist in preferences. */
    private static final String PREFS = "hud_layout";
    private final android.content.SharedPreferences prefs;
    private Bitmap editIcon, editIconOn, resetIcon;
    private float editX, editY, resetX, resetY, stickScale = 1; private int viewW, viewH;
    private boolean editing; private int editSel = NONE, editPointer = -1; private float editDx, editDy, pinchDist, pinchScale;
    private static final int NONE = -3, STICK = -2;
    private float itemRadius(int i) { return i == STICK ? 70 * density * stickScale : buttons[i].radius * density * buttons[i].scale; }

    TouchControls(Context context, Input input) {
        super(context);
        this.input = input;
        density = context.getResources().getDisplayMetrics().density;
        buttons = new Button[]{
            new Button("Atacar", "attack_light", MOUSE_LEFT, 40, false), new Button("Fijar", "target_lock", MOUSE_RIGHT, 32, false),
            new Button("Usar", "interact", SPACE, 32, false), new Button("Correr", "run", SHIFT, 30, false),
            new Button("Sigilo", "sneak_toggle", LCTRL, 30, true), new Button("Atrás", "pause", ESCAPE, 26, false),
            new Button("OK", "confirm", ENTER, 26, false), new Button("Mirar", "look_back", F, 24, false),
            new Button("Inv.", "inventory", TAB, 24, false), new Button("Rec.", "reload", R, 24, false),
        };
        for (Button b : buttons) { b.normal = icon(context, b.icon + "_normal"); b.down = icon(context, b.icon + "_pressed"); }
        stickBase = icon(context, "joystick_base_normal"); knobNormal = icon(context, "joystick_knob_normal"); knobDown = icon(context, "joystick_knob_pressed");
        bitmapPaint.setAlpha(200);   /* the HUD under the buttons stays visible */
        editIcon = icon(context, "hud_editor_normal"); editIconOn = icon(context, "hud_editor_pressed"); resetIcon = icon(context, "reset_layout_normal");
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        fill.setStyle(Paint.Style.FILL);
        ring.setStyle(Paint.Style.STROKE); ring.setStrokeWidth(2 * density); ring.setColor(Color.argb(95, 230, 230, 220));   // light: the HUD (bottom right) shows through
        text.setColor(Color.argb(150, 240, 240, 230)); text.setTextAlign(Paint.Align.CENTER); text.setFakeBoldText(true);
    }

    @Override protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        viewW = w; viewH = h;
        defaults(w, h);
        loadLayout();
    }
    private void defaults(int w, int h) {
        float d = density;
        stickScale = 1; for (Button b : buttons) b.scale = 1;
        editX = w / 2f - 90 * d; editY = 34 * d; resetX = w / 2f + 90 * d; resetY = 34 * d;
        stickRadius = 70 * d; stickX = 40 * d + stickRadius; stickY = h - 30 * d - stickRadius; knobX = stickX; knobY = stickY;
        float bx = w - 60 * d, by = h - 60 * d;
        place(0, bx - 30 * d, by - 20 * d);            // Attack: big, bottom right
        place(1, bx - 120 * d, by + 5 * d);            // Lock on / aim
        place(2, bx - 20 * d, by - 115 * d);           // Use
        place(3, bx - 105 * d, by - 90 * d);           // Run
        place(4, stickX + stickRadius + 55 * d, h - 50 * d);   // Sneak (toggle), next to the stick
        place(5, w - 46 * d, 46 * d);                  // Back / pause (Escape), top right
        place(6, w - 120 * d, 46 * d);                 // OK (Enter)
        place(7, bx - 200 * d, by + 12 * d);           // Look back
        place(8, 46 * d, 46 * d);                      // Inventory swap, top left
        place(9, 116 * d, 46 * d);                     // Reload
    }
    private void place(int i, float x, float y) { buttons[i].x = x; buttons[i].y = y; }
    private void loadLayout() {
        if (viewW <= 0 || viewH <= 0 || !prefs.contains("stick_x")) return;
        stickX = prefs.getFloat("stick_x", stickX / viewW) * viewW; stickY = prefs.getFloat("stick_y", stickY / viewH) * viewH;
        stickScale = prefs.getFloat("stick_s", 1); stickRadius = itemRadius(STICK); knobX = stickX; knobY = stickY;
        for (Button b : buttons) {
            b.x = prefs.getFloat(b.icon + "_x", b.x / viewW) * viewW; b.y = prefs.getFloat(b.icon + "_y", b.y / viewH) * viewH; b.scale = prefs.getFloat(b.icon + "_s", 1);
        }
    }
    private void saveLayout() {
        android.content.SharedPreferences.Editor e = prefs.edit();
        e.putFloat("stick_x", stickX / viewW).putFloat("stick_y", stickY / viewH).putFloat("stick_s", stickScale);
        for (Button b : buttons) e.putFloat(b.icon + "_x", b.x / viewW).putFloat(b.icon + "_y", b.y / viewH).putFloat(b.icon + "_s", b.scale);
        e.apply();
    }
    private void moveItem(int i, float x, float y) {
        float r = itemRadius(i); x = Math.max(r, Math.min(viewW - r, x)); y = Math.max(r, Math.min(viewH - r, y));
        if (i == STICK) { stickX = x; stickY = y; knobX = x; knobY = y; } else { buttons[i].x = x; buttons[i].y = y; }
    }
    private boolean near(float x, float y, float cx, float cy, float r) { return (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r * r; }
    /** Touches while editing the layout. */
    private void editTouch(MotionEvent e) {
        int action = e.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex(); float x = e.getX(i), y = e.getY(i);
            if (editSel != NONE && editPointer >= 0 && e.getPointerCount() >= 2) {   // second finger: pinch the selected item
                pinchDist = (float) Math.hypot(e.getX(0) - e.getX(1), e.getY(0) - e.getY(1)); pinchScale = editSel == STICK ? stickScale : buttons[editSel].scale;
                return;
            }
            if (near(x, y, editX, editY, 30 * density)) { editing = false; editSel = NONE; saveLayout(); invalidate(); return; }
            if (near(x, y, resetX, resetY, 30 * density)) { prefs.edit().clear().apply(); defaults(viewW, viewH); invalidate(); return; }
            int b = hit(x, y);
            if (b >= 0) editSel = b; else if (near(x, y, stickX, stickY, stickRadius)) editSel = STICK; else editSel = NONE;
            if (editSel != NONE) {
                editPointer = e.getPointerId(i);
                editDx = (editSel == STICK ? stickX : buttons[editSel].x) - x; editDy = (editSel == STICK ? stickY : buttons[editSel].y) - y;
            }
        } else if (action == MotionEvent.ACTION_MOVE && editSel != NONE) {
            if (e.getPointerCount() >= 2 && pinchDist > 0) {
                float dnow = (float) Math.hypot(e.getX(0) - e.getX(1), e.getY(0) - e.getY(1));
                float s = Math.max(0.5f, Math.min(2.0f, pinchScale * dnow / pinchDist));
                if (editSel == STICK) { stickScale = s; stickRadius = itemRadius(STICK); } else buttons[editSel].scale = s;
            } else {
                int i = e.findPointerIndex(editPointer);
                if (i >= 0) moveItem(editSel, e.getX(i) + editDx, e.getY(i) + editDy);
            }
            invalidate();
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            editSel = NONE; editPointer = -1; pinchDist = 0;
        } else if (action == MotionEvent.ACTION_POINTER_UP) {
            pinchDist = 0;
        }
    }
    /** Releases everything held, so the game sees no stuck key when editing starts. */
    private void releaseAll() {
        for (int k = 0; k < buttons.length; k++) while (buttons[k].pressed > 0) press(k, false);
        if (stickPointer >= 0) { stickPointer = -1; stick(stickX, stickY, false); }
        owner.clear(); mouse.clear();
    }

    @Override protected void onDraw(Canvas canvas) {
        // stick
        if (stickBase != null) drawIcon(canvas, stickBase, stickX, stickY, stickRadius);
        else { fill.setColor(Color.argb(55, 20, 20, 20)); canvas.drawCircle(stickX, stickY, stickRadius, fill); canvas.drawCircle(stickX, stickY, stickRadius, ring); }
        Bitmap knob = stickPointer >= 0 ? knobDown : knobNormal;
        if (knob != null) drawIcon(canvas, knob, knobX, knobY, 34 * density * stickScale);
        else { fill.setColor(stickPointer >= 0 ? Color.argb(150, 200, 60, 50) : Color.argb(90, 200, 200, 190)); canvas.drawCircle(knobX, knobY, 28 * density, fill); }
        for (Button b : buttons) {
            boolean on = b.pressed > 0 || b.latched;
            Bitmap bmp = on && b.down != null ? b.down : b.normal;
            if (bmp != null) { drawIcon(canvas, bmp, b.x, b.y, b.radius * density * b.scale); continue; }
            fill.setColor(on ? Color.argb(120, 200, 60, 50) : Color.argb(25, 20, 20, 20));
            float r = b.radius * density * b.scale;
            canvas.drawCircle(b.x, b.y, r, fill); canvas.drawCircle(b.x, b.y, r, ring);
            text.setTextSize((b.label.length() > 4 ? 12 : 14) * density);
            canvas.drawText(b.label, b.x, b.y + text.getTextSize() / 3, text);
        }
        Bitmap ed = editing && editIconOn != null ? editIconOn : editIcon;
        if (ed != null) drawIcon(canvas, ed, editX, editY, 22 * density);
        if (editing) {
            if (resetIcon != null) drawIcon(canvas, resetIcon, resetX, resetY, 22 * density);
            ring.setColor(Color.argb(200, 220, 70, 60));
            canvas.drawCircle(stickX, stickY, stickRadius, ring);
            for (Button b : buttons) canvas.drawCircle(b.x, b.y, b.radius * density * b.scale, ring);
            ring.setColor(Color.argb(95, 230, 230, 220));
            text.setTextSize(14 * density); text.setColor(Color.argb(230, 240, 240, 230));
            canvas.drawText("Editar controles: arrastra para mover, pellizca para cambiar el tamaño, toca el lápiz para terminar", viewW / 2f, 80 * density, text);
            text.setColor(Color.argb(150, 240, 240, 230));
        }
    }

    private int hit(float x, float y) {
        for (int i = 0; i < buttons.length; i++) {
            Button b = buttons[i]; float r = b.radius * density * b.scale * 1.2f;
            if ((x - b.x) * (x - b.x) + (y - b.y) * (y - b.y) <= r * r) return i;
        }
        return -1;
    }
    private void press(int index, boolean down) {
        Button b = buttons[index];
        if (b.toggle) {   // Sneak: a tap toggles it held
            if (down) { b.latched = !b.latched; input.key(b.key, b.latched); }
            invalidate(); return;
        }
        b.pressed += down ? 1 : -1;
        if (down && b.pressed == 1) input.key(b.key, true);
        if (!down && b.pressed == 0) input.key(b.key, false);
        invalidate();
    }
    /** The stick's arrows: 8 directions with a dead zone. */
    private void stick(float x, float y, boolean active) {
        float dx = x - stickX, dy = y - stickY, len = (float) Math.hypot(dx, dy);
        if (len > stickRadius) { dx *= stickRadius / len; dy *= stickRadius / len; }
        knobX = active ? stickX + dx : stickX; knobY = active ? stickY + dy : stickY;
        float dead = stickRadius * 0.3f;
        boolean[] want = new boolean[4];
        if (active && len > dead) {
            double a = Math.atan2(-dy, dx);   // 0 = right, counter-clockwise
            double s = Math.sin(a), c = Math.cos(a), t = Math.sin(Math.toRadians(22.5));
            want[0] = s > t; want[1] = s < -t; want[2] = c < -t; want[3] = c > t;
        }
        for (int i = 0; i < 4; i++) if (want[i] != arrows[i]) { arrows[i] = want[i]; input.key(ARROW_KEYS[i], want[i]); }
        invalidate();
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        int action = e.getActionMasked();
        if (editing) { editTouch(e); return true; }
        if ((action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN)
                && near(e.getX(e.getActionIndex()), e.getY(e.getActionIndex()), editX, editY, 30 * density)) {
            releaseAll(); editing = true; editSel = NONE; invalidate(); return true;
        }
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex(), id = e.getPointerId(i); float x = e.getX(i), y = e.getY(i);
            int b = hit(x, y);
            if (b >= 0) { owner.put(id, b); press(b, true); }
            else if (x < getWidth() * 0.45f && stickPointer < 0) { owner.put(id, -2); stickPointer = id; stick(x, y, true); }
            else { owner.put(id, -1); mouse.put(id, new float[]{x, y, SystemClock.uptimeMillis(), 0}); }
        } else if (action == MotionEvent.ACTION_MOVE) {
            for (int i = 0; i < e.getPointerCount(); i++) {
                int id = e.getPointerId(i);
                if (id == stickPointer) { stick(e.getX(i), e.getY(i), true); continue; }
                float[] m = mouse.get(id);
                if (m == null) continue;
                float dx = e.getX(i) - m[0], dy = e.getY(i) - m[1];
                int mx = Math.round(dx * MOUSE_GAIN), my = Math.round(dy * MOUSE_GAIN);
                if (mx != 0 || my != 0) {
                    input.mouseMove(mx, my);
                    m[0] += mx / MOUSE_GAIN; m[1] += my / MOUSE_GAIN; m[3] += Math.abs(dx) + Math.abs(dy);
                }
            }
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_CANCEL) {
            int i = e.getActionIndex(), id = e.getPointerId(i);
            Integer b = owner.get(id); owner.remove(id);
            if (b != null && b >= 0) press(b, false);
            if (id == stickPointer) { stickPointer = -1; stick(stickX, stickY, false); }
            float[] m = mouse.get(id); mouse.remove(id);
            if (m != null && action != MotionEvent.ACTION_CANCEL && m[3] < 24 * density && SystemClock.uptimeMillis() - m[2] < 350) click();
            if (action == MotionEvent.ACTION_CANCEL) {
                for (int k = 0; k < buttons.length; k++) while (buttons[k].pressed > 0) press(k, false);
                stickPointer = -1; stick(stickX, stickY, false); owner.clear(); mouse.clear();
            }
        }
        return true;
    }
    /** A tap: the left button held for 120 ms, long enough for the game to read it on a frame. */
    private void click() {
        input.key(MOUSE_LEFT, true);
        handler.postDelayed(() -> input.key(MOUSE_LEFT, false), 120);
    }
}
