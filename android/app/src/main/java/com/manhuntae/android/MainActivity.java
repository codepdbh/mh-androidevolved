package com.manhuntae.android;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.view.Gravity;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Research launcher; it does not start the game. */
public final class MainActivity extends Activity {
    private static final int PICK_FOLDER = 100;
    private TextView folderStatus;
    private SharedPreferences preferences;
    private volatile int validationGeneration;
    private static final String KNOWN_SHA256 = "5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52";
    private static final int KNOWN_EXE_SIZE = 6304256;
    private static native String nativeGetRuntimeDiagnostic();
    private static native String nativeInspectKnownPe(byte[] executable);

    private static String runtimeDiagnostic() {
        try {
            System.loadLibrary("mh_runtime");
            return nativeGetRuntimeDiagnostic();
        } catch (LinkageError | SecurityException e) {
            return "Diagnóstico nativo no disponible; juego no disponible.";
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("launcher", MODE_PRIVATE);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.rgb(25, 29, 27));
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(24); layout.setPadding(pad, pad, pad, pad);
        scroll.addView(layout); setContentView(scroll);
        layout.addView(text("MANHUNT", 30, Color.rgb(231, 231, 219)));
        layout.addView(text("ANDROID EVOLVED · PROTOTIPO DE INVESTIGACIÓN", 12, Color.rgb(199, 108, 94)));
        layout.addView(text("El juego aún no funciona en Android. Los datos del juego no se han verificado por completo.", 16, Color.LTGRAY));
        layout.addView(text(runtimeDiagnostic(), 14, Color.LTGRAY));
        folderStatus = text("", 14, Color.LTGRAY); layout.addView(folderStatus); updateFolderStatus();
        if (hasFolderPermission()) validateFolder(Uri.parse(preferences.getString("tree", "")));
        Button folder = new Button(this); folder.setText("Seleccionar carpeta del juego");
        folder.setOnClickListener(v -> selectFolder()); layout.addView(folder);
        Button play = new Button(this); play.setText("Jugar · aún no disponible"); play.setEnabled(false); layout.addView(play);
        layout.addView(text("Vista previa de controles", 20, Color.WHITE));
        layout.addView(text("Solo imágenes de diseño: las acciones y asignaciones del juego no están verificadas.", 14, Color.LTGRAY));
        for (String name : new String[]{"joystick_base", "attack_light", "aim", "interact", "run", "sneak", "pause"}) {
            LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL);
            ImageView icon = new ImageView(this); icon.setContentDescription(name);
            try (InputStream in = getAssets().open("touch_hud/" + name + "_normal.png")) {
                Bitmap bitmap = BitmapFactory.decodeStream(in);
                if (bitmap != null) icon.setImageBitmap(bitmap);
                else icon.setContentDescription(name + " · imagen no válida");
            } catch (IOException ex) { icon.setContentDescription(name + " · imagen no disponible"); }
            row.addView(icon, new LinearLayout.LayoutParams(dp(64), dp(64)));
            row.addView(text(name.replace('_', ' '), 15, Color.LTGRAY)); layout.addView(row);
        }
        layout.addView(text("El usuario debe aportar sus propios archivos. Esta aplicación no incluye contenido comercial.", 14, Color.LTGRAY));
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        view.setPadding(0, dp(10), 0, dp(10)); return view;
    }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private boolean hasFolderPermission() {
        String value = preferences.getString("tree", null);
        if (value != null) for (android.content.UriPermission p : getContentResolver().getPersistedUriPermissions()) {
            if (p.isReadPermission() && p.getUri().equals(Uri.parse(value))) return true;
        }
        return false;
    }
    private void updateFolderStatus() {
        folderStatus.setText(hasFolderPermission() ? "Carpeta seleccionada; archivos sin verificar." : "Datos del juego: carpeta sin seleccionar o permiso perdido.");
    }
    private void validateFolder(Uri tree) {
        final int generation = ++validationGeneration;
        folderStatus.setText("Comprobando manhunt.exe en la carpeta seleccionada…");
        new Thread(() -> {
            String result;
            try { result = inspectExecutable(tree, generation); }
            catch (IOException | SecurityException | IllegalArgumentException e) { result = "No se pudo leer la carpeta o el ejecutable: " + e.getClass().getSimpleName(); }
            catch (OutOfMemoryError e) { result = "No hay memoria suficiente para comprobar el ejecutable."; }
            final String message = result;
            runOnUiThread(() -> { if (!isFinishing() && !isDestroyed() && generation == validationGeneration) folderStatus.setText(message); });
        }, "game-data-check").start();
    }
    private String inspectExecutable(Uri tree, int generation) throws IOException {
        String root = DocumentsContract.getTreeDocumentId(tree);
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, root);
        String id = null;
        String[] columns = {DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE};
        try (Cursor cursor = getContentResolver().query(children, columns, null, null, null)) {
            if (cursor == null) return "El proveedor no permite enumerar la carpeta.";
            while (cursor.moveToNext()) {
                String name = cursor.getString(1);
                if (name != null && name.equalsIgnoreCase("manhunt.exe") && !DocumentsContract.Document.MIME_TYPE_DIR.equals(cursor.getString(2))) {
                    if (id != null) return "Hay varios archivos manhunt.exe; selecciona una carpeta sin duplicados.";
                    id = cursor.getString(0);
                }
            }
        }
        if (id == null) return "No se encontró manhunt.exe directamente en la carpeta seleccionada.";
        Uri file = DocumentsContract.buildDocumentUriUsingTree(tree, id);
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException e) { throw new IOException("SHA-256 unavailable", e); }
        long size = 0;
        try (InputStream in = getContentResolver().openInputStream(file)) {
            if (in == null) throw new IOException("provider returned no stream");
            byte[] buffer = new byte[65536]; int count;
            while ((count = in.read(buffer)) != -1) {
                if (generation != validationGeneration) return "Comprobación cancelada.";
                size += count;
                if (size > 64L * 1024 * 1024) return "El ejecutable supera el límite de análisis de 64 MiB.";
                digest.update(buffer, 0, count);
            }
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        if (!KNOWN_SHA256.contentEquals(hex) || size != KNOWN_EXE_SIZE)
            return "Ejecutable de versión desconocida. No se ha verificado compatibilidad ni integridad del resto de archivos.";
        byte[] data = new byte[KNOWN_EXE_SIZE];
        MessageDigest second;
        try { second = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException e) { throw new IOException("SHA-256 unavailable", e); }
        try (InputStream in = getContentResolver().openInputStream(file)) {
            if (in == null) throw new IOException("provider returned no stream");
            int offset = 0;
            while (offset < data.length) {
                if (generation != validationGeneration) return "Comprobación cancelada.";
                int count = in.read(data, offset, data.length - offset);
                if (count < 0) return "El ejecutable cambió durante la comprobación.";
                if (count == 0) {
                    int b = in.read();
                    if (b < 0) return "El ejecutable cambió durante la comprobación.";
                    data[offset++] = (byte)b;
                } else offset += count;
            }
            if (in.read() != -1) return "El ejecutable cambió durante la comprobación.";
        }
        second.update(data);
        StringBuilder verified = new StringBuilder();
        for (byte b : second.digest()) verified.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        if (!KNOWN_SHA256.contentEquals(verified)) return "El ejecutable cambió durante la comprobación.";
        if (generation != validationGeneration) return "Comprobación cancelada.";
        try { return nativeInspectKnownPe(data); }
        catch (LinkageError | SecurityException e) { return "Ejecutable identificado por SHA-256; análisis nativo no disponible. El juego sigue sin estar disponible."; }
    }
    private void selectFolder() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try { startActivityForResult(intent, PICK_FOLDER); }
        catch (android.content.ActivityNotFoundException e) { folderStatus.setText("No hay selector de carpetas disponible en este dispositivo."); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_FOLDER || result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (!DocumentsContract.isTreeUri(uri) || (data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION) == 0) {
            folderStatus.setText("La carpeta seleccionada no concedió acceso de lectura."); return;
        }
        try {
            getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            String previous = preferences.getString("tree", null);
            if (previous != null && !previous.equals(uri.toString())) {
                try { getContentResolver().releasePersistableUriPermission(Uri.parse(previous), Intent.FLAG_GRANT_READ_URI_PERMISSION); }
                catch (SecurityException ignored) { }
            }
            preferences.edit().putString("tree", uri.toString()).apply(); validateFolder(uri);
        } catch (SecurityException e) { folderStatus.setText("No se pudo conservar el permiso de lectura de la carpeta."); }
    }
    @Override protected void onDestroy() { validationGeneration++; super.onDestroy(); }
}
