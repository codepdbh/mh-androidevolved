# Assets táctiles

54 identificadores, tres estados cada uno: 162 PNG RGBA de 256 × 256 y fuentes SVG reproducibles. Diseño original generado con Pillow, sin gráficos comerciales. `python tools/generate_touch_assets.py` regenera los recursos y `python tools/verify_touch_assets.py` valida manifiesto, dimensiones, transparencia, márgenes, diferencias de estado y reproducción de píxeles y SVG. `preview.png` muestra todas las variantes.

Los nombres son propuestas visuales, no evidencia de que las acciones existan ni de que estén asociadas a teclas originales. Se necesita revisión visual y pruebas en móvil. La aplicación muestra una selección de estos PNG como vista previa; no constituyen un HUD de juego funcional.
