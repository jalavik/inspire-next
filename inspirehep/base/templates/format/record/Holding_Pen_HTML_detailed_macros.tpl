{#
# This file is part of INSPIRE.
# Copyright (C) 2015 CERN.
#
# INSPIRE is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.
#}

{% macro add_delimiter(loop, delimiter) %}
  {% if not loop.last %} {{ delimiter }} {% endif %}
{% endmacro %}


{% macro get_subject(term) %}
    {% if term.term %}
        <span> {{ term['term'] }}</span>
    {% else %}
        <span> {{ term['value'] }}</span>
    {% endif %}
{% endmacro %}


{% macro get_paper_date(record) %}
    {% if record.preprint_date %}
        <span> {{ record.preprint_date }}</span>
    {% endif %}
{% endmacro %}


{% macro get_arxiv_id(record) %}
    {% if record.arxiv_eprints %}
        {% if record['arxiv_eprints.value'][0] and 'oai:arXiv.org:' in record['arxiv_eprints.value'][0] %}
           {{ record['arxiv_eprints.value'][0][14:] }}
        {% elif 'arXiv:' in record['arxiv_eprints.value'][0] %}
           {{ record['arxiv_eprints.value'][0][6:] }}
        {% else %}
           {{ record['arxiv_eprints.value'][0] }}
        {% endif %}
    {% endif %}
{% endmacro %}


{% macro get_abstract(record) %}
    {{ record['abstracts'][0]['value'] }}
{% endmacro %}
