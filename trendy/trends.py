import datetime
from collections import Counter
from django.utils.functional import cached_property
from opal.core.fields import ForeignKeyOrFreeText
from opal.core import discoverable
from opal.core import subrecords
from dateutil.relativedelta import relativedelta
from django.db.models import Count
from trendy.utils import get_subrecord_qs_from_episode_qs
from django.utils.encoding import force_bytes
from six import text_type

import json


def encode_to_utf8(some_var):
    if not isinstance(some_var, text_type):
        return some_var
    else:
        return force_bytes(some_var)


def date_to_string(date):
    dt = datetime.datetime(date.year, date.month, date.day)
    return dt.strftime("%d/%m/%Y")


def string_to_date(date_str):
    dt = datetime.datetime.strptime(date_str, "%d/%m/%Y")
    return dt.date()


class Trendy(discoverable.DiscoverableFeature):
    module_name = "trends"

    def __init__(self, subrecord_api_name, request, field_name=None):
        self.subrecord_api_name = subrecord_api_name
        self.field_name = field_name
        self.request = request

    def get_graph_data(self, episode_queryset):
        raise NotImplementedError("a query needs to be implemented")

    def get_description(self, value=None):
        raise NotImplementedError("description needs to be implemented")

    def query(self, value, episode_queryset):
        raise NotImplementedError("query needs to be implemented")

    @property
    def label(self):
        raise NotImplementedError("label needs to be implemented")

    @classmethod
    def get_from_get_param(cls, request, some_key):
        splitted = some_key.split("__")
        if len(splitted) == 2:
            subrecord_api_name, trend_api_name = splitted
            Trend = cls.get(trend_api_name)
            return Trend(subrecord_api_name, request)
        else:
            subrecord_api_name, trend_api_name, field_name = splitted
            Trend = cls.get(trend_api_name)
            return Trend(subrecord_api_name, request, field_name=field_name)

    def append_to_request(self, link):
        full_path = self.request.get_full_path()
        if "?" in full_path:
            return "{0}&{1}".format(full_path, link)
        else:
            return "{0}?{1}".format(full_path, link)

    def to_link_key(self):
        if self.field_name:
            link_key = "{0}__{1}__{2}".format(
                self.subrecord_api_name,
                self.__class__.get_slug(),
                self.field_name,
            )
        else:
            link_key = "{0}__{1}".format(
                self.subrecord_api_name,
                self.__class__.get_slug(),
            )

        return link_key

    def to_link(self, value):
        link = "{0}={1}".format(
            self.to_link_key(), value
        )
        return self.append_to_request(link)

    @cached_property
    def subrecord(self):
        return subrecords.get_subrecord_from_api_name(
            self.subrecord_api_name
        )

    @property
    def field_display_name(self):
        if not self.field_name:
            raise ValueError('The trend does not have a field')
        else:
            return self.subrecord._get_field_title(self.field_name)

    def get_related_name(self, field=None):
        """ The db relationship between it an episode
            e.g. for Allergy it would be patient__allergy
        """
        related_name = self.subrecord.__name__.lower()
        if field:
            related_name = "{0}__{1}".format(related_name, field)
        if self.is_patient_subrecord:
            return "patient__{0}".format(related_name)
        else:
            return related_name

    @cached_property
    def is_patient_subrecord(self):
        return self.subrecord in subrecords.patient_subrecords()

    def get_field(self):
        if self.field_name:
            return getattr(self.subrecord, self.field_name)


class FKFTMixin(object):
    @property
    def relative_fk_field(self):
        return self.get_related_name("{}_fk".format(self.field_name))

    @property
    def relative_ft_field(self):
        return self.get_related_name("{}_ft".format(self.field_name))

    @property
    def ft_field(self):
        return "{0}_ft".format(self.field_name)

    @property
    def fk_field(self):
        return "{0}_fk".format(self.field_name)


class SubrecordCountPieChart(Trendy):
    """
        supplies a pie chart of the count of this subrecord
        ie. 10% of episodes have 2 etc
    """
    display_name = "Subrecord count"
    slug = "subrecord_count"

    @property
    def label(self):
        return "Number Of {} Per Episode".format(
            self.subrecord.get_display_name()
        )

    @property
    def count_field(self):
        return "{}_count".format(self.get_related_name())

    def annotate_queryset(self, episode_queryset):
        # TODO we need to check how this works with patient__
        return episode_queryset.annotate(**{
            self.count_field: Count(self.get_related_name())
        })

    def query(self, value, episode_queryset):
        annotated = self.annotate_queryset(episode_queryset)
        return annotated.filter(**{self.count_field: value})

    def get_graph_data(self, episode_queryset):
        qs = self.annotate_queryset(episode_queryset)
        counter = Counter(qs.values_list(self.count_field, flat=True))
        aggregate = [[encode_to_utf8(k), v] for k, v in counter.items()]
        links = {}
        for i in aggregate:
            links[i[0]] = self.to_link(i[0])
        result = {}
        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            links=links
        ))
        return result

    def get_description(self, value=None):
        description = "Episodes with {0} {1}".format(
            value, self.subrecord.get_display_name()
        )
        if not value == '1':
            description = "{}s".format(description)
        return description


class FTFKQueryPieChart(Trendy, FKFTMixin):
    """
        supplies a pie chart of the aggregated values of fk ft
    """
    display_name = "FKFTQuery"

    def label(self):
        link_key = self.to_link_key()
        previous_filtered = self.request.GET.getlist(link_key)
        if previous_filtered:
            label = "% Breakdown of {0} where the episode has a {0} of".format(
                self.field_display_name
            )
            if len(previous_filtered) == 1:
                conjunction = previous_filtered[0]
            else:
                conjunction = " and ".join(
                    [", ".join(previous_filtered[:-1]), previous_filtered[-1]]
                )
            return "{0} {1}".format(label, conjunction)
        else:
            return "% Breakdown Of {}".format(self.field_display_name)

    def query(self, value, episode_queryset):

        field = self.get_field()
        if not isinstance(field, ForeignKeyOrFreeText):
            raise ValueError("this trend expects a foreign key or free text")

        if value == 'None':
            value = None
            lookup = self.relative_fk_field
        else:
            lookup = "{0}__name".format(self.relative_fk_field)

        return episode_queryset.filter(**{lookup: value})

    def get_graph_data(self, episode_queryset):
        qs = get_subrecord_qs_from_episode_qs(self.subrecord, episode_queryset)
        link_key = self.to_link_key()
        previous_filtered = self.request.GET.getlist(link_key)

        for previous in previous_filtered:
            qs = qs.exclude(**{
                "{}_fk__name".format(self.field_name): previous
            })

        field = self.get_field()

        if isinstance(field, ForeignKeyOrFreeText):
            field_name = "{}_fk__name".format(self.field_name)
            annotated = qs.values(field_name).annotate(Count('id'))
            aggregate = []
            for key_connection in annotated:
                total_count = key_connection.pop('id__count')
                key = key_connection.values()[0]
                aggregate.append([encode_to_utf8(key), total_count])
        else:
            raise NotImplementedError(
                'at the moment we only support free text or fk'
            )

        links = {}
        for i in aggregate:
            links[i[0]] = self.to_link(i[0])
        result = {}
        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            links=links
        ))
        return result

    def get_description(self, value=None):
        return "{0} is {1}".format(self.field_name, value)


class EpisodeAdmissionBarChart(Trendy):
    """
        Provides a bar chart of admissions by quarter
    """
    display_name = "EpisodeAdmissions"
    label = "Episode Admissions"

    def get_description(self, value=None):
        return "Episode admissions for {}".format(value)

    def filter_by_quarter(self, episode_queryset, quarter):
        start_dt = quarter[0]
        admissions_qs = episode_queryset.filter(start__gte=start_dt)

        if len(quarter) == 2:
            end_dt = quarter[1]
            admissions_qs = admissions_qs.filter(end__lt=end_dt)
        return admissions_qs

    def query(self, value, episode_queryset):
        v = [string_to_date(i.strip()) for i in value.split("-")]
        return self.filter_by_quarter(episode_queryset, v)

    def get_graph_data(
        self,
        episode_queryset,
    ):
        result = {}

        quarters = [
            [datetime.date(2016, 7, 1), datetime.date(2016, 10, 1)],
            [datetime.date(2016, 10, 1), datetime.date(2017, 1, 1)],
            [datetime.date(2017, 1, 1), datetime.date(2017, 4, 1)],
            [datetime.date(2017, 4, 1), datetime.date(2017, 7, 1)],
            [datetime.date(2017, 7, 1)]
        ]

        admissions = []

        for quarter in quarters:
            admissions.append(
                self.filter_by_quarter(episode_queryset, quarter).count()
            )

        admissions.insert(0, "Admissions")
        x_axis = ["x"]

        for quarter in quarters:
            if len(quarter) == 1:
                x_axis.append(
                    "{} +".format(date_to_string(quarter[0]))
                )
            else:
                x_axis.append(
                    "{0} - {1}".format(
                        date_to_string(quarter[0]),
                        date_to_string(quarter[1])
                    )
                )
        aggregate = [x_axis, admissions]
        links = {}

        for i in aggregate[0][1:]:
            links[i] = self.to_link(i)

        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            links=links,
            subrecord=self.subrecord_api_name
        ))
        return result


class AgeBarChart(Trendy):
    """
        supplies a bar chart of the demographics ages
    """
    display_name = "Age"
    label = "Patient Age"

    def get_description(self, value=None):
        return "Age range between {}".format(value)

    def query(self, value, episode_queryset):
        age_group = [int(i.strip()) for i in value.split("-") if i.strip()]
        today = datetime.date.today()
        start_dt = today - relativedelta(years=age_group[0])
        age_group_qs = episode_queryset.filter(
            patient__demographics__date_of_birth__lte=start_dt
        )

        if len(age_group) == 2:
            end_dt = today - relativedelta(years=age_group[1])
            age_group_qs = age_group_qs.filter(
                patient__demographics__date_of_birth__gt=end_dt
            )

        return age_group_qs

    def get_graph_data(
        self,
        episode_queryset,
    ):
        subrecord = subrecords.get_subrecord_from_api_name(
            self.subrecord_api_name
        )
        result = {}
        age_groups = [
            [0, 20],
            [20, 40],
            [40, 60],
            [60, 80],
            [80]
        ]

        qs = get_subrecord_qs_from_episode_qs(subrecord, episode_queryset)

        age_counts = []
        today = datetime.date.today()

        for age_group in age_groups:
            start_dt = today - relativedelta(years=age_group[0])
            age_group_qs = qs.filter(date_of_birth__lte=start_dt)

            if len(age_group) == 1:
                age_counts.append(age_group_qs.count())
            else:
                end_dt = today - relativedelta(years=age_group[1])
                age_counts.append(
                    age_group_qs.filter(date_of_birth__gt=end_dt).count()
                )

        age_counts.insert(0, "Age")
        x_axis = ["x"]

        for age_group in age_groups:
            if len(age_group) == 1:
                x_axis.append(
                    "{} +".format(age_group[0])
                )
            else:
                x_axis.append(
                    "{0} - {1}".format(*age_group)
                )
        aggregate = [x_axis, age_counts]
        links = {}

        for i in aggregate[0][1:]:
            links[i] = self.to_link(i)

        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            links=links,
            subrecord=self.subrecord_api_name
        ))
        return result


class EmptyFieldGauge(Trendy, FKFTMixin):
    """
        provides all the subrecords where {{ field }} is empty
    """
    display_name = "EmptyFieldGauge"

    def get_description(self, value=None):
        return "{0} has not been filled in".format(self.field_name)

    def query(self, value, episode_queryset):
        return episode_queryset.filter(**{
            self.relative_fk_field: None,
            self.relative_ft_field: ""
        })

    def get_graph_data(
        self,
        episode_queryset,
    ):
        """ gives the % of subrecords where the field is None
        """
        qs = get_subrecord_qs_from_episode_qs(self.subrecord, episode_queryset)
        total = qs.count()
        count = 0

        if total == 0:
            amount = 0
        else:
            count = qs.filter(**{
                self.fk_field: None,
                self.ft_field: '',
            }).count()
            amount = round(float(count)/total, 3) * 100
        result = {}
        result["total"] = total
        result["count"] = count
        aggregate = [['None', amount]]
        links = {"None": self.to_link("None")}
        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            field=self.field_name,
            links=links,
            subrecord=self.subrecord_api_name
        ))
        return result


class NonCodedFkAndFTGauge(Trendy, FKFTMixin):
    """
        provides all fields where we have a free text field
    """
    display_name = "NonCodedFkAndFTGauge"

    def get_description(self, value=None):
        return "Number of {0} with a non-coded {1}".format(
            self.subrecord.get_display_name(),
            self.field_name
        )

    def query(
        self, value, episode_queryset
    ):
        non_coded = self.subrecord.objects.filter(
            **{self.fk_field: None}
        ).exclude(
            **{self.ft_field: ''}
        )
        self.subrecord.__name__.lower()
        query_arg = "{}__in".format(self.get_related_name())
        return episode_queryset.filter(
            **{query_arg: non_coded}
        )

    def get_graph_data(
            self, episode_queryset
    ):
        subrecord = subrecords.get_subrecord_from_api_name(
            self.subrecord_api_name
        )
        qs = get_subrecord_qs_from_episode_qs(subrecord, episode_queryset)
        total = qs.count()
        count = 0

        if total == 0:
            amount = 0
        else:
            count = qs.filter(**{
                self.fk_field: None
            }).exclude(**{
                self.ft_field: ''
            }).count()
            amount = round(float(count)/total, 3) * 100
        result = {}
        result["total"] = total
        result["count"] = count
        aggregate = [['None', amount]]
        links = {"None": self.to_link("None")}
        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            links=links,
            field=self.field_name,
            subrecord=self.subrecord_api_name
        ))
        return result


class MissingGauge(Trendy):
    display_name = "MissingGauge"

    def get_description(self, value=None):
        return "Number of episodes without a {}".format(
            self.subrecord.get_display_name(),
        )

    def query(
        self, value, episode_queryset
    ):
        related_name = self.subrecord.__name__.lower()
        key = "num_{}".format(related_name)
        qs = episode_queryset.annotate(**{
            key: Count(related_name)
        })
        return qs.filter(**{key: 0})

    def get_graph_data(
            self, episode_queryset
    ):
        """ gives the % of subrecords where the field is None
        """
        total = episode_queryset.count()
        count = 0
        result = {}

        if total == 0:
            amount = 0
        else:
            count = episode_queryset.annotate(
                subrecord_count=Count(self.subrecord_api_name)
            ).filter(subrecord_count=0).count()

            amount = round(float(count)/total, 3) * 100
        result["total"] = total
        result["count"] = count
        aggregate = [['None', amount]]
        links = {"None": self.to_link("None")}
        result["graph_vals"] = json.dumps(dict(
            aggregate=aggregate,
            subrecord=self.subrecord_api_name,
            links=links
        ))
        return result
