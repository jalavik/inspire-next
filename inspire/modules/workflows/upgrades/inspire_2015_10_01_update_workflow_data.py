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
# In applying this licence, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.

"""Migrate bibfield data model to new doJSON data model in workflows."""

import six


depends_on = []


def info():
    """Info about this upgrade."""
    return __doc__


def do_upgrade():
    """Implement your upgrades here."""
    from invenio_workflows.models import BibWorkflowObject, Workflow
    from invenio_deposit.models import Deposition

    from inspire.dojson.utils import legacy_export_as_marc
    from inspire.dojson.hep import hep2marc
    from inspire.modules.workflows.dojson import bibfield
    from inspire.modules.workflows.models import Payload

    for deposit in BibWorkflowObject.query.filter(
            BibWorkflowObject.module_name == "webdeposit"):
        d = Deposition(deposit)
        sip = d.get_latest_sip()
        if sip:
            sip.metadata = bibfield.do(sip.metadata)
            sip.package = legacy_export_as_marc(hep2marc.do(sip.metadata))
            d.save()

    workflows = ["process_record_arxiv"]
    workflow_objects = []
    for workflow_name in workflows:
        workflow_objects += BibWorkflowObject.query.join(
            BibWorkflowObject.workflow).filter(Workflow.name == workflow_name).all()

    for obj in workflow_objects:
        metadata = obj.get_data()
        if isinstance(metadata, six.string_types):
            # Ignore records that have string as data
            continue
        if 'drafts' in metadata:
            # New data model detected
            continue
        if hasattr(metadata, 'dumps'):
            metadata = metadata.dumps(clean=True)
        obj.data = bibfield.do(metadata)
        payload = Payload.create(workflow_object=obj, type=obj.workflow.name)
        payload.save()


def estimate():
    """Estimate running time of upgrade in seconds (optional)."""
    from invenio_workflows.models import BibWorkflowObject
    return BibWorkflowObject.query.count()


def pre_upgrade():
    """Run pre-upgrade checks (optional)."""
    pass


def post_upgrade():
    """Run post-upgrade checks (optional)."""
    pass
