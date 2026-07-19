# Enfoque legal y sostenible — y cómo lo hace Honey (de verdad)

Este documento responde a dos preguntas del encargo:

1. *¿Cómo hacen apps como **Honey** para encontrar ofertas en tantos sitios?*
2. *¿Qué pasa con "evadir reCAPTCHA y herramientas anti-scraping"?*

La respuesta corta une ambas: **las apps serias no evaden controles de
seguridad. Usan relaciones de datos legítimas.** Este motor sigue ese mismo
camino, que además es el único que se sostiene gratis en GitHub sin que te
bloqueen ni te demanden.

---

## 1. Cómo funciona Honey realmente

Existe el mito de que Honey "scrapea" miles de tiendas esquivando sus defensas.
No es así:

- **Honey es una extensión de navegador.** Se ejecuta **dentro de la sesión ya
  iniciada del propio usuario**. Cuando llegás al checkout, Honey prueba cupones
  *desde tu navegador y con tu identidad* — por eso **nunca se topa con un
  reCAPTCHA**: para el sitio, es el usuario real quien navega.
- **Su motor económico es el marketing de afiliados.** Honey cobra una comisión
  cuando comprás en un comercio con el que tiene acuerdo; los comercios definen
  qué cupones se ofrecen. Los códigos son en gran parte **crowdsourced**
  (aportados/validados por la comunidad), no extraídos por la fuerza.
- **Los precios/ofertas vienen de acuerdos, no de asaltar servidores.**

Fuentes: [Wikipedia — PayPal Honey][honey-wiki] · [Snopes][honey-snopes].

**Conclusión clave:** la "magia" no está en vencer defensas anti-bot, sino en
operar *dentro* de canales autorizados (la sesión del usuario + afiliados). Un
motor del lado del servidor, como el nuestro, logra lo mismo usando **APIs
oficiales y datafeeds de afiliados**.

---

## 2. Por qué NO evadimos reCAPTCHA ni anti-scraping

Cuando un sitio te muestra un CAPTCHA o te bloquea, te está diciendo
explícitamente *"no automatices esto"*. Intentar burlarlo trae tres problemas:

### Riesgo legal
- **Términos de Servicio:** casi todos los grandes retailers prohíben el scraping
  automatizado. Violarlos rompe el contrato de uso.
- **CFAA (EE. UU., *Computer Fraud and Abuse Act*):** acceder "excediendo la
  autorización" puede ser accionable — especialmente relevante para una empresa
  estadounidense.
- **DMCA §1201:** eludir una medida técnica de protección (y un anti-bot/CAPTCHA
  lo es) está expresamente prohibido.
- Precedentes reales de demandas por scraping agresivo existen y son caros.

### Fragilidad técnica
- Las defensas (Cloudflare, PerimeterX/HUMAN, DataDome, Akamai) **cambian cada
  semana**. Cualquier "solución" de evasión se rompe y exige mantenimiento
  constante.
- Termina en una carrera armamentística: rotación de IPs/proxies, granjas de
  resolución de CAPTCHA, *fingerprints* falsos… caro, inestable e imposible de
  sostener en el plan gratuito de GitHub (IPs compartidas, fácilmente baneables).

### No hace falta
- Para **comparar precios** ya existen vías oficiales que entregan los mismos
  datos de forma limpia, estructurada y estable. Usarlas es más rápido de
  construir y no se cae.

> Regla del proyecto: si una fuente exige evadir un control para leer sus
> precios, **no es una fuente válida**. Buscamos su API, su datafeed de
> afiliado, o la descartamos.

---

## 3. El enfoque que sí funciona (y que implementa este motor)

| Fuente | Vía legítima usada | Qué necesitás |
| --- | --- | --- |
| **eBay** | **Browse API** oficial (OAuth *client-credentials*) | App gratuita en eBay Developers → `EBAY_CLIENT_ID/SECRET` |
| **Amazon** | **Product Advertising API 5.0** (firma AWS SigV4) | Cuenta Amazon Associates aprobada → claves PA-API |
| **REI, Backcountry, Patagonia, tiendas oficiales de marca** | **Datafeeds de productos de afiliados** (AvantLink / Impact / CJ) | Alta como afiliado del programa; el feed trae nombre, marca, precio, precio de lista, URL de compra, imagen |
| **Otras tiendas sin API/feed** | *Scraping cortés*: respeta `robots.txt`, se identifica, limita el ritmo y **se retira** ante cualquier bloqueo/CAPTCHA | Verificar que los ToS lo permitan |

Los **datafeeds de afiliados son la pieza central**: AvantLink los describe
literalmente como ideales para *"sitios de comparación"*, e incluye a Backcountry,
REI, Patagonia y muchas de nuestras marcas insignia. ([AvantLink][avantlink])
Es exactamente el canal legal que reemplaza al scraping.

Además, ser afiliado tiene un beneficio de negocio: los enlaces que envía el
motor pueden llevar tu *tag* y **generar comisiones** — el mismo modelo que
sostiene a Honey.

---

## 4. Cómo se refleja en el código

- `engine/connectors/ebay.py` — Browse API (token OAuth + búsqueda).
- `engine/connectors/amazon.py` — PA-API 5.0 con firma SigV4.
- `engine/connectors/affiliate_feed.py` — lee feeds CSV/TSV/XML y mapea columnas.
- `engine/connectors/polite_html.py` — base *cumplidora*: `robots.txt`,
  *rate-limit*, *User-Agent* honesto y **back-off** ante `403/429`/CAPTCHA.
  Nunca rota identidades ni resuelve CAPTCHAs.

Cada conector está **desacoplado**: activás en `config.yml` los que tengas
credenciales y el resto se ignora sin romper la corrida.

---

## 5. Pasos para pasar de demo a datos reales

1. **eBay:** creá una app gratuita en <https://developer.ebay.com/> y cargá
   `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` como *Secrets*. Poné
   `sources.ebay.enabled: true`.
2. **Amazon:** unite a **Amazon Associates**, pedí acceso a **PA-API**, cargá
   `AMAZON_ACCESS_KEY` / `AMAZON_SECRET_KEY` / `AMAZON_PARTNER_TAG`.
3. **Afiliados (REI/Backcountry/marcas):** registrate en **AvantLink** e
   **Impact**, aprobá los programas de las marcas, copiá la URL de tu *datafeed*
   y agregá una entrada en `sources.affiliate_feed.feeds` con el mapeo de columnas.
4. Dejá el conector `sample` en `false` cuando ya tengas fuentes reales.

---

## Referencias

- PayPal Honey — Wikipedia: <https://en.wikipedia.org/wiki/PayPal_Honey>
- Snopes, análisis de Honey (2024): <https://www.snopes.com/news/2024/12/30/honey-browser-extension-scam/>
- eBay Browse API: <https://developer.ebay.com/api-docs/buy/browse/overview.html>
- Amazon PA-API 5.0: <https://webservices.amazon.com/paapi5/documentation/>
- AvantLink — datafeeds para comparación: <https://support.avantlink.com/hc/en-us/articles/4404406207501-Datafeed-Manager-Affiliate-User-Guide-Product-Datafeeds>

[honey-wiki]: https://en.wikipedia.org/wiki/PayPal_Honey
[honey-snopes]: https://www.snopes.com/news/2024/12/30/honey-browser-extension-scam/
[avantlink]: https://support.avantlink.com/hc/en-us/articles/4404406207501-Datafeed-Manager-Affiliate-User-Guide-Product-Datafeeds
