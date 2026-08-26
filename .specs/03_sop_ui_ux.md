# SPEC-03: UI/UX & Paleta Corporativa Pesco S.A.

## 1. Guía de Estilos y Colores
- **Primary / Corporate Red**: `#D32F2F` (Tailwind: `red-700`)
- **Primary Hover**: `#B71C1C` (Tailwind: `red-800`)
- **Dark Neutral**: `#1E293B` (Slate 800) / `#0F172A` (Slate 900)
- **Background**: `#F8FAFC` (Slate 50)
- **Card Background**: `#FFFFFF` con borde `border-slate-200` y sombra suave `shadow-sm`
- **Critical Urgency Badge**: `#FEE2E2` bg, `#991B1B` text
- **Medium Urgency Badge**: `#FEF3C7` bg, `#92400E` text
- **Normal Badge**: `#D1FAE5` bg, `#065F46` text

## 2. Componentes Frontend Exigidos
1. **Navbar Corporativo**: Logotipo Pesco S.A., Menú Módulos (Dashboard, Ingesta, Recomendador, Chat IA, Reportes), Perfil Usuario y Logout.
2. **KPI Cards con Microanimaciones**: Transiciones suave hover, íconos SVG limpios, valores numéricos formateados (ej: `$125.400 USD`, `1,420 SKUs`).
3. **Filtros Dinámicos (JS)**: Selects por Bodega, Categoría/Gerencia, Nivel de Urgencia y Buscador en tiempo real.
4. **Loading States & Drag & Drop**: Spinners personalizados Pesco para la carga del Excel `0. Stock Proyectado.xlsx`.
