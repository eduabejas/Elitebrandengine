# Fondo de video (opcional)

El sitio trae un **fondo de montaña animado** (escena CSS/SVG con parallax lento,
niebla a la deriva y un *push-in* estilo dron) que funciona sin ningún archivo ni
dependencia. Si querés reemplazarlo por **footage real** de una montaña/dron,
poné aquí un clip:

```
web/assets/video/mountain.mp4      # requerido (H.264/MP4, compatible con todos)
web/assets/video/mountain.webm     # opcional (VP9/WebM, más liviano)
```

El sitio lo detecta y lo muestra **solo si carga**; si no existe o falla, sigue
mostrando la escena animada (nunca queda un fondo en negro).

> Hasta que agregues `mountain.mp4`, la consola del navegador mostrará **un 404
> benigno** por ese archivo: es esperado (el video es opcional) y no afecta al
> sitio. Para usar también un WebM, agregá su ruta al atributo `data-sources`
> del `<video id="bg-video">` en `web/index.html`.

## De dónde bajarlo (gratis, uso comercial, sin atribución)

> Nota: este repositorio se construyó en un entorno cuya política de red bloquea
> los CDN de stock, por eso no se pudo incluir el clip automáticamente. Bajalo
> vos desde cualquiera de estas fuentes y arrastralo a esta carpeta:

- **Pexels** — <https://www.pexels.com/search/videos/mountain%20drone/>
  (ej.: <https://www.pexels.com/video/drone-flying-over-the-mountain-peak-4763824/>)
  · Licencia Pexels: uso libre, comercial, sin atribución.
- **Pixabay** — <https://pixabay.com/videos/search/drone%20mountain/>
  · Licencia Pixabay: uso libre, comercial, sin atribución.
- **Coverr** — <https://coverr.co/s/mountain> · loops de fondo, sin cuenta.

Elegí un clip **corto (5–15 s), en loop y horizontal**; bajá la versión HD
(1080p suele pesar 3–10 MB) para que el sitio cargue rápido.

## Recomendaciones

- **Que loopee bien:** buscá clips marcados como *loop* o con movimiento continuo.
- **Peso:** ideal < 8 MB. Si tu clip pesa mucho, recomprimilo (p. ej. HandBrake:
  MP4/H.264, 1080p, ~2–3 Mbps) o usá la versión 720p.
- **Sin audio:** el fondo va silenciado (`muted`) y en bucle (`loop`), así que el
  audio no importa.

## Alternativa: enlazar una URL en vez de subir el archivo

Si preferís no subir el archivo, editá `web/index.html` y agregá la URL directa
del `.mp4` al atributo `data-sources` del `<video id="bg-video">` (separá con
comas; se usa la primera que cargue). Tené en cuenta que algunos bancos de stock
desaconsejan el hotlink y la URL podría cambiar; subir el archivo es más estable.
