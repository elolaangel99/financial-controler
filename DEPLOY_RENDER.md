# Publicar Financial Controler Beta

## Qué necesitas
1. Una cuenta de GitHub.
2. Una cuenta de Render.

## Pasos
1. Crea un repositorio nuevo en GitHub llamado `financial-controler-beta`.
2. Sube **el contenido de esta carpeta**, no el ZIP entero dentro del repositorio.
3. En Render, crea un nuevo servicio desde ese repositorio.
4. Si Render detecta `render.yaml`, usa el Blueprint y confirma la creación.
5. Espera al despliegue. Render te dará una URL `*.onrender.com`.
6. Abre la URL y prueba `/health`: debe devolver `{"status":"ok"}`.

## Importante
- Esta beta usa SQLite y un disco persistente de 1 GB.
- No introduzcas datos bancarios reales todavía.
- Antes de cobrar o almacenar datos sensibles habrá que migrar a PostgreSQL y reforzar seguridad, RGPD, recuperación de contraseña, correo, backups y observabilidad.
- No compartas la `SECRET_KEY`. Render la genera automáticamente con el `render.yaml`.
