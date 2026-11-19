from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Default 20 per page; clients may ask for more with ?page_size= (max 200).
    The catalogue page needs the whole product list, not just the first page."""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200
