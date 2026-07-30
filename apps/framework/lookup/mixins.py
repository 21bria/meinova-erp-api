from django.db.models import Q


class SearchMixin:

    @staticmethod
    def apply_search(queryset, lookup, keyword):

        if not keyword:
            return queryset

        query = Q()

        for field in lookup.search_fields:
            query |= Q(**{
                f"{field}__icontains": keyword,
            })

        return queryset.filter(query)


class OrderingMixin:

    @staticmethod
    def apply_ordering(queryset, lookup):

        if lookup.ordering:
            return queryset.order_by(
                *lookup.ordering,
            )

        return queryset

class FilterMixin:
    @staticmethod
    def apply_filters(queryset, lookup, request):
        for field in lookup.filter_fields:
            value = request.query_params.get(field)

            if value not in (None, ""):
                queryset = queryset.filter(
                    **{
                        field: value,
                    }
                )

        return queryset
    
class PaginationMixin:

    @staticmethod
    def paginate(queryset, page, page_size):

        start = (page - 1) * page_size
        end = start + page_size

        return queryset[start:end]