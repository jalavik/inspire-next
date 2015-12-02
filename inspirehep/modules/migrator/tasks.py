# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2015 CERN.
#
# INSPIRE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE. If not, see <http://www.gnu.org/licenses/>.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.

"""Manage migration from INSPIRE legacy instance."""

from __future__ import absolute_import, print_function

from celery.utils.log import get_task_logger

import gzip
import re
import traceback

from six import text_type, string_types

from flask import current_app
from dojson.contrib.marc21.utils import create_record as marc_create_record
from invenio_celery import celery
from invenio_records.api import Record as record_api
from invenio_records.models import Record

from inspirehep.dojson.conferences import conferences
from inspirehep.dojson.experiments import experiments
from inspirehep.dojson.hep import hep
from inspirehep.dojson.hepnames import hepnames
from inspirehep.dojson.institutions import institutions
from inspirehep.dojson.jobs import jobs
from inspirehep.dojson.journals import journals
from inspirehep.dojson.processors import _collection_in_record

from invenio_workflows.registry import workflows
from invenio_workflows.models import (
    BibWorkflowObject,
    Workflow,
    ObjectVersion
)
from invenio_deposit.models import Deposition

from inspirehep.dojson.utils import legacy_export_as_marc
from inspirehep.dojson.hep import hep2marc
from inspirehep.modules.workflows.dojson import bibfield
from inspirehep.modules.workflows.models import Payload

from invenio_ext.sqlalchemy import db
from invenio_ext.es import es

from .models import InspireProdRecords

logger = get_task_logger(__name__)

CHUNK_SIZE = 1000

split_marc = re.compile('<record.*?>.*?</record>', re.DOTALL)


def chunker(iterable, chunksize=CHUNK_SIZE):
    buf = []
    for elem in iterable:
        buf.append(elem)
        if len(buf) == chunksize:
            yield buf
            buf = []
    if buf:
        yield buf


def split_blob(blob):
    """Split the blob using <record.*?>.*?</record> as pattern."""
    for match in split_marc.finditer(blob):
        yield match.group()


def split_stream(stream):
    """Split the stream using <record.*?>.*?</record> as pattern."""
    buf = []
    for row in stream:
        row = text_type(row, 'utf8')
        index = row.rfind('</record>')
        if index >= 0:
            buf.append(row[:index + 9])
            for blob in split_blob(''.join(buf)):
                yield blob.encode('utf8')
            buf = [row[index + 9:]]
        else:
            buf.append(row)


@celery.task(ignore_result=True)
def migrate_broken_records(broken_output=None, dry_run=False):
    """Migrate records declared as broken.

    Directly migrates the records declared as broken, e.g. if the dojson
    conversion script have been corrected.
    """
    for i, chunk in enumerate(chunker(
            record.marcxml for record in
            db.session.query(InspireProdRecords).filter_by(successful=False))):
        logger.info("Processed {} records".format(i * CHUNK_SIZE))
        chunk_broken_output = None
        if broken_output:
            chunk_broken_output = "{}-{}".format(broken_output, i)
        migrate_chunk.delay(chunk, chunk_broken_output, dry_run)


@celery.task(ignore_result=True)
def migrate(source, broken_output=None, dry_run=False):
    """Main migration function."""
    if source.endswith('.gz'):
        fd = gzip.open(source)
    else:
        fd = open(source)

    for i, chunk in enumerate(chunker(split_stream(fd), CHUNK_SIZE)):
        logger.info("Processed {} records".format(i * CHUNK_SIZE))
        chunk_broken_output = None
        if broken_output:
            chunk_broken_output = "{}-{}".format(broken_output, i)
        migrate_chunk.delay(chunk, chunk_broken_output, dry_run)


@celery.task(ignore_result=True)
def continuos_migration():
    """Task to continuosly migrate what is pushed up by Legacy."""
    from redis import StrictRedis
    redis_url = current_app.config.get('CACHE_REDIS_URL')
    r = StrictRedis.from_url(redis_url)
    while r.llen('legacy_records'):
        record = r.lpop('legacy_records')
        create_record(record, force=True)


@celery.task(ignore_result=True, compress='zlib', acks_late=True)
def migrate_chunk(chunk, broken_output=None, dry_run=False):
    from flask_sqlalchemy import models_committed
    from invenio_records.receivers import record_modification
    from invenio_records.tasks.index import get_record_index
    from invenio.base.globals import cfg
    from elasticsearch.helpers import bulk as es_bulk
    from invenio_records.signals import before_record_index
    models_committed.disconnect(record_modification)

    records_to_index = []
    try:
        for record in chunk:
            try:
                recid, json = create_record(record, force=True, dry_run=dry_run)
                index = get_record_index(json) or cfg['SEARCH_ELASTIC_DEFAULT_INDEX']
                before_record_index.send(recid, json=json)
                json.update({'_index': index, '_type': 'record', '_id': recid})
                records_to_index.append(json)
            except Exception as err:
                logger.exception(err)
                if broken_output:
                    broken_output_fd = open(broken_output, "a")
                    print(record, file=broken_output_fd)

        logger.info("Committing chunk")
        db.session.commit()
        logger.info("Sending chunk to elasticsearch")
        es_bulk(es, records_to_index, request_timeout=60)
    finally:
        models_committed.connect(record_modification)


def create_record(data, force=False, dry_run=False):
    record = marc_create_record(data)
    recid = None
    if '001' in record:
        recid = int(record['001'][0])
    if not dry_run and recid:
        prod_record = InspireProdRecords(recid=recid)
        prod_record.marcxml = data
    try:
        if _collection_in_record(record, 'institution'):
            json = institutions.do(record)
        elif _collection_in_record(record, 'experiment'):
            json = experiments.do(record)
        elif _collection_in_record(record, 'journals'):
            json = journals.do(record)
        elif _collection_in_record(record, 'hepnames'):
            json = hepnames.do(record)
        elif _collection_in_record(record, 'job') or \
                _collection_in_record(record, 'jobhidden'):
            json = jobs.do(record)
        elif _collection_in_record(record, 'conferences'):
            json = conferences.do(record)
        else:
            json = hep.do(record)
        if dry_run:
            return recid, json

        if force and any(key in json for key in ('control_number', 'recid')):
            try:
                control_number = json['control_number']
            except KeyError:
                control_number = json['recid']
            control_number = int(control_number)
            # Searches if record already exists.
            record = record_api.get_record(control_number)
            if record is None:
                # Adds the record to the db session.
                rec = Record(id=control_number)
                db.session.add(rec)
                record = record_api.create(json)
            else:
                record.update(json)
                record.commit()
            if recid:
                prod_record.successful = True
                db.session.merge(prod_record)
            logger.info("Elaborated record {}".format(control_number))
            return control_number, dict(record)
    except Exception:
        if recid:
            prod_record.successful = False
            db.session.merge(prod_record)
            logger.exception("Error in elaborating record ID {}".format(recid))
        raise


@celery.task(ignore_result=True)
def migrate_workflow_object(obj_id):
    try:
        obj = BibWorkflowObject.query.get(obj_id)
        rename_object_action(obj)
        if obj.workflow.name == "process_record_arxiv":
            metadata = obj.get_data()
            if isinstance(metadata, string_types):
                # Ignore records that have string as data
                return
            if 'drafts' in metadata:
                # New data model detected, just save and exit
                obj.save()
                return
            if hasattr(metadata, 'dumps'):
                metadata = metadata.dumps(clean=True)
            obj.data = bibfield.do(metadata)
            payload = Payload.create(
                type=obj.workflow.name,
                workflow_object=obj
            )
            payload.save()
        elif obj.workflow.name == "literature":
            d = Deposition(obj)
            sip = d.get_latest_sip()
            if sip:
                sip.metadata = bibfield.do(sip.metadata)
                sip.package = legacy_export_as_marc(hep2marc.do(sip.metadata))
                d.save()
        else:
            obj.save()  # To update and trigger indexing
        reset_workflow_object_states(obj)
    except Exception as err:
        from flask import current_app
        current_app.logger.error("Problem migrating record {0}".format(obj_id))
        current_app.logger.exception(err)
        msg = "Error: %r\n%s" % \
              (err, traceback.format_exc())
        obj.set_error_message(str(err), msg)
        obj.save(version=ObjectVersion.ERROR)
        raise


def rename_object_action(obj):
    if obj.get_action() == "arxiv_approval":
        obj.set_action("hep_approval", obj.get_action_message())


def reset_workflow_object_states(obj):
    """Fix workflow positions and states.

    Old states from Prod/QA:
    {(), (0,), (5, 3, 14), (5, 3, 14, 0), (5, 3, 15), (5, 3, 15, 1)}

    {(),
     (0,),
     (5,),
     (5, 3, 1),
     (5, 3, 10),
     (5, 3, 11),
     (5, 3, 12),
     (5, 3, 14),
     (5, 3, 14, 0),
     (6, 3, 4)}

    OLD -> NEW
    5, 3, 14 -> 0 end
    5, 3, 10 -> 14, 0 halted
    """
    pos = obj.get_current_task()
    if obj.version == ObjectVersion.COMPLETED:
        obj.save(task_counter=[len(workflows.get(obj.workflow.name).workflow) - 1])
        return
    elif obj.version == ObjectVersion.RUNNING:
        # Running? Nah that cannot be.
        obj.version = ObjectVersion.ERROR
    try:
        obj.get_current_task_info()
    except IndexError:
        # The current task counter is Invalid
        obj.version = ObjectVersion.ERROR

    if obj.workflow.name == "process_record_arxiv":
        if tuple(pos) in [
                (5,), (5, 3, 14), (5, 3, 14, 0), (5, 3, 15), (5, 3, 15, 1)]:
            pos = [len(workflows.get(obj.workflow.name).workflow) - 1]  # finished
        elif tuple(pos) in [(5, 3, 10), (5, 3, 11), (5, 3, 12)]:
            pos = [14, 0]  # halted
        elif len(pos) > 1 and pos[0] == 6:
            # We need to update pos from 6 to start of pre_processing part
            pos = [7]
        else:
            pos = [0]  # Nothing here, we go to start
        return pos
