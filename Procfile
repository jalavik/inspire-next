web: inspirehep --debug run
cache: redis-server
worker: celery worker -E -A inspirehep.celery --loglevel=INFO --workdir="${VIRTUAL_ENV}" --autoreload --pidfile="${VIRTUAL_ENV}/worker.pid" --purge
workermon: celery flower -A inspirehep.celery
# mathoid: node_modules/mathoid/server.js -c mathoid.config.yaml
indexer: elasticsearch -Dcluster.name="inspire" -Ddiscovery.zen.ping.multicast.enabled=false -Dpath.data="$VIRTUAL_ENV/var/data/elasticsearch"  -Dpath.logs="$VIRTUAL_ENV/var/log/elasticsearch"
