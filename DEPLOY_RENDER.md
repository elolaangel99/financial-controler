# Despliegue de Financial Controler con PostgreSQL en Render

1. En Render crea primero **New > Postgres**. Para una prueba inicial puedes usar Free, pero Render indica que los Postgres Free caducan a los 30 días; no los uses para datos reales de producción.
2. Pon nombre: `financial-controler-db`.
3. Elige una región cercana a tu web service y crea la base de datos.
4. Cuando esté creada, abre la base de datos y copia **Internal Database URL**.
5. Vuelve a `financial-controler-beta` > Environment.
6. Añade `DATABASE_URL` con esa Internal Database URL.
7. Asegúrate de tener `SECRET_KEY` generada por Render.
8. En Settings/Build & Deploy comprueba:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`
   - Branch: `main`
   - Language: Python 3
9. Guarda y haz **Manual Deploy > Deploy latest commit**.
10. Abre la URL `.onrender.com` y comprueba `/health`: debe devolver `{"status":"ok"}`.

### Importante
La instancia web Free puede apagarse tras 15 minutos sin tráfico y tardar alrededor de un minuto en despertar. Render también indica que el Postgres Free expira a los 30 días. Para una beta de prueba sirve; antes de meter usuarios reales hay que pasar a una configuración persistente y revisar seguridad, backups, RGPD y recuperación de cuenta.
