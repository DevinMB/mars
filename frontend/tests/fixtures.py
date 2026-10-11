"""Synthetic browser fixtures. No credentials or connection to a live backend."""
from copy import deepcopy

STAMP = '2026-09-16T12:00:00Z'
SOURCE = {
    'id': 1, 'name': 'readings', 'kind': 'source', 'connector': 'datagen',
    'description': 'Generated sensor readings.', 'sql_text': '', 'options': {'rows-per-second': '7'},
    'updated_at': STAMP, 'used_by': ['readings_to_output'], 'version': 1,
    'columns': [{'name': 'sensor_id', 'type': 'STRING'}, {'name': 'temperature', 'type': 'DOUBLE'}],
}
SOURCE.update(read_by=['readings_to_output'], written_by=[],
              resource={'key': 'table:readings', 'kind': 'datagen', 'label': 'readings'})
SINK = dict(SOURCE, id=2, name='output', kind='sink', connector='print', description='Console output.', options={},
            read_by=[], written_by=['readings_to_output'],
            resource={'key': 'table:output', 'kind': 'print', 'label': 'output'})
# Two entries on one Kafka topic, one written and one read, as the catalog groups them.
TOPIC = {'key': 'kafka:broker:9092/example-events', 'kind': 'kafka topic', 'label': 'example-events'}
EVENTS_OUT = dict(SOURCE, id=3, name='events_out', kind='table', connector='kafka', description='Enriched events.',
                  options={}, used_by=['enrich_events'], read_by=[], written_by=['enrich_events'], resource=TOPIC)
EVENTS_IN = dict(SOURCE, id=4, name='events_in', kind='table', connector='kafka', description=None,
                 options={}, used_by=['archive_events'], read_by=['archive_events'], written_by=[], resource=TOPIC)
RUN = {
    'id': 1, 'run_id': 1, 'job': 'readings_to_output', 'state': 'running',
    'started_at': STAMP, 'ended_at': None, 'restarts': 0, 'error_summary': None,
    'submitted_by': 'operator', 'triggered_by_schedule': False, 'restored_from': None,
    'flink_job_id': 'fixture-job', 'superseded': False, 'acknowledged': False,
    'acknowledged_by': None, 'savepoint_path': None,
}
JOB = {
    'id': 1, 'name': 'readings_to_output', 'description': 'Send sensor readings to the output.',
    'job_type': 'streaming', 'sql_text': 'INSERT INTO output SELECT * FROM readings;',
    'catalog_refs': ['readings', 'output'], 'enabled': True, 'version': 1,
    'target_name': None, 'latest_savepoint': None, 'updated_at': STAMP, 'latest_run': RUN,
    'schedule': {'mode': 'supervisor', 'enabled': True}, 'live_state': 'running', 'checkpoint_age_ms': 1000,
}
TARGET = {
    'name': 'default', 'description': 'Local cluster', 'flink_rest_url': 'http://cluster:8081',
    'gateway_url': 'http://gateway:8083', 'ui_url': '', 'labels': {}, 'enabled': True,
    'is_default': True, 'job_count': 1, 'reachable': True, 'flink_version': '2.2.1',
    'slots_total': 12, 'slots_available': 11,
}
CONNECTORS = [{
    'connector': name, 'displayName': name.title(), 'kinds': [kind], 'description': description,
    'docsUrl': None, 'supportsHealthCheck': False, 'source': 'built-in',
    'options': [], 'columns': [{'name': 'default_column', 'sqlType': 'STRING'}],
} for name, kind, description in [('datagen', 'source', 'Generate test records.'), ('print', 'sink', 'Write to the console.')]]


def fixtures():
    return deepcopy({
        '/api/auth/me': {'username': 'operator', 'role': 'admin', 'must_change_password': False},
        '/api/jobs': [JOB], '/api/jobs/readings_to_output': JOB,
        '/api/jobs/readings_to_output/runs': [RUN],
        '/api/jobs/readings_to_output/versions': [{'version': 1, 'note': 'Created', 'created_at': STAMP, 'created_by': 'operator'}],
        '/api/jobs/readings_to_output/script': {'statements': [JOB['sql_text']]},
        '/api/jobs/activity': [RUN], '/api/catalog': [SOURCE, SINK, EVENTS_OUT, EVENTS_IN],
        '/api/catalog/readings': SOURCE, '/api/catalog/output': SINK,
        '/api/catalog/readings/versions': [], '/api/catalog/output/versions': [],
        '/api/targets': [TARGET], '/api/cluster': dict(TARGET, targets_total=1, targets_reachable=1),
        '/api/pipeline': {
            'nodes': [
                {'id': 'job:enrich_events', 'type': 'job', 'label': 'enrich_events', 'state': 'running', 'cluster': None},
                {'id': 'job:archive_events', 'type': 'job', 'label': 'archive_events', 'state': 'failed', 'cluster': None},
                {'id': 'job:readings_to_output', 'type': 'job', 'label': 'readings_to_output', 'state': 'running', 'cluster': None},
                {'id': 'ext:1', 'type': 'external', 'label': 'event-collector', 'direction': 'produces', 'note': None,
                 'endpoint_id': 1, 'resource': 'kafka:broker:9092/raw-events'},
                {'id': 'res:kafka:broker:9092/raw-events', 'type': 'resource', 'kind': 'kafka topic', 'label': 'raw-events',
                 'key': 'kafka:broker:9092/raw-events', 'entries': ['raw_events']},
                {'id': 'res:' + TOPIC['key'], 'type': 'resource', 'kind': 'kafka topic', 'label': 'example-events',
                 'key': TOPIC['key'], 'entries': ['events_in', 'events_out']},
                {'id': 'res:table:readings', 'type': 'resource', 'kind': 'datagen', 'label': 'readings',
                 'key': 'table:readings', 'entries': ['readings']},
                {'id': 'res:table:output', 'type': 'resource', 'kind': 'print', 'label': 'output',
                 'key': 'table:output', 'entries': ['output']},
            ],
            'edges': [
                {'from': 'ext:1', 'to': 'res:kafka:broker:9092/raw-events'},
                {'from': 'res:kafka:broker:9092/raw-events', 'to': 'job:enrich_events'},
                {'from': 'job:enrich_events', 'to': 'res:' + TOPIC['key']},
                {'from': 'res:' + TOPIC['key'], 'to': 'job:archive_events'},
                {'from': 'res:table:readings', 'to': 'job:readings_to_output'},
                {'from': 'job:readings_to_output', 'to': 'res:table:output'},
            ],
            'unused': ['old_events_sample'],
        },
        '/api/system/version': {
            'console': {'revision': 'a' * 40, 'built_at': STAMP, 'image': 'ghcr.io/example/mars-console@sha256:' + '1' * 64,
                        'behind_by': 2, 'update_available': True,
                        'commits': [{'sha': 'c1' + '0' * 38, 'title': 'Example change one', 'date': STAMP},
                                    {'sha': 'c2' + '0' * 38, 'title': 'Example change two', 'date': STAMP}],
                        'how_to_update': {'needs_window': False, 'steps': ['docker pull example'], 'command': 'deploy.sh console bbbbbbb'}},
            'flink': {'revision': None, 'image': 'ghcr.io/example/mars-flink@sha256:' + '2' * 64},
            'update_check': {'enabled': True, 'channel': 'main', 'checked_at': STAMP, 'error': None},
            'latest': {'revision': 'b' * 40, 'label': 'bbbbbbb', 'published_at': STAMP, 'url': 'https://github.com/example/mars'}},
        '/api/targets/setup': {
            'flink_image': 'ghcr.io/example/mars-flink@sha256:' + '0' * 64, 'image_pinned': True,
            'registry': 'ghcr.io', 'same_machine_name': 'mars-b',
            'same_machine_rest_url': 'http://jobmanager-b:8081',
            'same_machine_gateway_url': 'http://sql-gateway-b:8083',
            'same_machine_command': 'docker compose --profile second-target up -d',
            'same_machine_registered': False,
            'other_machine_compose': '# A MARS cluster for another machine\nname: mars-target\nservices: {}\n'},
        '/api/connectors': CONNECTORS, '/api/secrets': [],
        '/api/users': [{'username': 'operator', 'role': 'admin', 'disabled': False, 'must_change_password': False,
                        'last_login_at': STAMP, 'created_at': STAMP, 'token_count': 0, 'is_self': True}],
        '/api/ai': {'kind': 'ollama', 'base_url': 'http://model:11434', 'model': 'test-model',
                    'secret_name': None, 'enabled': True, 'configured': True, 'timeout_seconds': 120,
                    'auth_method': 'none', 'auth_header': '', 'auth_username': '', 'extra_headers': {},
                    'temperature': '0', 'max_tokens': 1500},
        '/api/schema-registry': {'url': '', 'auth_method': 'none', 'username': '', 'secret_name': None,
                                'enabled': False, 'configured': False, 'timeout_seconds': 10},
    })
