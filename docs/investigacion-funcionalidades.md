# Investigación de funcionalidades para el asistente Telegram

Fecha de revisión: 3 de octubre de 2026.

Este documento registra la investigación previa. La integración posterior de las funciones está descrita en [la guía actual](../README.md).

## Conclusión

La base Telethon + MCP encaja con el objetivo de consultar una cuenta personal desde un asistente. La siguiente versión debería mejorar la precisión y continuidad de las búsquedas antes de incorporar funciones de administración. No hace falta cambiar de biblioteca para cubrir las primeras mejoras.

Esta revisión compara documentación pública de repositorios y Telegram con los archivos locales. No se instalaron ni probaron esos proyectos con una cuenta real; las funciones citadas son las que documentan sus autores. Las prioridades y el diseño propuesto son conclusiones propias.

## Proyectos comparados

| Proyecto | Lo que aporta a nuestro caso | Uso propuesto |
| --- | --- | --- |
| [chigwell/telegram-mcp](https://github.com/chigwell/telegram-mcp) | Contexto de mensajes, transcripción con caché, carpetas, borradores y eventos de mensajes entrantes | Referencia cercana a nuestra base Telethon; estudiar funciones concretas |
| [tolmachov/mcp-telegram](https://github.com/tolmachov/mcp-telegram/blob/main/README.md) | Documenta filtros de fecha/remitente/archivo/hilo, contexto y paginación global con cursor opaco | Referencia de interfaz de búsqueda; la página tuvo fallos de apertura en esta revisión, aunque su inventario fue recuperado mediante el buscador |
| [tolboy/telegram-mcp-tdlib](https://github.com/tolboy/telegram-mcp-tdlib/blob/master/README.md) | Bandeja compacta, contexto, mensaje desde enlace, exportaciones reanudables y seguimiento de cambios con huecos de cobertura explícitos | Referencia de resultados compactos y operaciones recuperables; usa TDLib, no trasladar llamadas directamente |
| [mcp-telegram/mcp-telegram](https://github.com/mcp-telegram/mcp-telegram) | Borradores, pendientes, temas de grupos, mensajes guardados, carpetas y mensajes programados | Mapa de futuras funciones de organización y comunicación |
| [Telepathy-Community](https://github.com/prose-intelligence-ltd/Telepathy-Community) | Archivo de chats, comentarios, reacciones, medios y relaciones entre mensajes reenviados | Inspiración para exportaciones con procedencia. Su README indica que no está activamente mantenido; no elegirlo como dependencia del servicio |

## Qué falta y en qué orden abordarlo

| Prioridad | Función | Pedido que permitiría | Situación actual y propuesta |
| --- | --- | --- | --- |
| 1 | Filtros de búsqueda | «Busca los PDF que Ana envió la semana pasada» | Solo hay consulta textual, chat y límite. Añadir fechas con zona horaria, remitente y tipo de medio; admitir búsqueda de archivos sin texto |
| 1 | Contexto de un resultado | «¿Qué respondieron a esa propuesta?» | Solo se devuelven coincidencias aisladas. Obtener mensaje exacto, mensaje respondido y una ventana anterior/posterior ordenada |
| 1 | Continuar búsquedas | «Muéstrame más resultados» | El historial tiene before_id; la búsqueda no. Añadir cursor por chat y cursor global compuesto. No usar un ID de mensaje aislado como cursor global porque los IDs pertenecen a chats distintos |
| 1 | Archivos reconocibles | «Encuentra el contrato adjunto» | has_media solo indica presencia de medios. Añadir nombre, tamaño, MIME y tipo. Después, descarga explícita a una carpeta local controlada |
| 1 | Chats mejor identificados | «Busca en el grupo de trabajo archivado» | Se filtra solo por nombre y se revisan hasta 1000 chats. Añadir @usuario, tipo, archivado, carpetas y continuación; señalar ambigüedad entre nombres iguales |
| 2 | Bandeja de pendientes | «¿Qué conversaciones tengo pendientes?» | Ya hay unread_count, pero falta filtro de no leídos, menciones y resumen con cobertura. La lectura para análisis no debería marcar mensajes como leídos por sí sola |
| 2 | Temas y comentarios | «Busca en el tema de ventas de ese grupo» | No hay parámetros de tema/hilo ni acceso dedicado a comentarios. Añadir temas de foros y respuestas según el tipo de chat |
| 2 | Abrir un enlace de Telegram | «Revisa este mensaje de t.me» | Generamos algunos enlaces, pero no los resolvemos. Añadir resolución de enlaces públicos y privados con verificación de acceso y tipo de chat |
| 2 | Audio y documentos | «Encuentra el audio donde hablamos del pago» | La búsqueda actual consulta texto de Telegram, no el contenido hablado ni el interior de PDFs. Transcribir/extractar bajo demanda y buscar en un índice local; indicar que una transcripción puede contener errores |
| 2 | Seguimiento incremental | «¿Qué cambió desde mi última consulta?» | receive_updates=False y sin marcadores persistentes. Guardar el último mensaje observado por chat. El seguimiento por consultas no equivale a registrar todas las ediciones y borrados; un historial de cambios exige eventos y cobertura explícita |
| 3 | Exportaciones | «Guarda esta conversación para revisarla» | Añadir exportación JSON o Markdown con fechas, referencias, cobertura y posibilidad de reanudar |
| 3 | Borradores y envíos | «Prepara una respuesta y envíala cuando te lo pida» | Separar preparación de envío; resolver destinatario exacto y evitar duplicados ante reintentos. La solicitud actual de investigación no autoriza enviar mensajes |
| 3 | Organización de cuenta | «Archiva este chat y organiza estas carpetas» | Incorporar herramientas de archivo, silenciar, carpetas y programación cuando ese uso sea solicitado |

## Detalles que podríamos pasar por alto

1. **Búsqueda de mensajes, descubrimiento de canales y búsqueda semántica son capacidades distintas.** La herramienta actual usa búsqueda textual de Telegram. Buscar canales públicos exige una operación adicional; buscar por significado exige un índice y un modelo. Ninguna promete cobertura de todo Telegram.
2. **Cobertura visible.** Devolver límite, continuación, chats revisados y restricciones; no presentar una página de resultados como si fuera una búsqueda exhaustiva.
3. **Presupuesto de respuesta.** Un máximo de 100 mensajes no limita el número de caracteres. Unos pocos mensajes largos pueden agotar el contexto del asistente. Añadir presupuesto de texto y truncado explícito con recuperación del original por ID.
4. **Fechas relativas.** Interpretar «ayer» o «esta semana» con America/Lima y convertir los límites para Telegram. Definir claramente si los extremos son inclusivos o exclusivos.
5. **Enlaces correctos.** message_data construye un enlace si cualquier chat tiene username. Un usuario privado también puede tenerlo: no asumir que username/message_id representa un enlace válido a su conversación. Validar tipo de entidad y usar las operaciones de enlaces cuando corresponda.
6. **Errores de MCP.** El comando informa FloodWait en terminal, pero las llamadas a herramientas carecen de una respuesta propia y estructurada con tiempo de espera, autorización requerida o chat inaccesible. Añadir un contrato compartido y evitar reintentos indefinidos.
7. **Inicio de sesión y estado.** Hoy el servidor depende de una sesión ya autorizada para iniciar. Añadir diagnóstico de configuración y estado; el acceso inicial por QR sería una mejora de comodidad.
8. **Archivo de sesión compartido.** La terminal y el servidor pueden abrir el mismo archivo SQLite. Diseñar un único proceso propietario de la sesión o impedir uso simultáneo antes de agregar monitores persistentes.
9. **Mensajes guardados.** Ya podemos consultar me. Lo que falta es su organización por conversación original y etiquetas, algunas asociadas a Premium; no tratar la búsqueda básica en guardados como una función ausente.
10. **Modelo de comunicación.** MCP ya sirve de interfaz para asistentes. Si se quiere integrar otros programas mediante HTTP, añadir una API REST autenticada como adaptador de la misma lógica; no abrir un servicio público sin una necesidad concreta.

## Propuesta de siguiente versión

Implementar primero filtros, contexto, paginación, metadatos de archivos y errores estructurados. Ejemplos de interfaz:

- buscar_mensajes(consulta, chat, desde, hasta, remitente, tipo_archivo, cursor, limite)
- obtener_contexto(chat, mensaje_id, anteriores, posteriores)
- obtener_mensaje(chat, mensaje_id)
- buscar_chats(consulta, tipo, archivados, cursor, limite)
- estado_conexion()

Para archivos sin texto, consulta podrá estar vacía si existe un filtro. La búsqueda global necesita un cursor que conserve los offsets globales requeridos por Telegram y la consulta original. Mantener los resultados como datos externos, preservar referencias para citas y probar fechas, límites, ambigüedad de chats y continuidad antes de usar la cuenta real.

La transcripción y el índice local son una segunda fase: elegir qué chats indexar, dónde guardar los datos y si el procesamiento será local o externo. La caché de transcripciones no hace que Telegram pueda buscarlas; debemos consultar también ese índice y distinguir ambos orígenes.

## Documentación oficial de apoyo

- [Telegram: búsqueda y filtros](https://core.telegram.org/api/search): filtros por medios y parámetros de búsqueda global.
- [Telegram: messages.search](https://core.telegram.org/method/messages.search): remitente, fechas, hilo y límites.
- [Telegram: mensajes guardados](https://core.telegram.org/api/saved-messages): conversación personal, diálogos de origen y etiquetas.
- [Telethon: cliente](https://docs.telethon.dev/en/stable/modules/client.html): búsqueda, historial y filtros de iter_messages.

No se modificó el comportamiento del servicio en esta investigación. La cuenta sigue pendiente de autenticación y registro de la integración en el asistente.
