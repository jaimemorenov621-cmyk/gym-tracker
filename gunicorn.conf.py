# Gunicorn lo lee solo (busca ./gunicorn.conf.py al arrancar): no hace falta
# tocar el Start Command de Render ("flask db upgrade && gunicorn app:app").
#
# Antes: 1 proceso, 1 hilo y 30 s de tope. Una petición lenta (el análisis de
# IA puede tardar más de 30 s) bloqueaba la app entera para todos y, al pasar
# de 30 s, gunicorn la mataba a medias (error en vez del análisis).
workers = 1      # plan gratuito de Render: 512 MB, un solo proceso
threads = 4      # trabajador gthread: una petición lenta no bloquea a las demás
timeout = 120    # margen para la IA (su cliente corta antes, a los 100 s)
