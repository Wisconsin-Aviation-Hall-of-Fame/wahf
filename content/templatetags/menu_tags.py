from django import template
from wagtail.models import Site

from content.models import Menu

register = template.Library()


# https://github.com/wagtail/bakerydemo/blob/master/bakerydemo/base/templatetags/navigation_tags.py
@register.simple_tag(takes_context=True)
def get_site_root(context):
    # This returns a core.Page. The main menu needs to have the site.root_page
    # defined else will return an object attribute error ('str' object has no
    # attribute 'get_children')
    return Site.find_for_request(context["request"]).root_page


@register.simple_tag()
def get_menu(slug):
    return (
        Menu.objects.filter(slug=slug).prefetch_related("menu_items__link_page").first()
    )


@register.inclusion_tag("tags/main_menu.html", takes_context=True)
def get_main_menu(context, slug, parent, calling_page=None):
    menu = (
        Menu.objects.filter(slug=slug).prefetch_related("menu_items__link_page").first()
    )
    menu_items = []

    if menu:
        for item in menu.menu_items.all():
            item.active = calling_page and item.link_page_id == calling_page.pk
            menu_items.append(item)

    return {
        "calling_page": calling_page,
        "menu_items": menu_items,
        "request": context["request"],
    }


@register.inclusion_tag("tags/footer_menu.html", takes_context=True)
def get_footer_menu(context, slug, parent, calling_page=None):
    menu = (
        Menu.objects.filter(slug=slug).prefetch_related("menu_items__link_page").first()
    )
    menu_items = []

    if menu:
        for item in menu.menu_items.all():
            item.active = calling_page and item.link_page_id == calling_page.pk
            menu_items.append(item)

    return {
        "calling_page": calling_page,
        "menu_items": menu_items,
        "request": context["request"],
    }
