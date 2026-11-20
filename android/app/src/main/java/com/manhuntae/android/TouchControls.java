package com.manhuntae.android;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.SparseArray;
import android.view.MotionEvent;
import android.view.View;

/**
 * On-screen controls over the game view (multi-touch), mapped to the game's default PC controls
 * (its REMAP CONTROLS screen): the arrow keys move (and navigate menus), Shift runs, left Ctrl
 * sneaks, the left mouse button attacks, the right one locks on/aims, Space uses, F looks back,
 * Tab swaps the inventory, R reloads, Enter accepts and Escape goes back/pauses.
 *
 * Left half: a virtual stick (arrow keys, 8 directions). Right half, outside the buttons: a drag
 * turns the camera (mouse motion) and a tap is a left click (it also skips movies).
 * Keys reach the port as DirectInput scan codes (mouse buttons as 0x100 + n).
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
        final String label; final int key; final float radius; final boolean toggle; float x, y; int pressed; boolean latched;
        Button(String label, int key, float radius, boolean toggle) { this.label = label; this.key = key; this.radius = radius; this.toggle = toggle; }
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
    private static final int[] ARROW_KEYS = {UP, DOWN, LEFT, RIGHT};

    TouchControls(Context context, Input input) {
        super(context);
        this.input = input;
        density = context.getResources().getDisplayMetrics().density;
        buttons = new Button[]{
            new Button("Atacar", MOUSE_LEFT, 40, false), new Button("Fijar", MOUSE_RIGHT, 32, false), new Button("Usar", SPACE, 32, false),
            new Button("Correr", SHIFT, 30, false), new Button("Sigilo", LCTRL, 30, true), new Button("Atrás", ESCAPE, 26, false),
            new Button("OK", ENTER, 26, false), new Button("Mirar", F, 24, false), new Button("Inv.", TAB, 24, false), new Button("Rec.", R, 24, false),
        };
        fill.setStyle(Paint.Style.FILL);
        ring.setStyle(Paint.Style.STROKE); ring.setStrokeWidth(2 * density); ring.setColor(Color.argb(150, 230, 230, 220));
        text.setColor(Color.argb(220, 240, 240, 230)); text.setTextAlign(Paint.Align.CENTER); text.setFakeBoldText(true);
    }

    @Override protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        float d = density;
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

    @Override protected void onDraw(Canvas canvas) {
        // stick
        fill.setColor(Color.argb(55, 20, 20, 20)); canvas.drawCircle(stickX, stickY, stickRadius, fill); canvas.drawCircle(stickX, stickY, stickRadius, ring);
        fill.setColor(stickPointer >= 0 ? Color.argb(150, 200, 60, 50) : Color.argb(90, 200, 200, 190)); canvas.drawCircle(knobX, knobY, 28 * density, fill);
        for (Button b : buttons) {
            boolean on = b.pressed > 0 || b.latched;
            fill.setColor(on ? Color.argb(150, 200, 60, 50) : Color.argb(70, 20, 20, 20));
            float r = b.radius * density;
            canvas.drawCircle(b.x, b.y, r, fill); canvas.drawCircle(b.x, b.y, r, ring);
            text.setTextSize((b.label.length() > 4 ? 12 : 14) * density);
            canvas.drawText(b.label, b.x, b.y + text.getTextSize() / 3, text);
        }
    }

    private int hit(float x, float y) {
        for (int i = 0; i < buttons.length; i++) {
            Button b = buttons[i]; float r = b.radius * density * 1.2f;
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
