#!/bin/sh
celery -A tasks:celery_app worker --loglevel=info --pool=solo --without-gossip --without-mingle --without-heartbeat &
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}