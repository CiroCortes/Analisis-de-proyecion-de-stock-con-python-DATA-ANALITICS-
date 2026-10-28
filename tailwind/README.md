# CSS de Tailwind

El sitio usa `static/css/tailwind.css`, generado con la herramienta oficial de Tailwind (3.4.17).
No depende de `cdn.tailwindcss.com`, que no responde desde la red de Pesco (28-oct-2026).

Si se agregan clases nuevas en plantillas o en código Python, regenerar desde la raíz del proyecto
(requiere Node):

    npx -y tailwindcss@3.4.17 -c tailwind/tailwind.config.js -i tailwind/input.css -o static/css/tailwind.css --minify

El archivo generado se versiona: correr el sistema no requiere Node.
