# Instructivo: bajar los reportes de Amazon sin entrar a Vendor Central

Esto reemplaza la descarga manual de los dos archivos semanales
`Amazon_SO_WTD_Ventas_*.xlsx` y `Amazon_SO_WTD_Inventario_*.xlsx`. En vez de
entrar a Vendor Central y exportarlos a mano, un script los pide a la API de
Amazon (SP-API) y arma los mismos xlsx, con el mismo formato: mismas columnas,
mismos encabezados, misma fila de metadatos.

Los numeros salen identicos. Se verifico contra los archivos descargados a
mano: mismo total de unidades y mismo dato ASIN por ASIN.

---

## 1. Lo que necesitas antes de empezar

Esto **no funciona con usuario y contrasena** de Vendor Central. La API usa
credenciales propias que hay que tramitar una sola vez.

| Requisito | Detalle |
|---|---|
| Cuenta de Vendor Central | con rol de **administrador** |
| Solicitud de acceso a SP-API | aprobada por Amazon (Solution Provider Portal) |
| Aplicacion registrada | de tipo **Produccion**, no Sandbox |
| Rol Brand Analytics | solo si vas a usar Data Kiosk (para titulo y marca) |
| Python 3.10 o superior | `python --version` para confirmar |

Si no tenes la app aprobada todavia, ese tramite va primero y tarda. El resto
de este instructivo asume que ya la tenes.

---

## 2. Las tres credenciales

Son tres cosas distintas y se consiguen en dos lugares distintos. Esta es la
parte donde se traba todo el mundo.

| Credencial | Donde sale | Ojo |
|---|---|---|
| **Client ID** | Solution Provider Portal, al registrar la app | empieza con `amzn1.application-oa2-client.` |
| **Client Secret** | idem | **se muestra una sola vez**, copialo al toque |
| **Refresh Token** | Vendor Central, paso aparte (abajo) | empieza con `Atzr\|`, ~330 caracteres |

### Como sacar el Refresh Token

Registrar la app te da ID y Secret. **Autorizarla sobre tu cuenta es un paso
separado** y es el que da el refresh token:

1. Entra a **Vendor Central** con el usuario **administrador** (tiene que ser
   el duenio de la app, no un usuario secundario).
2. **Configuracion → Central de Desarrolladores.**
3. En la fila de tu app: **Editar app / Acciones → Autorizar**.
4. Acepta la pantalla de consentimiento.
5. Te muestra el **Refresh Token**. **Se muestra una sola vez.** Copialo ya.

Si no aparece el boton *Autorizar*:

- La app tiene que estar **publicada/aprobada**, no en borrador.
- Solo aplica a apps privadas (uso propio). Si la registraste como publica, el
  flujo es otro (OAuth de tres patas con redirect URI).
- Tu usuario necesita el permiso de **Developer**, que es aparte del de
  administrador.

> **Antes de autorizar**, fijate si la app tiene asignado el rol **Brand
> Analytics**. Si no lo tiene y autorizas igual, el token no va a servir para
> Data Kiosk y vas a tener que repetir todo el paso.

---

## 3. Instalacion

Copia la carpeta completa a donde la quieras tener. Despues, en PowerShell:

```powershell
cd C:\ruta\donde\la\dejaste
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Son dos dependencias nada mas: `requests` y `openpyxl`.

### Configurar las credenciales

Copia `.env.example` a `.env` y completa las tres primeras lineas:

```powershell
copy .env.example .env
notepad .env
```

```ini
SPAPI_CLIENT_ID=amzn1.application-oa2-client.tu-id-aca
SPAPI_CLIENT_SECRET=amzn1.oa2-cs.v1.tu-secret-aca
SPAPI_REFRESH_TOKEN=Atzr|IwEBI...tu-refresh-token-aca

SPAPI_ENDPOINT=https://sellingpartnerapi-na.amazon.com
SPAPI_LWA_ENDPOINT=https://api.amazon.com/auth/o2/token
SPAPI_MARKETPLACE_ID=A1AM78C64UM0Y8
```

Las ultimas tres ya vienen bien para **Mexico**. Si trabajas otro pais hay que
cambiar `SPAPI_MARKETPLACE_ID`, y si es fuera de America tambien el endpoint
(`-eu` o `-fe` en vez de `-na`).

> **El `.env` tiene credenciales. Nunca lo subas a git ni lo mandes por
> correo.** Ya esta en el `.gitignore`.

### Probar que funciona

```powershell
python check_auth.py
```

Tiene que responder algo asi:

```
Access token OK (len=332)
Endpoint       : https://sellingpartnerapi-na.amazon.com
Marketplace    : A1AM78C64UM0Y8
Reports API OK: 0 reportes recientes
```

Si falla, mira la seccion 7.

---

## 4. Generar los dos archivos

Un solo comando:

```powershell
python export_xlsx.py --descarga 2026-08-30 --destino "C:\ruta\donde\los\guardas"
```

`--descarga` es **el domingo en que los bajarias a mano**. El script calcula
solo el rango de la semana y le pone al archivo el mismo nombre que tendria la
descarga manual.

Deja dos archivos:

```
Amazon_SO_WTD_Ventas_2026_08_30.xlsx
Amazon_SO_WTD_Inventario_2026_08_30.xlsx
```

Tarda unos 2 a 4 minutos. Los reportes de Amazon son asincronos: el script los
pide, espera a que esten listos y recien ahi los baja. Va imprimiendo el
avance (`IN_QUEUE`, `IN_PROGRESS`, `DONE`).

### Otras formas de correrlo

```powershell
# Rango explicito, por si necesitas algo fuera de la semana normal
python export_xlsx.py --desde 2026-08-23 --hasta 2026-08-29

# Sin titulo ni marca (mas rapido, se saltea Data Kiosk)
python export_xlsx.py --descarga 2026-08-30 --sin-catalogo

# Sin --destino, los deja en la carpeta out\
python export_xlsx.py --descarga 2026-08-30
```

---

## 5. Dos cosas que te van a morder si no las sabes

### La semana de Amazon es domingo a sabado

**No es lunes a domingo.** El archivo que se descarga el domingo 30 de agosto
cubre del **domingo 23 al sabado 29**.

Esto ya venia asi en la descarga manual, solo que no se nota: el nombre del
archivo dice `2026_08_30` pero adentro, en la fila 1, dice
`Rango de visualizacion=[23/08/26 - 29/08/26]`. **El nombre es la fecha de
descarga, no el rango de datos.** El rango real esta siempre en esa fila.

Si tu sistema aguas abajo usa semana ISO (lunes a domingo), hay **un dia de
desfase en cada punta** y los numeros no van a cerrar contra otros canales.
Para eso hay otro script, `build_semanal.py`, que reagrupa por semana ISO
aprovechando que la API entrega los datos dia por dia.

### Amazon publica los datos con ~34 horas de atraso

Los datos de un dia estan disponibles recien **dos dias despues, alrededor de
las 10am**. O sea:

- El domingo 30 **no** podes bajar la semana que cierra ese mismo domingo.
- Si pedis un rango que incluye dias no publicados, el reporte falla con
  `FATAL` y este mensaje:
  *"The report data for the requested date range is not yet available."*

**Regla practica: corre el script el martes**, no el domingo. Para entonces la
semana entera ya esta publicada.

---

## 6. Que traen los archivos

### Ventas — acumulado de la semana por ASIN

| Columna | Que es |
|---|---|
| ASIN | identificador de Amazon |
| Titulo del Producto | descripcion |
| Marca | |
| Ganancia por envios | ingreso, en MXN |
| COGS por envios | costo de lo vendido |
| **Unidades enviadas** | **el sell-out** |
| Devoluciones del cliente | vacio si es cero |

Ordenado por ganancia de mayor a menor. Solo aparecen los ASINs con
movimiento en la semana.

### Inventario — foto de un solo dia

Es un **snapshot del ultimo dia de la semana**, no un acumulado. Sumar
inventario a lo largo de la semana no tiene sentido: contarias el mismo stock
siete veces.

15 columnas. La que importa para stock disponible es **"Unidades aptas para la
venta disponibles"**.

> Las celdas vacias son datos que Amazon no reporta para ese ASIN. **No son
> ceros.** Vendor Central hace lo mismo en la descarga manual.

---

## 7. Cuando algo falla

| Lo que ves | Que pasa | Que hacer |
|---|---|---|
| `Faltan variables: SPAPI_...` | el `.env` esta incompleto | completa las tres credenciales |
| `401 invalid_client` | Client ID o Secret mal | revisalos, ojo con espacios al copiar |
| `400 invalid_grant` | refresh token vencido, revocado o de otra app | rehace el paso de **Autorizar** |
| `403` al buscar titulo/marca | falta el rol **Brand Analytics** | pedilo y volve a autorizar, o usa `--sin-catalogo` |
| `FATAL` + *"data ... not yet available"* | pediste dias que Amazon no publico | espera al martes, o usa `--hasta` con una fecha anterior |
| Archivo vacio, sin error | endpoint y marketplace no coinciden | para Mexico: `-na` + `A1AM78C64UM0Y8` |
| Tarda mucho / `429` | limite de Amazon | es normal, el script reintenta solo; no lo cortes |

> Los limites de Amazon son bajos: **crear un reporte esta limitado a 1 por
> minuto**. Si corres el script muchas veces seguidas te vas a topar con eso.
> Reintenta solo con espera progresiva; solo hay que tener paciencia.

---

## 8. Que archivos hay que copiar

El script **no es un archivo suelto**, necesita la carpeta completa:

```
export_xlsx.py          <- el que se corre
check_auth.py           <- prueba de credenciales
build_semanal.py        <- opcional: version en semana ISO
requirements.txt
.env.example            <- se copia a .env y se completa
config/
    __init__.py
    settings.py
spapi/
    __init__.py
    auth.py
    client.py
    reports.py
    data_kiosk.py
docs/
    instructivo.md      <- este archivo
```

**No copies el `.env`**, tiene credenciales. Cada uno usa las suyas.

---

## 9. En resumen

```powershell
# una sola vez
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # y completar las 3 credenciales
python check_auth.py        # confirmar que anda

# cada semana, un martes
python export_xlsx.py --descarga 2026-08-30 --destino "C:\ruta\donde\los\guardas"
```

Los tres puntos a no olvidar:

1. La semana va **domingo a sabado**, y el nombre del archivo es la fecha de
   descarga, no el rango de datos.
2. Corre el script **el martes**, por el atraso de ~34 horas de Amazon.
3. El inventario es una **foto de un dia**, no un acumulado.
