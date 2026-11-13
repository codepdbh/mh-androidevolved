# Icono Android

`manhunt-android-evolved.png` es la imagen generada para el launcher usando como referencia la imagen aportada por el propietario. Se copia sin transformación a `android/app/src/main/res/drawable-nodpi/` y se incluye mediante un icono adaptativo con margen de seguridad. Contiene los textos “MANHUNT” y “ANDROID EVOLVED”.

El recurso está integrado en el manifiesto, pero aún no se ha comprobado en una APK ni visualizado en el lanzador de un dispositivo. La referencia fue aportada por el usuario; cualquier distribución pública debe revisar los derechos sobre la imagen y la denominación.

## Repositorio público

El icono real y su copia en `drawable-nodpi/app_icon_art.png` se excluyen del repositorio público (`.gitignore`) hasta revisar los derechos de la referencia. Tras clonar, copiar `design/app_icon/placeholder.png` (marcador neutro generado) a `android/app/src/main/res/drawable-nodpi/app_icon_art.png`, o colocar allí un icono propio, antes de compilar recursos.
