# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2014, 2015 CERN.
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

"""Tasks related to user actions."""

from functools import wraps

from flask import current_app

from inspirehep.utils.helpers import (
    get_record_from_model,
)


def shall_upload_record(obj, *args, **kwargs):
    """Check if the record was approved."""
    return obj.extra_data.get("approved", False)


def shall_halt_workflow(obj, *args, **kwargs):
    """Check if the workflow shall be halted."""
    return obj.extra_data.get("halt_workflow", False)


def shall_push_remotely(*args, **kwargs):
    """Check if the record shall be robotuploaded."""
    return current_app.config.get("SERVER_NAME") != \
        current_app.config.get("CFG_ROBOTUPLOAD_SUBMISSION_BASEURL")


def add_core_check(obj, eng):
    """Check if CORE shall be added."""
    if obj.extra_data.get('core'):
        add_core(obj, eng)


def halt_record(action=None):
    """Halt the workflow for approval with optional action."""
    @wraps(halt_record)
    def _halt_record(obj, eng):
        eng.halt(action=obj.extra_data.get("halt_action") or action,
                 msg=obj.extra_data.get("halt_message", "Record has been halted."))
    return _halt_record


def add_core(obj, eng):
    """Add CORE collection tag to collections."""
    model = eng.workflow_definition.model(obj)
    record = get_record_from_model(model)
    collections = record.get("collections", [])
    # Do not add it again if already there
    has_core = [v for c in collections
                for v in c.values()
                if v.lower() == "core"]
    if not has_core:
        collections.append({"primary": "CORE"})
        record["collections"] = collections
    model.update()


def update_note(metadata):
    """Check if the record was approved as CORE."""
    new_notes = []
    for note in metadata.get("public_notes", []):
        if note.get("value", "") == "*Brief entry*":
            note = {"value": "*Temporary entry*"}
        new_notes.append(note)
    if new_notes:
        metadata["public_notes"] = new_notes
    return metadata


def reject_record(message):
    """Reject record with message."""
    @wraps(reject_record)
    def _reject_record(obj, *args, **kwargs):
        from inspirehep.modules.audit.api import log_prediction_action

        # Audit logging
        results = obj.extra_data["_tasks_results"]
        prediction_results = results.get("arxiv_guessing", {})
        log_prediction_action(
            action="reject_record",
            prediction_results=prediction_results,
            object_id=obj.id,
            user_id=0,
            source="workflow",
        )

        obj.extra_data["approved"] = False
        obj.extra_data["reason"] = message
        obj.log.info(message)
    return _reject_record


def is_record_relevant(obj, *args, **kwargs):
    """Shall we halt this workflow for potential acceptance or just reject?"""
    from inspirehep.modules.workflows.utils import (
        get_classification_from_task_results,
    )
    results = obj.extra_data["_tasks_results"]
    prediction_results = results.get("arxiv_guessing", {})
    classification_results = get_classification_from_task_results(obj)

    if prediction_results and classification_results:
        prediction_results = prediction_results[0].get("result")
        score = prediction_results.get("max_score")
        decision = prediction_results.get("decision")
        core_keywords = classification_results.get("Core keywords")
        if decision.lower() == "rejected" and score > 0 and \
                len(core_keywords) == 0:
            return False
    return True
