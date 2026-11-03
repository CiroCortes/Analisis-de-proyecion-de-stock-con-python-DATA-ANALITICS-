# Descarga las librerias de terceros (versiones fijas) a static/vendor para uso 100% offline.
# Ejecutar desde la raiz del proyecto: powershell -File tailwind\download_vendor.ps1
$ErrorActionPreference = 'Stop'
$faVersion = '6.5.1'
$chartVersion = '4.4.0'

$chartDir = 'static\vendor\chartjs'
$faCss = 'static\vendor\fontawesome\css'
$faFonts = 'static\vendor\fontawesome\webfonts'
New-Item -ItemType Directory -Force -Path $chartDir, $faCss, $faFonts | Out-Null

Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/chart.js@$chartVersion/dist/chart.umd.min.js" -OutFile "$chartDir\chart.umd.min.js"
Invoke-WebRequest -Uri "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$faVersion/css/all.min.css" -OutFile "$faCss\all.min.css"

$css = Get-Content "$faCss\all.min.css" -Raw
$files = [regex]::Matches($css, 'fa-[a-z0-9-]+\.(woff2|ttf)') | ForEach-Object { $_.Value } | Sort-Object -Unique
foreach ($f in $files) {
    Invoke-WebRequest -Uri "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/$faVersion/webfonts/$f" -OutFile "$faFonts\$f"
}
Get-ChildItem static\vendor -Recurse -File | Select-Object FullName, Length

