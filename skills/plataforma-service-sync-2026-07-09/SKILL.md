---
name: plataforma-service-sync-2026-07-09
description: Replicar en plataforma service los cambios de agendamiento compacto y alertas ODO reforzadas hechos en plataforma-transito el 2026-07-09, commit c78fb1e.
---

# Plataforma Service Sync 2026-07-09

Usa esta skill cuando el usuario pida replicar en `plataforma service` los cambios recientes del repo `plataforma-transito` del 2026-07-09.

## Fuente

Commit base:

```bash
c78fb1e Compactar agendamiento y reforzar alertas ODO
```

Archivos modificados en origen:

- `agendamiento/templates/agendamiento/schedule_grid.html`
- `agendamiento/views.py`
- `agendamiento/tests.py`
- `odo/services.py`
- `odo/tests.py`

## Cambios a Replicar

### Agendamiento

- La grilla debe iniciar por defecto con `15` dias, no `60`.
- El selector de rango debe incluir `15, 30, 60, 90, 120, 180`.
- Eliminar el flujo visual separado de `Vista 15 dias` y `Vista completa`.
- Mantener solo el selector `Dias` + boton `Ver rango`.
- La ruta antigua de 15 dias puede quedar como compatibilidad, redirigiendo a la grilla normal con `days=15`.
- Compactar el modal/tarjeta de clase:
  - `Ficha` pasa a `Nro ficha`.
  - campo de ficha corto, pensado para 3 a 6 digitos.
  - comentario dentro de la tarjeta.
  - quitar boton `Guardar comentario`.
  - `Guardar` debe guardar tambien `notes`.
  - botones cortos: `Guardar`, `Bloquear`, `Liberar`, `Quitar bloqueo`.

### ODO

- Alertas preventivas por kilometraje:
  - `500, 400, 300, 200, 100 km`
- Alertas preventivas por fecha:
  - `5, 4, 3, 2, 1 dias`
- Enviar correo en todos esos umbrales, no solo en algunos.
- Mantener envio critico cuando esta vencido.
- El asunto del correo debe indicar prioridad:
  - `PREVENTIVO`: 5/4 dias o 500/400 km.
  - `ATENCION`: 3/2 dias o 300/200 km.
  - `URGENTE`: 1 dia o 100 km.
  - `VENCIDO`: alerta critica.
- Si una lectura de odometro cruza varios umbrales de una vez, crear/enviar solo el umbral mas urgente alcanzado para evitar multiples correos por un solo registro.

## Validacion Esperada

Ejecutar al menos:

```bash
git diff --check
.venv/bin/python manage.py check
```

Si PostgreSQL local esta disponible, ejecutar tambien:

```bash
.venv/bin/python manage.py test agendamiento odo.tests.OdoAlertTests
```

Si los tests no corren por PostgreSQL local caido en `localhost:5432`, reportarlo como bloqueo de entorno, no como fallo del cambio.
