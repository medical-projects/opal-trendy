from django import template
from opal.core import subrecords
from opal.models import Patient
from django.db.models import Count
import json

register = template.Library()


@register.inclusion_tag('templatetags/pie_chart.html', takes_context=True)
def pie_chart(context, queryset, subrecord_api_name, field):
    subrecord = subrecords.get_subrecord_from_api_name(subrecord_api_name)
    patients = Patient.objects.filter(episode__in=queryset)
    qs = subrecord.objects.filter(patient__in=patients)
    annotated = qs.values(field).annotate(Count('id'))

    result = []
    for key_connection in annotated:
        total_count = key_connection.pop('id__count')
        key = key_connection.values()[0]
        result.append([str(key), total_count])

    # context["graph_vals"] = json.dumps(result)
    context["graph_vals"] = json.dumps(dict(hello='there'))
    return context
