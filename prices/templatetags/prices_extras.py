from django import template

register = template.Library()


@register.filter
def money(value):
    """95000 -> '95 000'. Same grouping the JS side uses, so prices read the same everywhere."""
    try:
        return f"{round(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return value
