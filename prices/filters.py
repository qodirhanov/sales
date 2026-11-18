from difflib import get_close_matches

import django_filters
from django.db.models import Case, IntegerField, When
from rest_framework import filters as drf_filters

from .models import Location, PriceEntry, Product
from .textnorm import search_tokens


class ProductFilter(django_filters.FilterSet):
    class Meta:
        model = Product
        fields = ["category"]


class LocationFilter(django_filters.FilterSet):
    class Meta:
        model = Location
        fields = ["district", "type"]


class PriceEntryFilter(django_filters.FilterSet):
    district = django_filters.NumberFilter(field_name="location__district_id")

    class Meta:
        model = PriceEntry
        fields = ["product", "location", "district"]


class ProductSearchFilter(drf_filters.SearchFilter):
    """?search=... that ignores case, spaces, apostrophes and Cyrillic/Latin differences.
    Every word must match ("mol go'sht" finds "Mol go'shti"; so does "MOLGOSHT").
    When nothing matches, falls back to close spellings (typo tolerance)."""

    def filter_queryset(self, request, queryset, view):
        tokens = search_tokens(request.query_params.get(self.search_param, ""))
        if not tokens:
            return queryset
        strict = queryset
        for token in tokens:
            strict = strict.filter(search_key__contains=token)
        if strict.exists():
            # Names that START with what was typed come first ("sum" -> Sumka before Qo'l sumka).
            starts = Case(When(search_key__startswith=tokens[0], then=0), default=1, output_field=IntegerField())
            return strict.annotate(_rank=starts).order_by("_rank", "name")

        # Typo fallback: compare the joined query with each product key, and each word with
        # the start of the key, so "mol goshtt" or "paxta yogg" still land somewhere sensible.
        joined = "".join(tokens)
        rows = list(queryset.values_list("pk", "search_key")[:5000])
        by_key = {}
        for pk, key in rows:
            by_key.setdefault(key, []).append(pk)
        wanted = set(get_close_matches(joined, by_key, n=8, cutoff=0.7))
        for pk, key in rows:
            if any(len(t) >= 4 and (key.startswith(t[:4]) and get_close_matches(t, [key[:len(t) + 2]], n=1, cutoff=0.8))
                   for t in tokens):
                wanted.add(key)
        ids = [pk for key in wanted for pk in by_key[key]]
        return queryset.filter(pk__in=ids)
