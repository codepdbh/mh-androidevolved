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
    private static native String nativeRunSelfTest();
    private static native String nativeReadDescriptor(int fd, byte[] expected);
    /** Optional private build artifacts: translated game code is never part of the public sources. */
    private static final String TRANSLATED_HARNESS = "libmhae_time_test.so";
    private static final String TRANSLATED_EXPECTED = "translated/time_expected.json";
    private TextView translatedStatus;

    private static String runtimeDiagnostic() {
        try {
            System.loadLibrary("mh_runtime");
            return nativeGetRuntimeDiagnostic() + "\n\n" + nativeRunSelfTest();
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
        layout.addView(text("Código traducido del juego", 20, Color.WHITE));
        translatedStatus = text("Ejecuta en un proceso aislado la candidata de tiempo traducida con datos sintéticos y compara el resultado con el validado frente a x86. No arranca el juego.", 14, Color.LTGRAY);
        layout.addView(translatedStatus);
        Button translated = new Button(this); translated.setText("Ejecutar prueba de código traducido");
        translated.setOnClickListener(v -> runTranslatedHarness(translated)); layout.addView(translated);
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
        String inspected;
        try { inspected = nativeInspectKnownPe(data); }
        catch (LinkageError | SecurityException e) { return "Ejecutable identificado por SHA-256; análisis nativo no disponible. El juego sigue sin estar disponible."; }
        if (generation != validationGeneration) return "Comprobación cancelada.";
        // Same file again, now through a read-only descriptor and the port's native read layer.
        try (android.os.ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(file, "r")) {
            if (pfd == null) return inspected + "\n\nLectura por descriptor: el proveedor no devolvió descriptor.";
            return inspected + "\n\n" + nativeReadDescriptor(pfd.getFd(), data);
        } catch (LinkageError e) {
            return inspected + "\n\nLectura por descriptor no disponible en esta biblioteca.";
        }
    }

    /** Runs the private translated harness, if this build includes it, and checks its output hashes. */
    private void runTranslatedHarness(Button button) {
        button.setEnabled(false);
        translatedStatus.setText("Ejecutando código traducido en un proceso aislado…");
        new Thread(() -> {
            String result;
            try { result = translatedHarnessReport(); }
            catch (IOException | InterruptedException | org.json.JSONException | SecurityException e) {
                result = "La prueba no pudo completarse: " + e.getClass().getSimpleName() + ": " + e.getMessage();
            }
            final String message = result;
            runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) { translatedStatus.setText(message); button.setEnabled(true); } });
        }, "translated-harness").start();
    }
    private String translatedHarnessReport() throws IOException, InterruptedException, org.json.JSONException {
        java.io.File binary = new java.io.File(getApplicationInfo().nativeLibraryDir, TRANSLATED_HARNESS);
        String expectedText;
        try (InputStream in = getAssets().open(TRANSLATED_EXPECTED)) { expectedText = new String(readAll(in), java.nio.charset.StandardCharsets.UTF_8); }
        catch (IOException e) { expectedText = null; }
        if (!binary.isFile() || expectedText == null)
            return "Esta compilación no incluye código traducido: se genera solo en el PC del propietario a partir de su copia del juego y no se distribuye.";
        org.json.JSONObject expected = new org.json.JSONObject(expectedText);
        if (!expected.getString("binary_sha256").equals(sha256(readFile(binary))))
            return "El binario traducido no coincide con el validado; no se ejecuta.";
        long started = android.os.SystemClock.elapsedRealtime();
        RunResult main = runHarness(binary, null), zero = runHarness(binary, "--virtual-zero"), x87 = runHarness(binary, "--x87-semantics");
        String[][] faults = {{"--null-object", "70"}, {"--missing-timer", "74"}, {"--missing-virtual", "75"}, {"--null-virtual-object", "71"}};
        int faultsOk = 0;
        for (String[] f : faults) if (runHarness(binary, f[0]).exit == Integer.parseInt(f[1])) faultsOk++;
        long elapsed = android.os.SystemClock.elapsedRealtime() - started;
        boolean mainOk = main.exit == 0 && expected.getString("main_output_sha256").equals(main.sha256);
        boolean zeroOk = zero.exit == 0 && expected.getString("zero_output_sha256").equals(zero.sha256);
        String loader = loaderReport() + "\n" + validatedReport("libmhae_allocator_test.so", "translated/allocator_expected.json",
            "Asignador de memoria del juego (constructor, reservar y liberar; 16 casos, 960 operaciones)")
            + "\n" + validatedReport("libmhae_heap_test.so", "translated/heap_expected.json",
            "Heap del juego sobre GlobalAlloc y secciones críticas del port (16 casos, 640 malloc)");
        elapsed = android.os.SystemClock.elapsedRealtime() - started;
        boolean all = mainOk && zeroOk && x87.exit == 0 && faultsOk == faults.length && !loader.contains("distinto") && !loader.contains("no se");
        return (all ? "CORRECTO" : "FALLO") + " · código traducido del juego ejecutado en ARM64 dentro de la app (" + elapsed + " ms)\n"
            + "· Candidata de tiempo 0x6081a0 con 13 dependencias traducidas, 256 casos: " + (mainOk ? "salida idéntica a la validada frente a x86" : "salida distinta (código " + main.exit + ")") + "\n"
            + "· Rama de argumento cero, 12 casos: " + (zeroOk ? "idéntica" : "distinta (código " + zero.exit + ")") + "\n"
            + "· Semántica x87 en el proceso traducido: " + (x87.exit == 0 ? "correcta" : "fallo " + x87.exit) + "\n"
            + "· Fallos controlados esperados: " + faultsOk + " de " + faults.length + "\n"
            + loader + "\n"
            + "Datos sintéticos y funciones restantes simuladas: no es el arranque del juego.";
    }
    private static final class RunResult { int exit; String sha256; }
    /** Runs the translated slot loader 0x605750 over synthetic slot files in a private cache directory. */
    private String loaderReport() throws IOException, InterruptedException, org.json.JSONException {
        java.io.File binary = new java.io.File(getApplicationInfo().nativeLibraryDir, "libmhae_loader_test.so");
        String expectedText;
        try (InputStream in = getAssets().open("translated/loader_expected.json")) { expectedText = new String(readAll(in), java.nio.charset.StandardCharsets.UTF_8); }
        catch (IOException e) { expectedText = null; }
        if (!binary.isFile() || expectedText == null) return "· Cargador de archivos 0x605750: no incluido en esta compilación.";
        org.json.JSONObject expected = new org.json.JSONObject(expectedText);
        if (!expected.getString("binary_sha256").equals(sha256(readFile(binary)))) return "· Cargador de archivos: binario distinto del validado; no se ejecuta.";
        java.io.File work = new java.io.File(getCacheDir(), "loader-" + System.nanoTime());
        if (!work.mkdir()) return "· Cargador de archivos: no se pudo crear el directorio temporal.";
        try {
            RunResult r = runHarness(binary, work.getAbsolutePath());
            boolean ok = r.exit == 0 && expected.getString("output_sha256").equals(r.sha256);
            return "· Cargador de archivos 0x605750 sobre asignador, heap y Win32 del port (52 funciones traducidas, 16 casos): "
                + (ok ? "idéntico a x86" : "distinto (código " + r.exit + ")");
        } finally {
            if (!work.delete()) work.deleteOnExit();
        }
    }
    /** Runs one private validated binary without arguments and checks the SHA-256 of its output. */
    private String validatedReport(String library, String asset, String label) throws IOException, InterruptedException, org.json.JSONException {
        java.io.File binary = new java.io.File(getApplicationInfo().nativeLibraryDir, library);
        String expectedText;
        try (InputStream in = getAssets().open(asset)) { expectedText = new String(readAll(in), java.nio.charset.StandardCharsets.UTF_8); }
        catch (IOException e) { expectedText = null; }
        if (!binary.isFile() || expectedText == null) return "· " + label + ": no incluido en esta compilación.";
        org.json.JSONObject expected = new org.json.JSONObject(expectedText);
        if (!expected.getString("binary_sha256").equals(sha256(readFile(binary)))) return "· " + label + ": binario distinto del validado; no se ejecuta.";
        RunResult r = runHarness(binary, null);
        return "· " + label + ": " + (r.exit == 0 && expected.getString("output_sha256").equals(r.sha256) ? "idéntico a x86" : "distinto (código " + r.exit + ")");
    }
    private RunResult runHarness(java.io.File binary, String argument) throws IOException, InterruptedException {
        ProcessBuilder builder = argument == null ? new ProcessBuilder(binary.getAbsolutePath()) : new ProcessBuilder(binary.getAbsolutePath(), argument);
        builder.redirectError(ProcessBuilder.Redirect.to(new java.io.File("/dev/null")));
        Process process = builder.start();
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException e) { process.destroy(); throw new IOException(e); }
        long total = 0;
        try (InputStream in = process.getInputStream()) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = in.read(buffer)) != -1) {
                total += count;
                if (total > 64L * 1024 * 1024) { process.destroyForcibly(); throw new IOException("salida demasiado grande"); }
                digest.update(buffer, 0, count);
            }
        }
        if (!process.waitFor(30, java.util.concurrent.TimeUnit.SECONDS)) { process.destroyForcibly(); throw new IOException("tiempo agotado"); }
        RunResult r = new RunResult(); r.exit = process.exitValue(); r.sha256 = hex(digest.digest()); return r;
    }
    private static byte[] readAll(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[8192]; int count;
        while ((count = in.read(buffer)) != -1) { out.write(buffer, 0, count); if (out.size() > 16 * 1024 * 1024) throw new IOException("archivo demasiado grande"); }
        return out.toByteArray();
    }
    private static byte[] readFile(java.io.File file) throws IOException {
        try (InputStream in = new java.io.FileInputStream(file)) { return readAll(in); }
    }
    private static String sha256(byte[] data) throws IOException {
        try { return hex(MessageDigest.getInstance("SHA-256").digest(data)); }
        catch (NoSuchAlgorithmException e) { throw new IOException(e); }
    }
    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder();
        for (byte b : bytes) out.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return out.toString();
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
