# Guía de operación — Elite Brand Engine

Manual práctico para poner en marcha y mantener el motor. No hace falta ser
programador para operarlo: casi todo se controla editando dos archivos
(`data/watchlist.json` y `config.yml`) y cargando algunos *Secrets* en GitHub.

---

## 1. Qué hace, en una frase

Vigila una lista de productos de marcas de montañismo, busca sus precios en
varias tiendas por vías legítimas, detecta cuándo hay una **oferta real**, te
avisa por **email** y publica un **sitio web** de comparación — todo **gratis**
en GitHub.

---

## 2. Prueba en 2 minutos (modo demo, sin configurar nada)

```bash
pip install -r requirements.txt
python scripts/seed_demo.py 30       # historial de precios de ejemplo
python -m engine.run --no-email      # corre una recolección (fuente demo)
cd web && python -m http.server 8000 # abrí http://localhost:8000
```

Vas a ver el sitio con ofertas de ejemplo y una insignia **"Modo demo"**. Esa
insignia desaparece sola cuando activás fuentes reales (eBay/Amazon/afiliados).

---

## 3. Editar los productos que se vigilan — `data/watchlist.json`

Cada producto es un objeto dentro de `"items"`. Campos:

| Campo | Obligatorio | Qué es |
| --- | --- | --- |
| `id` | sí | identificador único (sin espacios), ej. `arcteryx_beta_ar_jacket` |
| `brand` | sí | marca (se aceptan variantes: `arcteryx`, `Arc'teryx`…) |
| `name` | sí | nombre del modelo, ej. `Beta AR Jacket` |
| `category` | no | categoría para filtrar en el sitio, ej. `Hardshell` |
| `sizes` | no | tallas deseadas; **vacío = cualquiera**. Ej. `["M","L"]`, `["US 10.5"]`, `["65L"]` |
| `colors` | no | colores deseados; vacío = cualquiera. Ej. `["black","blue"]` |
| `target_price` | no | precio objetivo en USD: avisa si baja a ese valor o menos |
| `keywords` | no | términos extra para mejorar la búsqueda en las APIs/feeds |
| `upc` / `mpn` | no | código de barras / número de parte (mejora la precisión) |
| `active` | no | `false` para pausar un producto sin borrarlo |

Ejemplo:

```json
{
  "id": "tnf_nuptse_1996",
  "brand": "The North Face",
  "name": "1996 Retro Nuptse Jacket",
  "category": "Down Jacket",
  "sizes": ["M", "L", "XL"],
  "colors": ["black"],
  "target_price": 210.00,
  "keywords": ["700 fill", "puffer"]
}
```

> Consejo: poné un `target_price` realista (el precio de oferta que te haría
> comprar). Si no ponés ninguno, el motor igual detecta caídas comparando contra
> el historial.

---

## 4. Cómo decide que algo es "oferta"

Una oferta se dispara si se cumple **al menos una** condición (configurable en
`config.yml → detection`):

1. **Precio objetivo:** el precio llega a `target_price` o menos.
2. **Descuento vs. referencia:** el precio está ≥ `min_discount_pct` (15% por
   defecto) por debajo del precio de lista de la tienda o de la **mediana
   histórica**.
3. **Mínimo histórico:** con suficiente historial, el precio es el más bajo
   jamás registrado.

Solo cuentan las **variantes que pediste** (talla/color). Y un mismo aviso no se
reenvía por email dentro de `alert_ttl_days` (7 días por defecto).

---

## 5. Configurar el email de alertas

El transporte se detecta solo según los *Secrets* que cargues (el primero que
esté configurado gana). Cargalos en **GitHub → Settings → Secrets and variables
→ Actions**.

### Opción A — Gmail (SMTP con contraseña de aplicación)
1. Activá verificación en dos pasos en la cuenta de Gmail.
2. Creá una **contraseña de aplicación** (Google Account → Seguridad).
3. Cargá estos *Secrets*:
   - `SMTP_HOST = smtp.gmail.com`
   - `SMTP_PORT = 587`
   - `SMTP_USER = tucuenta@gmail.com`
   - `SMTP_PASS = ` (la contraseña de aplicación de 16 caracteres)
   - `SMTP_FROM = tucuenta@gmail.com`

### Opción B — SendGrid o Resend (recomendado para volumen)
- SendGrid: *Secret* `SENDGRID_API_KEY` (+ `ALERT_EMAIL_FROM` con un remitente verificado).
- Resend: *Secret* `RESEND_API_KEY` (+ `ALERT_EMAIL_FROM`).

### Destinatarios
Cargá una **Variable** (no secreta) `ALERT_EMAIL_TO` con los correos separados
por coma, o poné `email.to: ["compras@tuempresa.com"]` en `config.yml`.

> Sin transporte o sin destinatarios, el motor NO falla: escribe el email en
> `dist/last_email.html` (modo *dry-run*) para que lo revises.

### Qué muestra el email
Por cada oferta: **nombre del producto, talla, website (tienda), link directo y
precio** — más color, descuento y condición (nuevo/usado) como contexto.

---

## 6. Publicar el sitio y activar el cron (una sola vez)

1. Subí el repo a GitHub (repo **público** = minutos de Actions ilimitados).
2. **Settings → Pages → Source = "GitHub Actions".** El workflow *Deploy site*
   publica la web. Queda en `https://<usuario>.github.io/<repo>/`.
3. El workflow *Collect deals* ya corre **cada 6 horas** (y a mano desde la
   pestaña *Actions → Collect deals → Run workflow*). Recolecta, envía avisos y
   commitea los precios nuevos, lo que vuelve a publicar el sitio actualizado.

Para cambiar la frecuencia, editá el `cron` en
`.github/workflows/collect.yml` (mínimo recomendado: cada 1–2 horas).

---

## 7. Pasar de demo a datos reales

Resumen (detalle completo en
[ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md](ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md)):

1. **eBay:** app gratis en developer.ebay.com → *Secrets* `EBAY_CLIENT_ID/SECRET`
   → `sources.ebay.enabled: true`.
2. **Amazon:** Amazon Associates + PA-API → *Secrets* `AMAZON_ACCESS_KEY`,
   `AMAZON_SECRET_KEY`, `AMAZON_PARTNER_TAG` → `sources.amazon.enabled: true`.
3. **REI / Backcountry / Patagonia / marcas:** afiliate en **AvantLink**/**Impact**,
   copiá la URL de tu *datafeed* y agregá una entrada en
   `sources.affiliate_feed.feeds` con el mapeo de columnas.
4. Cuando tengas fuentes reales, poné `sources.sample.enabled: false`.

---

## 8. Solución de problemas

| Síntoma | Causa probable / arreglo |
| --- | --- |
| El sitio muestra "Modo demo" | Solo está activa la fuente `sample`. Activá eBay/Amazon/feeds. |
| No llegan emails | Faltan *Secrets* de transporte o `ALERT_EMAIL_TO`. Revisá el artefacto `last-email` del run para ver el contenido. |
| "enabled but not available" en el log | El conector está `enabled` pero faltan sus credenciales. |
| Pocos resultados de una fuente | Bajá `min_match_score` o agregá `keywords`/`upc` al producto. |
| El sitio no actualiza | Verificá que *Deploy site* corrió tras el commit de precios; que Pages use "GitHub Actions". |
| Un scraper propio deja de andar | Si aparece un CAPTCHA/bloqueo, **no lo evadas**: usá la API o el feed de esa tienda. |

---

## 9. Costos

**Cero.** GitHub Pages (hosting) + GitHub Actions (cron) son gratuitos para
repos públicos. Las APIs de eBay y los datafeeds de afiliados son gratuitos para
afiliados aprobados. El único "costo" es darte de alta como afiliado/desarrollador
en cada programa.
