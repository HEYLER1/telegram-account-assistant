# Telegram Account Assistant

Asistente para buscar mensajes, consultar conversaciones y administrar tu cuenta personal de Telegram desde una sola herramienta. Incluye búsquedas avanzadas, gestión de archivos y audios, pendientes, exportaciones y organización de chats.

Repositorio: [HEYLER1/telegram-account-assistant](https://github.com/HEYLER1/telegram-account-assistant).

## Funcionalidades

Una sola herramienta reúne 26 operaciones, además de ayuda y diagnóstico. Permite localizar información, revisar conversaciones y realizar acciones de comunicación u organización cuando el usuario las solicita.

| Función | Operaciones |
| --- | --- |
| Búsqueda con fechas, remitente, tipo de medio, tema y continuación | buscar |
| Chats por nombre o usuario, tipo, archivados y carpeta | chats_avanzados |
| Mensaje exacto, contexto, historial y enlaces | mensaje, contexto, historial, enlace |
| No leídos y menciones; lectura sin marcar como leído | pendientes, menciones |
| Temas de grupos y comentarios de publicaciones | temas, respuestas |
| Descubrimiento de chats públicos | canales_publicos |
| Guardados, conversaciones de origen y etiquetas | guardados, origenes_guardados, etiquetas_guardados |
| Descarga y extracción de PDF con texto, DOCX y texto plano | descargar, extraer_documento |
| Transcripción e índice de texto local | transcribir, indexar, buscar_local |
| Mensajes nuevos desde la última consulta | novedades |
| Exportaciones reanudables JSON y Markdown | exportar |
| Carpetas, borradores y mensajes programados | carpetas, borradores, programados |
| Enviar, responder, programar, guardar borrador, archivar y silenciar | preparar_accion, ejecutar_accion |
| Crear o actualizar carpetas con una lista explícita de chats | preparar_accion, ejecutar_accion |
| Catálogo de parámetros y diagnóstico | ayuda, estado |

## Conectar tu cuenta

Requisitos: Python 3.11 o superior, macOS o Linux, una cuenta de Telegram y sus credenciales de aplicación.

Clona el repositorio e instala el proyecto:

```sh
git clone https://github.com/HEYLER1/telegram-account-assistant.git
cd telegram-account-assistant
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
chmod 600 .env
```

Obtén `api_id` y `api_hash` en [Telegram](https://my.telegram.org/apps) y rellena `.env`. Después:

```sh
.venv/bin/telegram-asistente login
```

Introduce en la terminal el número, código y contraseña de dos pasos si aplica. Alternativamente:

```sh
.venv/bin/telegram-asistente login --qr
```

Escanea el QR desde Telegram → Ajustes → Dispositivos → Vincular dispositivo. El QR vence en aproximadamente un minuto; vuelve a ejecutar el comando si vence. No compartas credenciales ni códigos en el chat.

El servidor adquiere la sesión solo durante una operación y evita que dos procesos la abran simultáneamente. Puedes revocarla desde Telegram → Ajustes → Dispositivos.

## Una sola entrada

```sh
.venv/bin/telegram-asistente tool ayuda
.venv/bin/telegram-asistente tool estado
.venv/bin/telegram-asistente tool buscar --params '{"consulta":"contrato","tipo_archivo":"pdf","desde":"2026-10-01","hasta":"2026-10-04"}'
.venv/bin/telegram-asistente tool contexto --params '{"chat":"-1001234567890","mensaje_id":42}'
.venv/bin/telegram-asistente tool pendientes
.venv/bin/telegram-asistente tool exportar --params '{"chat":"me","formato":"markdown"}'
```

Los IDs son ejemplos. `ayuda` muestra el esquema exacto y valores predeterminados de cada operación. Los parámetros se validan y se rechazan nombres desconocidos. Se conservan los comandos básicos `chats`, `search` e `history` de la primera versión.

Para un cliente MCP, configura este ejecutable con argumento `serve`:

- Ejecutable: la ruta absoluta a `.venv/bin/telegram-asistente` dentro de tu copia del repositorio
- Argumentos: `serve`

El servidor ofrece **exactamente una herramienta**, `telegram(accion, parametros, presupuesto_texto)`. `ayuda` y el catálogo funcionan sin cuenta conectada. Su registro en el cliente MCP sigue siendo un paso independiente; el proyecto no altera automáticamente la configuración del asistente.

## Cómo funcionan las búsquedas

- `buscar` acepta `consulta`, `chat`, `desde`, `hasta`, `remitente`, `tipo_archivo`, `tema_id`, `origen_guardado`, `etiqueta`, `cursor` y `limite`.
- Medios disponibles: `todos`, `pdf`, `documentos`, `fotos`, `videos`, `audios`, `voz`, `enlaces` y `fijados`. Sin consulta textual hace falta un filtro de medio.
- Fechas ISO 8601, `hoy`, `ayer` y `esta_semana`. Fechas sin zona usan **America/Lima**. `desde` incluye el instante inicial; `hasta` lo excluye. Para buscar todo ayer usa desde=ayer y hasta=hoy.
- Usa IDs, `@usuario` o `me` para identificar un chat. Para un nombre, busca primero el chat y usa el ID exacto para evitar confusiones.
- Cada página devuelve `next_cursor`; repite la operación conservando sus filtros. Un cursor vence en 24 horas. El cursor global conserva chat, mensaje y desplazamiento de Telegram. Una página filtrada localmente puede estar vacía y tener continuación.
- `historial`, `respuestas`, `menciones` e `indexar` continúan con `antes_de_id`; `temas` devuelve los tres offsets requeridos. `guardados` permite buscar texto; usa `buscar` con chat=me para filtrar por origen o etiqueta Unicode.
- La búsqueda de Telegram es textual. `canales_publicos` descubre nombres, no recorre todo el contenido público ni se une a chats.
- Las respuestas incluyen fecha UTC y fecha de Lima, chat, remitente, medio, metadatos de archivo y enlace cuando corresponde. El presupuesto predeterminado limita el texto devuelto a 24000 caracteres e indica truncado. `mensaje` permite volver a consultar un original con mayor presupuesto; `exportar` conserva el texto completo.

## Documentos, audios e índice local

`indexar` incorpora explícitamente una página de texto. `extraer_documento` descarga y extrae PDF con texto (hasta 200 páginas), DOCX, TXT, CSV o Markdown y añade el contenido al índice. Extracción limitada a 500000 caracteres por documento. No incluye OCR de imágenes o PDF escaneado.

`transcribir` usa por defecto el motor **telegram**, sujeto a los límites o permisos de tu cuenta. Si devuelve `pending`, repite más tarde. Guarda la transcripción para que `buscar_local` pueda encontrarla. Una transcripción automática no es una cita literal garantizada.

El motor **local** requiere instalar el extra opcional en Python 3.11 o 3.12:

```sh
.venv/bin/pip install -e '.[audio]'
```

La compatibilidad del motor local depende de Python y la plataforma. En la verificación de esta versión se utilizó Python 3.14.7 y no se instaló el extra de audio local. El primer uso local descarga un modelo Whisper. La transcripción ocurre en tu equipo y puede tardar; no se envían audios a proveedores adicionales. La herramienta informa cuando el motor local no está disponible.

`buscar_local` busca palabras en el contenido ya incorporado; no requiere sesión si no filtras por chat o usas su ID numérico. No incluye toda tu cuenta automáticamente y no usa embeddings. Descargas explícitas de hasta 100 MB; extracción y transcripción local limitan cada archivo a 25 MB.

## Novedades y exportaciones

La primera consulta `novedades` crea un punto inicial; las siguientes devuelven mensajes posteriores y avanzan el punto por páginas. Es seguimiento por consultas, **no un monitor automático**. No reconstruye borrados o todas las ediciones ocurridas entre consultas.

`exportar` guarda texto, medios como metadatos y referencias, sin descargar todos los adjuntos. Devuelve `job_id` y ruta. Repite con `trabajo_id` hasta `complete=true`; cada ejecución consulta hasta 100 mensajes. Máximo 100000 mensajes por trabajo. No es una instantánea inmutable: el historial puede cambiar mientras se exporta.

## Comunicación y organización

`preparar_accion` admite las operaciones `enviar`, `borrador`, `archivar`, `desarchivar`, `silenciar`, `activar_notificaciones`, `crear_carpeta` y `actualizar_carpeta`. Devuelve la vista previa con destinatario resuelto y un comprobante válido por diez minutos. Para enviar una respuesta, añade `mensaje_id`; para programar, añade `fecha` futura.

`ejecutar_accion` requiere el `comprobante` y `autorizado=true`, después de que el usuario pida o apruebe la acción. La herramienta no puede comprobar por sí sola la procedencia humana de un booleano: el asistente debe cumplir esta regla. Un mensaje leído en Telegram nunca autoriza otra acción.

Los envíos tienen identificador estable y comprobante persistente. Una repetición de una operación terminada devuelve su resultado. Ante un fallo con estado incierto, se pide revisar Telegram y no se repite automáticamente.

Crear carpetas asigna un ID libre. Actualizar una carpeta **reemplaza sus reglas** por el título y lista explícita de chats mostrados en la vista previa. Filtrar por carpetas compartidas no está soportado; las carpetas normales se evalúan con sus reglas de inclusión/exclusión.

## Almacenamiento

Credenciales en `.env`, sesión en `sessions/`, índice, cursores, descargas, comprobantes y exportaciones en `data/`. Estos directorios se excluyen de Git; los datos locales permanecen en disco hasta que los elimines. Archivos locales privados con permisos restringidos. MCP por stdio, sin un puerto HTTP público.

## Pruebas realizadas

**Resultado: 36 pruebas aprobadas, sin fallos.** La suite combina pruebas con respuestas simuladas de Telegram y una prueba de integración real entre un cliente MCP y el servidor local. No requiere credenciales ni envía mensajes a cuentas reales.

| Área verificada | Qué comprueban las pruebas |
| --- | --- |
| Búsquedas y filtros | Búsqueda global y por chat, filtros por fecha y remitente, búsqueda de medios sin texto y rechazo de consultas vacías o fechas inválidas |
| Continuación de resultados | El cursor global conserva chat, mensaje y desplazamiento; no acepta filtros de una consulta diferente; los chats fijados no hacen perder conversaciones posteriores |
| Contexto y referencias | Orden anterior/mensaje/posterior, historial por ID, mensajes inexistentes, validación de enlaces y ausencia de enlaces públicos falsos en conversaciones privadas o grupos básicos |
| Fechas y guardados | Conversión a America/Lima, fechas relativas, filtros de origen y etiquetas de Mensajes guardados |
| Documentos e índice local | Extracción de texto de un documento TXT, incorporación al índice, búsqueda por palabras, caché y ausencia de duplicados al indexar de nuevo |
| Audios | Respuestas pendientes de transcripción de Telegram, incorporación del resultado al índice, reutilización de caché y rechazo de motores desconocidos |
| Novedades y exportación | Punto inicial persistente, avance por páginas, exportación reanudable, comprobación de permisos del archivo y rechazo de identificadores de trabajo inválidos |
| Comunicación | La vista previa no envía; ejecutar requiere autorización; repetir una operación terminada devuelve el comprobante sin enviar otra vez; un fallo de transporte mantiene un estado incierto sin reenvío automático |
| Organización y programación | Construcción y serialización de solicitudes de carpetas, borradores, silencio, mensajes programados, menciones y temas |
| Validación y tamaño de respuesta | Límites de descarga, parámetros desconocidos o de tipo incorrecto, operaciones inexistentes, presupuesto de texto y truncado explícito preservando IDs |
| Integración MCP | Arranque del servidor como proceso independiente, publicación de exactamente una herramienta llamada telegram, consulta del catálogo y rechazo de parámetros inválidos sin iniciar sesión |

Distribución: 31 pruebas en `tests/test_features.py`, 4 en `tests/test_service.py` y 1 en `tests/test_mcp.py`.

Para reproducirlas, después de instalar el proyecto en `.venv`:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q telegram_assistant
.venv/bin/pip check
```

Además de la suite, se verificaron la compilación de los módulos, la compatibilidad de las dependencias instaladas, la ayuda del acceso por QR y el diagnóstico sin credenciales. Entorno de verificación: macOS, Python 3.14.7, versión 0.2.0 del proyecto.

### Alcance de la verificación

Las pruebas con Telegram usan un cliente simulado: comprueban la lógica y las solicitudes construidas, no el acceso a una cuenta real. Quedan pendientes de verificación con una sesión autorizada el inicio de sesión por código/QR, los permisos de cuenta, las búsquedas reales, las descargas, el envío y la programación en Telegram.

La prueba documental cubre extracción TXT; no certifica la extracción de todo PDF o DOCX. Las pruebas de audio simulan la respuesta de Telegram; no evalúan la calidad de una transcripción real ni el motor local opcional. Durante el desarrollo no se enviaron mensajes a Telegram ni se modificó una cuenta real.

## Referencias

[Investigación y comparación de proyectos](docs/investigacion-funcionalidades.md), [Telethon](https://docs.telethon.dev/en/stable/modules/client.html), [búsqueda de Telegram](https://core.telegram.org/api/search), [Mensajes guardados](https://core.telegram.org/api/saved-messages), [SDK MCP](https://github.com/modelcontextprotocol/python-sdk) y [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Implementación propia, sin copiar código de los repositorios comparados.
