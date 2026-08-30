# Pasos manuales — Automatización + Dashboard web

Esto es lo que **vos** tenés que hacer a mano en GitHub (Claude Code no puede
tocar la interfaz web de GitHub). Corresponde al plan en
[PLAN_AUTOMATIZACION_WEB.md](PLAN_AUTOMATIZACION_WEB.md). Se hace **una vez**
que el código del plan (workflow, exportador, dashboard) ya esté implementado y
mergeado a `main` — no hay nada para hacer todavía si solo existe el plan.

## 1. Habilitar GitHub Pages

1. Andá a `https://github.com/Gab9Cruzz/UsOpen_Prediction/settings/pages`.
2. En **Build and deployment → Source**, elegí **"Deploy from a branch"**
   (decisión D2 del plan — la opción más simple, sin action extra).
3. En **Branch**, elegí `main` y la carpeta **`/docs`**.
4. Guardá. GitHub tarda 1-2 minutos en publicar la primera vez. La URL del sitio
   va a ser `https://gab9cruzz.github.io/UsOpen_Prediction/`.
5. Verificación: abrí esa URL — deberías ver el dashboard (asumiendo que ya
   existe al menos un `docs/data/resultados_simulacion.json` commiteado, ver
   commit #4 de la sección 7.1 del plan).

## 2. Dar permiso de escritura al bot de Actions

El workflow necesita hacer `git push` con el token automático de GitHub
(`GITHUB_TOKEN`). Desde 2023 GitHub crea los repos nuevos con ese token en modo
**solo lectura** por default — sin este paso, el `git push` del bot falla con
un error 403 silencioso (el job puede aparecer en verde igual si no revisás el
log del paso de commit).

1. Andá a `https://github.com/Gab9Cruzz/UsOpen_Prediction/settings/actions`.
2. Bajá hasta **Workflow permissions**.
3. Elegí **"Read and write permissions"**.
4. Guardá.

(El propio workflow YAML también declara `permissions: contents: write` — este
toggle de Settings es el techo máximo que ese `permissions:` no puede superar;
hacen falta los dos.)

## 3. Mantenimiento anual — actualizar la ventana del cron

El workflow corre solo durante un rango de fechas fijo (decisión D1 del plan:
correrlo los 365 días del año no tiene sentido para un torneo de ~2 semanas).
**Una vez al año**, antes de que arranque el próximo US Open:

1. Confirmá las fechas oficiales de esa edición (usopen.org o Wikipedia).
2. Abrí `.github/workflows/actualizar_prediccion.yml`.
3. Actualizá el rango de fechas hardcodeado que usa el chequeo de "¿estamos en
   ventana de torneo?" (el propio archivo va a tener un comentario marcando
   exactamente esa línea).
4. Commiteá el cambio (`chore: actualizar ventana del torneo a YYYY`).

**Ya NO hace falta** actualizar el año del torneo por separado — el workflow
pasa `--draw-year "$(date +%Y)"` dinámicamente (hallazgo #9 de la revisión de
este plan), así que ese valor se ajusta solo con la fecha del calendario.

## 4. Verificar que el workflow corrió (primeras veces)

1. Andá a la pestaña **Actions** del repo.
2. Buscá la corrida más reciente de "Actualizar predicción" (o el nombre que
   tenga el workflow).
3. Si está en rojo: abrí el log. Los motivos más comunes, en orden de
   probabilidad:
   - Falta el paso 2 de acá arriba (permisos de escritura).
   - Sackmann/su mirror están caídos (`atp_matches_<año>.csv` no se pudo
     descargar) — reintenta solo, no hace falta acción tuya.
   - Wikipedia cambió el formato del artículo del sorteo — esto SÍ requiere
     revisar `src/data/live_draw.py` (fuera del alcance de este documento,
     es un cambio de código).

## 5. Primer commit manual (arranque en frío)

Antes de que el cron corra por primera vez, el sitio no debe arrancar vacío
(ver "HORA 6+" en el plan). Corré una vez a mano, en tu máquina:

```bash
python simular_usopen.py --update-data --export-json docs/data/resultados_simulacion.json
git add docs/data/resultados_simulacion.json
git commit -m "feat(web): primer JSON exportado a mano (arranque en frío)"
git push
```

Esto es un paso único — de ahí en más lo hace solo el workflow.
