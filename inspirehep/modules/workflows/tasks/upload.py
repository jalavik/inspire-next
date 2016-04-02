# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2015, 2016 CERN.
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

"""Tasks related to record uploading."""

import jsonpatch
import StringIO
import six

from flask import current_app

from werkzeug.utils import import_string

from invenio_db import db

from invenio_records import Record, create_record, get_record


def convert_record_to_json(obj, eng):
    """Convert one record from MARCXML to JSON."""
    source = StringIO.StringIO(obj.data)

    processor = current_app["RECORD_PROCESSORS"]["marcxml"]
    if isinstance(processor, six.string_types):
        processor = import_string(processor)

    for record in processor(source):
        # Should only be one.
        obj.data = record
        break
    source.close()


def store_record_sip(obj, *args, **kwargs):
    """Update existing record via `control_number` or create new (SIP)."""
    from inspirehep.utils.helpers import get_model_from_obj
    from invenio_records.tasks import create_record as create

    model = get_model_from_obj(obj)
    sip = model.get_latest_sip()
    record = sip.metadata
    force = False
    if "control_number" in record:
        record['recid'] = record.get('control_number')
        force = True
    create.delay(json=record, force=force)


def store_record(obj, *args, **kwargs):
    """Update existing record via `control_number` or create new (obj.data)."""
    record = obj.data
    if "control_number" in record:
        record['recid'] = record.get('control_number')
        create_related_record(record['recid'])
    _store_record(record)


def create_related_record(recid):
    """Create a record in BibRec as required when creating a new recid."""
    if Record.query.get(recid) is None:
        rec = Record(id=recid)
        db.session.add(rec)


def _store_record(record):
    """Update existing record via `control_number` or create new."""
    if "control_number" in record:
        existing_record = get_record(record['control_number'])
        if existing_record is not None:
            patch = jsonpatch.JsonPatch.from_diff(existing_record, record)
            updated_record = existing_record.patch(patch=patch)
            updated_record.commit()
        else:
            # New record with some hardcoded recid/control_number
            create_record(data=record)
    else:
        create_record(data=record)
