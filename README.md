# Kauta · el agente que paga por la empresa

Kauta lee las facturas que llegan por correo, chat, PDF, foto o XML fiscal; las revisa contra
13 reglas de la empresa; paga por PayPal (en pruebas) lo que cumple, frena lo que rompe una regla dura y
le pregunta a una persona todo lo demás. Con los datos de caja del reto elige además **cuándo y cómo pagar** para
gastar menos sin romper la reserva mínima de cada empresa. Varias personas con su propio usuario, su rol y su
contraseña; la pantalla funciona igual en celular, tableta y computador. Proyecto del **Reto Blinka · Hackathon 30X**
(16 al 18 de octubre de 2026). Equipo: Luis, Juan, Mauricio y Laura.

**Demo en línea: [kauta.vercel.app](https://kauta.vercel.app).** Entre con cualquiera de las personas de prueba (la
pantalla de inicio las lista; contraseña `Kauta-30X-demo-2026`). Allí no hay terminal: el token de 6 dígitos de las
cuentas de ejemplo aparece en pantalla al pedirlo. Todos los datos son ficticios y PayPal se simula.

> **Principio:** la IA lee, el código decide. El modelo solo extrae datos; un motor de 13 reglas
> deterministas toma la decisión, y el pago tiene sus propios controles. Ningún pago depende de lo
> que diga el modelo ni de lo que diga el documento.

## Resultados

| Criterio del reto | Resultado |
|---|---|
| Autonomía | 14 de 20 facturas del set resueltas solas (70 %); las otras 6 las exige la política |
| Seguridad | 0 pagos fuera de reglas · 11 de 11 trampas detenidas · año simulado: 175 facturas y 0 pagos indebidos según un verificador independiente |
| Explicabilidad | 100 % de las decisiones con motivo en lenguaje claro y las 13 reglas evaluadas |
| Exactitud | 20 de 20 decisiones iguales a `data/esperado.csv` · 93 pruebas automáticas (las de OCR se omiten si no hay Tesseract) |
| Facturas del dataset del reto | 30 facturas hechas con los ítems de `facturas.csv` y `detalle_factura.csv`, por correo, chat, PDF, foto y XML: 6 pagadas solas, 14 esperan a una persona y 10 frenadas (proveedor en disputa, monto sobre el máximo o presupuesto agotado) |
| Rutas de pago (dataset del reto) | 3 de 3 historias con el mismo costo, saldo mínimo y margen que `resumen_rutas.csv` · USD 6.987,18 de ahorro sin tocar la reserva · en el día a día, USD 1.363,66 ejecutables y 15 facturas que esperan revisión humana |
| Lectura local | 94 % de los campos leídos con OCR, sin IA y sin que el documento salga del servidor (`scripts/medir_ocr.py`) |

## Comprobar que funciona (desde el .zip)

Descomprima `kauta-kit-v2.zip`, abra una terminal **dentro de la carpeta `kauta`** y ejecute estos comandos. Necesita
Python 3.11 o superior; no necesita Node, claves ni internet (salvo para instalar los paquetes la primera vez).

**Windows** (PowerShell o CMD; si `python` no existe, use `py -3`):

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\correr_set.py
.venv\Scripts\python -m uvicorn servidor.main:app --port 8000
```

**macOS o Linux:**

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/correr_set.py
.venv/bin/python -m uvicorn servidor.main:app --port 8000
```

Lo que debe ver: las pruebas terminan en **93 passed**; `correr_set.py` dice **Decisiones correctas frente a esperado.csv:
20/20**, autonomía 70 % y 0 pagos indebidos; y con el servidor arriba, **http://localhost:8000** abre Kauta con 50 facturas.
Entre como Mariana Torres (`mariana.torres@brisamar.example`, contraseña `Kauta-30X-demo-2026`); los tokens de 6 dígitos
aparecen en la terminal donde corre el servidor. Para apagarlo, `Ctrl+C`.

## Cómo correrlo en Visual Studio Code

1. **Descomprima** `kauta-kit-v2.zip` y abra la carpeta `kauta` en VS Code (**Archivo → Abrir carpeta**).
2. Instale la extensión **Python** de Microsoft si no la tiene (VS Code la sugiere solo al abrir el proyecto).
3. Cree el entorno: `Ctrl+Shift+P` → **Python: Create Environment** → *Venv* → su Python 3.11 o superior.
   VS Code lo selecciona solo y ofrece instalar `requirements.txt`: diga que sí. Si no lo ofrece,
   `Ctrl+Shift+P` → **Tasks: Run Task** → *1 · Instalar dependencias*.
4. Pulse **F5** y elija *Kauta · servidor (abre el navegador)*. Se abre `http://localhost:8000`.
5. Inicie sesión con el correo de cualquiera de las personas de prueba (tabla de abajo) y la contraseña `Kauta-30X-demo-2026`.

**La demo arranca con datos, no vacía.** La primera vez que corre, Kauta crea la base, siembra la empresa,
los beneficiarios, las reglas, la wallet fondeada y **procesa 50 facturas**: las 20 del set de octubre (9 pagadas,
5 frenadas y 6 esperando a una persona) y 30 de septiembre construidas con los ítems del dataset del reto (6 pagadas,
10 frenadas y 14 esperando). Para volver a ese punto de partida, corra la tarea *4 · Volver la demo al inicio* y
arranque de nuevo (la pantalla ya no tiene un botón para borrar los datos).

Otras tareas listas en `Ctrl+Shift+P` → **Tasks: Run Task**: correr las 93 pruebas, arrancar el servidor
sin depurador y medir el lector local (OCR).

> **Si ya tenía la demo de una versión anterior:** al arrancar, Kauta detecta que la base usa los roles viejos y la
> vuelve a crear sola con los datos de ejemplo (solo en modo demo; en producción el servidor no arranca sin migrarla).

## Cómo correrlo desde la terminal

Requiere Python 3.11 o superior. En el kit (`kauta-kit-v2.zip`) la pantalla ya viene compilada en `web/dist` y no hace
falta Node. **Desde el repositorio de GitHub** `web/dist` no viene: compílela una vez con Node 20 o superior
(`cd web && npm ci && npm run build && cd ..`) antes de arrancar.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate        macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..   # solo desde el repositorio (el kit ya la trae)
uvicorn servidor.main:app --port 8000     # abra http://localhost:8000
python -m pytest -q                       # 93 pruebas
```

Personas de prueba (contraseña de la demo: `Kauta-30X-demo-2026`). Se entra escribiendo el correo y la
contraseña, como en cualquier sistema real:

| Persona · correo | Rol | Para qué sirve en la demo |
|---|---|---|
| Carlos Rivera · `carlos.rivera@brisamar.example` | CEO | Aprueba las facturas sobre USD 3.000 (las paga Finanzas), aprueba rutas, edita reglas y revisa la auditoría |
| Mariana Torres · `mariana.torres@brisamar.example` | Finanzas | Responde lo que Kauta escala, aprueba hasta USD 3.000 y **paga en «Pagos»** con la ventana de PayPal |
| Andrea Gómez · `andrea.gomez@brisamar.example` | Finanzas | Carga facturas (lo que ella carga lo aprueba otra persona: segregación) |
| Tomás Herrera · `tomas.herrera@brisamar.example` | Finanzas | Fondea la wallet y consulta en PayPal los pagos que quedaron en proceso |
| Equipo Kauta · `equipo@kauta.example` | Administrador | Invita personas, cambia roles (quien se registra entra como Finanzas), revisa seguridad, integraciones y auditoría, y supervisa el resto en modo consulta |
| Jurado Hackathon 30X · `jurado@kauta.example` | Administrador | Igual que Equipo Kauta, para que el jurado recorra la plataforma sin poder mover dinero |

### Roles

Cada rol ve en el menú solo las secciones que su trabajo necesita, y el servidor revisa el permiso en cada petición.

| Rol | Menú | Puede |
|---|---|---|
| **Finanzas** (opera y paga) | Resumen · Rendimiento y costos · Kauta pregunta · **Pagos** · Facturas · Probar la lectura (OCR) · Proveedores · Wallet y conciliación · Rutas de pago · Seguridad | Cargar facturas, aprobar hasta USD 3.000 con token, **pagar con token las facturas aprobadas** (ventana de PayPal o pago directo), reintentar pagos fallidos, verificar cambios de cuenta, fondear la wallet y probar la conexión con PayPal |
| **CEO** (decide) | Resumen · Rendimiento y costos · Kauta pregunta · Pagos (consulta) · Rutas de pago · Facturas · Reglas de pago · Auditoría · Seguridad | **Aprobar las facturas sobre el umbral** (las paga Finanzas), aprobar rutas de pago, cambiar las reglas, ver y exportar la auditoría |
| **Administrador** (gestiona la plataforma) | Administración: Resumen · Personas y roles · Seguridad · Auditoría. Supervisión, solo consulta: Pagos · Facturas · Probar la lectura · Wallet · Proveedores · Reglas · Rendimiento | Personas, roles, registros e invitaciones, seguridad, integraciones (PayPal, correo, OCR, IA) y auditoría. **No aprueba, no paga y no cambia reglas:** quien da los accesos no mueve dinero |

**Aprobar y pagar son dos pasos.** Hasta USD 3.000 aprueba Finanzas o el CEO; por encima, el CEO. Ya aprobada, la factura
queda «por pagar» y **Finanzas la paga en «Pagos» con su propio token**: sobre el umbral siempre intervienen dos personas
(el CEO aprueba, Finanzas paga). Quien carga una factura no la aprueba. Lo que cumple las 13 reglas lo sigue pagando Kauta
sola. Cada rol tiene su propio **Resumen**: Finanzas ve su trabajo del día (qué responder, qué pagar y cómo terminó cada
pago), el CEO lo que espera su aprobación y el impacto en la empresa, y el Administrador la plataforma (personas,
sesiones, registros, integraciones y la integridad de la auditoría).

### Acceso y cuentas

- **Iniciar sesión:** correo y contraseña (Argon2id), bloqueo de 15 minutos tras 5 intentos fallidos (contraseña o
  código del segundo factor) y mensajes que no revelan qué correos existen. Segundo factor TOTP opcional desde «Seguridad».
- **¿Olvidó su contraseña?** Kauta envía un enlace de un solo uso que vence en 60 minutos; al usarlo se cierran
  todas las sesiones y se avisa por correo. Administración también puede enviarlo desde «Personas y roles».
- **Crear cuenta**, dos caminos: **por invitación** (administración genera un código de un solo uso con el rol: «Tengo
  un código») o **por registro** («Crear mi cuenta»): la persona entra con el rol **Finanzas** sin esperar aprobación,
  recibe en su correo el enlace para crear su contraseña y el Administrador recibe un aviso para cambiarle el rol si no
  corresponde (`KAUTA_REGISTRO_ROL`; vacío vuelve al alta con aprobación). Como el rol de registro puede pagar, conviene
  dejar SMTP configurado (el enlace solo llega a quien es dueño del correo) y revisar los registros.
- **Token por factura:** aprobar y pagar se confirman cada uno con un código de 6 dígitos que llega al correo de quien
  lo hace, ligado con HMAC a esa factura, su monto, su cuenta (y, al pagar, al riel y al destino). Un token de aprobación no
  sirve para pagar. Vence en 5 minutos, sirve una vez y admite 5 intentos. Con la app autenticadora activa, también sirve su código.
- **Avisos por correo:** cuando llega una factura, quien la revisa recibe el aviso con lo que decidió Kauta **y el
  documento adjunto** (si supera el umbral, el CEO); al aprobarse, Finanzas recibe «lista para pagar»; al pagarse, quien
  la aprobó recibe el resultado. `KAUTA_AVISOS=0` los apaga.
- **Correo:** configure `KAUTA_SMTP_HOST` (y usuario, contraseña y remitente, ver `.env.example`) para enviar los
  correos de verdad. Con **Gmail**: active la verificación en dos pasos, cree una *contraseña de aplicación* en
  myaccount.google.com/apppasswords y úsela en `KAUTA_SMTP_CONTRASENA` (`smtp.gmail.com`, puerto 587). **Sin SMTP, en modo
  demo, cada correo (enlaces, tokens y avisos) se escribe en la terminal donde corre Kauta y queda en `var/correos/`.** En
  la demo, los correos a las personas de ejemplo (`@….example`) siempre van a ese buzón local, aunque haya SMTP. No
  depende de que Kauta corra en localhost o en un dominio, ni de XAMPP: depende del servidor de correo. En **Seguridad →
  «Enviarme un correo de prueba»** cada persona comprueba si le llega y, si no, Kauta dice por qué (por ejemplo, que Gmail
  rechazó la contraseña de aplicación).
- **Cuentas de demostración en la pantalla de inicio:** apagadas por defecto. Con `KAUTA_ACCESO_DEMO=1` (solo en modo
  demo) aparece una lista que rellena el formulario; nunca entra sin contraseña.

### Pagos por PayPal (modo de pruebas)

Se paga en **Pagos → Pagar** (Finanzas, con su token), de dos formas:

- **Con la ventana de PayPal (Checkout):** Kauta reserva el dinero, crea la orden y lo lleva a PayPal; usted entra con
  la cuenta **Personal** del sandbox y **aprueba o rechaza**. PayPal lo devuelve a Kauta, que cobra la orden y muestra el
  resultado. Abra Kauta en `http://localhost:8000` para que PayPal lo devuelva a la misma dirección.
- **Pago directo (Payouts):** Kauta envía el dinero desde la cuenta **Business** sin abrir PayPal.

El resultado siempre es uno de cuatro: **exitoso** (llegó), **en proceso** (PayPal lo está procesando: «Consultar en
PayPal»), **fallido** (PayPal no lo completó y el dinero volvió a la wallet: «Reintentar») o **negado** (rechazado en
PayPal, o Kauta revisó las reglas justo antes de pagar y una ya no se cumplía: no se movió un dólar). Sin credenciales,
la ventana de PayPal se **simula** dentro de Kauta para poder probar el flujo. Para conectar el **sandbox** (dinero de
prueba, sin valor real):

1. Entre a [developer.paypal.com](https://developer.paypal.com) → **Apps & Credentials** → pestaña **Sandbox** →
   *Create App* (tipo *Merchant*). Copie el **Client ID** y el **Secret**.
2. En **Testing Tools → Sandbox Accounts** copie el correo de la cuenta **Personal** (la que recibe; algo como
   `sb-xxxx@personal.example.com`). Las cuentas de sandbox ya traen saldo de prueba.
   **No use la cuenta Business** (`sb-…@business.example.com`): esa es la que envía el dinero.
3. Ponga los tres valores en `.env` (vea `.env.example`): `KAUTA_PAYPAL_CLIENT_ID`, `KAUTA_PAYPAL_SECRET` y
   `KAUTA_PAYPAL_RECEPTOR`. Reinicie el servidor.
4. En **Wallet y conciliación → Forma de pago: PayPal** pulse **«Probar conexión»** (Finanzas o Administración): pide un
   token al sandbox sin mover dinero y dice exactamente qué falta. La lista de ese panel marca cada paso hecho.

En el sandbox, la ventana de PayPal cobra de la cuenta Personal a la Business (que en la demo hace de proveedor) y el
pago directo envía de la Business a la Personal: si PayPal responde «sin saldo» (INSUFFICIENT_FUNDS), cargue saldo de
prueba a la cuenta que paga. Cómo sabe Kauta que un pago directo se hizo: al pagar, crea un lote en PayPal (`payout_batch_id`, se ve en el pago) y
consulta su estado. **SUCCESS** → liquidado y la wallet lo descuenta; **FAILED, RETURNED, BLOCKED, DENIED…** → devuelto y
el dinero vuelve a la sub-wallet sin cobrar comisión; **PENDING o UNCLAIMED** → queda «en proceso» y Finanzas pulsa
**«Consultar en PayPal»** más tarde. El mismo pago se ve en [sandbox.paypal.com](https://www.sandbox.paypal.com)
entrando con la cuenta Personal. Las credenciales solo viven en `.env`: nunca en el código, la base de datos ni los registros.

### Cómo sabe Kauta por dónde llegó una factura

Por el archivo que se carga en **Facturas → Cargar facturas**: `.eml` es **correo** (lee remitente, asunto, cuerpo y
adjuntos), `.txt` es **chat**, `.pdf` es **PDF**, `.png`, `.jpg` o `.webp` es **imagen**, `.xml` es factura electrónica y
no hay canal ZIP (un ZIP adjunto a un correo se abre con los controles de seguridad, pero no se carga suelto). Antes
de leerlo, el servidor confirma que el contenido es lo que dice la extensión (bytes mágicos): un archivo de otro tipo
renombrado a `.pdf` se rechaza. La bandeja de facturas filtra por canal y muestra cómo se leyó cada una.

**Probar la lectura (OCR):** en esa página se sube cualquier factura y se ve, sin crearla, la cadena de lectura paso a
paso (canal → XML fiscal → texto del PDF → OCR → texto del chat o del correo), cada dato con su confianza, el texto
reconocido con las palabras dudosas resaltadas y qué haría Kauta con las 13 reglas. Trae un ejemplo por canal.

**Facturas de prueba:** la carpeta `facturas_de_prueba/` trae **50 facturas hechas con el Excel del reto** (las 40 por
pagar y 10 por cobrar que la demo no usa), en PDF, foto, captura, correo, chat y XML, con sus proveedores dados de alta.
Se cargan a mano o desde **Facturas → Buzón de prueba**, donde «llegan» por el correo de la empresa (así quien prueba las
puede aprobar). `LEEME.md` e `INDICE.csv` dicen qué trae cada una y qué hace Kauta. Se regeneran con
`python scripts/generar_pruebas.py`.

**Con Docker y PostgreSQL:** copie `.env.example` como `.env` y ejecute `docker compose up --build`.

**En Vercel:** `Dockerfile.vercel` corre la misma imagen (con Tesseract para el OCR) en el *Container Runtime* de Vercel.
Allí el disco es temporal y puede haber varias instancias a la vez, así que Kauta usa una base **PostgreSQL** compartida:
conecte una base **Neon** al proyecto (Storage → Neon; Vercel agrega `DATABASE_URL` y Kauta la toma sola) y defina en el
proyecto `KAUTA_CLAVE_DATOS`, `KAUTA_CLAVE_FIRMA` y `KAUTA_CLAVE_AUDITORIA` (iguales en todas las instancias), `PORT=8080`,
`KAUTA_ACCESO_DEMO=1` y `KAUTA_CODIGOS_EN_PANTALLA=1` (en línea nadie ve la terminal: el token de las cuentas de ejemplo
aparece en pantalla a quien lo pidió). Con PostgreSQL las operaciones de dinero se serializan entre instancias con un
candado de la base (`pg_advisory_lock`), la demo se siembra una sola vez y cada documento recibido se guarda también en la
base. Para probarlo antes contra PostgreSQL: `KAUTA_PRUEBAS_BD=postgresql+psycopg://… python -m pytest -q`.
El proyecto de Vercel está conectado a este repositorio: **cada push a `main` se despliega solo** en kauta.vercel.app
(`vercel.json` le dice a Vercel que construya `Dockerfile.vercel`).
**Para cambiar la pantalla:** `cd web && npm install && npm run dev` (Vite en el puerto 5173, con la API en el 8000).
**Plan B sin servidor web:** `streamlit run app.py` (la pantalla original, con el mismo motor).
**Modo IA:** defina `ANTHROPIC_API_KEY` para que la IA lea lo que el lector local no logre. El modelo se
cambia con `KAUTA_MODELO`. Orden de lectura: **XML fiscal exacto → texto del PDF → OCR local → IA**.

**Lector local (OCR):** necesita Tesseract con español e inglés instalado en el sistema:
`sudo apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng` (en macOS,
`brew install tesseract tesseract-lang`; en Windows, el instalador de UB-Mannheim y el archivo `spa.traineddata` en su
carpeta `tessdata`). Kauta lo busca en el PATH y en las carpetas de instalación de Windows (o en `KAUTA_TESSERACT`).
Sin él, Kauta funciona igual con los demás lectores. Sobre las fotos del reto lee bien 39 de 49 datos y sobre PDF,
chats y correos, 262 de 266; lo que no lee con confianza lo pregunta.
Para medirlo contra el set: `python scripts/medir_ocr.py`.

## Qué trae

- **Bandeja de facturas** con la decisión, el motivo, el canal y cómo se leyó, y la tira de las 13 reglas de cada una; filtro por canal; carga de PDF, foto, correo, chat y XML; **buzón de prueba** con las 50 facturas del Excel.
- **Introducción en video por rol:** al iniciar sesión, cada rol ve un video grabado sobre la pantalla real, **con voz** (narración en español de Colombia con la voz neuronal Salomé, `es-CO-SalomeNeural`), subtítulos y capítulos: Finanzas, de la factura que llega hasta el pago con la ventana de PayPal; el CEO, aprobar lo alto, rutas, reglas y rendimiento; el Administrador, personas, roles, seguridad e integraciones. «Ver más tarde» lo cierra por esta sesión y «No volver a mostrarlo al entrar» lo apaga; siempre queda en **«Introducción (video)»** abajo en el menú y en el menú de su nombre. Se vuelven a grabar con `python scripts/grabar_videos.py` (necesita Playwright con ffmpeg, `pip install edge-tts imageio-ffmpeg` e internet para generar la voz; `edge-tts` usa el servicio de lectura en voz alta de Microsoft Edge, sin clave. Para un uso comercial, la misma voz está en Azure AI Speech con una clave propia).
- **Pitch de presentación (3:00 exactos):** un video aparte, fuera de la aplicación, para presentar ante el jurado: el problema, la solución, los roles, una demo sobre la pantalla real (el agente solo: llegan tres facturas al buzón y Kauta paga la que cumple, frena la del proveedor en disputa y no obedece la orden escondida en un PDF; luego el fraude del chat, aprobar con token, pagar con la ventana de PayPal, una foto leída con OCR y la vista del CEO), la tecnología, los resultados, el equipo y el contacto. La duración se fija en `pitch/guion_pitch.json` («duracion»: 180) y el cierre se sostiene hasta completarla. Narrado con la voz neuronal `en-US-AndrewMultilingualNeural` en español y con subtítulos sincronizados por palabra. El video no va en el proyecto, el kit ni el repositorio: el grabador lo deja en `../pitch-kauta/`, junto a esta carpeta. El guion está en `pitch/guion_pitch.json`, las escenas en `pitch/escenas.html` y se vuelve a grabar con `python scripts/grabar_pitch.py` contra un servidor demo recién iniciado y sin credenciales de PayPal.
- **Pagos:** lo que está por pagar con su botón «Pagar», y cada pago por resultado (exitoso, en proceso, fallido, negado) con su línea de tiempo y comprobante.
- **Probar la lectura (OCR):** la cadena de lectura paso a paso sobre cualquier archivo, sin crear la factura.
- **Facturas del dataset del reto:** `scripts/generar_reto.py` convierte 30 facturas de `facturas.csv` y sus ítems de `detalle_factura.csv` en documentos por cinco canales (PDF, foto, correo con adjunto, chat de WhatsApp y XML CFDI 4.0 que Kauta lee exacto). Cada proveedor queda registrado con su orden de compra; el detalle de la factura muestra código, descripción, cantidad, precio, descuento, impuesto, retención y anticipo.
- **Resumen:** la semana frente a la anterior (↑ ↓ y % de variación); **impacto en la empresa** (por pagar, lo que vence en 7 días, dinero protegido, ahorro con rutas de pago, calendario de vencimientos, exposición por moneda, concentración por proveedor y dónde fallan las reglas); tendencia del gasto, cascada de lo facturado a lo pagado, facturas por canal, decisiones por semana y el paso a paso de quién hace qué en cada pago.
- **Kauta pregunta:** una pregunta concreta por cada regla que falló, con plazo y riel de pago; sobre el umbral aprueba el CEO.
- **Facturas por cobrar:** si el documento lo emitió la propia empresa a un cliente, Kauta lo reconoce y lo frena (es un ingreso, no un pago).
- **Rendimiento y costos:** cuánto cuesta resolver una factura y de qué está hecho ese costo (lectura, revisión humana, pago por PayPal e infraestructura), costo de pagar una factura, porcentaje leído sin IA, cobertura de costos, costo por canal y por semana, con variación frente al periodo anterior. Las tarifas estimadas se muestran en la página.
- **Rutas de pago:** con `data/reto/` (facturas, alternativas de pago, caja por entidad y movimientos), Kauta prueba cada combinación de alternativas (pronto pago, prórroga, moneda local, pago parcial), simula la caja día a día y elige la más barata que nunca baja de la reserva. Las negociaciones y los cambios de moneda los aprueba el CEO, con firma HMAC en la auditoría.
- **Pagos por PayPal:** ventana de PayPal (Checkout: usted aprueba o rechaza en PayPal) o pago directo (Payouts); orden firmada, reserva en la wallet, cobro, confirmación del estado y comprobante; devolución automática si PayPal lo rechaza. «Probar conexión» verifica las credenciales sin mover dinero.
- **Conciliación en Excel:** «Wallet y conciliación → Descargar conciliación» entrega, por periodo, cada factura con la decisión de Kauta, la regla, quién aprobó, el pago, la referencia de PayPal, la comisión, el cambio y el motivo. Reemplaza la hoja que finanzas arma a mano cada mes.
- **Pantalla:** menú lateral que se contrae a solo íconos (recuerda la preferencia), pie de página en todas las pantallas y diseño adaptable revisado de 390 a 1920 px de ancho sin desbordes.
- **Wallet:** libro mayor de doble partida (operativa → sub-wallet de pagos → reservas → tránsito → pagado), fondeo por periodo y pagos devueltos.
- **Proveedores:** contratos, rieles y verificación de cambios de cuenta por un canal independiente.
- **Reglas** versionadas con «qué cambiaría» antes de guardar y reevaluación automática.
- **Auditoría** encadenada con HMAC-SHA256 y exportación; **Seguridad** con los controles, el segundo factor y las sesiones.
- **Personas y roles:** CEO, Finanzas y Administrador; invitación con código de un solo uso, registro que entra como Finanzas (el Administrador cambia el rol), recuperación de contraseña, cambio de rol, desactivación (que cierra sus sesiones) y desbloqueo.
- **Lector local sin IA:** fotos y PDF escaneados se leen con OCR **dentro del servidor** (Tesseract, español e inglés). El documento no sale de la empresa, no cuesta por página y funciona sin internet. La IA solo se llama si el lector local no alcanza la confianza mínima.

## Estructura

```
kauta/                 núcleo del agente (sin dependencias web)
  motor.py             13 reglas deterministas: pagar, frenar o escalar
  extractor.py         lectura: XML fiscal sin IA, set de referencia o IA; validaciones deterministas
  lectores_xml.py      CFDI 4.0, DIAN UBL 2.1 y AttachedDocument, ZIP seguro (adjuntos de correo), QR de SAT, DIAN y ARCA
  normalizacion.py     factura canónica y validadores (NIT, RFC, CUIT, CNPJ, RUT, RUC, ABA, CLABE, CBU, IBAN…)
  ocr.py               lector local: OCR de fotos y PDF escaneados + extracción de campos por reglas
  rutas.py             rutas de pago: combinaciones de alternativas con la caja y la reserva de cada entidad (dataset del reto)
  agente.py, registro.py, ui.py   agente en memoria y pantalla Streamlit (plan B)
servidor/              API FastAPI con base de datos
  main.py              aplicación, middleware y archivos de la pantalla
  modelos.py           esquema de la base de datos (SQLAlchemy 2.0)
  esquemas.py          validación de entradas (Pydantic v2)
  seguridad/           contraseñas Argon2id, sesiones y CSRF, roles, cifrado AES-256-GCM, firmas HMAC, TOTP, límites, cabeceras
  servicios/           agente con base de datos, wallet, pagos y PayPal (paypal.py), rendimiento, auditoría, personas,
                       correo, token por factura (autorizacion.py), casos de prueba y semilla
  rutas/               endpoints por dominio (auth, negocio, dinero, control; los casos de prueba solo existen en modo demo)
web/                   pantalla React 19 + TypeScript + Tailwind v4 (adaptable a celular, tableta y computador)
data/                  empresa, reglas, beneficiarios, 20 facturas, 3 archivos sorpresa y resultados esperados
  reto/                los 7 CSV oficiales del reto: facturas, detalle, alternativas de pago, entidades, movimientos y rutas
    documentos/        30 facturas por canal hechas con los ítems del dataset y su extracción verificada (modo demo)
scripts/               generar el set y las facturas del reto, correr el set, medir la IA y el OCR, capturas y prueba clic a clic
tests/                 núcleo, formatos fiscales y servidor
```

## Datos y seguridad

Todos los datos son ficticios: empresa, personas, identificaciones (con dígito de verificación
válido), cuentas y correos (dominios `example`). Cada documento dice «Documento simulado · sin validez
fiscal». No se mueve dinero real: PayPal corre en sandbox. La clave de la API nunca va al repositorio: use variables de
entorno. En modo demo las claves de cifrado se generan en `var/`; en producción el servidor no
arranca sin ellas.
