# -*- encoding: utf-8 -*-
#import urllib

from django.core.urlresolvers import reverse, NoReverseMatch
from django.contrib import messages
from django.db.models import Q, Count, get_model
from django.db.models.query import QuerySet
from django.db.models.related import RelatedObject
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.utils.translation import ugettext as _
from django.utils import simplejson
from django.views.generic.list_detail import object_detail, object_list
from django.views.generic.create_update import delete_object # create_object, update_object, 
import django.views.generic as django_gv
from django.core.exceptions import ImproperlyConfigured
from django.forms.models import inlineformset_factory #, ModelForm
from main import cart_utils

from forms import FilterForm, GenericConfirmForm, GenericAssignRemoveForm, \
                  InlineModelForm
import settings

def add_filter(request, list_filters, **kwargs):
    """ Add list filters to form and eventually filter the queryset

        @param list_filter a list of dicts, each describing a filter

        A filter can have the following items:
            'name' required, the field name in the html form
            'destination' required, the field filter name. It can be a string like
                        "name__icontains", a plain field like "manufacturer" or
                        a list/tuple of strings, that will be OR-ed together
                        If it is a callable, it will be called like fn(data)
                        and expected to return a Q() filter-expression
            'queryset' optional, if set, it will be a ModelChoice form (selection) with
                    the queryset records as options
            'lookup_channel': optional, if set, it will present an AutoComplete for that
                    completion "channel"
    """
    filters = []
    filter_dict = dict([(f['name'], f) for f in list_filters])
    if request.method == 'GET':
        filter_form = FilterForm(list_filters, request.GET, qargs=kwargs)
        if filter_form.is_valid():
            for name, data in filter_form.cleaned_data.items():
                if not data:
                    continue
                dest = filter_dict[name]['destination']
                if isinstance(dest, basestring):
                    filters.append(Q(**{dest:data}))
                elif isinstance(dest, (tuple, list)):
                    q = None
                    for idest in dest:
                        nq = Q(**{idest:data})
                        if q is None:
                            q = nq
                        else:
                            q = q | nq
                    filters.append(q)
                elif callable(dest):
                    q = dest(data)
                    if not isinstance(q, Q):
                        raise TypeError("Callable at filter %s returned a %s" % (name, type(q)))
                    filters.append(q)
                else:
                    raise TypeError("invalid destination: %s" % type(dest))

    else:
        filter_form = FilterForm(list_filters, qargs=kwargs)

    return filter_form, filters

def generic_list(request, list_filters=[], queryset_filter=None, *args, **kwargs):
    """
        Remember that choice fields may need the "get_FOO_display" method rather than
        a direct value of "FOO".
    """
    filters = None
    if list_filters:
        filter_form, filters = add_filter(request, list_filters)
        kwargs['extra_context']['filter_form'] = filter_form

    if 'queryset' in kwargs and not isinstance(kwargs['queryset'], QuerySet) \
                and callable(kwargs['queryset']):
        queryset_fn = kwargs.pop('queryset')
        # since we evaluate the queryset here, this breaks the caching and
        # allows different result set per request (as desired).
        # Otherwise, the queryset would be queried once in db and reused
        # across requests, with same rows.
        kwargs['queryset'] = queryset_fn(request)

    if filters:
        kwargs['queryset'] = kwargs['queryset'].filter(*filters)

    return object_list(request,  template_name='generic_list.html', *args, **kwargs)

class GenericBloatedListView(django_gv.ListView):
    """ A list view with all (?) the features

        Supports:
            - Filter sub-form
            - dynamic (callable) queryset
            - selectable sorting TODO
            - groupping
            - second-row fields
            [ - cart actions ] TODO
    """
    template_name = 'bloated_list.html'
    extra_context = None
    group_by = False
    group_fields = None
    order_by = False
    list_filters = None
    prefetch_fields = None
    filter_form = None
    url_attribute = 'get_absolute_url'
    extra_columns = None
    enable_sorting = True
    title = None

    def get_title(self):
        if getattr(self, 'title', None):
            return self.title
        elif self.object_list:
            return _("List of %s") % unicode(self.object_list.model._meta.verbose_name_plural)
        else:
            return _("List")

    def get_context_data(self, **kwargs):
        if 'object_list' not in kwargs:
            context = super(GenericBloatedListView, self).get_context_data(**kwargs)
        else:
            context = kwargs.copy()
        if self.extra_context:
            context.update(self.extra_context)
            context.pop('extra_columns', None)

        context['url_attribute'] = self.url_attribute
        context['title'] = self.get_title()
        if self.filter_form:
            context['filter_form'] = self.filter_form
        return context

    def _select_prefetch(self, queryset, fields_list):
        if fields_list:
            queryset = queryset.select_related(*(tuple(set(fields_list))))
        # TODO: in Django 1.4 there is also prefetch_related(), which is more optimal
        return queryset

    def _calc_columns(self, request):
        """ Construct the "columns" list, order_by of fields
        """
        object_model_meta = self.object_list.model._meta
        ctx_columns = [ {'name': object_model_meta.verbose_name }, ]
        if object_model_meta.ordering:
            # the model ordering will be the one used when clicking the first column
            ctx_columns[0]['order_attribute'] = object_model_meta.ordering[0]

        extra_columns = self.extra_columns
        if (not extra_columns) and self.extra_context \
                    and 'extra_columns' in self.extra_context:
            extra_columns = self.extra_context['extra_columns']
        if extra_columns:
            for column in extra_columns:
                if column.get('under', False):
                    # This must become the second row of some other column
                    cunder = column['under']
                    for par in ctx_columns:
                        if (cunder == par.get('attribute', 'id')):
                            par.setdefault('subrows', []).append(column)
                            break
                    else:
                        raise KeyError("Column %s not found to place %s under it" % \
                                (cunder, column.get('attribute', column['name'])))
                    continue
                ctx_columns.append(column.copy())

        if self.enable_sorting:
            get_params = request.GET.copy()
            if 'order_by' in get_params:
                self.order_by = (get_params['order_by'], )
            order_field = None
            descending = False
            if self.order_by:
                if self.order_by[0].startswith('-'):
                    descending = True
                    order_field = self.order_by[0][1:]
                else:
                    order_field = self.order_by[0]
            for col in ctx_columns:
                attr = col.get('order_attribute', col.get('attribute', None))
                # Note that we allow order_attribute=False to deactivate ordering
                # for this field.
                if not attr:
                    continue
                else:
                    attr = attr.replace('.', '__')
                col['sortable'] = True
                get_params['order_by'] = attr
                if attr == order_field:
                    col['url_class'] = 'sorted'
                    if descending:
                        col['url_spanclass'] = 'famfam active famfam-arrow_up'
                    else:
                        col['url_spanclass'] = 'famfam active famfam-arrow_down'
                        get_params['order_by'] = '-' + attr
                col['url']= '?' + get_params.urlencode()
        return ctx_columns

    def get_queryset(self):
        filters = None
        if self.queryset and not isinstance(self.queryset, QuerySet) \
                and callable(self.queryset):
            # since we evaluate the queryset here, this breaks the caching and
            # allows different result set per request (as desired).
            # Otherwise, the queryset would be queried once in db and reused
            # across requests, with same rows.
            queryset = self.queryset(self.request)
        else:
            queryset = super(GenericBloatedListView, self).get_queryset()

        if self.list_filters:
            # must be after basic queryset has been computed!
            filter_form, filters = add_filter(self.request, self.list_filters, \
                        parent=self, parent_queryset=queryset)
            self.filter_form = filter_form

        if filters:
            queryset = queryset.filter(*filters)

        return queryset

    def apply_order(self, queryset):
        if isinstance(self.order_by, basestring):
            order = (self.order_by, )
        else:
            order = self.order_by
        return queryset.order_by(*order)

    def get(self, request, *args, **kwargs):
        self.object_list = base_queryset = self.get_queryset()
        columns = self._calc_columns(request)
        
        if self.group_by:
            # so far, the 'group_by' must be a field!
            group = self.group_by
            rel_field = base_queryset.model._meta.get_field(group)
            # we need the order by (group__id) so that any natural ordering on our model
            # or the foreign models is avoided (too expensive)
            #    A strange thing, here: if base_queryset == none(), it will still yield
            #    all groups available!
            grp_results = base_queryset.order_by(group + '__id').values(group).annotate(items_count=Count('pk'))

            assert rel_field.rel, rel_field # assume it's a Foreign key
            grp_rdict1 = dict([(gd[group], gd['items_count']) for gd in grp_results if gd['items_count']])
            del grp_results

            # We query on the foreign field now, and paginate that to limit the results
            grp_queryset = rel_field.rel.to.objects.filter(id__in=grp_rdict1.keys())
            self.group_order = False
            new_group_fields = False
            if self.group_fields:
                grp_queryset = self._select_prefetch(grp_queryset, [ f['attribute'] for f in self.group_fields if f.get('attribute', None)])

                if self.enable_sorting:
                    descending = False
                    if self.order_by and self.order_by[0].startswith(group+'__'):
                        # Order shall apply to the groupping field!
                        self.group_order = self.order_by[0][len(group)+2:]
                        descending = False
                    elif self.order_by and self.order_by[0].startswith('-' + group +'__'):
                        self.group_order = self.order_by[0][len(group)+3:]
                        descending = True

                    get_params = request.GET.copy()

                new_group_fields = []
                for col in self.group_fields:
                    col = col.copy()
                    new_group_fields.append(col)
                    attr = col.get('order_attribute', col.get('attribute', None))
                    if not attr:
                        continue
                    else:
                        attr = attr.replace('.', '__')
                    
                    if self.enable_sorting:
                        col['sortable'] = True
                        get_params['order_by'] = group + '__' + attr
                        if self.group_order and attr == self.group_order:
                            col['url_class'] = 'sorted'
                            if descending:
                                col['url_spanclass'] = 'famfam active famfam-arrow_up'
                            else:
                                col['url_spanclass'] = 'famfam active famfam-arrow_down'
                                get_params['order_by'] = '-' + get_params['order_by']
                        col['url']= '?' + get_params.urlencode()
                if self.group_order:
                    if descending:
                        self.group_order = '-' + self.group_order
                    grp_queryset = grp_queryset.order_by(self.group_order)

            page_size = self.get_paginate_by(grp_queryset) \
                    or getattr(settings, 'PAGINATION_DEFAULT_PAGINATION', 20)
            
            if page_size:
                paginator, page, grp_queryset, is_paginated = self.paginate_queryset(grp_queryset, page_size)
            else:
                paginator = page = is_paginated = None

            context = self.get_context_data(paginator=paginator, page_obj=page, \
                    is_paginated=is_paginated, object_list=base_queryset.none(),
                    group_fields=new_group_fields, columns=columns)
            
            # Now, iterate over the group and prepare the list(dict) of results
            
            grp_results = []
            grp_expand = self.kwargs.get('grp_expand') or self.request.GET.get('grp_expand', None)
            get_params = request.GET.copy()
            relations = list(self.prefetch_fields)
            relations.append(group)
            for grp in grp_queryset:
                items = None
                if unicode(grp.id) == grp_expand:
                    get_params['grp_expand'] = '' # second click collapses the item
                    # TODO: perhaps expand all if grp_expand == '*' , but then
                    # we would have an issue with limiting at page_size
                    
                    items = self._select_prefetch(base_queryset.filter(**{group:grp}), relations)
                    if self.order_by and not self.group_order:
                        items = self.apply_order(items)
                    if page_size:
                        items = items[:page_size] # no way, so far, to display more!
                else:
                    get_params['grp_expand'] = grp.id
                grp_url = '?' + get_params.urlencode()
                grp_results.append(dict(group=grp, url=grp_url, \
                        items_count=grp_rdict1[grp.id], items=items))
            context['group_results'] = grp_results
        else:
            if self.order_by:
                base_queryset = self.apply_order(base_queryset)
            #if extra_context and 'extra_columns' self.extra_context:
            #    TODO
            base_queryset = self._select_prefetch(base_queryset, self.prefetch_fields)
            allow_empty = self.get_allow_empty()
            if not allow_empty and len(self.object_list) == 0:
                raise Http404(_(u"Empty list and '%(class_name)s.allow_empty' is False.")
                            % {'class_name': self.__class__.__name__})
            context = self.get_context_data(object_list=base_queryset, columns=columns)
        return self.render_to_response(context)

def generic_delete(*args, **kwargs):
    try:
        kwargs['post_delete_redirect'] = reverse(kwargs['post_delete_redirect'])
    except NoReverseMatch:
        pass

    if 'extra_context' in kwargs:
        kwargs['extra_context']['delete_view'] = True
    else:
        kwargs['extra_context'] = {'delete_view':True}

    return delete_object(template_name='generic_confirm.html', *args, **kwargs)

def generic_confirm(request, _view, _title=None, _model=None, _object_id=None, _message='', *args, **kwargs):
    if request.method == 'POST':
        form = GenericConfirmForm(request.POST)
        if form.is_valid():
            if hasattr(_view, '__call__'):
                return _view(request, *args, **kwargs)
            else:
                return HttpResponseRedirect(reverse(_view, args=args, kwargs=kwargs))

    data = {}

    try:
        object = _model.objects.get(pk=kwargs[_object_id])
        data['object'] = object
    except:
        pass

    try:
        data['title'] = _title
    except:
        pass

    try:
        data['message'] = _message
    except:
        pass

    form=GenericConfirmForm()

    return render_to_response('generic_confirm.html',
        data,
        context_instance=RequestContext(request))	

def generic_assign_remove(request, title, obj, left_list_qryset, left_list_title, right_list_qryset, right_list_title, add_method, remove_method, item_name, list_filter=None):
    left_filter = None
    filter_form = None
    if list_filter:
        filter_form, filters = add_filter(request, list_filter)
        if filters:
            left_filter = filters


    if request.method == 'POST':
        post_data = request.POST
        form = GenericAssignRemoveForm(left_list_qryset, right_list_qryset, left_filter, request.POST)
        if form.is_valid():
            action = post_data.get('action','')
            if action == "assign":
                for item in form.cleaned_data['left_list']:
                    add_method(item)
                if form.cleaned_data['left_list']:
                    messages.success(request, _(u"The selected %s were added.") % unicode(item_name))

            if action == "remove":
                for item in form.cleaned_data['right_list']:
                    remove_method(item)
                if form.cleaned_data['right_list']:
                    messages.success(request, _(u"The selected %s were removed.") % unicode(item_name))

    form = GenericAssignRemoveForm(left_list_qryset=left_list_qryset, right_list_qryset=right_list_qryset, left_filter=left_filter)

    return render_to_response('generic_assign_remove.html', {
    'form':form,
    'object':obj,
    'title':title,
    'left_list_title':left_list_title,
    'right_list_title':right_list_title,
    'filter_form':filter_form,
    },
    context_instance=RequestContext(request))


def generic_detail(request, object_id, form_class, queryset, title=None, extra_context={}, extra_fields=[],
                template_name='generic_detail.html'):
    #if isinstance(form_class, DetailForm):
    if queryset is not None and not isinstance(queryset, QuerySet) \
                and callable(queryset):
        queryset = queryset(request)

    try:
        if extra_fields:
            form = form_class(instance=queryset.get(id=object_id), extra_fields=extra_fields)
        else:
            form = form_class(instance=queryset.get(id=object_id))
    except ObjectDoesNotExist:
        raise Http404

    extra_context['form'] = form
    extra_context['title'] = title

    return object_detail(
        request,
        template_name=template_name,
        extra_context=extra_context,
        queryset=queryset,
        object_id=object_id,
    )


class _InlineViewMixin(object):
    extra_context = None
    inline_fields = ()
    _inline_formsets = None
    form_mode = None

    def __init__(self, **kwargs):
        super(_InlineViewMixin, self).__init__(**kwargs)
        if not self.model:
            form_class = self.get_form_class()
            if form_class:
                self.model = form_class._meta.model
            elif hasattr(self, 'object') and self.object is not None:
                self.model = self.object.__class__

        self._inline_formsets = {}
        infields = self.inline_fields
        if isinstance(infields, (tuple, list)):
            infields = dict.fromkeys(infields, InlineModelForm)
        for inlf, iform_class in infields.items():
            relo = self.model._meta.get_field_by_name(inlf)
            if not isinstance(relo[0], RelatedObject):
                raise ImproperlyConfigured("Field %s.%s is not a related object for inlined field of %s" % \
                    (self.model._meta.object_name, inlf, self.__class__.__name__))
            self._inline_formsets[inlf] = inlineformset_factory(self.model, \
                            relo[0].model, form=iform_class, extra=1)
            # explicitly set this (new) attribute, because jinja2 is not allowed to see '_meta'
            self._inline_formsets[inlf].title = relo[0].model._meta.verbose_name_plural

    def form_valid(self, form):
        if hasattr(form, '_pre_save_by_user'):
            form._pre_save_by_user(self.request.user)
        context = self.get_context_data()
        if all([ inline_form.is_valid() for inline_form in context['formsets']]):
            self.object = form.save()
            for inline_form in context['formsets']:
                inline_form.instance = self.object
                inline_form.save()
            return HttpResponseRedirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))

    def get_context_data(self, **kwargs):
        context = super(_InlineViewMixin, self).get_context_data(**kwargs)

        if self.request.POST:
            iargs = (self.request.POST, self.request.FILES)
        else:
            iargs =()

        context['formsets'] = []
        for inlf in self.inline_fields:
            kwargs = dict(instance=self.object)
            context['formsets'].append(self._inline_formsets[inlf](*iargs, **kwargs))
        if self.extra_context:
            context.update(self.extra_context)
        if self.form_mode:
            context['form_mode'] = self.form_mode
        return context

    def get_form(self, form_class):
        form = super(_InlineViewMixin, self).get_form(form_class)
        if hasattr(form, '_init_by_user'):
            form._init_by_user(self.request.user)
        return form

    def get_success_url(self):
        if callable(self.success_url):
            return self.success_url(self.object, self.request)
        else:
            return super(_InlineViewMixin, self).get_success_url()

class GenericCreateView(_InlineViewMixin, django_gv.CreateView):
    template_name = 'generic_form_fs.html'
    form_mode = 'create'

class GenericUpdateView(_InlineViewMixin, django_gv.UpdateView):
    template_name = 'generic_form_fs.html'
    form_mode = 'update'

class _CartOpenCloseView(django_gv.detail.SingleObjectMixin, django_gv.TemplateView):
    # TODO def get_queryset() w. callable

    def get_context_data(self, **kwargs):
        context = super(_CartOpenCloseView, self).get_context_data(**kwargs)
        if self.extra_context:
            context.update(self.extra_context)
        context['action_fn'] = self._action_fn
        context['object'] = self.object
        context['object_name'] = self.object._meta.verbose_name
        return context

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(_CartOpenCloseView, self).get(request, object=self.object, **kwargs)

class CartOpenView(_CartOpenCloseView):
    """ A view that immediately adds the object as a cart, and then gives instructions
    """
    template_name = 'generic_cart_open.html'
    extra_context = None
    dest_model = None

    def _action_fn(self, context):
        if context['carts'].open_as_cart(self.object, self.dest_model):
            self.request.session.modified = True
        else:
            context['action_failed'] = _("The cart is already open.")


class CartCloseView(_CartOpenCloseView):

    template_name = 'generic_cart_close.html'
    extra_context = None
    dest_model = None

    def _action_fn(self, context):
        if context['carts'].close_cart(self.object):
            self.request.session.modified = True
        else:
            context['action_failed'] = _("The cart is not open.")

class JSON_RPC_ResponseMixin(object):
    def _render_to_response(self, context):
        return self.get_json_response(self.convert_context_to_json(context))

    def get_json_response(self, content, **httpresponse_kwargs):
        print "JSON:", content
        return HttpResponse(content, content_type='application/json', **httpresponse_kwargs)

    def convert_context_to_json(self, context):
        return simplejson.dumps(context)

class _ModifyCartView(JSON_RPC_ResponseMixin, django_gv.RedirectView):
    """ Adds some item to a cart. Works both in HTML and JSON mode (AJAX)

        It will try to add `model` into `cart_model #pk`.

        In HTML mode, it will redirect to the page
    """
    item_model = None
    cart_model = None
    extra_context = None
    url_attribute = 'get_absolute_url'

    def __init__(self, *args, **kwargs):
        super(_ModifyCartView, self).__init__(*args, **kwargs)
        if isinstance(self.item_model, basestring):
            self.item_model = get_model(*(self.item_model.split('.',1)))
        if isinstance(self.cart_model, basestring):
            self.cart_model = get_model(*(self.cart_model.split('.',1)))

    def get_context_data(self, **kwargs):
        context = super(CartOpenView, self).get_context_data(**kwargs)
        if self.extra_context:
            context.update(self.extra_context)
        return context

    def _add_or_remove(self, cart, obj):
        raise NotImplementedError

    def get_redirect_url(self, **kwargs):
        if 'HTTP_REFERER' in self.request.META:
            return self.request.META['HTTP_REFERER']
        else:
            fn = getattr(self.cart_object, self.url_attribute)
            return fn()

    def get(self, request, pk, **kwargs):
        # pk = kwargs['pk']
        self.cart_object = get_object_or_404(self.cart_model, pk=pk)
        error_msg = None
        try:
            item_pk = request.GET.get('item', None)
            if not item_pk:
                raise ObjectDoesNotExist
            item_object = self.item_model.objects.get(pk=item_pk)
            msg, verb = self._add_or_remove(self.cart_object, item_object)
            messages.success(request, msg)
        except ObjectDoesNotExist:
            error_msg = _('Item %s could not be found.') % (kwargs.get('item', '?'),)
            messages.error(request, error_msg)
        except Exception, e:
            error_msg = str(e)
            messages.error(request, error_msg)

        if self.request.is_ajax():
            resp = dict(id=None, result=None, error=None)
            if verb:
                resp['result'] = verb
            else:
                resp['error']= dict(code=1, message= error_msg or _("Could not alter item"), data=None)
            return JSON_RPC_ResponseMixin._render_to_response(self, resp)
        else:
            return super(_ModifyCartView, self).get(request, **kwargs)

class AddToCartView(_ModifyCartView):
    def _add_or_remove(self, cart, obj):
        verb = cart.add_to_cart(obj)
        message = _("%(item)s added to %(cart)s") % {'item': unicode(obj), 'cart': unicode(cart.get_cart_name())}
        return message, verb

class RemoveFromCartView(_ModifyCartView):
    def _add_or_remove(self, cart, obj):
        verb = cart.remove_from_cart(obj)
        message = _("%(item)s removed from %(cart)s") % {'item': unicode(obj), 'cart': unicode(cart.get_cart_name())}
        return message, verb

#eof
